"""
Fraud-engine API.

The pipeline endpoint runs synchronously. That is a deliberate choice for a
demo-scale network: cycle detection finishes in milliseconds and scoring in a
couple of seconds, so a job queue would add Redis, a worker process and polling
endpoints in exchange for nothing an officer would notice. The point at which
that stops being true is measured by a test - see
test_detection_is_fast_enough_to_run_synchronously.
"""
from django.db import transaction
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from core.models import Company, Invoice, active_dataset
from core.permissions import IsSupervisor
from core.roles import permissions_for, role_of
from core.views import StandardPagination

from . import ledger, mailer, reporting
from .graph_builder import build_graph, graph_summary
from .models import CaseReport, DetectionRun, FlaggedRing, LedgerBlock, RiskScore
from .pipeline import execute_run
from .risk_scoring import load_metadata
from .serializers import (
    CaseReportDetailSerializer,
    CaseReportSerializer,
    DetectionRunSerializer,
    FlaggedRingDetailSerializer,
    FlaggedRingSerializer,
    LedgerBlockSerializer,
)
from .settings_helpers import risk_threshold


def _company_name_map(rings) -> dict[int, str]:
    """One query for every company name referenced by a set of alerts."""
    ids = {cid for ring in rings for cid in (ring.company_ids or [])}
    return dict(Company.objects.filter(id__in=ids).values_list("id", "name"))


def latest_run(dataset=None) -> DetectionRun | None:
    """The most recent detection run for a dataset (the active one by default)."""
    dataset = dataset or active_dataset()
    if dataset is None:
        return None
    return DetectionRun.objects.filter(dataset=dataset).first()


def _resolve_run(request) -> DetectionRun | None:
    """?run=<id> if given and valid, otherwise the latest run of the active dataset."""
    run_id = request.query_params.get("run")
    if run_id:
        return DetectionRun.objects.filter(pk=run_id).first()
    return latest_run()


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


@api_view(["POST"])
def run_detection(request):
    """
    POST /api/fraud/run/

    Body (all optional): {"name": "Detection 3", "note": "..."}

    Runs both detectors over the active dataset and stores the result as one
    named, dated DetectionRun. Previous runs are left untouched, and any
    decision an officer already made about the same pattern is carried forward
    so nobody re-reviews work they already did.
    """
    try:
        run = execute_run(
            name=request.data.get("name", "") if request.data else "",
            note=request.data.get("note", "") if request.data else "",
            user=request.user,
        )
    except ValueError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    except FileNotFoundError as exc:
        return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return Response(
        {
            "detail": f"'{run.name}' complete.",
            "run": DetectionRunSerializer(run).data,
            "graph": getattr(run, "graph_summary", {}),
            "note": (
                "Alerts are candidates, not verdicts - genuine two-way trade also "
                "forms loops. Review each one and confirm or dismiss it."
            ),
        },
        status=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# Detection runs
# ---------------------------------------------------------------------------


class DetectionRunListView(generics.ListAPIView):
    """GET /api/fraud/runs/ — every run, newest first. ?dataset=<id> to filter."""

    serializer_class = DetectionRunSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = DetectionRun.objects.select_related("dataset", "created_by")
        dataset_id = self.request.query_params.get("dataset")
        if dataset_id:
            qs = qs.filter(dataset_id=dataset_id)
        return qs


class DetectionRunDetailView(generics.RetrieveAPIView):
    queryset = DetectionRun.objects.select_related("dataset", "created_by")
    serializer_class = DetectionRunSerializer


@api_view(["DELETE"])
def delete_run(request, pk):
    """DELETE /api/fraud/runs/{id}/delete/ — discard a run and its alerts."""
    run = DetectionRun.objects.filter(pk=pk).first()
    if run is None:
        return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)
    if run.reports.exists():
        return Response(
            {
                "detail": "This run has an issued case report and cannot be deleted. "
                "The report is part of the audit record."
            },
            status=status.HTTP_409_CONFLICT,
        )
    name = run.name
    run.delete()
    return Response({"detail": f"'{name}' deleted."})


# ---------------------------------------------------------------------------
# Alerts (rings and mills)
# ---------------------------------------------------------------------------


class FlaggedRingListView(generics.ListAPIView):
    """
    GET /api/fraud/rings/ — alerts for one run, highest risk first.

    ?run=<id>       a specific run (default: latest run of the active dataset)
    ?status=        pending | confirmed | dismissed
    ?kind=          ring | mill
    """

    serializer_class = FlaggedRingSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        run = _resolve_run(self.request)
        if run is None:
            return FlaggedRing.objects.none()

        qs = FlaggedRing.objects.filter(run=run).select_related("reviewed_by")

        status_param = self.request.query_params.get("status")
        if status_param:
            qs = qs.filter(status=status_param)

        kind = self.request.query_params.get("kind")
        if kind:
            qs = qs.filter(kind=kind)

        # Legacy flag, still accepted so old clients keep working.
        confirmed = self.request.query_params.get("confirmed")
        if confirmed is not None:
            qs = qs.filter(officer_confirmed=confirmed.lower() in {"1", "true", "yes"})

        return qs.order_by("-risk_score", "id")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company_names"] = _company_name_map(self.get_queryset())
        return context


class FlaggedRingDetailView(generics.RetrieveAPIView):
    """GET /api/fraud/rings/{id}/ — member companies, invoices, score, explanation."""

    queryset = FlaggedRing.objects.select_related("reviewed_by", "run")
    serializer_class = FlaggedRingDetailSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["company_names"] = _company_name_map([self.get_object()])
        return context


@api_view(["POST"])
@permission_classes([IsSupervisor])
@transaction.atomic
def confirm_ring(request, pk):
    """
    POST /api/fraud/rings/{id}/confirm/  — SUPERVISOR ONLY.

    Confirming an alert as fraudulent is the act that starts recovery
    proceedings against a real business, so it is the one decision that needs a
    second, more senior pair of eyes. An officer prepares the case and can
    clear it; a supervisor sanctions it.

    This is also the point where a machine suggestion becomes a human decision,
    so it is where the evidence is committed to the tamper-evident ledger -
    along with the model version and threshold that produced the score they
    acted on.
    """
    ring = FlaggedRing.objects.filter(pk=pk).select_related("run").first()
    if ring is None:
        return Response({"detail": "Alert not found."}, status=status.HTTP_404_NOT_FOUND)

    if ring.status == FlaggedRing.STATUS_CONFIRMED:
        return Response(
            {
                "detail": "This alert was already confirmed and recorded in the ledger.",
                "ring_id": ring.id,
                "confirmed_at": ring.confirmed_at,
            },
            status=status.HTTP_409_CONFLICT,
        )

    # The confirming officer is whoever is authenticated, not a client-supplied
    # string - the ledger's evidentiary value depends on knowing who actually
    # confirmed a ring, and a bearer token already proves that.
    officer = request.user.username
    note = (request.data or {}).get("note", "") if request.data else ""

    companies = list(Company.objects.filter(id__in=ring.company_ids or []))
    by_id = {c.id: c for c in companies}
    ordered = [by_id[cid] for cid in (ring.company_ids or []) if cid in by_id]
    invoices = list(Invoice.objects.filter(id__in=ring.invoice_ids or []))

    ring.mark_confirmed(user=request.user, note=note)

    payload = ledger.build_ring_payload(ring, ordered, invoices, officer=officer)
    block = ledger.append_block(payload)

    return Response(
        {
            "detail": "Confirmed as fraudulent and written to the audit ledger.",
            "ring_id": ring.id,
            "block": LedgerBlockSerializer(block).data,
            "chain": ledger.verify_chain(),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
@transaction.atomic
def dismiss_ring(request, pk):
    """
    POST /api/fraud/rings/{id}/dismiss/
    Body: {"reason": "<code>", "note": "optional free text"}

    An officer looked at this alert and says it is not fraud.

    This is the half of the loop that did not exist before. Without it the
    system held no negative examples at all: it could be told it was right,
    never that it was wrong, so it could not measure its own precision and
    could never improve. The reason code is the useful part - if most
    dismissals say "genuine two-way trade" that is a specific, fixable model
    failure rather than a vague sense that precision is poor.

    The dismissal goes into the ledger too. Clearing a taxpayer is a decision
    about a real business, and the record that an allegation was examined and
    dropped belongs in the audit trail just as much as a confirmation does.
    """
    ring = FlaggedRing.objects.filter(pk=pk).select_related("run").first()
    if ring is None:
        return Response({"detail": "Alert not found."}, status=status.HTTP_404_NOT_FOUND)

    if ring.status == FlaggedRing.STATUS_CONFIRMED:
        return Response(
            {
                "detail": "This alert was already confirmed as fraudulent and written "
                "to the ledger. A confirmation cannot be reversed from here."
            },
            status=status.HTTP_409_CONFLICT,
        )

    data = request.data or {}
    reason = (data.get("reason") or "").strip()
    valid = dict(FlaggedRing.DISMISSAL_REASONS)
    if reason not in valid:
        return Response(
            {
                "detail": "A dismissal reason is required.",
                "valid_reasons": [
                    {"code": code, "label": label}
                    for code, label in FlaggedRing.DISMISSAL_REASONS
                ],
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    note = (data.get("note") or "").strip()
    ring.mark_dismissed(reason=reason, user=request.user, note=note)

    payload = ledger.build_dismissal_payload(
        ring, reason_label=valid[reason], officer=request.user.username, note=note
    )
    block = ledger.append_block(payload)

    return Response(
        {
            "detail": "Alert cleared. The decision is recorded as training data.",
            "ring_id": ring.id,
            "block": LedgerBlockSerializer(block).data,
            "chain": ledger.verify_chain(),
        },
        status=status.HTTP_201_CREATED,
    )


@api_view(["GET"])
def dismissal_reasons(request):
    """GET /api/fraud/dismissal-reasons/ — the codes the dismiss action accepts."""
    return Response(
        [{"code": code, "label": label} for code, label in FlaggedRing.DISMISSAL_REASONS]
    )


# ---------------------------------------------------------------------------
# Case reports
# ---------------------------------------------------------------------------


class CaseReportListView(generics.ListAPIView):
    """GET /api/reports/ — every issued report, newest first. ?run=<id> to filter."""

    serializer_class = CaseReportSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = CaseReport.objects.select_related("run", "run__dataset", "generated_by")
        run_id = self.request.query_params.get("run")
        if run_id:
            qs = qs.filter(run_id=run_id)
        return qs


class CaseReportDetailView(generics.RetrieveAPIView):
    queryset = CaseReport.objects.select_related("run", "run__dataset", "generated_by")
    serializer_class = CaseReportDetailSerializer


@api_view(["POST"])
@transaction.atomic
def create_report(request, pk):
    """
    POST /api/fraud/runs/{id}/report/
    Body (optional): {"title": "...", "send": true, "recipients": ["a@b.com"]}

    Builds the supervisor's case report for one run, hashes it into the audit
    ledger, and emails it to the officer and their supervisor.
    """
    run = DetectionRun.objects.filter(pk=pk).select_related("dataset").first()
    if run is None:
        return Response({"detail": "Run not found."}, status=status.HTTP_404_NOT_FOUND)

    data = request.data or {}
    officer = request.user.username
    summary = reporting.build_summary(run)

    extra = [e.strip() for e in (data.get("recipients") or []) if str(e).strip()]
    recipients = mailer.resolve_recipients(getattr(request.user, "email", ""))
    for email in extra:
        if email.lower() not in {r.lower() for r in recipients}:
            recipients.append(email)

    title = (data.get("title") or "").strip() or f"Case report — {run.name}"
    html = reporting.render_report_html(run, summary, officer, recipients)

    report = CaseReport.objects.create(
        run=run,
        title=title,
        generated_by=request.user,
        html=html,
        summary=summary,
        content_hash=reporting.content_hash(html, summary),
        recipients=recipients,
    )

    # Hash first, send second: the ledger records what was issued, and it
    # should say so even if the mail server is misconfigured.
    block = ledger.append_block(
        ledger.build_report_payload(report, officer=officer)
    )
    report.ledger_block = block
    report.save(update_fields=["ledger_block"])

    if data.get("send", True):
        mailer.send_report(
            report,
            subject=f"[GST Fraud Detection] {title}",
            text_body=reporting.plain_text_version(summary, officer),
        )

    report.refresh_from_db()
    return Response(
        CaseReportDetailSerializer(report).data, status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
def resend_report(request, pk):
    """POST /api/reports/{id}/send/ — retry delivery after fixing SMTP settings."""
    report = CaseReport.objects.filter(pk=pk).select_related("run").first()
    if report is None:
        return Response({"detail": "Report not found."}, status=status.HTTP_404_NOT_FOUND)

    mailer.send_report(
        report,
        subject=f"[GST Fraud Detection] {report.title}",
        text_body=reporting.plain_text_version(
            report.summary or {}, request.user.username
        ),
    )
    report.refresh_from_db()
    return Response(CaseReportSerializer(report).data)


@api_view(["GET"])
def mail_status(request):
    """GET /api/reports/mail-status/ — is SMTP usable, and who would be copied in?"""
    from .settings_helpers import supervisor_emails

    return Response(
        {
            "configured": mailer.is_configured(),
            "officer_email": getattr(request.user, "email", "") or None,
            "supervisors": supervisor_emails(),
            "recipients": mailer.resolve_recipients(getattr(request.user, "email", "")),
        }
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

    ?ring_members_only=true returns just the companies inside flagged alerts,
    which is what an officer actually wants to look at once scoring has run.
    """
    graph = build_graph()
    run = _resolve_run(request)

    scores: dict[int, float] = {}
    ring_members: set[int] = set()
    ring_of: dict[int, int] = {}

    if run is not None:
        scores = dict(
            RiskScore.objects.filter(run=run).values_list("company_id", "score")
        )
        for ring in FlaggedRing.objects.filter(run=run).order_by("-risk_score"):
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

    One call for the dashboard header: which dataset is loaded, how far the
    pipeline has been run against it, how much of the queue a human has
    actually reviewed, and whether the ledger still verifies.
    """
    dataset = active_dataset()
    run = _resolve_run(request)
    threshold = risk_threshold()

    alerts = FlaggedRing.objects.filter(run=run) if run else FlaggedRing.objects.none()

    return Response(
        {
            "dataset": (
                {
                    "id": dataset.id,
                    "name": dataset.name,
                    "uploaded_at": dataset.uploaded_at,
                }
                if dataset
                else None
            ),
            "run": (
                {
                    "id": run.id,
                    "name": run.name,
                    "started_at": run.started_at,
                    "model_version": run.model_version,
                }
                if run
                else None
            ),
            "companies": (
                Company.objects.filter(dataset=dataset).count()
                if dataset
                else Company.objects.count()
            ),
            "invoices": (
                Invoice.objects.filter(dataset=dataset).count()
                if dataset
                else Invoice.objects.count()
            ),
            "rings_detected": alerts.filter(kind=FlaggedRing.KIND_RING).count(),
            "mills_detected": alerts.filter(kind=FlaggedRing.KIND_MILL).count(),
            "rings_scored": alerts.exclude(risk_score=0).count(),
            "rings_confirmed": alerts.filter(status=FlaggedRing.STATUS_CONFIRMED).count(),
            "rings_dismissed": alerts.filter(status=FlaggedRing.STATUS_DISMISSED).count(),
            "rings_pending": alerts.filter(status=FlaggedRing.STATUS_PENDING).count(),
            "high_risk_rings": alerts.filter(risk_score__gte=threshold).count(),
            "companies_scored": RiskScore.objects.filter(run=run).count() if run else 0,
            "risk_threshold": threshold,
            "ledger": ledger.verify_chain(),
            "model": load_metadata().get("metrics", {}),
            "role": role_of(request.user),
            "permissions": permissions_for(request.user),
        }
    )
