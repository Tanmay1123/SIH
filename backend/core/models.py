"""
Base data model: the datasets, the taxpayers, and the invoices between them.

Company and Invoice live in one module on purpose. They are small, they are
always read together, and the whole fraud pipeline treats them as a single
"who traded with whom" picture.

Dataset sits above both. Every upload becomes its own Dataset rather than
overwriting the last one, so an officer can come back next week, pick a
previous upload, and see exactly what was found in it. Exactly one dataset is
"active" at a time - that is the one the dashboard, the graph and detection
all operate on.
"""
from django.conf import settings
from django.db import models


class Dataset(models.Model):
    """
    One uploaded companies+invoices CSV pair, kept as its own investigation
    universe.

    Uploading used to wipe everything. It no longer does: each upload is a
    separate Dataset, so past uploads (and every detection run against them)
    stay browsable. Switching the active dataset switches what the whole
    application is looking at.
    """

    name = models.CharField(max_length=200)
    note = models.TextField(blank=True)

    uploaded_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="datasets",
    )

    # Original filenames, purely so an officer can recognise their own upload.
    companies_filename = models.CharField(max_length=255, blank=True)
    invoices_filename = models.CharField(max_length=255, blank=True)

    company_count = models.PositiveIntegerField(default=0)
    invoice_count = models.PositiveIntegerField(default=0)

    # Exactly one dataset is active. Enforced in activate(), not by a database
    # constraint: a partial unique index on a boolean is Postgres-specific and
    # this project still has to run on SQLite for tests.
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"{self.name} ({self.company_count} companies)"

    def activate(self):
        """Make this the dataset the rest of the application operates on."""
        Dataset.objects.exclude(pk=self.pk).update(is_active=False)
        if not self.is_active:
            self.is_active = True
            self.save(update_fields=["is_active"])
        return self


def active_dataset() -> "Dataset | None":
    """
    The dataset the application is currently working on, if any.

    Returns None when nothing has been uploaded yet, and also in the test
    suite, which creates Company rows directly without a Dataset. Callers must
    treat None as "no dataset filter", not as an error.
    """
    return Dataset.objects.filter(is_active=True).first()


class AppSetting(models.Model):
    """
    Application settings an administrator can change without touching .env.

    A tiny key/value table rather than a settings model with typed columns,
    because these are genuinely a handful of unrelated knobs and a schema
    migration for each new one would be pure friction.

    Resolution order is DB, then the environment, then a hardcoded default -
    so `.env` still works as the deployment default and the UI overrides it.
    Reading goes through `settings_store.get_setting()`, never directly.
    """

    key = models.CharField(max_length=64, unique=True)
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="setting_changes",
    )

    class Meta:
        ordering = ["key"]

    def __str__(self):
        return f"{self.key} = {self.value[:40]}"


class Company(models.Model):
    """A GST-registered business. One node in the trade graph."""

    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="companies",
        null=True,
        blank=True,
    )

    # Not globally unique any more - the same GSTIN legitimately appears in two
    # different uploads. Uniqueness is per dataset, enforced by the constraint
    # below.
    gstin = models.CharField(max_length=15, db_index=True)
    pan = models.CharField(max_length=10, db_index=True)
    name = models.CharField(max_length=255)

    # Shared director names / addresses across supposedly unrelated companies
    # are one of the strongest real-world shell-company signals, so they are
    # indexed: the feature pipeline groups on them, and the graph builder now
    # turns them into actual edges.
    director_name = models.CharField(max_length=255, db_index=True)
    registered_address = models.CharField(max_length=500, db_index=True)

    registered_date = models.DateField()
    declared_turnover = models.DecimalField(max_digits=16, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "companies"
        constraints = [
            models.UniqueConstraint(
                fields=["dataset", "gstin"], name="uniq_gstin_per_dataset"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.gstin})"


class Invoice(models.Model):
    """A single tax invoice. One directed edge (seller -> buyer) in the graph."""

    # Denormalised from seller.dataset so the graph builder can filter invoices
    # in one indexed query instead of joining through companies.
    dataset = models.ForeignKey(
        Dataset,
        on_delete=models.CASCADE,
        related_name="invoices",
        null=True,
        blank=True,
    )

    seller = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="sales_invoices"
    )
    buyer = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="purchase_invoices"
    )
    amount = models.DecimalField(max_digits=16, decimal_places=2)
    date = models.DateField(db_index=True)
    goods_description = models.CharField(max_length=255)

    # An e-way bill is required for most goods movements above a threshold.
    # Invoices without one are a classic "paper-only, no goods moved" tell.
    has_eway_bill = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [
            models.Index(fields=["seller", "buyer"]),
            models.Index(fields=["dataset"]),
        ]

    def __str__(self):
        return f"INV-{self.pk}: {self.seller_id} -> {self.buyer_id} ({self.amount})"
