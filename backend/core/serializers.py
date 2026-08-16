from rest_framework import serializers

from .models import Company, Invoice


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
    """
    Company plus its trade summary.

    The fraud engine bolts its risk score onto this serializer later in the
    build; for now it is the base record plus simple counts.
    """

    total_sales_count = serializers.SerializerMethodField()
    total_purchase_count = serializers.SerializerMethodField()

    class Meta(CompanySerializer.Meta):
        fields = CompanySerializer.Meta.fields + [
            "total_sales_count",
            "total_purchase_count",
        ]

    def get_total_sales_count(self, obj):
        return obj.sales_invoices.count()

    def get_total_purchase_count(self, obj):
        return obj.purchase_invoices.count()


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
