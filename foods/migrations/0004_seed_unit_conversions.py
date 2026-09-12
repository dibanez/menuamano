"""Seed approximate weight equivalences for the shared catalogue.

Pieces refer to a medium size. Volume rows give grams per millilitre and apply to every volume
unit (ml, l, tablespoons). Households can override any of them for their own use.
"""

from decimal import Decimal

from django.db import migrations
from django.utils.text import slugify

MEDIUM = "tamaño mediano, aproximado"
DENSITY = "densidad aproximada"

# ingredient name, unit, grams per unit, note
CONVERSIONS = [
    ("Huevo", "unit", "60", "huevo mediano con cáscara, aproximado"),
    ("Tomate", "unit", "150", MEDIUM),
    ("Cebolla", "unit", "150", MEDIUM),
    ("Patata", "unit", "200", MEDIUM),
    ("Zanahoria", "unit", "80", MEDIUM),
    ("Calabacín", "unit", "250", MEDIUM),
    ("Pimiento rojo", "unit", "200", MEDIUM),
    ("Pimiento verde", "unit", "150", MEDIUM),
    ("Berenjena", "unit", "300", MEDIUM),
    ("Pepino", "unit", "250", MEDIUM),
    ("Puerro", "unit", "150", MEDIUM),
    ("Lechuga", "unit", "400", MEDIUM),
    ("Limón", "unit", "120", MEDIUM),
    ("Naranja", "unit", "200", MEDIUM),
    ("Plátano", "unit", "120", MEDIUM),
    ("Manzana", "unit", "180", MEDIUM),
    ("Kiwi", "unit", "80", MEDIUM),
    ("Aguacate", "unit", "200", MEDIUM),
    ("Ajo", "clove", "5", "diente mediano, aproximado"),
    ("Aceite de oliva", "ml", "0.92", DENSITY),
    ("Leche entera", "ml", "1.03", DENSITY),
    ("Leche sin lactosa", "ml", "1.03", DENSITY),
    ("Nata para cocinar", "ml", "1.0", DENSITY),
    ("Azúcar", "ml", "0.85", "azúcar blanco a granel, aproximado"),
    ("Sal", "ml", "1.2", "sal fina, aproximado"),
    ("Harina de trigo", "ml", "0.55", "harina sin tamizar, aproximado"),
]


def normalized(name):
    return slugify(name).replace("-", " ").strip()


def seed(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    UnitConversion = apps.get_model("foods", "UnitConversion")
    for name, unit, grams, note in CONVERSIONS:
        ingredient = Ingredient.objects.filter(household__isnull=True, normalized_name=normalized(name)).first()
        if ingredient is None:
            continue
        UnitConversion.objects.update_or_create(
            ingredient=ingredient, household=None, unit=unit, defaults={"grams": Decimal(grams), "note": note}
        )


def unseed(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    UnitConversion = apps.get_model("foods", "UnitConversion")
    names = [normalized(name) for name, *_ in CONVERSIONS]
    UnitConversion.objects.filter(
        household__isnull=True, ingredient__in=Ingredient.objects.filter(household__isnull=True, normalized_name__in=names)
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("foods", "0003_unit_conversion")]

    operations = [migrations.RunPython(seed, unseed)]
