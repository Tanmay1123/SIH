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

from .models import Company, Invoice

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
def load_dataset(companies_file, invoices_file) -> ImportResult:
    """
    Replace the entire dataset with what's in the two uploaded files.

    Mirrors the old seed-data command's behaviour: a new dataset is a new
    investigation universe, so detected rings, scores and the audit ledger are
    cleared along with the companies and invoices. (Confirmed rings already
    written to the ledger were, by design, permanent evidence of a decision
    made about the *previous* dataset - once that dataset is gone the rings
    referencing it can no longer be meaningfully re-examined, so they are
    cleared too. This mirrors exactly how `seed_demo_data` behaved before it
    was removed.)
    """
    company_rows, company_errors = parse_companies(companies_file)
    if company_errors:
        raise CsvImportError(company_errors)

    known_gstins = {c["gstin"] for c in company_rows}
    invoice_rows, invoice_errors = parse_invoices(invoices_file, known_gstins)
    if invoice_errors:
        raise CsvImportError(invoice_errors)

    # Local import: avoids a core -> fraud_engine import at module load time.
    from fraud_engine.models import FlaggedRing, LedgerBlock, RiskScore

    LedgerBlock.objects.all().delete()
    FlaggedRing.objects.all().delete()
    RiskScore.objects.all().delete()
    Invoice.objects.all().delete()
    Company.objects.all().delete()

    companies = Company.objects.bulk_create(
        [Company(**row) for row in company_rows], batch_size=500
    )
    pk_by_gstin = {c.gstin: c.pk for c in companies}

    Invoice.objects.bulk_create(
        [
            Invoice(
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

    return ImportResult(
        companies_created=len(companies), invoices_created=len(invoice_rows)
    )
