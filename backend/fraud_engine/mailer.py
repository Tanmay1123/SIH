"""
Sending a report by email.

Deliberately thin. Django already knows how to talk SMTP; this module only
decides who receives a report and turns a failure into a stored error rather
than a 500, because a report that failed to send is a state an officer needs
to see and retry, not a crash.

WHAT GOES IN THE EMAIL
    A short cover note in the message body - a few sentences, readable on a
    phone - with the full report attached as a PDF. It did not used to work
    this way: the first version pasted the entire one-page report into the
    body, which read as a wall of formatting rather than a letter, and gave
    "professional-looking email" nothing to be professional about. The PDF is
    generated fresh from `report.html` at send time rather than stored - the
    row's content hash already guarantees that HTML has not changed since it
    was issued, so regenerating it costs nothing and stores nothing extra.

    The body still carries GSTINs and company names in summary form, and SMTP
    is not a channel confidential taxpayer information should cross in a real
    deployment - production would send a short notification plus an
    authenticated link back into the application instead. That difference is
    worth stating out loud rather than quietly shipping.
"""
from __future__ import annotations

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.utils import timezone

from .models import CaseReport
from .settings_helpers import supervisor_emails


class MailNotConfigured(RuntimeError):
    """Raised when no SMTP host has been configured yet."""


def is_configured() -> bool:
    backend = getattr(settings, "EMAIL_BACKEND", "")
    if "console" in backend or "locmem" in backend:
        return True
    return bool(getattr(settings, "EMAIL_HOST", ""))


def resolve_recipients(officer_email: str = "") -> list[str]:
    """Officer first, then every configured supervisor, de-duplicated."""
    recipients: list[str] = []
    seen: set[str] = set()
    for email in [officer_email, *supervisor_emails()]:
        email = (email or "").strip()
        if email and email.lower() not in seen:
            seen.add(email.lower())
            recipients.append(email)
    return recipients


def send_report(report: CaseReport, officer: str) -> CaseReport:
    """
    Deliver one report - run or company, `report.report_type` says which - as
    a short cover note with the full document attached as a PDF.

    Never raises for a delivery problem - the officer sees the error in the
    Reports tab and can fix the credentials and retry.
    """
    from django.utils.text import slugify

    from . import reporting

    recipients = list(report.recipients or [])
    if not recipients:
        report.status = CaseReport.STATUS_FAILED
        report.error = (
            "No recipients. Set an email address on your account, or configure "
            "REPORT_SUPERVISOR_EMAILS in .env."
        )
        report.save(update_fields=["status", "error"])
        return report

    if not is_configured():
        report.status = CaseReport.STATUS_FAILED
        report.error = (
            "SMTP is not configured. Set EMAIL_HOST, EMAIL_HOST_USER and "
            "EMAIL_HOST_PASSWORD in .env, then try again."
        )
        report.save(update_fields=["status", "error"])
        return report

    try:
        pdf_bytes = reporting.render_pdf(report.html)
        connection = get_connection(fail_silently=False)
        message = EmailMultiAlternatives(
            subject=f"[GST Fraud Detection] {report.title}",
            body=reporting.plain_text_cover(report, officer),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=recipients,
            connection=connection,
        )
        message.attach_alternative(
            reporting.render_cover_email_html(report, officer), "text/html"
        )
        message.attach(
            f"{slugify(report.title) or 'report'}.pdf", pdf_bytes, "application/pdf"
        )
        message.send()
    except Exception as exc:  # noqa: BLE001 - surfaced to the officer verbatim
        report.status = CaseReport.STATUS_FAILED
        report.error = f"{type(exc).__name__}: {exc}"
        report.save(update_fields=["status", "error"])
        return report

    report.status = CaseReport.STATUS_SENT
    report.sent_at = timezone.now()
    report.error = ""
    report.save(update_fields=["status", "sent_at", "error"])
    return report
