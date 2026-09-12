"""Add the "legumes" trait to pulses and to every ingredient that contains soy, peanut or lupin.

Keeps stored traits consistent with IMPLIED_TRAITS (soy, peanut and lupin imply legumes), which
Ingredient.save() applies from now on but historical rows do not have yet.
"""

from django.db import migrations
from django.utils.text import slugify

PULSES = ["Lentejas", "Garbanzos cocidos", "Alubias blancas", "Guisantes congelados"]
LEGUME_SOURCES = ["soy", "peanut", "lupin"]


def normalized(name):
    return slugify(name).replace("-", " ").strip()


def add_legumes(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    pulses = Ingredient.objects.filter(household__isnull=True, normalized_name__in=[normalized(n) for n in PULSES])
    implied = Ingredient.objects.filter(traits__overlap=LEGUME_SOURCES)
    for ingredient in (pulses | implied).distinct():
        if "legumes" not in ingredient.traits:
            ingredient.traits = sorted({*ingredient.traits, "legumes"})
            ingredient.save(update_fields=["traits"])


def remove_legumes(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    for ingredient in Ingredient.objects.filter(traits__contains=["legumes"]):
        ingredient.traits = [t for t in ingredient.traits if t != "legumes"]
        ingredient.save(update_fields=["traits"])


class Migration(migrations.Migration):
    dependencies = [("foods", "0005_legumes_trait")]

    operations = [migrations.RunPython(add_legumes, remove_legumes)]
