"""
Sending a case report by email.

Deliberately thin. Django already knows how to talk SMTP; this module only
decides who receives a report and turns a failure into a stored error rather
than a 500, because a report that failed to send is a state an officer needs
to see and retry, not a crash.

A NOTE ON WHAT GOES IN THE EMAIL
    For this build the report travels in the message body, which is what makes
    the demo work end to end. In a real deployment it would not: the body
    carries GSTINs, company names and risk assessments, and SMTP is not a
    channel that confidential taxpayer information should cross. Production
    would send a short notification plus an authenticated link back into the
    application, and that difference is worth stating out loud rather than
    quietly shipping.
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


def send_report(report: CaseReport, subject: str, text_body: str) -> CaseReport:
    """
    Deliver one report. Records success or the exact failure on the row.

    Never raises for a delivery problem - the officer sees the error in the
    Reports tab and can fix the credentials and retry.
    """
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
        connection = get_connection(fail_silently=False)
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
            to=recipients,
            connection=connection,
        )
        message.attach_alternative(report.html, "text/html")
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
