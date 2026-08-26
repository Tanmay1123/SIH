"""
Runtime policy knobs.

These used to be literals scattered through the code - the risk threshold was
the number 70 written into two different files. They are *policy*, not
constants: they trade officer time against missed rings, and a department
should be able to move them without a redeploy.

Everything here reads through core.settings_store, so a value set in the
Settings page beats `.env`, which beats a hardcoded default. Every detection
run and every ledger block records the threshold in force when it ran, so a
past decision can always be read back against the policy that produced it.
"""
from __future__ import annotations

from core.settings_store import get_email_list, get_float, get_int, get_setting


def risk_threshold() -> float:
    """The score at or above which an alert counts as high risk."""
    return get_float("risk_threshold")


def mill_min_score() -> float:
    """Minimum score before a suspected invoice mill is raised as an alert."""
    return get_float("mill_min_score")


def max_ring_size() -> int:
    """Longest circular-trade chain to search for."""
    return get_int("max_ring_size")


def organisation_name() -> str:
    return get_setting("organisation_name")


def supervisor_emails() -> list[str]:
    """
    Who receives a case report alongside the officer who issued it.

    The configured list, plus anyone in the Supervisors group who has an email
    address on their account - so adding a supervisor in /admin/ is enough,
    without also remembering to type their address into settings.
    """
    from django.contrib.auth import get_user_model

    from core.roles import supervisor_group_name

    configured = get_email_list("report_supervisor_emails")

    try:
        group_emails = list(
            get_user_model()
            .objects.filter(groups__name=supervisor_group_name())
            .exclude(email="")
            .values_list("email", flat=True)
        )
    except Exception:
        # Never let a missing group or an unmigrated auth table block a report.
        group_emails = []

    seen: set[str] = set()
    out: list[str] = []
    for email in configured + group_emails:
        key = (email or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(email.strip())
    return out
