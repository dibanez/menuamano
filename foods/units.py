"""Quantity arithmetic. Conversions only happen inside one dimension (mass, volume)."""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .models import UNIT_INFO, Dimension, Unit

BASE_UNIT = {Dimension.MASS: Unit.G, Dimension.VOLUME: Unit.ML}

PLURALS = {
    Unit.UNIT: "unidades",
    Unit.CLOVE: "dientes",
    Unit.SLICE: "lonchas",
    Unit.CAN: "latas",
    Unit.BUNCH: "manojos",
    Unit.PACK: "paquetes",
    Unit.PINCH: "pizcas",
    Unit.TBSP: "cucharadas",
    Unit.TSP: "cucharaditas",
}


def dimension_of(unit):
    return UNIT_INFO[Unit(unit)][0]


def to_base(quantity, unit):
    """Return (aggregation unit, quantity in that unit).

    Mass goes to grams and volume to millilitres. Count units stay as they are, so
    «2 dientes» and «1 unidad» of the same ingredient are never merged.
    """
    unit = Unit(unit)
    dimension, factor = UNIT_INFO[unit]
    if factor is None:
        return unit, Decimal(quantity)
    return BASE_UNIT[dimension], Decimal(quantity) * factor


def scale(quantity, base_servings, servings):
    if quantity is None:
        return None
    if not base_servings:
        return Decimal(quantity)
    return (Decimal(quantity) * Decimal(servings) / Decimal(base_servings)).quantize(Decimal("0.001"))


def format_number(value, places=2):
    if value is None or value == "":
        return ""
    try:
        value = Decimal(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return str(value)
    text = f"{value:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def unit_label(unit, quantity=None):
    unit = Unit(unit)
    if quantity is not None and Decimal(quantity) != 1 and unit in PLURALS:
        return PLURALS[unit]
    return unit.label


def format_quantity(quantity, unit):
    """Human friendly quantity: 1500 g -> «1,5 kg», 3 unit -> «3 unidades»."""
    if quantity is None:
        return "al gusto"
    quantity = Decimal(quantity)
    unit = Unit(unit)
    if unit == Unit.G and quantity >= 1000:
        quantity, unit = quantity / 1000, Unit.KG
    elif unit == Unit.ML and quantity >= 1000:
        quantity, unit = quantity / 1000, Unit.L
    places = 0 if unit in (Unit.G, Unit.ML) and quantity >= 10 else 2
    number = format_number(quantity, places)
    return f"{number} {unit_label(unit, quantity)}"
