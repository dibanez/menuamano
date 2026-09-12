from django import template

from core.choices import MealType
from foods.models import Trait
from foods.units import format_number, format_quantity

register = template.Library()

TRAIT_LABELS = dict(Trait.choices)
MEAL_LABELS = dict(MealType.choices)
STATUS_LABELS = {
    "ok": "Compatible",
    "unknown": "Revisar",
    "conflict": "Incompatible",
}


@register.filter
def qty(value, unit):
    return format_quantity(value, unit)


@register.filter
def num(value):
    return format_number(value)


@register.filter
def input_num(value):
    """Value for <input type="number">: always a dot decimal, never localised."""
    return format_number(value).replace(",", ".")


@register.filter
def trait_label(value):
    return TRAIT_LABELS.get(value, value)


@register.filter
def meal_label(value):
    return MEAL_LABELS.get(value, value)


@register.filter
def status_label(value):
    return STATUS_LABELS.get(value, "")


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    return mapping.get(key)


@register.inclusion_tag("partials/status_badge.html")
def status_badge(status):
    return {"status": status, "label": STATUS_LABELS.get(status, "")}
