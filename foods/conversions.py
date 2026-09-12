"""Conversions between pieces, volumes and grams, only through known equivalences.

Within a dimension (g↔kg, ml↔l, tablespoons) conversions are exact and live in `foods.units`.
Across dimensions a `UnitConversion` must exist for the ingredient; otherwise nothing is
converted and quantities stay apart. Results of cross-dimension conversions are approximate.
"""

from decimal import Decimal

from django.db.models import Q

from .models import UNIT_INFO, Dimension, Unit, UnitConversion
from .units import to_base


def load(household, ingredient_ids):
    """{ingredient_id: {unit: grams}} with the household's rows overriding the catalogue's."""
    tables = {}
    rows = UnitConversion.objects.filter(ingredient_id__in=list(ingredient_ids)).filter(
        Q(household__isnull=True) | Q(household=household)
    )
    for row in sorted(rows, key=lambda r: r.household_id is not None):
        tables.setdefault(row.ingredient_id, {})[str(row.unit)] = row.grams
    return tables


def shopping_unit(ingredient):
    """Unit used to aggregate an ingredient in the shopping list: its usual unit's base unit."""
    return to_base(Decimal("1"), ingredient.default_unit)[0]


def grams_per(unit, table):
    """Grams in one `unit` of the ingredient, or None when no equivalence is known."""
    dimension, factor = UNIT_INFO[Unit(unit)]
    if dimension == Dimension.MASS:
        return factor
    if dimension == Dimension.VOLUME:
        per_ml = table.get(str(Unit.ML))
        return per_ml * factor if per_ml else None
    return table.get(str(Unit(unit)))


def convert(quantity, unit, target_unit, table):
    """Convert `quantity unit` into `target_unit` through grams. None if an equivalence is missing."""
    source = grams_per(unit, table)
    target = grams_per(target_unit, table)
    if source is None or target is None:
        return None
    return (Decimal(quantity) * source / target).quantize(Decimal("0.001"))
