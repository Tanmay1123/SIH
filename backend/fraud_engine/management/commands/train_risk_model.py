"""
Train the fraud risk model and write the artifact to models_artifacts/.

Run once at setup time - or never, because a pretrained artifact is committed
to the repository so a fresh clone can score rings immediately:

    python manage.py train_risk_model

Training deliberately does NOT read the database. It generates fresh synthetic
networks with their own seeds, so the shipped model has never seen the demo
data it is later asked to score.
"""
from django.core.management.base import BaseCommand

from fraud_engine.risk_scoring import MODEL_PATH, train_and_save


class Command(BaseCommand):
    help = "Train the XGBoost fraud risk model on freshly generated synthetic networks."

    def add_arguments(self, parser):
        parser.add_argument(
            "--networks",
            type=int,
            default=10,
            help="How many synthetic networks to generate (last 2 are held out).",
        )

    def handle(self, *args, **options):
        n = max(options["networks"], 4)
        seeds = [101 * (i + 1) for i in range(n)]

        self.stdout.write(f"Training risk model on {n - 2} networks, holding out 2...")
        metrics = train_and_save(seeds=seeds)

        self.stdout.write(self.style.SUCCESS(f"\nModel saved to {MODEL_PATH}"))
        self.stdout.write("\nHeld-out performance (networks the model never saw):")
        self.stdout.write(f"  rows            : {metrics['holdout_rows']}")
        self.stdout.write(f"  shell companies : {metrics['holdout_positives']}")
        self.stdout.write(f"  ROC AUC         : {metrics['holdout_roc_auc']}")
        self.stdout.write(f"  Avg precision   : {metrics['holdout_avg_precision']}")
