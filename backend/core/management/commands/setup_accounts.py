"""
Create (or update) the console's user accounts.

WHY THIS IS A COMMAND AND NOT A README STEP
-------------------------------------------
`createsuperuser` makes one account, interactively, with no role. A department
needs several accounts with the right roles attached, and a team needs to be
able to recreate them identically on someone else's laptop. Doing that by hand
is how you end up with an officer who is quietly in the Supervisors group.

The command is **idempotent**: run it twice and you get the same three accounts,
not six. An existing account has its name, email and role brought into line;
its password is left alone unless you ask for it to be reset, because silently
changing someone's password is not an update, it is a lockout.
"""
from __future__ import annotations

import secrets
import string

from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.roles import officer_group_name, supervisor_group_name

# Used only when the command is run with no --officer/--supervisor arguments.
DEFAULT_TEAM = [
    ("supervisor", "supervisor", "Supervisor", ""),
    ("officer", "officer1", "Officer One", ""),
    ("officer", "officer2", "Officer Two", ""),
]

# Unambiguous alphabet: no O/0, l/1/I. These get read off a screen and typed by
# someone else, and "was that a one or an ell" is not a good use of anyone's
# demo slot.
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"


def make_password(length: int = 14) -> str:
    return "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(length))


def parse_spec(value: str, role: str) -> tuple[str, str, str, str]:
    """`username:Full Name:email` — name and email both optional."""
    parts = [p.strip() for p in value.split(":")]
    if not parts or not parts[0]:
        raise CommandError(f"--{role} needs at least a username, got {value!r}")
    username = parts[0]
    full_name = parts[1] if len(parts) > 1 else ""
    email = parts[2] if len(parts) > 2 else ""
    return role, username, full_name, email


class Command(BaseCommand):
    help = "Create or update officer and supervisor accounts, with roles attached."

    def add_arguments(self, parser):
        parser.add_argument(
            "--officer",
            action="append",
            default=[],
            metavar="username[:Full Name[:email]]",
            help="An officer account. Repeatable.",
        )
        parser.add_argument(
            "--supervisor",
            action="append",
            default=[],
            metavar="username[:Full Name[:email]]",
            help="A supervisor account. Repeatable.",
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Use this password for every account created. Omit to generate one each.",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Also reset the password of accounts that already exist.",
        )
        parser.add_argument(
            "--remove",
            action="append",
            default=[],
            metavar="username",
            help="Delete this account. Refuses to delete a superuser. Repeatable.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        supervisors, _ = Group.objects.get_or_create(name=supervisor_group_name())
        officers, _ = Group.objects.get_or_create(name=officer_group_name())

        for username in options["remove"]:
            self._remove(username)

        specs = [parse_spec(v, "supervisor") for v in options["supervisor"]]
        specs += [parse_spec(v, "officer") for v in options["officer"]]
        if not specs and not options["remove"]:
            specs = [(role, u, n, e) for role, u, n, e in DEFAULT_TEAM]
            self.stdout.write(
                self.style.WARNING(
                    "No accounts given, so creating the default team. Pass --officer "
                    "and --supervisor to name your own."
                )
            )

        created: list[tuple[str, str, str]] = []

        for role, username, full_name, email in specs:
            user, is_new = User.objects.get_or_create(username=username)

            if full_name:
                first, _, last = full_name.partition(" ")
                user.first_name, user.last_name = first, last
            if email:
                user.email = email

            password = None
            if is_new or options["reset_password"]:
                password = options["password"] or make_password()
                user.set_password(password)

            user.is_staff = False
            user.save()

            # A superuser is a supervisor whatever the groups say (see
            # core.roles), so never demote one by accident here.
            if role == "supervisor" or user.is_superuser:
                user.groups.add(supervisors)
                user.groups.remove(officers)
            else:
                user.groups.add(officers)
                user.groups.remove(supervisors)

            label = "created" if is_new else "updated"
            self.stdout.write(
                f"  {self.style.SUCCESS(label):<20} {username:<14} {role:<11} "
                f"{user.email or '(no email set)'}"
            )
            if password:
                created.append((username, password, role))

        if created:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("Passwords (shown once):"))
            for username, password, role in created:
                self.stdout.write(f"  {username:<14} {password:<18} {role}")
            self.stdout.write("")
            self.stdout.write(
                "Nobody can read these back out - Django only stores the hash. "
                "Write them down now, and have each person change theirs from "
                "the Profile page."
            )

        untouched = User.objects.exclude(
            username__in=[s[1] for s in specs]
        ).order_by("username")
        if untouched.exists():
            self.stdout.write("")
            self.stdout.write("Other accounts left alone:")
            for user in untouched:
                role = "superuser" if user.is_superuser else (
                    "supervisor" if user.groups.filter(name=supervisor_group_name()).exists()
                    else "officer"
                )
                self.stdout.write(f"  {user.username:<14} {role}")

    def _remove(self, username: str) -> None:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(f"  {'not found':<20} {username}")
            return
        if user.is_superuser:
            raise CommandError(
                f"Refusing to delete the superuser {username!r}. Remove its "
                "superuser flag in /admin/ first if you really mean to."
            )
        user.delete()
        self.stdout.write(f"  {self.style.WARNING('removed'):<20} {username}")
