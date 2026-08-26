"""
Parsing and loading for officer-uploaded datasets.

The running application never generates its own data. An officer uploads two
CSV files - one row per company, one row per invoice - and this module is the
only path by which Company/Invoice rows enter the database. Invoices reference
companies by GSTIN rather than database id, since the uploader has no idea what
primary keys this database will assign.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction

from .models import Company, Dataset, Invoice

COMPANY_COLUMNS = [
    "gstin", "pan", "name", "director_name", "registered_address",
    "registered_date", "declared_turnover",
]
INVOICE_COLUMNS = [
    "seller_gstin", "buyer_gstin", "amount", "date", "goods_description",
    "has_eway_bill",
]

TRUE_STRINGS = {"1", "true", "yes", "y"}
FALSE_STRINGS = {"0", "false", "no", "n", ""}


class CsvImportError(Exception):
    """Raised with a list of human-readable problems; nothing is written."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ImportResult:
    companies_created: int
    invoices_created: int
    dataset_id: int | None = None
    dataset_name: str = ""


def _read_rows(upload) -> list[dict]:
    text = upload.read().decode("utf-8-sig")
    return list(csv.DictReader(io.StringIO(text)))


def _require_columns(rows: list[dict], required: list[str], filename: str) -> None:
    if not rows:
        raise CsvImportError([f"{filename} has no data rows."])
    missing = [c for c in required if c not in rows[0]]
    if missing:
        raise CsvImportError(
            [f"{filename} is missing required column(s): {', '.join(missing)}"]
        )


def _parse_date(value: str, row_num: int, filename: str, errors: list[str]):
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    errors.append(f"{filename} row {row_num}: unparseable date '{value}'")
    return None


def _parse_decimal(value: str, row_num: int, filename: str, field: str, errors: list[str]):
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, AttributeError):
        errors.append(f"{filename} row {row_num}: unparseable {field} '{value}'")
        return None


def _parse_bool(value: str) -> bool:
    return (value or "").strip().lower() in TRUE_STRINGS


def parse_companies(upload) -> tuple[list[dict], list[str]]:
    rows = _read_rows(upload)
    _require_columns(rows, COMPANY_COLUMNS, upload.name)

    errors: list[str] = []
    seen_gstins: set[str] = set()
    parsed = []
    for i, row in enumerate(rows, start=2):  # header is row 1
        gstin = (row.get("gstin") or "").strip()
        if not gstin:
            errors.append(f"{upload.name} row {i}: missing gstin")
            continue
        if gstin in seen_gstins:
            errors.append(f"{upload.name} row {i}: duplicate gstin '{gstin}'")
            continue
        seen_gstins.add(gstin)

        registered_date = _parse_date(row.get("registered_date"), i, upload.name, errors)
        turnover = _parse_decimal(
            row.get("declared_turnover"), i, upload.name, "declared_turnover", errors
        )
        if registered_date is None or turnover is None:
            continue

        parsed.append(
            {
                "gstin": gstin,
                "pan": (row.get("pan") or "").strip(),
                "name": (row.get("name") or "").strip(),
                "director_name": (row.get("director_name") or "").strip(),
                "registered_address": (row.get("registered_address") or "").strip(),
                "registered_date": registered_date,
                "declared_turnover": turnover,
            }
        )
    return parsed, errors


def parse_invoices(upload, known_gstins: set[str]) -> tuple[list[dict], list[str]]:
    rows = _read_rows(upload)
    _require_columns(rows, INVOICE_COLUMNS, upload.name)

    errors: list[str] = []
    parsed = []
    for i, row in enumerate(rows, start=2):
        seller_gstin = (row.get("seller_gstin") or "").strip()
        buyer_gstin = (row.get("buyer_gstin") or "").strip()

        if seller_gstin not in known_gstins:
            errors.append(f"{upload.name} row {i}: seller_gstin '{seller_gstin}' not in companies file")
            continue
        if buyer_gstin not in known_gstins:
            errors.append(f"{upload.name} row {i}: buyer_gstin '{buyer_gstin}' not in companies file")
            continue

        inv_date = _parse_date(row.get("date"), i, upload.name, errors)
        amount = _parse_decimal(row.get("amount"), i, upload.name, "amount", errors)
        if inv_date is None or amount is None:
            continue

        parsed.append(
            {
                "seller_gstin": seller_gstin,
                "buyer_gstin": buyer_gstin,
                "amount": amount,
                "date": inv_date,
                "goods_description": (row.get("goods_description") or "").strip(),
                "has_eway_bill": _parse_bool(row.get("has_eway_bill")),
            }
        )
        # Cap the error list so one badly-formed file doesn't return megabytes
        # of messages - the first 200 problems are enough to know it's broken.
        if len(errors) > 200:
            errors.append("... too many errors, stopped checking further rows.")
            break
    return parsed, errors


@transaction.atomic
def load_dataset(
    companies_file, invoices_file, name: str = "", user=None, note: str = ""
) -> ImportResult:
    """
    Load an uploaded CSV pair as a new Dataset and make it the active one.

    This no longer wipes anything. Each upload is its own investigation
    universe: previous datasets, the detection runs made against them, and the
    audit ledger all survive. That is what lets an officer come back next week,
    pick an earlier upload, and see exactly what was found in it.

    The new dataset becomes active, so the dashboard, the graph and detection
    all immediately point at it.
    """
    company_rows, company_errors = parse_companies(companies_file)
    if company_errors:
        raise CsvImportError(company_errors)

    known_gstins = {c["gstin"] for c in company_rows}
    invoice_rows, invoice_errors = parse_invoices(invoices_file, known_gstins)
    if invoice_errors:
        raise CsvImportError(invoice_errors)

    dataset = Dataset.objects.create(
        name=(name or "").strip() or _default_name(),
        note=note or "",
        uploaded_by=user if (user is not None and user.is_authenticated) else None,
        companies_filename=getattr(companies_file, "name", "") or "",
        invoices_filename=getattr(invoices_file, "name", "") or "",
        company_count=len(company_rows),
        invoice_count=len(invoice_rows),
    )

    companies = Company.objects.bulk_create(
        [Company(dataset=dataset, **row) for row in company_rows], batch_size=500
    )
    # bulk_create does not populate primary keys on every backend, so read them
    # back rather than trusting the returned instances.
    pk_by_gstin = dict(
        Company.objects.filter(dataset=dataset).values_list("gstin", "pk")
    )

    Invoice.objects.bulk_create(
        [
            Invoice(
                dataset=dataset,
                seller_id=pk_by_gstin[row["seller_gstin"]],
                buyer_id=pk_by_gstin[row["buyer_gstin"]],
                amount=row["amount"],
                date=row["date"],
                goods_description=row["goods_description"],
                has_eway_bill=row["has_eway_bill"],
            )
            for row in invoice_rows
        ],
        batch_size=1000,
    )

    dataset.activate()

    return ImportResult(
        companies_created=len(companies),
        invoices_created=len(invoice_rows),
        dataset_id=dataset.pk,
        dataset_name=dataset.name,
    )


def _default_name() -> str:
    """A readable fallback name when the officer did not supply one."""
    from django.utils import timezone

    return f"Upload {timezone.localtime().strftime('%d %b %Y, %H:%M')}"
