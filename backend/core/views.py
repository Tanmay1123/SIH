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
from .models import Company, Dataset, Invoice, active_dataset
from .serializers import (
    CompanyDetailSerializer,
    CompanySerializer,
    DatasetSerializer,
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
        dataset = active_dataset()
        if dataset is not None:
            qs = qs.filter(dataset=dataset)
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
        dataset = active_dataset()
        if dataset is not None:
            qs = qs.filter(dataset=dataset)
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
# Datasets
# ---------------------------------------------------------------------------


class DatasetListView(generics.ListAPIView):
    """GET /api/datasets/ — every upload, newest first."""

    queryset = Dataset.objects.select_related("uploaded_by")
    serializer_class = DatasetSerializer
    pagination_class = None


@api_view(["POST"])
def activate_dataset(request, pk):
    """
    POST /api/datasets/{id}/activate/

    Switch which upload the whole application is looking at. Past detection
    runs against that dataset come back with it.
    """
    dataset = Dataset.objects.filter(pk=pk).first()
    if dataset is None:
        return Response({"detail": "Dataset not found."}, status=status.HTTP_404_NOT_FOUND)
    dataset.activate()
    return Response(
        {"detail": f"'{dataset.name}' is now the active dataset.",
         "dataset": DatasetSerializer(dataset).data}
    )


@api_view(["PATCH"])
def rename_dataset(request, pk):
    """PATCH /api/datasets/{id}/ — {"name": "...", "note": "..."}"""
    dataset = Dataset.objects.filter(pk=pk).first()
    if dataset is None:
        return Response({"detail": "Dataset not found."}, status=status.HTTP_404_NOT_FOUND)

    data = request.data or {}
    name = (data.get("name") or "").strip()
    if name:
        dataset.name = name[:200]
    if "note" in data:
        dataset.note = data.get("note") or ""
    dataset.save(update_fields=["name", "note"])
    return Response(DatasetSerializer(dataset).data)


@api_view(["DELETE"])
def delete_dataset(request, pk):
    """
    DELETE /api/datasets/{id}/delete/

    Removes an upload and everything detected from it. Refused if any of its
    runs produced a case report, because that report is part of the audit
    record and deleting the evidence behind it would leave a dangling claim.
    """
    dataset = Dataset.objects.filter(pk=pk).first()
    if dataset is None:
        return Response({"detail": "Dataset not found."}, status=status.HTTP_404_NOT_FOUND)

    from fraud_engine.models import CaseReport

    if CaseReport.objects.filter(run__dataset=dataset).exists():
        return Response(
            {
                "detail": "A case report has been issued from this dataset, so it is "
                "part of the audit record and cannot be deleted."
            },
            status=status.HTTP_409_CONFLICT,
        )

    was_active = dataset.is_active
    name = dataset.name
    dataset.delete()

    # Never leave the application with no active dataset while others exist.
    if was_active:
        replacement = Dataset.objects.first()
        if replacement is not None:
            replacement.activate()

    return Response({"detail": f"'{name}' deleted."})


@api_view(["POST"])
@parser_classes([MultiPartParser])
def upload_dataset(request):
    """
    POST /api/data/upload/  (multipart/form-data)

    Fields: `companies` and `invoices`, each a CSV file, plus an optional
    `name`. See core/csv_import.py for the required column layout.

    Each upload is stored as its own dataset and becomes the active one.
    Nothing is deleted: previous uploads, their detection runs and the audit
    ledger all survive, so an officer can come back and look at any of them.
    """
    companies_file = request.FILES.get("companies")
    invoices_file = request.FILES.get("invoices")
    if not companies_file or not invoices_file:
        return Response(
            {"detail": "Both a 'companies' file and an 'invoices' file are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        result = load_dataset(
            companies_file,
            invoices_file,
            name=request.data.get("name", ""),
            note=request.data.get("note", ""),
            user=request.user,
        )
    except CsvImportError as exc:
        return Response(
            {"detail": "The upload could not be processed.", "errors": exc.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "detail": f"'{result.dataset_name}' loaded and made active. "
            "Previous datasets and their detection runs are unchanged.",
            "dataset_id": result.dataset_id,
            "dataset_name": result.dataset_name,
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
