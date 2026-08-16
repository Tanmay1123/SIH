"""
Base data model: the taxpayers and the invoices between them.

Company and Invoice live in one module on purpose. They are small, they are
always read together, and the whole fraud pipeline treats them as a single
"who traded with whom" picture.
"""
from django.db import models


class Company(models.Model):
    """A GST-registered business. One node in the trade graph."""

    gstin = models.CharField(max_length=15, unique=True, db_index=True)
    pan = models.CharField(max_length=10, db_index=True)
    name = models.CharField(max_length=255)

    # Shared director names / addresses across supposedly unrelated companies
    # are one of the strongest real-world shell-company signals, so they are
    # indexed: the feature pipeline groups on them.
    director_name = models.CharField(max_length=255, db_index=True)
    registered_address = models.CharField(max_length=500, db_index=True)

    registered_date = models.DateField()
    declared_turnover = models.DecimalField(max_digits=16, decimal_places=2)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name_plural = "companies"

    def __str__(self):
        return f"{self.name} ({self.gstin})"


class Invoice(models.Model):
    """A single tax invoice. One directed edge (seller -> buyer) in the graph."""

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
        ]

    def __str__(self):
        return f"INV-{self.pk}: {self.seller_id} -> {self.buyer_id} ({self.amount})"
