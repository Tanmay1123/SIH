from rest_framework import serializers

from core.models import Company, Invoice
from core.serializers import CompanySerializer, InvoiceSerializer

from .models import CaseReport, DetectionRun, FlaggedRing, LedgerBlock, RiskScore


class FlaggedRingSerializer(serializers.ModelSerializer):
    ring_size = serializers.IntegerField(read_only=True)
    company_names = serializers.SerializerMethodField()
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    dismissal_reason_label = serializers.SerializerMethodField()
    reviewed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = FlaggedRing
        fields = [
            "id",
            "run",
            "kind",
            "kind_label",
            "closure",
            "company_ids",
            "company_names",
            "ring_size",
            "risk_score",
            "explanation",
            "evidence",
            "total_cycle_value",
            "detected_at",
            "status",
            "status_label",
            "officer_confirmed",
            "confirmed_at",
            "dismissal_reason",
            "dismissal_reason_label",
            "review_note",
            "reviewed_by_name",
            "reviewed_at",
        ]

    def get_company_names(self, obj):
        # The view prefetches this map so the list endpoint stays at one query.
        lookup = self.context.get("company_names") or {}
        return [lookup.get(cid, f"Company {cid}") for cid in (obj.company_ids or [])]

    def get_dismissal_reason_label(self, obj):
        return dict(FlaggedRing.DISMISSAL_REASONS).get(obj.dismissal_reason, "")

    def get_reviewed_by_name(self, obj):
        return obj.reviewed_by.username if obj.reviewed_by_id else None


class FlaggedRingDetailSerializer(FlaggedRingSerializer):
    """Full evidence bundle for one alert: its companies and its invoices."""

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
            .order_by("date")[:200]
        )
        return InvoiceSerializer(invoices, many=True).data


class DetectionRunSerializer(serializers.ModelSerializer):
    dataset_name = serializers.CharField(source="dataset.name", read_only=True)
    created_by_name = serializers.SerializerMethodField()
    alert_count = serializers.IntegerField(read_only=True)
    reviewed_count = serializers.SerializerMethodField()
    confirmed_count = serializers.SerializerMethodField()
    dismissed_count = serializers.SerializerMethodField()
    report_count = serializers.SerializerMethodField()

    class Meta:
        model = DetectionRun
        fields = [
            "id",
            "dataset",
            "dataset_name",
            "name",
            "note",
            "started_at",
            "finished_at",
            "created_by_name",
            "model_version",
            "model_trained_at",
            "risk_threshold",
            "companies_scored",
            "rings_detected",
            "mills_detected",
            "alert_count",
            "high_risk_count",
            "total_value_at_risk",
            "reviewed_count",
            "confirmed_count",
            "dismissed_count",
            "report_count",
        ]

    def get_created_by_name(self, obj):
        return obj.created_by.username if obj.created_by_id else None

    def get_confirmed_count(self, obj):
        return obj.rings.filter(status=FlaggedRing.STATUS_CONFIRMED).count()

    def get_dismissed_count(self, obj):
        return obj.rings.filter(status=FlaggedRing.STATUS_DISMISSED).count()

    def get_reviewed_count(self, obj):
        return obj.rings.exclude(status=FlaggedRing.STATUS_PENDING).count()

    def get_report_count(self, obj):
        return obj.reports.count()


class CaseReportSerializer(serializers.ModelSerializer):
    run_name = serializers.CharField(source="run.name", read_only=True)
    dataset_name = serializers.CharField(source="run.dataset.name", read_only=True)
    generated_by_name = serializers.SerializerMethodField()
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    ledger_index = serializers.SerializerMethodField()

    class Meta:
        model = CaseReport
        fields = [
            "id",
            "run",
            "run_name",
            "dataset_name",
            "title",
            "generated_at",
            "generated_by_name",
            "summary",
            "content_hash",
            "recipients",
            "status",
            "status_label",
            "sent_at",
            "error",
            "ledger_index",
        ]

    def get_generated_by_name(self, obj):
        return obj.generated_by.username if obj.generated_by_id else None

    def get_ledger_index(self, obj):
        return obj.ledger_block.index if obj.ledger_block_id else None


class CaseReportDetailSerializer(CaseReportSerializer):
    """Adds the rendered document itself."""

    class Meta(CaseReportSerializer.Meta):
        fields = CaseReportSerializer.Meta.fields + ["html"]


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
