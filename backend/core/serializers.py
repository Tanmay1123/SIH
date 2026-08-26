from rest_framework import serializers

from .models import Company, Dataset, Invoice


class DatasetSerializer(serializers.ModelSerializer):
    uploaded_by_name = serializers.SerializerMethodField()
    run_count = serializers.SerializerMethodField()
    latest_run = serializers.SerializerMethodField()

    class Meta:
        model = Dataset
        fields = [
            "id",
            "name",
            "note",
            "uploaded_at",
            "uploaded_by_name",
            "companies_filename",
            "invoices_filename",
            "company_count",
            "invoice_count",
            "is_active",
            "run_count",
            "latest_run",
        ]

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by_id else None

    def get_run_count(self, obj):
        return obj.runs.count()

    def get_latest_run(self, obj):
        run = obj.runs.first()  # DetectionRun.Meta orders newest first
        if run is None:
            return None
        return {
            "id": run.id,
            "name": run.name,
            "started_at": run.started_at,
            "high_risk_count": run.high_risk_count,
            "alert_count": run.alert_count,
        }


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = [
            "id",
            "gstin",
            "pan",
            "name",
            "director_name",
            "registered_address",
            "registered_date",
            "declared_turnover",
        ]


class CompanyDetailSerializer(CompanySerializer):
    """Company, its trade summary, and whatever the fraud engine knows about it."""

    total_sales_count = serializers.SerializerMethodField()
    total_purchase_count = serializers.SerializerMethodField()
    risk_score = serializers.SerializerMethodField()
    risk_computed_at = serializers.SerializerMethodField()
    feature_snapshot = serializers.SerializerMethodField()
    explanation = serializers.SerializerMethodField()
    rings = serializers.SerializerMethodField()

    class Meta(CompanySerializer.Meta):
        fields = CompanySerializer.Meta.fields + [
            "total_sales_count",
            "total_purchase_count",
            "risk_score",
            "risk_computed_at",
            "feature_snapshot",
            "explanation",
            "rings",
        ]

    def get_total_sales_count(self, obj):
        return obj.sales_invoices.count()

    def get_total_purchase_count(self, obj):
        return obj.purchase_invoices.count()

    def _latest_score(self, obj):
        # Cached on the instance so four method fields cost one query, not four.
        if not hasattr(obj, "_cached_latest_score"):
            obj._cached_latest_score = obj.risk_scores.order_by("-computed_at").first()
        return obj._cached_latest_score

    def get_risk_score(self, obj):
        score = self._latest_score(obj)
        return round(score.score, 2) if score else None

    def get_risk_computed_at(self, obj):
        score = self._latest_score(obj)
        return score.computed_at if score else None

    def get_feature_snapshot(self, obj):
        score = self._latest_score(obj)
        return score.feature_snapshot if score else {}

    def get_explanation(self, obj):
        score = self._latest_score(obj)
        return score.explanation if score else []

    def get_rings(self, obj):
        """
        Which flagged alerts this company appears in, most recent run first.

        Filtered in Python rather than with a JSONField `contains` lookup:
        that lookup is PostgreSQL-only and would break the SQLite path used
        for running tests without a database server. There are only tens of
        alerts per run, so the cost is irrelevant.
        """
        from fraud_engine.models import FlaggedRing

        latest = self._latest_score(obj)
        qs = FlaggedRing.objects.all()
        if latest is not None and latest.run_id:
            qs = qs.filter(run_id=latest.run_id)

        return [
            {
                "id": ring.id,
                "kind": ring.kind,
                "risk_score": round(ring.risk_score, 2),
                "ring_size": ring.ring_size,
                "status": ring.status,
                "officer_confirmed": ring.officer_confirmed,
            }
            for ring in qs
            if obj.id in (ring.company_ids or [])
        ]


class InvoiceSerializer(serializers.ModelSerializer):
    seller_name = serializers.CharField(source="seller.name", read_only=True)
    buyer_name = serializers.CharField(source="buyer.name", read_only=True)

    class Meta:
        model = Invoice
        fields = [
            "id",
            "seller",
            "seller_name",
            "buyer",
            "buyer_name",
            "amount",
            "date",
            "goods_description",
            "has_eway_bill",
        ]
