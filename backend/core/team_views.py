"""
Accounts, roles, the supervisor's view of the team, and editable settings.

Split out of views.py, which is about companies and invoices, because this is
a different concern entirely: who is using the system and what they have been
doing with it.
"""
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .permissions import IsSupervisor
from .roles import is_supervisor, permissions_for, role_label, role_of, supervisor_group_name
from .settings_store import SETTINGS_SPEC, describe_all, set_setting

User = get_user_model()


def profile_payload(user) -> dict:
    """Everything the UI needs to know about the signed-in account."""
    return {
        "id": user.id,
        "username": user.username,
        "email": user.email or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "full_name": (f"{user.first_name} {user.last_name}").strip() or user.username,
        "role": role_of(user),
        "role_label": role_label(user),
        "is_superuser": user.is_superuser,
        "date_joined": user.date_joined,
        "last_login": user.last_login,
        "permissions": permissions_for(user),
    }


@api_view(["GET", "PATCH"])
def me(request):
    """
    GET  /api/auth/me/    the signed-in account, its role and what it may do
    PATCH same            update your own name or email

    The email matters operationally: it is where your copy of a case report is
    sent, so an account with no address silently drops out of the recipient
    list.
    """
    if request.method == "PATCH":
        data = request.data or {}
        for field in ("first_name", "last_name", "email"):
            if field in data:
                setattr(request.user, field, (data.get(field) or "").strip()[:254])
        request.user.save(update_fields=["first_name", "last_name", "email"])

    return Response(profile_payload(request.user))


@api_view(["POST"])
def change_password(request):
    """POST /api/auth/change-password/ — {current_password, new_password}."""
    data = request.data or {}
    current = data.get("current_password") or ""
    new = data.get("new_password") or ""

    if not request.user.check_password(current):
        return Response(
            {"detail": "Your current password is not correct."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if len(new) < 8:
        return Response(
            {"detail": "Choose a password of at least 8 characters."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    request.user.set_password(new)
    request.user.save(update_fields=["password"])

    # The old token was issued against the old credentials; reissue so the
    # caller stays signed in on this device and nowhere else.
    from rest_framework.authtoken.models import Token

    Token.objects.filter(user=request.user).delete()
    token, _ = Token.objects.get_or_create(user=request.user)
    return Response({"detail": "Password changed.", "token": token.key})


# ---------------------------------------------------------------------------
# The supervisor's view of the team
# ---------------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsSupervisor])
def team_overview(request):
    """
    GET /api/team/ — every account, with what they have actually been doing.

    Supervisor-only, and the reason the role exists. Officers decide their own
    cases - confirming is not gated - so oversight is after the fact rather than
    in the way, and this is where it happens: who confirmed what, how much of
    the queue each officer has worked through, and what was cleared rather than
    pursued. Every row here is one officer's actual decisions, attributed.
    """
    from fraud_engine.models import CaseReport, DetectionRun, FlaggedRing

    users = (
        User.objects.filter(is_active=True)
        .prefetch_related("groups")
        .annotate(
            confirmed=Count(
                "reviewed_rings",
                filter=Q(reviewed_rings__status=FlaggedRing.STATUS_CONFIRMED),
                distinct=True,
            ),
            dismissed=Count(
                "reviewed_rings",
                filter=Q(reviewed_rings__status=FlaggedRing.STATUS_DISMISSED),
                distinct=True,
            ),
            runs=Count("detection_runs", distinct=True),
            reports=Count("case_reports", distinct=True),
        )
        .order_by("-is_superuser", "username")
    )

    members = []
    for user in users:
        last_decision = (
            FlaggedRing.objects.filter(reviewed_by=user)
            .order_by("-reviewed_at")
            .values_list("reviewed_at", flat=True)
            .first()
        )
        members.append(
            {
                **profile_payload(user),
                "activity": {
                    "confirmed": user.confirmed,
                    "dismissed": user.dismissed,
                    "reviewed": user.confirmed + user.dismissed,
                    "runs": user.runs,
                    "reports": user.reports,
                    "last_decision_at": last_decision,
                    "last_seen": user.last_login,
                },
            }
        )

    pending = FlaggedRing.objects.filter(status=FlaggedRing.STATUS_PENDING).count()
    return Response(
        {
            "supervisor_group": supervisor_group_name(),
            "members": members,
            "totals": {
                "officers": sum(1 for m in members if m["role"] == "officer"),
                "supervisors": sum(1 for m in members if m["role"] == "supervisor"),
                "runs": DetectionRun.objects.count(),
                "reports": CaseReport.objects.count(),
                "pending_review": pending,
                "confirmed": FlaggedRing.objects.filter(
                    status=FlaggedRing.STATUS_CONFIRMED
                ).count(),
                "dismissed": FlaggedRing.objects.filter(
                    status=FlaggedRing.STATUS_DISMISSED
                ).count(),
            },
        }
    )


@api_view(["GET"])
@permission_classes([IsSupervisor])
def team_activity(request):
    """
    GET /api/team/activity/ — a merged feed of who did what, newest first.

    Decisions, detection runs and issued reports in one timeline, so a
    supervisor can see the shape of the team's work without opening three
    screens.
    """
    from fraud_engine.models import CaseReport, DetectionRun, FlaggedRing

    limit = min(int(request.query_params.get("limit", 40)), 200)
    events = []

    decisions = (
        FlaggedRing.objects.exclude(status=FlaggedRing.STATUS_PENDING)
        .exclude(reviewed_at__isnull=True)
        .select_related("reviewed_by", "run")
        .order_by("-reviewed_at")[:limit]
    )
    reason_labels = dict(FlaggedRing.DISMISSAL_REASONS)
    for alert in decisions:
        confirmed = alert.status == FlaggedRing.STATUS_CONFIRMED
        events.append(
            {
                "kind": "confirmed" if confirmed else "dismissed",
                "at": alert.reviewed_at,
                "actor": alert.reviewed_by.username if alert.reviewed_by_id else "unknown",
                "title": (
                    f"{'Confirmed' if confirmed else 'Cleared'} "
                    f"{'mill' if alert.kind == FlaggedRing.KIND_MILL else 'ring'} #{alert.id}"
                ),
                "detail": (
                    f"risk {alert.risk_score:.1f}"
                    + ("" if confirmed else f" · {reason_labels.get(alert.dismissal_reason, '')}")
                ),
                "note": alert.review_note or "",
                "run": alert.run.name if alert.run_id else "",
                "alert_id": alert.id,
            }
        )

    for run in DetectionRun.objects.select_related("created_by", "dataset").order_by(
        "-started_at"
    )[:limit]:
        events.append(
            {
                "kind": "run",
                "at": run.started_at,
                "actor": run.created_by.username if run.created_by_id else "system",
                "title": f"Ran detection — {run.name}",
                "detail": (
                    f"{run.rings_detected} rings, {run.mills_detected} mills, "
                    f"{run.high_risk_count} high risk"
                ),
                "note": "",
                "run": run.name,
            }
        )

    for report in CaseReport.objects.select_related("generated_by", "run").order_by(
        "-generated_at"
    )[:limit]:
        events.append(
            {
                "kind": "report",
                "at": report.generated_at,
                "actor": report.generated_by.username if report.generated_by_id else "system",
                "title": f"Issued “{report.title}”",
                "detail": f"to {len(report.recipients or [])} recipient(s) · {report.status}",
                "note": "",
                "run": report.run.name if report.run_id else "",
            }
        )

    events = [e for e in events if e["at"] is not None]
    events.sort(key=lambda e: e["at"], reverse=True)
    return Response(events[:limit])


@api_view(["POST"])
@permission_classes([IsSupervisor])
def set_member_role(request, pk):
    """
    POST /api/team/{id}/role/ — {"role": "officer" | "supervisor"}

    Supervisor-only. A supervisor cannot demote themselves: that is the one
    move that could leave a deployment with nobody able to confirm anything.
    """
    from django.contrib.auth.models import Group

    target = User.objects.filter(pk=pk).first()
    if target is None:
        return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

    role = ((request.data or {}).get("role") or "").strip().lower()
    if role not in {"officer", "supervisor"}:
        return Response(
            {"detail": "Role must be 'officer' or 'supervisor'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if target.pk == request.user.pk and role == "officer":
        return Response(
            {"detail": "You cannot remove your own supervisor role."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if target.is_superuser and role == "officer":
        return Response(
            {
                "detail": "This is a superuser account and is always a supervisor. "
                "Change it in the Django admin if that is really what you want."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    group, _ = Group.objects.get_or_create(name=supervisor_group_name())
    if role == "supervisor":
        target.groups.add(group)
    else:
        target.groups.remove(group)

    return Response(profile_payload(target))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@api_view(["GET"])
def app_settings(request):
    """
    GET /api/settings/ — every configurable value, where it came from, and
    what it does. Readable by anyone signed in so the UI can show the policy
    in force; only a supervisor may change it.
    """
    return Response(
        {
            "settings": describe_all(),
            "editable": is_supervisor(request.user),
        }
    )


@api_view(["PATCH"])
@permission_classes([IsSupervisor])
def update_app_settings(request):
    """
    PATCH /api/settings/ — {"risk_threshold": "65", ...}

    An empty string clears the override, so the value falls back to `.env` and
    then to the built-in default.
    """
    data = request.data or {}
    unknown = [k for k in data if k not in SETTINGS_SPEC]
    if unknown:
        return Response(
            {"detail": f"Unknown setting(s): {', '.join(unknown)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    for key, value in data.items():
        spec = SETTINGS_SPEC[key]
        if spec["type"] == "number" and str(value).strip():
            try:
                number = float(value)
            except (TypeError, ValueError):
                return Response(
                    {"detail": f"{spec['label']} must be a number."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            low, high = spec.get("min"), spec.get("max")
            if (low is not None and number < low) or (high is not None and number > high):
                return Response(
                    {"detail": f"{spec['label']} must be between {low} and {high}."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        set_setting(key, value, user=request.user)

    return Response({"settings": describe_all(), "editable": True, "saved_at": timezone.now()})
