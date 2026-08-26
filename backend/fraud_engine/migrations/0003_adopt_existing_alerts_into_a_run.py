"""
Carry pre-existing alerts and scores into a DetectionRun, and backfill status.

Two things need fixing for an install that already has data:

1. Alerts and risk scores now hang off a DetectionRun, and every query filters
   by one. Rows with no run would silently vanish from the dashboard.

2. `officer_confirmed` used to be the only decision state. It is now paired
   with `status`, which also covers "dismissed". Anything already confirmed
   must say so in both places, or the two would disagree from day one.
"""
from django.db import migrations


def adopt(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    DetectionRun = apps.get_model("fraud_engine", "DetectionRun")
    FlaggedRing = apps.get_model("fraud_engine", "FlaggedRing")
    RiskScore = apps.get_model("fraud_engine", "RiskScore")

    # Status backfill applies whether or not there is a dataset to hang a run
    # off, so do it unconditionally first.
    FlaggedRing.objects.filter(officer_confirmed=True).update(status="confirmed")
    FlaggedRing.objects.filter(officer_confirmed=False).update(status="pending")

    orphan_alerts = FlaggedRing.objects.filter(run__isnull=True)
    orphan_scores = RiskScore.objects.filter(run__isnull=True)
    if not orphan_alerts.exists() and not orphan_scores.exists():
        return

    dataset = Dataset.objects.filter(is_active=True).first() or Dataset.objects.first()
    if dataset is None:
        # Alerts with no dataset behind them cannot be attributed to a run.
        # They are detection output with no data left to explain them, so
        # dropping them is the honest outcome rather than inventing a dataset.
        orphan_alerts.delete()
        orphan_scores.delete()
        return

    run = DetectionRun.objects.create(
        dataset=dataset,
        name="Previous detection",
        note=(
            "Created automatically when detection-run history was introduced. "
            "These results were already in the database and predate named runs, "
            "so the model version and threshold behind them are not recorded."
        ),
        risk_threshold=70.0,
        model_version="",
        companies_scored=orphan_scores.count(),
        rings_detected=orphan_alerts.count(),
        high_risk_count=orphan_alerts.filter(risk_score__gte=70).count(),
    )

    orphan_alerts.update(run=run)
    orphan_scores.update(run=run)


def unadopt(apps, schema_editor):
    DetectionRun = apps.get_model("fraud_engine", "DetectionRun")
    FlaggedRing = apps.get_model("fraud_engine", "FlaggedRing")
    RiskScore = apps.get_model("fraud_engine", "RiskScore")

    for run in DetectionRun.objects.filter(name="Previous detection"):
        FlaggedRing.objects.filter(run=run).update(run=None)
        RiskScore.objects.filter(run=run).update(run=None)
        run.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("fraud_engine", "0002_flaggedring_closure_flaggedring_dismissal_reason_and_more"),
        ("core", "0003_adopt_existing_rows_into_a_dataset"),
    ]

    operations = [migrations.RunPython(adopt, unadopt)]
