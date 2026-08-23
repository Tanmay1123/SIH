from django.contrib.auth import authenticate
from django.db.models import Q
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, parser_classes, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .csv_import import CsvImportError, load_dataset
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


# ---------------------------------------------------------------------------
# Dataset upload
# ---------------------------------------------------------------------------


@api_view(["POST"])
@parser_classes([MultiPartParser])
def upload_dataset(request):
    """
    POST /api/data/upload/  (multipart/form-data)

    Fields: `companies` and `invoices`, each a CSV file. See
    core/csv_import.py for the required column layout. Replaces the entire
    dataset - companies, invoices, detected rings, scores and the audit
    ledger - with what's in the two files.
    """
    companies_file = request.FILES.get("companies")
    invoices_file = request.FILES.get("invoices")
    if not companies_file or not invoices_file:
        return Response(
            {"detail": "Both a 'companies' file and an 'invoices' file are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = load_dataset(companies_file, invoices_file)
    except CsvImportError as exc:
        return Response(
            {"detail": "The upload could not be processed.", "errors": exc.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "detail": "Dataset loaded. Detected rings, scores and the audit "
            "ledger from any previous dataset have been cleared.",
            "companies_created": result.companies_created,
            "invoices_created": result.invoices_created,
        },
        status=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    """POST /api/auth/login/ — {username, password} -> {token, username}."""
    username = (request.data or {}).get("username", "").strip()
    password = (request.data or {}).get("password", "")

    user = authenticate(request, username=username, password=password)
    if user is None:
        return Response(
            {"detail": "Incorrect username or password."},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    token, _ = Token.objects.get_or_create(user=user)
    return Response({"token": token.key, "username": user.username})


@api_view(["POST"])
def logout(request):
    """POST /api/auth/logout/ — invalidate the caller's current token."""
    Token.objects.filter(user=request.user).delete()
    return Response({"detail": "Logged out."})


@api_view(["GET"])
def whoami(request):
    """GET /api/auth/whoami/ — used by the frontend to validate a stored token."""
    return Response({"username": request.user.username})
