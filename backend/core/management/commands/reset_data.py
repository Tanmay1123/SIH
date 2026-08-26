"""
Wipe every case record, keeping the accounts.

WHY THIS EXISTS
---------------
Before a demo you want an empty console: no half-reviewed queue from last
week's testing, no ledger blocks recording decisions nobody remembers making.
What you do NOT want is to lose the accounts and have to recreate three users
and their roles while people are watching.

So this deletes the data and leaves `auth_user` alone. It is the opposite of
`flush`, which drops everything including the accounts.

DELETED: datasets, companies, invoices, detection runs, alerts, risk scores,
         ledger blocks, case reports.
KEPT:    user accounts, their roles, and (unless --settings-too) any policy
         values a supervisor configured.

It refuses to run without --yes, because "clear the database" typed into the
wrong terminal is a bad afternoon.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import AppSetting, Company, Dataset, Invoice
from fraud_engine.models import (
    CaseReport,
    DetectionRun,
    FlaggedRing,
    LedgerBlock,
    RiskScore,
)

# Order matters: children before parents, so nothing is deleted out from under
# a foreign key. It is also the order the counts read best in.
TARGETS = [
    ("Case reports", CaseReport),
    ("Ledger blocks", LedgerBlock),
    ("Risk scores", RiskScore),
    ("Alerts", FlaggedRing),
    ("Detection runs", DetectionRun),
    ("Invoices", Invoice),
    ("Companies", Company),
    ("Datasets", Dataset),
]


class Command(BaseCommand):
    help = "Delete all case data (datasets, alerts, ledger, reports). Keeps accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes", action="store_true", help="Required. Confirms the deletion."
        )
        parser.add_argument(
            "--settings-too",
            action="store_true",
            help="Also clear database setting overrides, falling back to .env.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be deleted and stop.",
        )

    def handle(self, *args, **options):
        counts = [(label, model, model.objects.count()) for label, model in TARGETS]
        total = sum(c for _, _, c in counts)

        self.stdout.write(self.style.MIGRATE_HEADING("Currently in the database:"))
        for label, _, count in counts:
            self.stdout.write(f"  {label:<16} {count:>8,}")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("\nAlready empty. Nothing to do."))
            return

        if options["dry_run"]:
            self.stdout.write(f"\nDry run: {total:,} rows would be deleted.")
            return

        if not options["yes"]:
            raise CommandError(
                f"This would permanently delete {total:,} rows. "
                "Re-run with --yes if that is what you want."
            )

        with transaction.atomic():
            for label, model, _ in counts:
                model.objects.all().delete()
            if options["settings_too"]:
                AppSetting.objects.all().delete()

        self.stdout.write(
            self.style.SUCCESS(f"\nDeleted {total:,} rows. Accounts were left alone.")
        )
        self.stdout.write(
            "Upload a CSV pair from Detections, or fabricate one at /lab."
        )
