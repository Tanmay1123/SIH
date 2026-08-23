"""
Fraud-engine API.

The two pipeline endpoints (rebuild-graph, score) run synchronously. That is a
deliberate choice for a demo-scale network: cycle detection finishes in
milliseconds and scoring in a couple of seconds, so a job queue would add
Redis, a worker process and polling endpoints in exchange for nothing an
officer would notice. The point at which that stops being true is measured by
a test - see test_detection_is_fast_enough_to_run_synchronously.
"""
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.models import Company, Invoice
from core.views import StandardPagination

from . import ledger
from .cycle_detection import detect_rings
from .graph_builder import build_graph, graph_summary
from .models import FlaggedRing, LedgerBlock, RiskScore
from .risk_scoring import load_metadata, run_scoring
from .serializers import (
    FlaggedRingDetailSerializer,
    FlaggedRingSerializer,
    LedgerBlockSerializer,
)


def _company_name_map(rings) -> dict[int, str]:
    """One query for every company name referenced by a set of rings."""
    ids = {cid for ring in rings for cid in (ring.company_ids or [])}
    return dict(Company.objects.filter(id__in=ids).values_list("id", "name"))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@api_view(["POST"])
@transaction.atomic
def rebuild_graph(request):
    """
    POST /api/fraud/rebuild-graph/

    Rebuild the trade graph from current database state, re-run circular-trade
    detection, and store the results as FlaggedRing rows.

    Rings already confirmed by an officer are preserved: a confirmation is a
    human decision backed by a ledger block, and a rebuild must never silently
    erase it. Rings that are merely detected are replaced.
    """
    graph = build_graph()
    if graph.number_of_nodes() == 0:
        return Response(
            {"detail": "No companies in the database. Upload a dataset first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    rings = detect_rings(graph)

    confirmed = {r.signature: r for r in FlaggedRing.objects.filter(officer_confirmed=True)}
    FlaggedRing.objects.filter(officer_confirmed=False).delete()

    created = 0
    for evidence in rings:
        signature = ",".join(str(c) for c in sorted(evidence["company_ids"]))
        existing = confirmed.get(signature)
        if existing:
            # Refresh the evidence but leave the human decision alone.
            existing.invoice_ids = evidence["invoice_ids"]
            existing.total_cycle_value = evidence["total_cycle_value"]
            existing.save(update_fields=["invoice_ids", "total_cycle_value"])
            continue

        FlaggedRing.objects.create(
            company_ids=evidence["company_ids"],
            invoice_ids=evidence["invoice_ids"],
            total_cycle_value=evidence["total_cycle_value"],
        )
        created += 1

    return Response(
        {
            "detail": "Graph rebuilt and circular-trade detection complete.",
            "graph": graph_summary(graph),
            "rings_detected": len(rings),
            "rings_created": created,
            "rings_preserved_as_confirmed": len(confirmed),
            "note": (
                "Rings are candidates, not verdicts - genuine two-way trade also "
                "forms loops. Run /api/fraud/score/ to rank them."
            ),
        }
    )


@api_view(["POST"])
def score_rings(request):
    """
    POST /api/fraud/score/

    Run feature engineering, the XGBoost risk model and SHAP explanation over
    the current companies and detected rings. Writes a fresh RiskScore per
    company and updates each ring's score and explanation.
    """
    try:
        result = run_scoring()
    except FileNotFoundError as exc:
        return Response(
            {"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE
        )

    if not FlaggedRing.objects.exists():
        result["warning"] = (
            "No rings are stored yet. Run /api/fraud/rebuild-graph/ first."
        )
    return Response(result)


# ---------------------------------------------------------------------------
# Rings
# ---------------------------------------------------------------------------


class FlaggedRingListView(generics.ListAPIView):
    """GET /api/fraud/rings/ — flagged rings, highest risk first."""

    serializer_class = FlaggedRingSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = FlaggedRing.objects.all().order_by("-risk_score", "id")
        confirmed = self.request.query_params.get("confirmed")
        if confirmed is not None:
            qs = qs.filter(officer_confirmed=confirmed.lower() in {"1", "true", "yes"})
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company_names"] = _company_name_map(self.get_queryset())
        return context


class FlaggedRingDetailView(generics.RetrieveAPIView):
    """GET /api/fraud/rings/{id}/ — member companies, invoices, score, explanation."""

    queryset = FlaggedRing.objects.all()
    serializer_class = FlaggedRingDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company_names"] = _company_name_map([self.get_object()])
        return context


@api_view(["POST"])
@transaction.atomic
def confirm_ring(request, pk):
    """
    POST /api/fraud/rings/{id}/confirm/

    An officer confirms a ring as fraudulent. This is the point where a machine
    suggestion becomes a human decision, so it is also the point where the
    evidence is committed to the tamper-evident ledger.
    """
    try:
        ring = FlaggedRing.objects.get(pk=pk)
    except FlaggedRing.DoesNotExist:
        return Response({"detail": "Ring not found."}, status=status.HTTP_404_NOT_FOUND)

    if ring.officer_confirmed:
        return Response(
            {
                "detail": "This ring was already confirmed and recorded in the ledger.",
                "ring_id": ring.id,
                "confirmed_at": ring.confirmed_at,
            },
            status=status.HTTP_409_CONFLICT,
        )

    # The confirming officer is whoever is authenticated, not a client-supplied
    # string - the ledger's evidentiary value depends on knowing who actually
    # confirmed a ring, and a bearer token already proves that.
    officer = request.user.username

    companies = list(Company.objects.filter(id__in=ring.company_ids or []))
    by_id = {c.id: c for c in companies}
    ordered = [by_id[cid] for cid in (ring.company_ids or []) if cid in by_id]
    invoices = list(Invoice.objects.filter(id__in=ring.invoice_ids or []))

    ring.officer_confirmed = True
    ring.confirmed_at = timezone.now()
    ring.save(update_fields=["officer_confirmed", "confirmed_at"])

    payload = ledger.build_ring_payload(ring, ordered, invoices, officer=officer)
    block = ledger.append_block(payload)

    return Response(
        {
            "detail": "Ring confirmed as fraudulent and written to the audit ledger.",
            "ring_id": ring.id,
            "block": LedgerBlockSerializer(block).data,
            "chain": ledger.verify_chain(),
        },
        status=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


class LedgerBlockListView(generics.ListAPIView):
    """GET /api/ledger/blocks/ — every block, oldest first."""

    queryset = LedgerBlock.objects.all().order_by("index")
    serializer_class = LedgerBlockSerializer
    pagination_class = None


@api_view(["GET"])
def verify_ledger(request):
    """GET /api/ledger/verify/ — walk the chain and report whether it is intact."""
    return Response(ledger.verify_chain())


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------


@api_view(["GET"])
def graph_data(request):
    """
    GET /api/fraud/graph/

    The whole trade network in one payload, shaped for Cytoscape.

    This exists because the paginated /api/companies/ and /api/invoices/
    endpoints would need ~70 round trips to draw one picture. Edges are the
    collapsed per-pair relationships from graph_builder, not raw invoices, so
    the browser renders ~1,100 edges instead of ~3,500.

    ?ring_members_only=true returns just the companies inside flagged rings,
    which is what an officer actually wants to look at once scoring has run.
    """
    graph = build_graph()
    scores = dict(
        RiskScore.objects.order_by("company_id", "-computed_at").values_list(
            "company_id", "score"
        )
    )

    ring_members: set[int] = set()
    ring_of: dict[int, int] = {}
    for ring in FlaggedRing.objects.all().order_by("-risk_score"):
        for cid in ring.company_ids or []:
            ring_members.add(cid)
            ring_of.setdefault(cid, ring.id)

    only_rings = request.query_params.get("ring_members_only", "").lower() in {
        "1", "true", "yes",
    }
    visible = ring_members if only_rings else set(graph.nodes)

    nodes = [
        {
            "data": {
                "id": str(node),
                "label": attrs.get("name") or f"Company {node}",
                "gstin": attrs.get("gstin"),
                "risk_score": round(scores.get(node, 0.0), 2),
                "in_ring": node in ring_members,
                "ring_id": ring_of.get(node),
            }
        }
        for node, attrs in graph.nodes(data=True)
        if node in visible
    ]

    edges = [
        {
            "data": {
                "id": f"e{seller}-{buyer}",
                "source": str(seller),
                "target": str(buyer),
                "total_amount": attrs.get("total_amount", 0.0),
                "invoice_count": attrs.get("invoice_count", 0),
                "eway_missing": attrs.get("eway_missing", 0),
            }
        }
        for seller, buyer, attrs in graph.edges(data=True)
        if seller in visible and buyer in visible
    ]

    return Response(
        {
            "nodes": nodes,
            "edges": edges,
            "summary": graph_summary(graph),
            "ring_member_count": len(ring_members),
        }
    )


@api_view(["GET"])
def pipeline_status(request):
    """
    GET /api/fraud/status/

    One call for the dashboard header: how much data exists, how far the
    pipeline has been run, and whether the ledger still verifies.
    """
    rings = FlaggedRing.objects.all()
    scored = rings.exclude(risk_score=0).count()

    return Response(
        {
            "companies": Company.objects.count(),
            "invoices": Invoice.objects.count(),
            "rings_detected": rings.count(),
            "rings_scored": scored,
            "rings_confirmed": rings.filter(officer_confirmed=True).count(),
            "high_risk_rings": rings.filter(risk_score__gte=70).count(),
            "companies_scored": RiskScore.objects.count(),
            "ledger": ledger.verify_chain(),
            "model": load_metadata().get("metrics", {}),
        }
    )
