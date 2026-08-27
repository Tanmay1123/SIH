"""
Who is allowed to do what.

Two roles, mirroring how enforcement actually works: an **officer** builds a
case, a **supervisor** sanctions it.

    OFFICER     upload data, run detection, review alerts, DISMISS an alert as
                not fraud, issue case reports.
    SUPERVISOR  everything an officer can do, plus CONFIRM an alert as
                fraudulent, see every officer's activity, and change
                application settings.

The split is deliberate and it is the point of having roles at all. Confirming
a ring is the act that starts recovery proceedings against a real business, so
it is the one decision that needs a second, more senior pair of eyes. Clearing
an alert stays with the officer: being able to say "I looked, this is a normal
business" is the feedback the detector needs, and gating it behind a supervisor
would just mean it never happens.

Membership is a Django Group, so it is administered from /admin/ with no code
change. A superuser is always treated as a supervisor - otherwise the first
account created by `createsuperuser` could lock itself out of confirming.
"""
from __future__ import annotations

from django.conf import settings

OFFICER_GROUP = "Officers"


def supervisor_group_name() -> str:
    return getattr(settings, "SUPERVISOR_GROUP_NAME", "Supervisors")


def officer_group_name() -> str:
    """
    The officer group is a label, not a permission.

    `is_officer` below grants officer rights to every authenticated account, so
    nothing breaks if someone is missing from this group. It exists so /admin/
    and the Team page can show what an account is meant to be, rather than
    leaving officers as "not in any group".
    """
    return OFFICER_GROUP


def is_supervisor(user) -> bool:
    if user is None or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=supervisor_group_name()).exists()


def is_officer(user) -> bool:
    """Every authenticated account is at least an officer."""
    return bool(user and user.is_authenticated)


def role_of(user) -> str:
    return "supervisor" if is_supervisor(user) else "officer"


def role_label(user) -> str:
    return "Supervisor" if is_supervisor(user) else "Officer"


def permissions_for(user) -> dict:
    """
    What this account may do, as flags the frontend can read directly.

    Sent with every /auth/me/ so the UI can hide actions it would only be
    refused for. The server still enforces every one of these independently -
    hiding a button is a courtesy, never a control.
    """
    supervisor = is_supervisor(user)
    return {
        "can_review": True,
        "can_dismiss": True,
        "can_run_detection": True,
        "can_upload": True,
        "can_issue_report": True,
        # Confirming used to be supervisor-only, on the argument that it starts
        # recovery proceedings and so wants a second pair of eyes. It is an
        # officer's call now: the officer is the one who read the evidence, and
        # routing every confirmation through a supervisor made them the
        # bottleneck on the queue rather than a check on it.
        #
        # What still holds the accountability: every confirmation names the
        # authenticated officer who made it, and that name goes into the
        # tamper-evident ledger with the model version and threshold they acted
        # on. Supervisors see every officer's decisions on the Team page. The
        # review is after the fact and on the record, rather than in the way.
        "can_confirm": True,
        "can_view_team": supervisor,
        "can_edit_settings": supervisor,
        "can_manage_datasets": True,
    }
