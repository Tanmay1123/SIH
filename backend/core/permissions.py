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
    Supervisor-only: oversight and policy.

    Casework is not gated - officers confirm and clear alerts themselves, and
    every decision is attributed to them in the ledger. What a supervisor keeps
    is the ability to see the whole team's activity and to change the settings
    everyone else works to.
    """

    message = (
        "Only a supervisor can do this. Officers handle casework; seeing the "
        "whole team's activity and changing detection settings are a "
        "supervisor's."
    )

    def has_permission(self, request, view):
        return is_supervisor(request.user)
