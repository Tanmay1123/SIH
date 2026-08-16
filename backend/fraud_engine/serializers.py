from rest_framework import serializers

from core.models import Company, Invoice
from core.serializers import CompanySerializer, InvoiceSerializer

from .models import FlaggedRing, LedgerBlock, RiskScore


class FlaggedRingSerializer(serializers.ModelSerializer):
    ring_size = serializers.IntegerField(read_only=True)
    company_names = serializers.SerializerMethodField()

    class Meta:
        model = FlaggedRing
        fields = [
            "id",
            "company_ids",
            "company_names",
            "ring_size",
            "risk_score",
            "explanation",
            "total_cycle_value",
            "detected_at",
            "officer_confirmed",
            "confirmed_at",
        ]

    def get_company_names(self, obj):
        # The view prefetches this map so the list endpoint stays at one query.
        lookup = self.context.get("company_names") or {}
        return [lookup.get(cid, f"Company {cid}") for cid in (obj.company_ids or [])]


class FlaggedRingDetailSerializer(FlaggedRingSerializer):
    """Full evidence bundle for one ring: its companies and its invoices."""

    companies = serializers.SerializerMethodField()
    invoices = serializers.SerializerMethodField()

    class Meta(FlaggedRingSerializer.Meta):
        fields = FlaggedRingSerializer.Meta.fields + [
            "companies",
            "invoices",
            "invoice_ids",
        ]

    def get_companies(self, obj):
        # Preserve cycle order (A -> B -> C -> A), not database order.
        by_id = {c.id: c for c in Company.objects.filter(id__in=obj.company_ids or [])}
        ordered = [by_id[cid] for cid in (obj.company_ids or []) if cid in by_id]
        return CompanySerializer(ordered, many=True).data

    def get_invoices(self, obj):
        invoices = (
            Invoice.objects.filter(id__in=obj.invoice_ids or [])
            .select_related("seller", "buyer")
            .order_by("date")
        )
        return InvoiceSerializer(invoices, many=True).data


class RiskScoreSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source="company.name", read_only=True)
    gstin = serializers.CharField(source="company.gstin", read_only=True)

    class Meta:
        model = RiskScore
        fields = [
            "id",
            "company",
            "company_name",
            "gstin",
            "score",
            "computed_at",
            "feature_snapshot",
            "explanation",
        ]


class LedgerBlockSerializer(serializers.ModelSerializer):
    class Meta:
        model = LedgerBlock
        fields = ["index", "timestamp", "payload", "previous_hash", "hash"]
