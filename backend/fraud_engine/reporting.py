"""
The supervisor's case report.

The workflow: an officer works through the alert queue, confirming or
dismissing each one, then issues a report. It goes by email to the officer and
to their supervisor, and its content hash goes into the audit ledger - so the
report a supervisor approved can later be proven to be the report on file.

DESIGN CONSTRAINT: ONE PAGE
    A supervisor reads dozens of these. The report leads with the decision and
    the money, puts the evidence one line per case, and pushes provenance to
    the footer. Everything here is generated from stored evidence - the risk
    score the model produced, the SHAP sentences it already wrote, the officer's
    own note. Nothing is invented or rephrased by a language model: this
    document can become the basis for recovery proceedings against a real
    business, and a fabricated sentence in it would be a serious problem.

    Rendered as inline-styled HTML tables rather than a stylesheet, because
    that is the only layout that survives Outlook, Gmail and Apple Mail intact.
    The same HTML is also the source for the PDF (render_pdf, below): one
    document, two ways to look at it, never two things that could drift apart.

WHY A COMPANY ALSO GETS ITS OWN REPORT
    A run report is a supervisor's inbox document: dozens of cases, one page,
    built for a five-minute read. It is the wrong shape when an officer is
    looking at ONE flagged company and wants "why is this red, and what do we
    know about it" as a single file they can save to a case folder or hand to
    someone else. render_company_report_html builds that: the company's own
    details plus the same SHAP-derived explanation sentences already shown in
    the evidence panel, with nothing recomputed or reworded - it is a different
    shape of the same evidence, not a second opinion.
"""
from __future__ import annotations

import hashlib
import io
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from core.models import Company

from .models import CaseReport, FlaggedRing

# --- palette: ink and brass, an audit document, not a dashboard ------------
INK = "#141a24"
BODY = "#3b4653"
MUTED = "#6e7988"
RULE = "#dce1e7"
WASH = "#f5f6f8"
BRASS = "#8f6410"
BRASS_WASH = "#f3ead7"
DANGER = "#8c3a2e"
GOOD = "#2f6b45"

FONT = "'Helvetica Neue', Helvetica, Arial, sans-serif"


def inr(value) -> str:
    """Rupees, the way an Indian officer reads them."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n >= 1e7:
        return f"₹{n / 1e7:.2f} Cr"
    if n >= 1e5:
        return f"₹{n / 1e5:.2f} L"
    return f"₹{n:,.0f}"


def _esc(text) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _top_reason(alert: FlaggedRing) -> str:
    for reason in alert.explanation or []:
        if reason.get("direction") == "increases_risk" and reason.get("text"):
            return reason["text"]
    for reason in alert.explanation or []:
        if reason.get("text"):
            return reason["text"]
    return "No explanation was recorded for this alert."


def build_summary(run) -> dict:
    """The facts the report is assembled from. Also stored on the CaseReport."""
    alerts = list(run.rings.all())
    confirmed = [a for a in alerts if a.status == FlaggedRing.STATUS_CONFIRMED]
    dismissed = [a for a in alerts if a.status == FlaggedRing.STATUS_DISMISSED]
    pending = [a for a in alerts if a.status == FlaggedRing.STATUS_PENDING]

    company_ids = {cid for a in confirmed for cid in (a.company_ids or [])}
    names = dict(
        Company.objects.filter(id__in=company_ids).values_list("id", "name")
    )

    reason_labels = dict(FlaggedRing.DISMISSAL_REASONS)
    dismissal_breakdown: dict[str, int] = {}
    for alert in dismissed:
        label = reason_labels.get(alert.dismissal_reason, "Unspecified")
        dismissal_breakdown[label] = dismissal_breakdown.get(label, 0) + 1

    confirmed_value = sum(
        (a.total_cycle_value or Decimal(0) for a in confirmed), start=Decimal(0)
    )

    return {
        "run_name": run.name,
        "dataset_name": run.dataset.name,
        "run_date": run.started_at.isoformat() if run.started_at else None,
        "alerts_total": len(alerts),
        "confirmed_count": len(confirmed),
        "dismissed_count": len(dismissed),
        "pending_count": len(pending),
        "confirmed_value": str(confirmed_value),
        "companies_implicated": len(company_ids),
        "rings_confirmed": sum(1 for a in confirmed if a.kind == FlaggedRing.KIND_RING),
        "mills_confirmed": sum(1 for a in confirmed if a.kind == FlaggedRing.KIND_MILL),
        "dismissal_breakdown": dismissal_breakdown,
        "model_version": run.model_version,
        "risk_threshold": run.risk_threshold,
        "cases": [
            {
                "id": a.id,
                "kind": a.get_kind_display(),
                "closure": a.closure,
                "risk_score": round(a.risk_score, 1),
                "value": str(a.total_cycle_value),
                "companies": [names.get(c, f"Company {c}") for c in (a.company_ids or [])[:6]],
                "company_count": len(a.company_ids or []),
                "reason": _top_reason(a),
                "note": a.review_note,
                "reviewed_by": a.reviewed_by.username if a.reviewed_by else None,
            }
            for a in sorted(confirmed, key=lambda x: -x.risk_score)
        ],
    }


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _stat(label: str, value: str, colour: str = INK) -> str:
    return (
        f'<td style="padding:0 18px 0 0;vertical-align:top;">'
        f'<div style="font:600 10px {FONT};letter-spacing:.11em;'
        f'text-transform:uppercase;color:{MUTED};padding-bottom:4px;">{_esc(label)}</div>'
        f'<div style="font:600 22px {FONT};color:{colour};line-height:1;">{_esc(value)}</div>'
        f"</td>"
    )


def _case_row(index: int, case: dict) -> str:
    chain = " → ".join(_esc(n) for n in case["companies"])
    if case["company_count"] > len(case["companies"]):
        chain += f" … (+{case['company_count'] - len(case['companies'])})"

    closure_note = ""
    if case["closure"] == FlaggedRing.CLOSURE_CONTROL:
        closure_note = (
            f'<span style="display:inline-block;background:{BRASS_WASH};color:{BRASS};'
            f'font:700 9px {FONT};letter-spacing:.08em;padding:2px 6px;margin-left:6px;'
            f'border-radius:2px;">CLOSED BY SHARED OWNERSHIP</span>'
        )

    note = ""
    if case.get("note"):
        note = (
            f'<div style="font:italic 12px {FONT};color:{MUTED};padding-top:6px;">'
            f"Officer's note: {_esc(case['note'])}</div>"
        )

    return f"""
    <tr>
      <td style="padding:14px 0;border-bottom:1px solid {RULE};vertical-align:top;">
        <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
          <tr>
            <td style="vertical-align:top;">
              <div style="font:600 14px {FONT};color:{INK};">
                {index}. {_esc(case['kind'])} · Case #{case['id']}{closure_note}
              </div>
              <div style="font:400 12px {FONT};color:{BODY};padding-top:4px;">{chain}</div>
              <div style="font:400 12.5px {FONT};color:{BODY};padding-top:7px;line-height:1.5;">
                {_esc(case['reason'])}
              </div>
              {note}
            </td>
            <td width="120" style="vertical-align:top;text-align:right;padding-left:16px;">
              <div style="font:700 19px {FONT};color:{DANGER};line-height:1;">{case['risk_score']}</div>
              <div style="font:400 10px {FONT};color:{MUTED};padding-top:3px;">RISK SCORE</div>
              <div style="font:600 13px {FONT};color:{INK};padding-top:9px;">{inr(case['value'])}</div>
              <div style="font:400 10px {FONT};color:{MUTED};padding-top:2px;">AT RISK</div>
            </td>
          </tr>
        </table>
      </td>
    </tr>"""


def render_report_html(run, summary: dict, officer: str, supervisors: list[str]) -> str:
    """Build the one-page report a supervisor receives."""
    from .settings_helpers import organisation_name

    org = organisation_name()
    generated = timezone.localtime().strftime("%d %B %Y, %H:%M")
    cases_html = (
        "".join(_case_row(i, c) for i, c in enumerate(summary["cases"], start=1))
        or f'<tr><td style="padding:18px 0;font:400 13px {FONT};color:{MUTED};">'
           "No cases were confirmed as fraudulent in this run.</td></tr>"
    )

    dismissal_rows = "".join(
        f'<tr><td style="font:400 12px {FONT};color:{BODY};padding:3px 14px 3px 0;">{_esc(label)}</td>'
        f'<td style="font:600 12px {FONT};color:{INK};padding:3px 0;">{count}</td></tr>'
        for label, count in summary["dismissal_breakdown"].items()
    ) or (
        f'<tr><td style="font:400 12px {FONT};color:{MUTED};padding:3px 0;">'
        "Nothing was dismissed in this run.</td></tr>"
    )

    lead = (
        f"Of {summary['alerts_total']} alert(s) raised in this run, the reviewing officer "
        f"confirmed <strong>{summary['confirmed_count']}</strong> as fraudulent, involving "
        f"<strong>{summary['companies_implicated']} companies</strong> and "
        f"<strong>{inr(summary['confirmed_value'])}</strong> of circulated value. "
        f"{summary['dismissed_count']} alert(s) were examined and cleared."
    )
    if summary["pending_count"]:
        lead += f" {summary['pending_count']} alert(s) remain unreviewed."

    return f"""<div style="margin:0;padding:24px;background:{WASH};">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:700px;margin:0 auto;background:#ffffff;border:1px solid {RULE};">
  <tr>
    <td style="padding:26px 30px 20px;border-bottom:2px solid {INK};">
      <div style="font:700 10px {FONT};letter-spacing:.16em;text-transform:uppercase;color:{BRASS};padding-bottom:10px;">
        {_esc(org)} · Case Report
      </div>
      <div style="font:600 25px {FONT};color:{INK};line-height:1.15;">{_esc(run.name)}</div>
      <div style="font:400 12.5px {FONT};color:{MUTED};padding-top:7px;">
        Dataset: {_esc(summary['dataset_name'])} &nbsp;·&nbsp; Issued {generated} &nbsp;·&nbsp; Officer: {_esc(officer)}
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px 0;">
      <div style="font:400 14px {FONT};color:{BODY};line-height:1.62;">{lead}</div>
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px;">
      <table role="presentation" cellpadding="0" cellspacing="0">
        <tr>
          {_stat("Confirmed", str(summary["confirmed_count"]), DANGER)}
          {_stat("Value at risk", inr(summary["confirmed_value"]), INK)}
          {_stat("Companies", str(summary["companies_implicated"]), INK)}
          {_stat("Cleared", str(summary["dismissed_count"]), GOOD)}
        </tr>
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:0 30px;">
      <div style="font:700 10px {FONT};letter-spacing:.14em;text-transform:uppercase;color:{BRASS};
                  padding:8px 0 2px;border-top:1px solid {RULE};">
        Confirmed cases, highest risk first
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        {cases_html}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px 0;">
      <div style="font:700 10px {FONT};letter-spacing:.14em;text-transform:uppercase;color:{BRASS};padding-bottom:8px;">
        Alerts examined and cleared
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0">{dismissal_rows}</table>
      <div style="font:400 11.5px {FONT};color:{MUTED};padding-top:8px;line-height:1.55;">
        Cleared alerts are retained as training data. They are how the detector learns
        what ordinary trade looks like, and they are the only record of where it was wrong.
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:22px 30px 26px;">
      <div style="border-top:1px solid {RULE};padding-top:14px;font:400 11px {FONT};color:{MUTED};line-height:1.7;">
        <strong style="color:{BODY};">Provenance.</strong>
        Model version <span style="font-family:monospace;">{_esc(summary['model_version'] or 'n/a')}</span> ·
        high-risk threshold {summary['risk_threshold']:.0f} ·
        run started {_esc(run.started_at.strftime('%d %b %Y %H:%M') if run.started_at else '—')}.<br>
        Every confirmed case above is recorded in the tamper-evident audit ledger. This report's
        own content hash is written to that ledger, so the document a supervisor approved can
        later be proven to be the document on file.<br>
        <strong style="color:{BODY};">Recipients.</strong> {_esc(', '.join(supervisors) or 'none configured')}<br>
        <em>Machine-assisted analysis. Every case above was reviewed and confirmed by a named
        officer; nothing in this system blocks a refund automatically.</em>
      </div>
    </td>
  </tr>
</table>
</div>"""


def content_hash(html: str, summary: dict) -> str:
    """SHA-256 over the rendered report plus the facts it was built from."""
    import json

    material = html + "|" + json.dumps(summary, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def plain_text_version(summary: dict, officer: str) -> str:
    """Fallback body for mail clients that refuse HTML."""
    lines = [
        f"CASE REPORT — {summary['run_name']}",
        f"Dataset: {summary['dataset_name']}",
        f"Officer: {officer}",
        "",
        f"Confirmed fraudulent : {summary['confirmed_count']}",
        f"Value at risk        : {inr(summary['confirmed_value'])}",
        f"Companies implicated : {summary['companies_implicated']}",
        f"Examined and cleared : {summary['dismissed_count']}",
        "",
        "CONFIRMED CASES",
    ]
    for i, case in enumerate(summary["cases"], start=1):
        lines.append(
            f"{i}. {case['kind']} #{case['id']} — risk {case['risk_score']}, "
            f"{inr(case['value'])} — {' → '.join(case['companies'])}"
        )
        lines.append(f"   {case['reason']}")
    if not summary["cases"]:
        lines.append("(none)")
    lines += [
        "",
        f"Model version {summary['model_version']}, threshold {summary['risk_threshold']:.0f}.",
        "Every case was reviewed and confirmed by a named officer.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def render_pdf(html: str) -> bytes:
    """
    Convert report HTML to a PDF: what gets viewed in-app, downloaded, and
    attached to the email.

    xhtml2pdf's built-in fonts have no glyph for the rupee sign - it prints as
    a small black box instead of ₹. Everywhere else this codebase renders ₹
    (the browser preview, the HTML email body) that is fine, because real
    browsers and mail clients ship fonts that cover it. A generated PDF is not
    a browser, so the swap to the ASCII "Rs." every Indian financial document
    already falls back to happens only on this path - the HTML shown in the
    app is untouched.
    """
    import logging

    from xhtml2pdf import pisa

    # xhtml2pdf warns, per call, about CSS it doesn't support (em-based
    # letter-spacing, in this report's headings) and just ignores it - the
    # PDF still renders correctly, only slightly less tracked-out than the
    # HTML version. That is a cosmetic trade worth making for a pure-Python
    # renderer; logging it as a warning on every single report generated is
    # not, so it is quieted to errors only.
    logging.getLogger("xhtml2pdf").setLevel(logging.ERROR)

    pdf_ready_html = html.replace("₹", "Rs. ")
    buffer = io.BytesIO()
    result = pisa.CreatePDF(pdf_ready_html, dest=buffer)
    if result.err:
        raise RuntimeError(f"PDF generation failed ({result.err} error(s)).")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Company report
# ---------------------------------------------------------------------------


def build_company_summary(company: Company) -> dict:
    """
    Everything a company report is built from: its own record, its trade
    totals, its most recent risk assessment, and every alert it appears in.

    Deliberately reads the same evidence the Network page's evidence panel
    already shows (CompanyDetailSerializer in core/serializers.py) rather than
    recomputing anything, so the PDF can never say something different from
    what the officer already saw on screen before downloading it.
    """
    latest_score = company.risk_scores.order_by("-computed_at").first()

    sales = company.sales_invoices.all()
    purchases = company.purchase_invoices.all()
    sales_value = sales.aggregate(total=Sum("amount"))["total"] or Decimal(0)
    purchase_value = purchases.aggregate(total=Sum("amount"))["total"] or Decimal(0)

    # Same Python-side filter CompanyDetailSerializer.get_rings uses: JSONField
    # `contains` is PostgreSQL-only and would break the SQLite test path, and
    # there are only ever tens of alerts per run, so filtering here costs
    # nothing worth avoiding.
    alerts_qs = FlaggedRing.objects.all()
    if latest_score is not None and latest_score.run_id:
        alerts_qs = alerts_qs.filter(run_id=latest_score.run_id)
    alerts = [a for a in alerts_qs if company.id in (a.company_ids or [])]

    reason_labels = dict(FlaggedRing.DISMISSAL_REASONS)

    return {
        "company_id": company.id,
        "name": company.name,
        "gstin": company.gstin,
        "pan": company.pan,
        "director_name": company.director_name,
        "registered_address": company.registered_address,
        "registered_date": company.registered_date.isoformat(),
        "declared_turnover": str(company.declared_turnover),
        "sales_count": sales.count(),
        "sales_value": str(sales_value),
        "purchase_count": purchases.count(),
        "purchase_value": str(purchase_value),
        "risk_score": round(latest_score.score, 2) if latest_score else None,
        "risk_computed_at": latest_score.computed_at.isoformat() if latest_score else None,
        "model_version": latest_score.run.model_version if latest_score and latest_score.run_id else None,
        "risk_threshold": latest_score.run.risk_threshold if latest_score and latest_score.run_id else None,
        "explanation": (latest_score.explanation if latest_score else []),
        "alerts": [
            {
                "id": a.id,
                "kind": a.get_kind_display(),
                "closure": a.closure,
                "risk_score": round(a.risk_score, 1),
                "ring_size": a.ring_size,
                "status": a.status,
                "status_label": a.get_status_display(),
                "dismissal_reason": reason_labels.get(a.dismissal_reason, ""),
                "review_note": a.review_note,
                "reviewed_by": a.reviewed_by.username if a.reviewed_by_id else None,
            }
            for a in sorted(alerts, key=lambda x: -x.risk_score)
        ],
    }


def _company_stat_row(label: str, value: str) -> str:
    return (
        f'<tr><td style="font:400 12px {FONT};color:{MUTED};padding:3px 14px 3px 0;'
        f'vertical-align:top;">{_esc(label)}</td>'
        f'<td style="font:600 12.5px {FONT};color:{INK};padding:3px 0;">{_esc(value)}</td></tr>'
    )


def _company_explanation_html(explanation: list[dict]) -> str:
    if not explanation:
        return (
            f'<div style="font:400 12.5px {FONT};color:{MUTED};padding:6px 0;">'
            "This company was not a candidate in any circular-trade loop, so it was "
            "never scored - there is no model explanation to show.</div>"
        )
    rows = []
    for reason in explanation:
        raises = reason.get("direction") == "increases_risk"
        colour = DANGER if raises else GOOD
        marker = "&#9650;" if raises else "&#9660;"  # ▲ / ▼, as ASCII-safe entities
        rows.append(
            f'<div style="padding:6px 0;border-bottom:1px solid {RULE};">'
            f'<span style="font:700 11px {FONT};color:{colour};">{marker}</span> '
            f'<span style="font:400 12.5px {FONT};color:{BODY};">{_esc(reason.get("text", ""))}</span>'
            f"</div>"
        )
    return "".join(rows)


def _company_alert_row(alert: dict) -> str:
    status_colour = {
        "confirmed": DANGER,
        "dismissed": GOOD,
        "pending": MUTED,
    }.get(alert["status"], MUTED)
    closure_note = (
        " (closed by shared ownership)" if alert["closure"] == FlaggedRing.CLOSURE_CONTROL else ""
    )
    note = (
        f'<div style="font:italic 11.5px {FONT};color:{MUTED};padding-top:3px;">'
        f"{_esc(alert['dismissal_reason'] or alert['review_note'])}</div>"
        if (alert["dismissal_reason"] or alert["review_note"])
        else ""
    )
    return f"""
    <tr>
      <td style="padding:9px 0;border-bottom:1px solid {RULE};">
        <div style="font:600 12.5px {FONT};color:{INK};">
          {_esc(alert['kind'])} #{alert['id']}{closure_note} &nbsp;·&nbsp;
          <span style="color:{status_colour};">{_esc(alert['status_label'])}</span>
        </div>
        <div style="font:400 11.5px {FONT};color:{MUTED};padding-top:2px;">
          {alert['ring_size']} companies · risk {alert['risk_score']}
        </div>
        {note}
      </td>
    </tr>"""


def render_company_report_html(summary: dict, officer: str) -> str:
    """
    One company, one document: its registration details, its trade totals,
    why the model rated it the way it did, and every alert it has appeared in.

    Same ink-and-brass palette and inline-table layout as the run report, for
    the same reason - it has to render identically in a browser tab, a PDF,
    and the handful of mail clients that still matter.
    """
    from .settings_helpers import organisation_name

    org = organisation_name()
    generated = timezone.localtime().strftime("%d %B %Y, %H:%M")

    score = summary["risk_score"]
    score_html = (
        f'<span style="font:700 30px {FONT};color:{DANGER};">{score}</span>'
        if score is not None
        else f'<span style="font:600 16px {FONT};color:{MUTED};">Not scored</span>'
    )

    alerts_html = (
        "".join(_company_alert_row(a) for a in summary["alerts"])
        or f'<tr><td style="font:400 12.5px {FONT};color:{MUTED};padding:10px 0;">'
           "This company does not appear in any flagged ring or mill.</td></tr>"
    )

    provenance = ""
    if summary.get("model_version"):
        provenance = (
            f'Model version <span style="font-family:monospace;">{_esc(summary["model_version"])}</span> '
            f'&nbsp;·&nbsp; high-risk threshold {summary["risk_threshold"]:.0f} &nbsp;·&nbsp; '
        )

    return f"""<div style="margin:0;padding:24px;background:{WASH};">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:700px;margin:0 auto;background:#ffffff;border:1px solid {RULE};">
  <tr>
    <td style="padding:26px 30px 20px;border-bottom:2px solid {INK};">
      <div style="font:700 10px {FONT};letter-spacing:.16em;text-transform:uppercase;color:{BRASS};padding-bottom:10px;">
        {_esc(org)} · Company Report
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        <tr>
          <td style="vertical-align:top;">
            <div style="font:600 23px {FONT};color:{INK};line-height:1.2;">{_esc(summary['name'])}</div>
            <div style="font:400 12px {FONT};color:{MUTED};font-family:monospace;padding-top:4px;">
              {_esc(summary['gstin'])}
            </div>
          </td>
          <td width="110" style="vertical-align:top;text-align:right;">
            {score_html}
            <div style="font:400 10px {FONT};color:{MUTED};padding-top:2px;">RISK SCORE</div>
          </td>
        </tr>
      </table>
      <div style="font:400 12px {FONT};color:{MUTED};padding-top:9px;">
        Issued {generated} &nbsp;·&nbsp; Requested by {_esc(officer)}
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px 0;">
      <div style="font:700 10px {FONT};letter-spacing:.14em;text-transform:uppercase;color:{BRASS};padding-bottom:8px;">
        Registration
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        {_company_stat_row("PAN", summary['pan'])}
        {_company_stat_row("Director", summary['director_name'])}
        {_company_stat_row("Registered address", summary['registered_address'])}
        {_company_stat_row("Registered on", summary['registered_date'])}
        {_company_stat_row("Declared annual turnover", inr(summary['declared_turnover']))}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:18px 30px 0;">
      <table role="presentation" cellpadding="0" cellspacing="0">
        {_stat("Sales invoices", str(summary['sales_count']), INK)}
        {_stat("Sold", inr(summary['sales_value']), INK)}
        {_stat("Purchase invoices", str(summary['purchase_count']), INK)}
        {_stat("Bought", inr(summary['purchase_value']), INK)}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px 0;">
      <div style="font:700 10px {FONT};letter-spacing:.14em;text-transform:uppercase;color:{BRASS};padding-bottom:2px;">
        Why this score
      </div>
      {_company_explanation_html(summary['explanation'])}
    </td>
  </tr>

  <tr>
    <td style="padding:20px 30px 0;">
      <div style="font:700 10px {FONT};letter-spacing:.14em;text-transform:uppercase;color:{BRASS};padding-bottom:2px;">
        Appears in
      </div>
      <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
        {alerts_html}
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:22px 30px 26px;">
      <div style="border-top:1px solid {RULE};padding-top:14px;font:400 11px {FONT};color:{MUTED};line-height:1.7;">
        <strong style="color:{BODY};">Provenance.</strong>
        {provenance}risk computed {_esc(summary['risk_computed_at'] or 'not yet computed')}.<br>
        <em>Machine-assisted analysis. This document explains a risk score; it is not itself
        a finding of fraud, and confirms nothing that a named officer has not confirmed.</em>
      </div>
    </td>
  </tr>
</table>
</div>"""


def plain_text_company_version(summary: dict, officer: str) -> str:
    """Fallback body for mail clients that refuse HTML."""
    lines = [
        f"COMPANY REPORT — {summary['name']} ({summary['gstin']})",
        f"Requested by: {officer}",
        "",
        f"Risk score           : {summary['risk_score'] if summary['risk_score'] is not None else 'not scored'}",
        f"Director             : {summary['director_name']}",
        f"Registered address   : {summary['registered_address']}",
        f"Registered on        : {summary['registered_date']}",
        f"Declared turnover    : {inr(summary['declared_turnover'])}",
        f"Sales / purchases    : {summary['sales_count']} invoices sold "
        f"({inr(summary['sales_value'])}) / {summary['purchase_count']} bought "
        f"({inr(summary['purchase_value'])})",
        "",
        "WHY THIS SCORE",
    ]
    for reason in summary["explanation"]:
        lines.append(f"  - {reason.get('text', '')}")
    if not summary["explanation"]:
        lines.append("  (not a candidate in any circular-trade loop)")
    lines += ["", "APPEARS IN"]
    for a in summary["alerts"]:
        lines.append(f"  {a['kind']} #{a['id']} — {a['status_label']}, risk {a['risk_score']}")
    if not summary["alerts"]:
        lines.append("  (no flagged ring or mill)")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Cover email — the short note that carries the PDF attachment
# ---------------------------------------------------------------------------


def _cover_lead(report: CaseReport) -> str:
    summary = report.summary or {}
    if report.report_type == CaseReport.REPORT_TYPE_COMPANY:
        score = summary.get("risk_score")
        score_note = f"a risk score of {score}" if score is not None else "no risk score yet"
        return (
            f"Attached is the company report for <strong>{_esc(summary.get('name', ''))}</strong> "
            f"({_esc(summary.get('gstin', ''))}), currently rated {score_note}. It sets out the "
            "company's registration details, trade totals, and the evidence behind its score."
        )
    return (
        f"Attached is the case report for <strong>{_esc(summary.get('run_name', report.title))}</strong>. "
        f"Of {summary.get('alerts_total', 0)} alert(s) raised, "
        f"<strong>{summary.get('confirmed_count', 0)} were confirmed as fraudulent</strong> and "
        f"{summary.get('dismissed_count', 0)} were examined and cleared."
    )


def render_cover_email_html(report: CaseReport, officer: str) -> str:
    """
    The email BODY. Short, on purpose: the full document is the PDF attached
    to it, not another copy of it pasted into the message. A supervisor
    reading this on a phone should be able to tell in five seconds what it is
    and who to ask about it, then open the attachment for the rest.
    """
    from .settings_helpers import organisation_name

    org = organisation_name()
    generated = timezone.localtime().strftime("%d %B %Y, %H:%M")

    return f"""<div style="margin:0;padding:24px;background:{WASH};">
<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="max-width:560px;margin:0 auto;background:#ffffff;border:1px solid {RULE};">
  <tr>
    <td style="padding:24px 28px 18px;border-bottom:2px solid {INK};">
      <div style="font:700 10px {FONT};letter-spacing:.16em;text-transform:uppercase;color:{BRASS};padding-bottom:8px;">
        {_esc(org)}
      </div>
      <div style="font:600 18px {FONT};color:{INK};">{_esc(report.title)}</div>
    </td>
  </tr>
  <tr>
    <td style="padding:20px 28px;">
      <div style="font:400 13.5px {FONT};color:{BODY};line-height:1.65;">{_cover_lead(report)}</div>
      <div style="font:400 12px {FONT};color:{MUTED};padding-top:14px;">
        Issued {generated} by {_esc(officer)}. The full report is attached as a PDF.
      </div>
    </td>
  </tr>
  <tr>
    <td style="padding:16px 28px 22px;border-top:1px solid {RULE};">
      <div style="font:400 10.5px {FONT};color:{MUTED};line-height:1.6;">
        <em>Machine-assisted analysis, sent from {_esc(org)}'s GST fraud detection console.
        The attached document's content is hashed into a tamper-evident audit ledger at the
        moment it is issued.</em>
      </div>
    </td>
  </tr>
</table>
</div>"""


def plain_text_cover(report: CaseReport, officer: str) -> str:
    if report.report_type == CaseReport.REPORT_TYPE_COMPANY:
        summary = report.summary or {}
        lead = (
            f"Attached is the company report for {summary.get('name', '')} "
            f"({summary.get('gstin', '')})."
        )
    else:
        lead = f"Attached is the case report for {report.title}."
    return f"{report.title}\n\n{lead}\n\nIssued by {officer}. See the attached PDF for the full report."
