"""
Wrap any pre-existing companies/invoices into a Dataset.

Before this release an upload replaced everything and there was no Dataset
concept, so rows carry no dataset link. Left alone they would become invisible
the moment a new dataset was uploaded, since every query now filters by the
active dataset. This adopts them into one clearly-named dataset and makes it
active, so an existing install keeps working exactly as it did.
"""
from django.db import migrations


def adopt(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    Company = apps.get_model("core", "Company")
    Invoice = apps.get_model("core", "Invoice")

    orphans = Company.objects.filter(dataset__isnull=True)
    if not orphans.exists():
        return

    dataset = Dataset.objects.create(
        name="Existing data",
        note=(
            "Created automatically when dataset history was introduced. These "
            "companies and invoices were already loaded and had no dataset of "
            "their own."
        ),
        company_count=orphans.count(),
        invoice_count=Invoice.objects.filter(dataset__isnull=True).count(),
        is_active=not Dataset.objects.filter(is_active=True).exists(),
    )

    orphans.update(dataset=dataset)
    Invoice.objects.filter(dataset__isnull=True).update(dataset=dataset)


def unadopt(apps, schema_editor):
    Dataset = apps.get_model("core", "Dataset")
    Company = apps.get_model("core", "Company")
    Invoice = apps.get_model("core", "Invoice")

    for dataset in Dataset.objects.filter(name="Existing data"):
        Company.objects.filter(dataset=dataset).update(dataset=None)
        Invoice.objects.filter(dataset=dataset).update(dataset=None)
        dataset.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0002_alter_company_gstin_dataset_company_dataset_and_more"),
    ]

    operations = [migrations.RunPython(adopt, unadopt)]
