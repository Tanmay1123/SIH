"""
The detection pipeline, as one named run.

Previously "Run detection" was two endpoints that each wiped and rebuilt global
state. Now one call produces one DetectionRun: an immutable, named, dated
record of what the system found, which model version found it, and at what
threshold. Running again creates another run and leaves the previous one intact,
so an officer can compare what changed.

The run covers two detectors, not one:

  rings - closed invoice loops, from cycle_detection. The graph is built WITH
          control edges, so loops that close through a shared director or
          registered address are found too, not only loops closed by a bill.

  mills - fake invoice mills, from mill_detection. Not loops at all: a shell
          selling to many unrelated buyers and buying from nobody. Cycle
          detection is structurally blind to these, and they are the most
          common form of real GST fraud.

Both land in the same FlaggedRing table with a `kind`, so the API, the queue
and the dashboard treat them uniformly.
"""
from __future__ import annotations

import hashlib

from django.db import transaction
from django.utils import timezone

from core.models import Dataset, active_dataset

from .cycle_detection import detect_rings
from .graph_builder import build_graph_from_dataframes, graph_summary, load_dataframes
from .mill_detection import detect_mills
from .models import DetectionRun, FlaggedRing, RiskScore
from .risk_scoring import (
    MODEL_PATH,
    FEATURE_NAMES,
    load_metadata,
    ring_risk,
    score_network,
)
from .settings_helpers import max_ring_size, mill_min_score, risk_threshold


def model_version() -> str:
    """
    A short, stable fingerprint of the scoring model actually in use.

    Recorded on every run and copied into every ledger block that run produces,
    so a confirmed ring can always be traced back to the exact model that
    flagged it - and so promoting a new model is visible in the audit trail
    rather than silent.
    """
    digest = hashlib.sha256()
    try:
        digest.update(MODEL_PATH.read_bytes())
    except OSError:
        digest.update(b"no-model-artifact")
    digest.update("|".join(FEATURE_NAMES).encode("utf-8"))
    return digest.hexdigest()[:16]


def _default_run_name(dataset: Dataset) -> str:
    n = dataset.runs.count() + 1
    return f"Detection {n}"


def _carry_forward_decisions(dataset: Dataset) -> dict[str, FlaggedRing]:
    """
    The most recent officer decision per pattern, across earlier runs of this
    dataset.

    An officer who already ruled on a ring should not have to rule on it again
    just because detection was re-run over the same data. Decisions are keyed
    by the ring's order-independent signature, so the same set of companies
    carries its verdict forward.
    """
    decided: dict[str, FlaggedRing] = {}
    previous = (
        FlaggedRing.objects.filter(run__dataset=dataset)
        .exclude(status=FlaggedRing.STATUS_PENDING)
        .select_related("reviewed_by")
        .order_by("reviewed_at")
    )
    for ring in previous:
        decided[ring.signature] = ring
    return decided


@transaction.atomic
def execute_run(
    dataset: Dataset | None = None,
    name: str = "",
    user=None,
    note: str = "",
) -> DetectionRun:
    """Run both detectors over a dataset and store the result as one run."""
    dataset = dataset or active_dataset()
    if dataset is None:
        raise ValueError("No dataset is active. Upload a companies/invoices CSV pair first.")

    companies, invoices = load_dataframes(dataset)
    if companies.empty:
        raise ValueError("This dataset has no companies in it.")

    threshold = risk_threshold()
    meta = load_metadata()

    run = DetectionRun.objects.create(
        dataset=dataset,
        name=(name or "").strip() or _default_run_name(dataset),
        note=note or "",
        created_by=user if (user is not None and user.is_authenticated) else None,
        model_version=model_version(),
        model_trained_at=str(meta.get("trained_at", "")),
        risk_threshold=threshold,
    )

    # Two graphs, on purpose.
    #
    # The model's four cycle features (in_cycle_count, min_cycle_length,
    # min_cycle_amount_cv, max_cycle_value_log) were learned on a pure invoice
    # graph. Feeding it cycle counts inflated by control edges would be scoring
    # outside its training distribution - the numbers would move for a reason
    # the model has never seen, and the scores would not mean what they claim.
    #
    # So features come from the invoice-only graph, exactly as at training
    # time, while the reported alerts come from the control-augmented graph.
    # The score stays honest; the extra rings still get surfaced.
    trade_graph = build_graph_from_dataframes(companies, invoices)
    feature_rings = detect_rings(trade_graph, max_length=max_ring_size())

    graph = build_graph_from_dataframes(companies, invoices, include_control_edges=True)
    rings = detect_rings(graph, max_length=max_ring_size())
    mills = detect_mills(companies, invoices, min_score=mill_min_score())

    company_scores = score_network(companies, invoices, feature_rings)

    carried = _carry_forward_decisions(dataset)

    # ---- store per-company scores ----------------------------------------
    RiskScore.objects.bulk_create(
        [
            RiskScore(
                run=run,
                company_id=int(cid),
                score=float(row["score"]),
                feature_snapshot=row["features"],
                explanation=row["explanation"],
            )
            for cid, row in company_scores.iterrows()
        ],
        batch_size=500,
    )

    # ---- store alerts -----------------------------------------------------
    alerts: list[FlaggedRing] = []

    for evidence in rings:
        score, explanation = ring_risk(evidence, company_scores)
        alerts.append(
            FlaggedRing(
                run=run,
                kind=FlaggedRing.KIND_RING,
                closure=evidence.get("closure", FlaggedRing.CLOSURE_INVOICE),
                company_ids=evidence["company_ids"],
                invoice_ids=evidence["invoice_ids"],
                total_cycle_value=evidence["total_cycle_value"],
                risk_score=score,
                explanation=explanation,
                evidence={
                    "length": evidence.get("length"),
                    "hop_amounts": evidence.get("hop_amounts", []),
                    "amount_cv": evidence.get("amount_cv"),
                    "invoice_count": evidence.get("invoice_count"),
                    "eway_missing_count": evidence.get("eway_missing_count"),
                    "eway_missing_ratio": evidence.get("eway_missing_ratio"),
                    "control_links": evidence.get("control_links", []),
                },
            )
        )

    for evidence in mills:
        alerts.append(
            FlaggedRing(
                run=run,
                kind=FlaggedRing.KIND_MILL,
                closure=FlaggedRing.CLOSURE_INVOICE,
                company_ids=evidence["company_ids"],
                invoice_ids=evidence["invoice_ids"],
                total_cycle_value=evidence["total_cycle_value"],
                risk_score=evidence["risk_score"],
                explanation=evidence["explanation"],
                evidence=dict(
                    evidence["evidence"],
                    mill_company_id=evidence["mill_company_id"],
                    mill_company_name=evidence["mill_company_name"],
                ),
            )
        )

    # Apply any decision the officer already made about the same pattern.
    for alert in alerts:
        prior = carried.get(alert.signature)
        if prior is None:
            continue
        alert.status = prior.status
        alert.officer_confirmed = prior.officer_confirmed
        alert.confirmed_at = prior.confirmed_at
        alert.dismissal_reason = prior.dismissal_reason
        alert.review_note = prior.review_note
        alert.reviewed_by = prior.reviewed_by
        alert.reviewed_at = prior.reviewed_at

    FlaggedRing.objects.bulk_create(alerts, batch_size=500)

    # ---- roll up ----------------------------------------------------------
    high_risk = [a for a in alerts if a.risk_score >= threshold]
    run.companies_scored = len(company_scores)
    run.rings_detected = sum(1 for a in alerts if a.kind == FlaggedRing.KIND_RING)
    run.mills_detected = sum(1 for a in alerts if a.kind == FlaggedRing.KIND_MILL)
    run.high_risk_count = len(high_risk)
    run.total_value_at_risk = sum((a.total_cycle_value for a in high_risk), start=0)
    run.finished_at = timezone.now()
    run.save(
        update_fields=[
            "companies_scored", "rings_detected", "mills_detected",
            "high_risk_count", "total_value_at_risk", "finished_at",
        ]
    )

    run.graph_summary = graph_summary(graph)  # transient, for the API response
    return run
