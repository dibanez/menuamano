"""Mark the catalogue ingredients that are, or usually carry, added sugars.

People with diabetes have a restriction on added sugars. Processed products keep their
"review the label" status: some brands sell them without sugar, and a household label review
replaces this information.
"""

from django.db import migrations

ADDED_SUGAR = "added_sugar"
SUGARY = ["Azúcar", "Miel", "Mermelada", "Chocolate negro", "Tomate frito"]


def mark(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    for ingredient in Ingredient.objects.filter(household__isnull=True, name__in=SUGARY):
        if ADDED_SUGAR not in ingredient.traits:
            ingredient.traits = sorted([*ingredient.traits, ADDED_SUGAR])
            ingredient.save(update_fields=["traits"])


def unmark(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    for ingredient in Ingredient.objects.filter(household__isnull=True, name__in=SUGARY):
        if ADDED_SUGAR in ingredient.traits:
            ingredient.traits = [trait for trait in ingredient.traits if trait != ADDED_SUGAR]
            ingredient.save(update_fields=["traits"])


class Migration(migrations.Migration):
    dependencies = [("foods", "0008_alter_ingredient_traits_and_more")]

    operations = [migrations.RunPython(mark, unmark)]
