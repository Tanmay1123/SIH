"""
Fraud-engine schema: what the detector found, what it scored, and what an
officer permanently committed to the audit ledger.
"""
from django.db import models

from core.models import Company


class FlaggedRing(models.Model):
    """
    One closed circular-trade loop found in the invoice graph.

    A flagged ring is a *candidate*, not a verdict. Cycle detection is
    deliberately generous - genuine two-way trade also produces cycles - and
    it is the risk score that separates fraud from ordinary reciprocal trade.
    """

    # Company primary keys in cycle order: [A, B, C] means A -> B -> C -> A.
    company_ids = models.JSONField(default=list)
    detected_at = models.DateTimeField(auto_now_add=True)

    risk_score = models.FloatField(default=0.0)  # 0-100, populated by scoring
    # List of {feature, value, impact, text} dicts derived from SHAP.
    explanation = models.JSONField(default=list)

    # Aggregate evidence captured at detection time.
    total_cycle_value = models.DecimalField(
        max_digits=18, decimal_places=2, default=0
    )
    invoice_ids = models.JSONField(default=list)

    officer_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-risk_score", "id"]

    def __str__(self):
        return f"Ring #{self.pk} ({len(self.company_ids or [])} companies, risk {self.risk_score:.1f})"

    @property
    def ring_size(self) -> int:
        return len(self.company_ids or [])

    @property
    def signature(self) -> str:
        """Order-independent identity, used to avoid duplicate rows on rebuild."""
        return ",".join(str(c) for c in sorted(self.company_ids or []))


class RiskScore(models.Model):
    """The most recent ML risk assessment for a single company."""

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="risk_scores"
    )
    score = models.FloatField()  # 0-100
    computed_at = models.DateTimeField(auto_now_add=True)

    # The exact feature values the score was computed from, so an officer can
    # always reconstruct why a company was rated the way it was.
    feature_snapshot = models.JSONField(default=dict)
    explanation = models.JSONField(default=list)

    class Meta:
        ordering = ["-score"]
        indexes = [models.Index(fields=["company", "-computed_at"])]

    def __str__(self):
        return f"{self.company_id}: {self.score:.1f}"


class LedgerBlock(models.Model):
    """
    One block in the tamper-evident audit chain.

    Rows are append-only by convention: every block stores the hash of the
    block before it, so editing any historical payload breaks every hash that
    follows and `ledger.verify_chain()` reports exactly where.
    """

    index = models.PositiveIntegerField(unique=True)
    timestamp = models.DateTimeField()
    payload = models.JSONField(default=dict)
    previous_hash = models.CharField(max_length=64)
    hash = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ["index"]

    def __str__(self):
        return f"Block #{self.index} {self.hash[:12]}..."
