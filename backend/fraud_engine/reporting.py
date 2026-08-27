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

# --- palette ---------------------------------------------------------------
# Near-monochrome on purpose. Colour in this document carries one meaning -
# red is risk, green is cleared - and nothing else competes with it. The
# previous version tinted headings and labels brass, which on a printed page
# read as stray orange text rather than as structure.
INK = "#16202b"      # headings
BODY = "#39424e"     # running text
MUTED = "#78828f"    # labels, captions, provenance
RULE = "#d8dde3"     # hairlines
RULE_DARK = "#16202b"  # the one heavy rule, under the masthead
DANGER = "#9a2f22"   # risk
GOOD = "#2c6b45"     # cleared

# Used only by the email cover note below, which is still a real email and so
# is still built the email way: inline styles on a table, on a tinted page.
# The reports themselves are print documents and use the stylesheet instead.
WASH = "#f4f6f8"

# xhtml2pdf resolves the 14 standard PDF base fonts by name and silently falls
# back for anything else. "Helvetica" is one of them, so it is what actually
# renders - naming a web font stack here only produced a substitution.
FONT = "Helvetica"

# ---------------------------------------------------------------------------
# The print stylesheet
# ---------------------------------------------------------------------------
# WHY A STYLESHEET AND NOT INLINE STYLES
#     These two documents used to be built as inline-styled nested tables,
#     because they were emailed as the message body and that is the only thing
#     Outlook renders reliably. They are not emailed any more - the mail is a
#     short cover note with the PDF attached - so their only consumer is
#     xhtml2pdf, and inline email HTML is the wrong shape for it: `max-width`
#     with `margin:0 auto` does not centre on a fixed-width page, and nested
#     table padding leaks into three different left edges.
#
# WHAT xhtml2pdf WILL NOT DO, learned the hard way
#     text-transform      ignored - so labels are uppercased in Python instead
#     letter-spacing      ignored in em units, unreliable otherwise - not used
#     border-radius       ignored
#     display:inline-block  ignored, which is why the old badge collided with
#                           the text beside it
#     flex / grid         unsupported entirely; columns are <table> cells
#
# Everything below is confined to what it actually honours: @page and @frame,
# class selectors, pt sizes, solid borders, padding, and table layout.
_STYLESHEET = f"""
@page {{
  size: a4 portrait;
  margin: 1.5cm 1.6cm 2.1cm 1.6cm;
  @frame footer {{
    -pdf-frame-content: page-footer;
    bottom: 1.05cm; left: 1.6cm; right: 1.6cm; height: 0.8cm;
  }}
}}
body {{ font-family: {FONT}; font-size: 9.5pt; color: {BODY}; line-height: 1.45; }}

/* masthead ------------------------------------------------------------- */
.eyebrow    {{ font-size: 7.5pt; font-weight: bold; color: {MUTED}; }}
.doc-title  {{ font-size: 19pt; font-weight: bold; color: {INK}; padding-top: 5pt; }}
.doc-meta   {{ font-size: 8.5pt; color: {MUTED}; padding-top: 4pt; }}
/* The masthead rule lives on a one-cell table, not on a div wrapping the
   whole block. xhtml2pdf draws a div's border-bottom once per block child
   rather than once for the div, so the previous version ruled off under the
   eyebrow, the title AND the meta line - three hairlines where one belongs.
   Table cell borders it gets right. */
.masthead   {{ border-bottom: 1.2pt solid {RULE_DARK}; padding-bottom: 9pt; }}

/* sections ------------------------------------------------------------- */
.lead       {{ font-size: 10pt; color: {BODY}; padding-top: 13pt; line-height: 1.55; }}
.section    {{ font-size: 8pt; font-weight: bold; color: {INK};
               padding: 16pt 0 5pt 0; border-bottom: 0.6pt solid {RULE}; }}

/* the four headline numbers -------------------------------------------- */
.stats      {{ padding-top: 11pt; }}
.stat-label {{ font-size: 7.5pt; color: {MUTED}; padding-bottom: 2pt; }}
.stat-value {{ font-size: 15pt; font-weight: bold; color: {INK}; }}
.stat-risk  {{ font-size: 15pt; font-weight: bold; color: {DANGER}; }}
.stat-good  {{ font-size: 15pt; font-weight: bold; color: {GOOD}; }}

/* one confirmed case ---------------------------------------------------- */
.case       {{ border-bottom: 0.6pt solid {RULE}; padding: 8pt 0; }}
.case-title {{ font-size: 10pt; font-weight: bold; color: {INK}; }}
.case-chain {{ font-size: 8.5pt; color: {BODY}; padding-top: 3pt; }}
.case-why   {{ font-size: 9pt; color: {BODY}; padding-top: 4pt; line-height: 1.5; }}
.case-note  {{ font-size: 8.5pt; color: {MUTED}; padding-top: 4pt; }}
.case-score {{ font-size: 14pt; font-weight: bold; color: {DANGER}; }}
.case-value {{ font-size: 9.5pt; font-weight: bold; color: {INK}; padding-top: 5pt; }}
.case-cap   {{ font-size: 7pt; color: {MUTED}; padding-top: 1pt; }}
.tag        {{ font-size: 7pt; color: {MUTED}; }}

/* key/value rows -------------------------------------------------------- */
.kv-key     {{ font-size: 9pt; color: {MUTED}; padding: 3.5pt 12pt 3.5pt 0; }}
.kv-val     {{ font-size: 9pt; font-weight: bold; color: {INK}; padding: 3.5pt 0; }}

/* explanation bullets ---------------------------------------------------- */
.why        {{ font-size: 9pt; color: {BODY}; padding: 5pt 0;
               border-bottom: 0.6pt solid {RULE}; line-height: 1.45; }}
.why-up     {{ font-weight: bold; color: {DANGER}; }}
.why-down   {{ font-weight: bold; color: {GOOD}; }}

/* footer + provenance ---------------------------------------------------- */
.prov       {{ font-size: 7.5pt; color: {MUTED}; line-height: 1.6;
               padding-top: 9pt; border-top: 0.6pt solid {RULE}; }}
.prov b     {{ color: {BODY}; }}
.pagenum    {{ font-size: 7.5pt; color: {MUTED}; }}
.mono       {{ font-family: Courier; font-size: 8pt; }}
.right      {{ text-align: right; }}
.empty      {{ font-size: 9pt; color: {MUTED}; padding: 8pt 0; }}
"""


def _document(body: str, footer_left: str) -> str:
    """Wrap a report body in the page, the stylesheet, and a numbered footer."""
    return f"""<html><head><meta charset="utf-8"><style>{_STYLESHEET}</style></head>
<body>
<div id="page-footer">
  <table width="100%"><tr>
    <td class="pagenum">{footer_left}</td>
    <td class="pagenum right">Page <pdf:pagenumber> of <pdf:pagecount></td>
  </tr></table>
</div>
{body}
</body></html>"""


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


def _stat(label: str, value: str, cls: str = "stat-value") -> str:
    """One of the headline numbers. `cls` carries the meaning, not a hex code."""
    return (
        f'<td width="25%" valign="top">'
        f'<div class="stat-label">{_esc(label.upper())}</div>'
        f'<div class="{cls}">{_esc(value)}</div>'
        f"</td>"
    )


def _case_row(index: int, case: dict) -> str:
    """
    One confirmed case: what it is on the left, what it is worth on the right.

    The whole row carries page-break-inside:avoid, so a case never splits
    across two pages with its score stranded on the second.
    """
    chain = " &#8594; ".join(_esc(n) for n in case["companies"])
    if case["company_count"] > len(case["companies"]):
        chain += f" &#8230; (+{case['company_count'] - len(case['companies'])} more)"

    # Was an inline-block badge, which xhtml2pdf does not lay out - it rendered
    # jammed against the case number with no gap. A parenthetical reads the
    # same and cannot collide with anything.
    closure_note = ""
    if case["closure"] == FlaggedRing.CLOSURE_CONTROL:
        closure_note = '<span class="tag"> &#183; closed by shared ownership</span>'

    note = ""
    if case.get("note"):
        note = f'<div class="case-note">Officer\'s note: {_esc(case["note"])}</div>'

    return f"""
    <table width="100%" repeat="0" style="page-break-inside: avoid;">
      <tr><td class="case" valign="top">
        <table width="100%">
          <tr>
            <td valign="top">
              <div class="case-title">{index}. {_esc(case['kind'])} &#183; Case #{case['id']}{closure_note}</div>
              <div class="case-chain">{chain}</div>
              <div class="case-why">{_esc(case['reason'])}</div>
              {note}
            </td>
            <td width="88" valign="top" class="right">
              <div class="case-score">{case['risk_score']}</div>
              <div class="case-cap">RISK SCORE</div>
              <div class="case-value">{inr(case['value'])}</div>
              <div class="case-cap">AT RISK</div>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>"""


def render_report_html(run, summary: dict, officer: str, supervisors: list[str]) -> str:
    """Build the one-page report a supervisor receives."""
    from .settings_helpers import organisation_name

    org = organisation_name()
    generated = timezone.localtime().strftime("%d %B %Y, %H:%M")
    cases_html = "".join(
        _case_row(i, c) for i, c in enumerate(summary["cases"], start=1)
    ) or '<div class="empty">No cases were confirmed as fraudulent in this run.</div>'

    dismissal_rows = "".join(
        f'<tr><td class="kv-key" width="72%">{_esc(label)}</td>'
        f'<td class="kv-val">{count}</td></tr>'
        for label, count in summary["dismissal_breakdown"].items()
    ) or '<tr><td class="empty">Nothing was cleared in this run.</td></tr>'

    lead = (
        f"Of {summary['alerts_total']} alert(s) raised in this run, the reviewing officer "
        f"confirmed <strong>{summary['confirmed_count']}</strong> as fraudulent, involving "
        f"<strong>{summary['companies_implicated']} companies</strong> and "
        f"<strong>{inr(summary['confirmed_value'])}</strong> of circulated value. "
        f"{summary['dismissed_count']} alert(s) were examined and cleared."
    )
    if summary["pending_count"]:
        lead += f" {summary['pending_count']} alert(s) remain unreviewed."

    started = run.started_at.strftime("%d %b %Y %H:%M") if run.started_at else "&#8212;"

    body = f"""
<table width="100%"><tr><td class="masthead">
  <div class="eyebrow">{_esc(org.upper())} &#183; CASE REPORT</div>
  <div class="doc-title">{_esc(run.name)}</div>
  <div class="doc-meta">
    Dataset: {_esc(summary['dataset_name'])} &#183;
    Issued {generated} &#183; Officer: {_esc(officer)}
  </div>
</td></tr></table>

<div class="lead">{lead}</div>

<table width="100%" class="stats"><tr>
  {_stat("Confirmed", str(summary["confirmed_count"]), "stat-risk")}
  {_stat("Value at risk", inr(summary["confirmed_value"]))}
  {_stat("Companies", str(summary["companies_implicated"]))}
  {_stat("Cleared", str(summary["dismissed_count"]), "stat-good")}
</tr></table>

<div class="section">CONFIRMED CASES &#183; HIGHEST RISK FIRST</div>
{cases_html}

<div class="section">ALERTS EXAMINED AND CLEARED</div>
<table width="100%">{dismissal_rows}</table>
<div class="case-note">
  Cleared alerts are retained as training data. They are how the detector learns what
  ordinary trade looks like, and the only record of where it was wrong.
</div>

<div class="prov">
  <b>Provenance.</b>
  Model version <span class="mono">{_esc(summary['model_version'] or 'n/a')}</span> &#183;
  high-risk threshold {summary['risk_threshold']:.0f} &#183; run started {started}.<br/>
  Every confirmed case above is recorded in the tamper-evident audit ledger. This report's
  own content hash is written to that ledger, so the document a supervisor approved can
  later be proven to be the document on file.<br/>
  <b>Recipients.</b> {_esc(', '.join(supervisors) or 'none configured')}<br/>
  <i>Machine-assisted analysis. Every case above was reviewed and confirmed by a named
  officer; nothing in this system blocks a refund automatically.</i>
</div>"""

    return _document(body, f"{_esc(org)} &#183; {_esc(run.name)}")


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
        # Formatted here, not isoformat(): this string is printed straight into
        # the report's provenance line, and a raw ISO stamp with microseconds
        # and a UTC offset read as debug output next to "Issued 27 August 2026".
        "risk_computed_at": (
            timezone.localtime(latest_score.computed_at).strftime("%d %B %Y, %H:%M")
            if latest_score
            else None
        ),
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
        f'<tr><td class="kv-key" width="34%" valign="top">{_esc(label)}</td>'
        f'<td class="kv-val">{_esc(value)}</td></tr>'
    )


def _company_explanation_html(explanation: list[dict]) -> str:
    if not explanation:
        return (
            '<div class="empty">This company was not a candidate in any circular-trade '
            "loop, so it was never scored &#8212; there is no model explanation to show.</div>"
        )
    rows = []
    for reason in explanation:
        raises = reason.get("direction") == "increases_risk"
        cls = "why-up" if raises else "why-down"
        marker = "&#9650;" if raises else "&#9660;"  # ▲ / ▼, as ASCII-safe entities
        rows.append(
            f'<div class="why"><span class="{cls}">{marker}</span> '
            f'{_esc(reason.get("text", ""))}</div>'
        )
    return "".join(rows)


def _company_alert_row(alert: dict) -> str:
    cls = {"confirmed": "why-up", "dismissed": "why-down"}.get(alert["status"], "")
    closure_note = (
        " (closed by shared ownership)"
        if alert["closure"] == FlaggedRing.CLOSURE_CONTROL
        else ""
    )
    note = (
        f'<div class="case-note">{_esc(alert["dismissal_reason"] or alert["review_note"])}</div>'
        if (alert["dismissal_reason"] or alert["review_note"])
        else ""
    )
    return f"""
    <tr><td class="case" valign="top">
      <div class="case-title">
        {_esc(alert['kind'])} #{alert['id']}{closure_note} &#183;
        <span class="{cls}">{_esc(alert['status_label'])}</span>
      </div>
      <div class="case-chain">{alert['ring_size']} companies &#183; risk {alert['risk_score']}</div>
      {note}
    </td></tr>"""


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
        f'<div class="case-score" style="font-size:22pt;">{score}</div>'
        f'<div class="case-cap">RISK SCORE</div>'
        if score is not None
        else '<div class="stat-label">NOT SCORED</div>'
    )

    alerts_html = "".join(
        _company_alert_row(a) for a in summary["alerts"]
    ) or '<tr><td class="empty">This company does not appear in any flagged ring or mill.</td></tr>'

    provenance = ""
    if summary.get("model_version"):
        provenance = (
            f'Model version <span class="mono">{_esc(summary["model_version"])}</span> '
            f'&#183; high-risk threshold {summary["risk_threshold"]:.0f} &#183; '
        )

    body = f"""
<table width="100%"><tr><td class="masthead">
  <div class="eyebrow">{_esc(org.upper())} &#183; COMPANY REPORT</div>
  <table width="100%"><tr>
    <td valign="top">
      <div class="doc-title">{_esc(summary['name'])}</div>
      <div class="doc-meta mono">{_esc(summary['gstin'])}</div>
    </td>
    <td width="92" valign="top" class="right">{score_html}</td>
  </tr></table>
  <div class="doc-meta">Issued {generated} &#183; Requested by {_esc(officer)}</div>
</td></tr></table>

<div class="section">REGISTRATION</div>
<table width="100%">
  {_company_stat_row("PAN", summary['pan'])}
  {_company_stat_row("Director", summary['director_name'])}
  {_company_stat_row("Registered address", summary['registered_address'])}
  {_company_stat_row("Registered on", summary['registered_date'])}
  {_company_stat_row("Declared annual turnover", inr(summary['declared_turnover']))}
</table>

<table width="100%" class="stats"><tr>
  {_stat("Sales invoices", str(summary['sales_count']))}
  {_stat("Sold", inr(summary['sales_value']))}
  {_stat("Purchase invoices", str(summary['purchase_count']))}
  {_stat("Bought", inr(summary['purchase_value']))}
</tr></table>

<div class="section">WHY THIS SCORE</div>
{_company_explanation_html(summary['explanation'])}

<div class="section">APPEARS IN</div>
<table width="100%">{alerts_html}</table>

<div class="prov">
  <b>Provenance.</b>
  {provenance}risk computed {_esc(summary['risk_computed_at'] or 'not yet computed')}.<br/>
  <i>Machine-assisted analysis. This document explains a risk score; it is not itself
  a finding of fraud, and confirms nothing that a named officer has not confirmed.</i>
</div>"""

    return _document(body, f"{_esc(org)} &#183; {_esc(summary['name'])}")


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
      <div style="font:700 10px {FONT};letter-spacing:.16em;text-transform:uppercase;color:{MUTED};padding-bottom:8px;">
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
