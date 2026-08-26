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
"""
from __future__ import annotations

import hashlib
from decimal import Decimal

from django.utils import timezone

from core.models import Company

from .models import FlaggedRing

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
