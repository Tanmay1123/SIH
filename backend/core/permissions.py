"""
DRF permission classes for the two roles.

Kept separate from roles.py so the role logic stays importable from places
that have no business importing rest_framework (migrations, the mailer, the
report builder).
"""
from rest_framework.permissions import BasePermission

from .roles import is_supervisor


class IsSupervisor(BasePermission):
    """
    Supervisor-only. Used on the actions that carry real consequence:
    confirming an alert as fraudulent, viewing every officer's activity, and
    changing application settings.
    """

    message = (
        "Only a supervisor can do this. Officers prepare and clear cases; "
        "confirming one as fraudulent is a supervisor's decision."
    )

    def has_permission(self, request, view):
        return is_supervisor(request.user)
