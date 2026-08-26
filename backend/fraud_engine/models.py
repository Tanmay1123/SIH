"""
Fraud-engine schema: what the detector found, what it scored, what an officer
decided about it, and what was permanently committed to the audit ledger.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from core.models import Company, Dataset


class DetectionRun(models.Model):
    """
    One named pass of the detection pipeline over one dataset.

    Every "Run detection" creates one of these. Rings and risk scores hang off
    it, so a run is a permanent, self-contained record of what the system found
    at a point in time - which model version produced it, and at what risk
    threshold. Re-running does not erase the previous run.
    """

    dataset = models.ForeignKey(
        Dataset, on_delete=models.CASCADE, related_name="runs"
    )
    name = models.CharField(max_length=200)
    note = models.TextField(blank=True)

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="detection_runs",
    )

    # Provenance. Recorded here and copied into every ledger block this run
    # produces, so a confirmed ring can always be traced back to the exact
    # model and policy threshold that flagged it.
    model_version = models.CharField(max_length=64, blank=True)
    model_trained_at = models.CharField(max_length=32, blank=True)
    risk_threshold = models.FloatField(default=70.0)

    # Result counters, denormalised so the reports list needs no aggregation.
    companies_scored = models.PositiveIntegerField(default=0)
    rings_detected = models.PositiveIntegerField(default=0)
    mills_detected = models.PositiveIntegerField(default=0)
    high_risk_count = models.PositiveIntegerField(default=0)
    total_value_at_risk = models.DecimalField(
        max_digits=20, decimal_places=2, default=0
    )

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.dataset.name})"

    @property
    def alert_count(self) -> int:
        return self.rings_detected + self.mills_detected


class FlaggedRing(models.Model):
    """
    One suspicious pattern found in the invoice graph.

    Despite the name this is no longer only a closed loop. `kind` says which
    shape was found:

      ring - a closed invoice loop A -> B -> C -> A (classic circular trading)
      mill - a fake-invoice mill: a company that sells to many unrelated
             buyers and buys from almost nobody. Not a loop at all, and the
             most common form of real GST fraud, which pure cycle detection
             is structurally blind to.

    A flagged item is a *candidate*, not a verdict. Cycle detection is
    deliberately generous - genuine two-way trade also produces cycles - and it
    is the risk score, then a human, that separates fraud from ordinary trade.
    """

    KIND_RING = "ring"
    KIND_MILL = "mill"
    KIND_CHOICES = [
        (KIND_RING, "Circular trade ring"),
        (KIND_MILL, "Fake invoice mill"),
    ]

    # How a ring closes. An invoice-closed ring is A -> B -> C -> A entirely in
    # bills. A control-closed ring is A -> B -> C where C and A share a
    # director or a registered address: the loop closes through ownership
    # rather than through a bill, which is the smarter way to run the fraud
    # because it leaves no closing invoice to find.
    CLOSURE_INVOICE = "invoice"
    CLOSURE_CONTROL = "control"
    CLOSURE_CHOICES = [
        (CLOSURE_INVOICE, "Closed by invoice"),
        (CLOSURE_CONTROL, "Closed by shared ownership"),
    ]

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_DISMISSED = "dismissed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Awaiting review"),
        (STATUS_CONFIRMED, "Confirmed fraudulent"),
        (STATUS_DISMISSED, "Dismissed - not fraud"),
    ]

    # Why an officer said "not fraud". These are the training signal we had no
    # way to collect before: the system could previously only ever be told it
    # was right, never that it was wrong.
    DISMISSAL_REASONS = [
        ("genuine_trade", "Genuine two-way trade"),
        ("not_circular", "Shell company, but not a circular ring"),
        ("already_open", "Already under investigation"),
        ("insufficient", "Insufficient evidence to act"),
        ("data_quality", "Data quality problem, not fraud"),
        ("other", "Other (see note)"),
    ]

    run = models.ForeignKey(
        DetectionRun,
        on_delete=models.CASCADE,
        related_name="rings",
        null=True,
        blank=True,
    )

    kind = models.CharField(max_length=16, choices=KIND_CHOICES, default=KIND_RING)
    closure = models.CharField(
        max_length=16, choices=CLOSURE_CHOICES, default=CLOSURE_INVOICE
    )

    # Company primary keys in cycle order: [A, B, C] means A -> B -> C -> A.
    # For a mill, the first id is the mill itself and the rest are its buyers.
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

    # Free-form shape evidence: hop amounts for a ring, buyer counts for a
    # mill, which ownership link closed the loop, and so on.
    evidence = models.JSONField(default=dict)

    # ---- officer decision ---------------------------------------------------
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True
    )
    # Kept alongside `status` because it is what the ledger payloads, the API
    # and the dashboard have always called this. Never set it directly - use
    # mark_confirmed() / mark_dismissed() so the two can never disagree.
    officer_confirmed = models.BooleanField(default=False)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    dismissal_reason = models.CharField(
        max_length=32, choices=DISMISSAL_REASONS, blank=True
    )
    review_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_rings",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-risk_score", "id"]
        indexes = [models.Index(fields=["run", "-risk_score"])]

    def __str__(self):
        label = "Mill" if self.kind == self.KIND_MILL else "Ring"
        return f"{label} #{self.pk} ({len(self.company_ids or [])} companies, risk {self.risk_score:.1f})"

    @property
    def ring_size(self) -> int:
        return len(self.company_ids or [])

    @property
    def signature(self) -> str:
        """Order-independent identity, used to avoid duplicate rows on rebuild."""
        return f"{self.kind}:" + ",".join(str(c) for c in sorted(self.company_ids or []))

    def mark_confirmed(self, user=None, note: str = ""):
        """An officer confirms this as fraudulent."""
        self.status = self.STATUS_CONFIRMED
        self.officer_confirmed = True
        self.confirmed_at = timezone.now()
        self.reviewed_by = user
        self.reviewed_at = self.confirmed_at
        self.review_note = note
        self.dismissal_reason = ""
        self.save(
            update_fields=[
                "status", "officer_confirmed", "confirmed_at",
                "reviewed_by", "reviewed_at", "review_note", "dismissal_reason",
            ]
        )
        return self

    def mark_dismissed(self, reason: str, user=None, note: str = ""):
        """
        An officer looked at this and says it is not fraud.

        This is the half of the loop that did not exist before. Without it the
        system holds no negative examples, cannot measure its own precision,
        and can never improve.
        """
        self.status = self.STATUS_DISMISSED
        self.officer_confirmed = False
        self.confirmed_at = None
        self.dismissal_reason = reason
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.review_note = note
        self.save(
            update_fields=[
                "status", "officer_confirmed", "confirmed_at",
                "dismissal_reason", "reviewed_by", "reviewed_at", "review_note",
            ]
        )
        return self


class RiskScore(models.Model):
    """The most recent ML risk assessment for a single company."""

    run = models.ForeignKey(
        DetectionRun,
        on_delete=models.CASCADE,
        related_name="scores",
        null=True,
        blank=True,
    )
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
        indexes = [
            models.Index(fields=["company", "-computed_at"]),
            models.Index(fields=["run"]),
        ]

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


class CaseReport(models.Model):
    """
    A supervisor-facing summary of one detection run, and its delivery record.

    The workflow this exists for: an officer works through the alerts, confirms
    or dismisses each one, then issues a report. The report goes to the officer
    and to their supervisor by email, and its content hash is written to the
    audit ledger - so the report a supervisor approved can later be proven to
    be the report on file.
    """

    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Generated, not sent"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Send failed"),
    ]

    run = models.ForeignKey(
        DetectionRun, on_delete=models.CASCADE, related_name="reports"
    )
    title = models.CharField(max_length=200)

    generated_at = models.DateTimeField(auto_now_add=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="case_reports",
    )

    # The rendered report, kept verbatim so what was sent can always be re-read
    # exactly as the supervisor received it.
    html = models.TextField(blank=True)
    summary = models.JSONField(default=dict)
    content_hash = models.CharField(max_length=64, blank=True)

    recipients = models.JSONField(default=list)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT
    )
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    ledger_block = models.ForeignKey(
        LedgerBlock,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reports",
    )

    class Meta:
        ordering = ["-generated_at", "-id"]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"
