"""Quantities at home («Tenemos una cantidad») become pantry batches without expiry date."""

from django.db import migrations


def stock_to_batches(apps, schema_editor):
    PantryItem = apps.get_model("shopping", "PantryItem")
    PantryBatch = apps.get_model("shopping", "PantryBatch")
    for entry in PantryItem.objects.filter(kind="stock"):
        PantryBatch.objects.create(
            household_id=entry.household_id, ingredient_id=entry.ingredient_id, quantity=entry.quantity,
            unit=entry.unit if entry.quantity is not None else "", bought_on=entry.updated_at.date(),
            created_by_id=entry.updated_by_id,
        )
        entry.delete()


class Migration(migrations.Migration):
    dependencies = [("shopping", "0004_pantry_batches")]

    operations = [migrations.RunPython(stock_to_batches, migrations.RunPython.noop)]
