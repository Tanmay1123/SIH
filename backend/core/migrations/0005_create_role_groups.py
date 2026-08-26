"""
Create the two role groups and put existing accounts somewhere sensible.

Roles are Django Groups so they can be administered from /admin/ with no code
change. Existing superusers become supervisors — otherwise the first account,
created by `createsuperuser`, would find it could no longer confirm anything.
Everyone else lands as an officer, which is the safe default: officers can do
everything except sanction a case.
"""
from django.db import migrations

SUPERVISOR_GROUP = "Supervisors"
OFFICER_GROUP = "Officers"


def create_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")

    supervisors, _ = Group.objects.get_or_create(name=SUPERVISOR_GROUP)
    officers, _ = Group.objects.get_or_create(name=OFFICER_GROUP)

    for user in User.objects.all():
        if user.is_superuser:
            user.groups.add(supervisors)
        elif not user.groups.filter(name__in=[SUPERVISOR_GROUP, OFFICER_GROUP]).exists():
            user.groups.add(officers)


def drop_groups(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=[SUPERVISOR_GROUP, OFFICER_GROUP]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0004_appsetting"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [migrations.RunPython(create_groups, drop_groups)]
