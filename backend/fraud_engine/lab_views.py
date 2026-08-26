"""
API for the Dataset Lab.

The lab is a workshop, not part of the case-handling console. It reads nothing
from the database, sees no company, invoice, alert or officer decision, and
produces nothing but fabricated CSV text. That is why `presets`, `preview` and
`download` are open: the lab exists to produce the data an empty console needs,
and putting it behind the login of the console it is meant to fill would be a
circle.

`load` is different - it writes rows - so it needs an account, and it goes in
through `core.csv_import.load_dataset`, the same validated door an officer's
upload uses. Generated data gets no shortcut past the importer.
"""
from __future__ import annotations

import io
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from core.csv_import import CsvImportError, load_dataset

from .dataset_lab import (
    BAND_BLURBS,
    BAND_LABELS,
    BAND_ORDER,
    MAX_COMPANIES,
    MEDIUM_FLOOR,
    MIN_COMPANIES,
    PRESETS,
    LabSpec,
    analyse,
    build_lab_dataset,
    readme_text,
    summarise,
)

# How many rows of each file the preview hands back, so the UI can show what
# the CSV actually looks like without shipping the whole thing.
SAMPLE_ROWS = 6


@api_view(["GET"])
@permission_classes([AllowAny])
def lab_presets(request):
    """The starting points, plus the limits the UI should enforce locally."""
    return Response(
        {
            "presets": PRESETS,
            "defaults": LabSpec().as_dict(),
            "limits": {
                "min_companies": MIN_COMPANIES,
                "max_companies": MAX_COMPANIES,
            },
            "bands": [
                {"key": key, "label": BAND_LABELS[key], "blurb": BAND_BLURBS[key]}
                for key in BAND_ORDER
            ],
            "medium_floor": MEDIUM_FLOOR,
        }
    )


def _generate(request):
    spec = LabSpec.from_dict(request.data.get("spec") or request.data)
    return spec, build_lab_dataset(spec)


@api_view(["POST"])
@permission_classes([AllowAny])
def lab_preview(request):
    """
    Generate a dataset and run the real detector over it, without saving either.

    The response deliberately carries two different things: what was *planted*
    (from the answer key) and what was *found* (from the pipeline). Showing only
    the first would let the lab claim a success it never demonstrated.
    """
    spec, dataset = _generate(request)
    return Response(
        {
            "spec": spec.as_dict(),
            "summary": summarise(dataset),
            "analysis": analyse(dataset),
            "sample": {
                "companies": dataset.companies[:SAMPLE_ROWS],
                "invoices": dataset.invoices[:SAMPLE_ROWS],
                # Planted rows first. The first six rows of the answer key are
                # almost always ordinary traders, which shows nothing about
                # what the file is for.
                "answer_key": sorted(
                    dataset.answer_key,
                    key=lambda row: BAND_ORDER.index(row["band"]),
                )[:SAMPLE_ROWS],
            },
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def lab_download(request):
    """The two upload files plus the answer key and a note, as one zip."""
    spec, dataset = _generate(request)
    generated_at = timezone.localtime().strftime("%d %b %Y at %H:%M")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("companies.csv", dataset.companies_csv())
        archive.writestr("invoices.csv", dataset.invoices_csv())
        archive.writestr("answer_key.csv", dataset.answer_key_csv())
        archive.writestr("README.txt", readme_text(dataset, generated_at))

    stamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    filename = f"codenova-dataset-seed{spec.seed}-{stamp}.zip"

    response = HttpResponse(buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def lab_load(request):
    """
    Generate a dataset and load it into the console as a new Dataset.

    Goes through `load_dataset` rather than writing rows directly, so generated
    data is parsed and validated by exactly the code that handles a real
    upload. If the generator ever emitted something the importer would reject,
    this is where it would fail - which is the point of not bypassing it.
    """
    spec, dataset = _generate(request)

    name = (request.data.get("name") or "").strip() or (
        f"Generated - seed {spec.seed}"
    )
    note = (
        f"Fabricated by the Dataset Lab. Seed {spec.seed}: {spec.rings} rings, "
        f"{spec.mills} mills, {spec.grey_rings} grey rings, "
        f"{spec.grey_mills} grey mills, {spec.honest_loops} honest loops. "
        "No real taxpayer data."
    )

    companies_file = SimpleUploadedFile(
        "companies.csv", dataset.companies_csv().encode("utf-8"), "text/csv"
    )
    invoices_file = SimpleUploadedFile(
        "invoices.csv", dataset.invoices_csv().encode("utf-8"), "text/csv"
    )

    try:
        result = load_dataset(
            companies_file, invoices_file, name=name, user=request.user, note=note
        )
    except CsvImportError as exc:
        return Response(
            {"detail": "The generated data failed import.", "errors": exc.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "dataset_id": result.dataset_id,
            "dataset_name": result.dataset_name,
            "companies_created": result.companies_created,
            "invoices_created": result.invoices_created,
            "spec": spec.as_dict(),
            "summary": summarise(dataset),
        },
        status=status.HTTP_201_CREATED,
    )
