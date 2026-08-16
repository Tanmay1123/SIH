from django.db.models import Q
from rest_framework import generics
from rest_framework.pagination import PageNumberPagination

from .models import Company, Invoice
from .serializers import (
    CompanyDetailSerializer,
    CompanySerializer,
    InvoiceSerializer,
)


class StandardPagination(PageNumberPagination):
    """
    Pagination for list endpoints, with a client-controlled `?page_size=`
    (capped at 500) so the dashboard can fetch a whole feed in one request
    instead of stitching pages together in the browser.

    Applied per-view rather than as REST_FRAMEWORK's DEFAULT_PAGINATION_CLASS:
    rest_framework.generics resolves that setting while its own module body is
    still executing, so naming a class that lives in a module which imports
    generics is a circular import.
    """

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 500


class CompanyListView(generics.ListAPIView):
    """GET /api/companies/ — paginated company list, optional ?search= by name/GSTIN."""

    serializer_class = CompanySerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Company.objects.all()
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(gstin__icontains=search))
        return qs


class CompanyDetailView(generics.RetrieveAPIView):
    """GET /api/companies/{id}/ — a single company record."""

    queryset = Company.objects.all()
    serializer_class = CompanyDetailSerializer


class InvoiceListView(generics.ListAPIView):
    """
    GET /api/invoices/ — paginated invoice list.

    Filters:
      ?company=<id>  invoices where the company is either side of the trade
      ?seller=<id> / ?buyer=<id>  one side only
    """

    serializer_class = InvoiceSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Invoice.objects.select_related("seller", "buyer")
        params = self.request.query_params

        company = params.get("company")
        if company:
            qs = qs.filter(Q(seller_id=company) | Q(buyer_id=company))

        seller = params.get("seller")
        if seller:
            qs = qs.filter(seller_id=seller)

        buyer = params.get("buyer")
        if buyer:
            qs = qs.filter(buyer_id=buyer)

        return qs


class InvoiceDetailView(generics.RetrieveAPIView):
    queryset = Invoice.objects.select_related("seller", "buyer")
    serializer_class = InvoiceSerializer
