"""Shopping list computation.

Needed quantities are derived from the plan; purchased quantities and manual items belong to
people and are never overwritten by a recalculation. Recalculating is idempotent.
"""

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from foods.models import CATEGORY_ORDER, Category
from foods.units import scale, to_base
from planning.models import MODES_WITH_SHOPPING
from planning.services import meals_queryset

from .models import ShoppingItem, ShoppingList

ZERO = Decimal("0")


@dataclass
class Need:
    ingredient: object
    unit: str
    quantity: Decimal = ZERO
    sources: list = field(default_factory=list)


def item_key(ingredient_id, unit):
    return f"ing:{ingredient_id}:{str(unit)}"


def compute_needs(household, start, end):
    """Aggregate ingredients of meals that need preparation, scaled to planned servings."""
    needs = OrderedDict()
    meals = meals_queryset(household).filter(date__gte=start, date__lte=end, mode__in=MODES_WITH_SHOPPING)
    for meal in meals.order_by("date", "meal_type"):
        meal_servings = meal.servings
        for meal_recipe in meal.recipes.all():
            servings = meal_recipe.effective_servings(meal_servings)
            for line in meal_recipe.ingredients.all():
                if line.manual_quantity is not None:
                    total = line.manual_quantity
                else:
                    total = scale(line.quantity, meal_recipe.base_servings, servings)
                if total is None or total <= 0:
                    continue  # "to taste" or nobody attending
                unit, quantity = to_base(total, line.unit)
                key = item_key(line.ingredient_id, unit)
                need = needs.setdefault(key, Need(ingredient=line.ingredient, unit=unit))
                need.quantity += quantity
                need.sources.append(
                    {
                        "meal_id": meal.pk,
                        "date": meal.date.isoformat(),
                        "meal_type": meal.get_meal_type_display(),
                        "recipe": meal_recipe.name,
                        "quantity": str(quantity.quantize(Decimal("0.001"))),
                        "unit": str(unit),
                    }
                )
    return needs


@dataclass
class RecalcStats:
    created: int = 0
    updated: int = 0
    surplus: int = 0
    removed: int = 0


def recalculate(shopping_list):
    stats = RecalcStats()
    needs = compute_needs(shopping_list.household, shopping_list.start_date, shopping_list.end_date)
    with transaction.atomic():
        # Row lock serialises concurrent recalculations of the same list.
        ShoppingList.objects.select_for_update().get(pk=shopping_list.pk)
        existing = {item.key: item for item in shopping_list.items.filter(is_manual=False)}
        for key, need in needs.items():
            quantity = need.quantity.quantize(Decimal("0.001"))
            item = existing.pop(key, None)
            if item is None:
                ShoppingItem.objects.create(
                    shopping_list=shopping_list, key=key, ingredient=need.ingredient, name=need.ingredient.name,
                    category=need.ingredient.category, unit=need.unit, needed_quantity=quantity, sources=need.sources,
                )
                stats.created += 1
            else:
                item.needed_quantity = quantity
                item.sources = need.sources
                item.name = need.ingredient.name
                item.category = need.ingredient.category
                item.save(update_fields=["needed_quantity", "sources", "name", "category", "updated_at"])
                stats.updated += 1
        for item in existing.values():
            if item.purchased_quantity > 0:
                # Keep the purchase record; it shows up as surplus of the plan.
                item.needed_quantity = ZERO
                item.sources = []
                item.save(update_fields=["needed_quantity", "sources", "updated_at"])
                stats.surplus += 1
            else:
                item.delete()
                stats.removed += 1
        shopping_list.recalculated_at = timezone.now()
        shopping_list.save(update_fields=["recalculated_at"])
    return stats


def recalculate_for_dates(household, dates):
    dates = [d for d in dates if d]
    if not dates:
        return 0
    first, last = min(dates), max(dates)
    lists = ShoppingList.objects.filter(household=household, start_date__lte=last, end_date__gte=first)
    count = 0
    for shopping_list in lists:
        if any(shopping_list.start_date <= d <= shopping_list.end_date for d in dates):
            recalculate(shopping_list)
            count += 1
    return count


@transaction.atomic
def create_list(household, user, start, end, name=""):
    shopping_list = ShoppingList.objects.create(
        household=household, created_by=user, start_date=start, end_date=end, name=name
    )
    recalculate(shopping_list)
    return shopping_list


def set_purchased(item, user, quantity):
    item.purchased_quantity = max(Decimal(quantity), ZERO)
    item.purchased_by = user
    item.purchased_at = timezone.now()
    item.save(update_fields=["purchased_quantity", "purchased_by", "purchased_at", "updated_at"])
    return item


def add_manual_item(shopping_list, name, quantity=None, unit="", note="", category=Category.OTHER):
    return ShoppingItem.objects.create(
        shopping_list=shopping_list, is_manual=True, name=name, needed_quantity=quantity or ZERO,
        unit=unit, manual_note=note, category=category,
    )


def grouped_items(shopping_list):
    """Items grouped by category in aisle order, with surplus items listed separately."""
    labels = dict(Category.choices)
    groups = OrderedDict((c, []) for c in CATEGORY_ORDER)
    surplus = []
    for item in shopping_list.items.select_related("ingredient").order_by("name"):
        if item.is_surplus and item.needed_quantity == 0:
            surplus.append(item)
        else:
            groups.setdefault(item.category, []).append(item)
    return [(labels.get(c, c), items) for c, items in groups.items() if items], surplus
