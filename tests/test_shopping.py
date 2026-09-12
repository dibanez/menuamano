from datetime import timedelta
from decimal import Decimal

import pytest

from core.choices import MealType
from foods.units import format_quantity, to_base
from planning import services as planning
from planning.models import MealMode
from shopping import services as shopping
from shopping.models import ShoppingItem

from .factories import ingredient, make_diner, make_recipe


@pytest.fixture
def pasta(household):
    return make_recipe(
        household, "Espaguetis con tomate",
        [("Espaguetis", 400, "g"), ("Tomate triturado", 400, "g"), ("Ajo", 2, "clove"), ("Sal", None, "g")],
        base_servings=4,
    )


@pytest.fixture
def planned_dinner(household, admin_user, monday, pasta):
    make_diner(household, "Ana")
    make_diner(household, "Luis")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    meal, _ = planning.add_recipe(meal, pasta, admin_user)
    return meal


def items_by_name(shopping_list):
    return {i.name: i for i in shopping_list.items.all()}


def test_needs_scale_with_servings_and_skip_to_taste(household, admin_user, monday, planned_dinner):
    sl = shopping.create_list(household, admin_user, monday, monday + timedelta(days=6))
    items = items_by_name(sl)
    assert items["Espaguetis"].needed_quantity == Decimal("200")
    assert items["Ajo"].needed_quantity == Decimal("1")
    assert "Sal" not in items  # "to taste" lines never reach the list
    assert items["Espaguetis"].sources[0]["recipe"] == "Espaguetis con tomate"


def test_recalculating_twice_does_not_duplicate(household, admin_user, monday, planned_dinner):
    sl = shopping.create_list(household, admin_user, monday, monday)
    before = sorted((i.key, i.needed_quantity) for i in sl.items.all())
    shopping.recalculate(sl)
    shopping.recalculate(sl)
    after = sorted((i.key, i.needed_quantity) for i in sl.items.all())
    assert before == after
    assert sl.items.count() == len(before)


def test_recalculation_keeps_manual_items_and_purchases(household, admin_user, monday, planned_dinner):
    sl = shopping.create_list(household, admin_user, monday, monday)
    manual = shopping.add_manual_item(sl, "Servilletas", Decimal("1"), "pack")
    pasta_item = sl.items.get(name="Espaguetis")
    shopping.set_purchased(pasta_item, admin_user, Decimal("150"))

    shopping.recalculate(sl)

    manual.refresh_from_db()
    pasta_item.refresh_from_db()
    assert manual.name == "Servilletas" and manual.is_manual
    assert pasta_item.purchased_quantity == Decimal("150")
    assert pasta_item.pending_quantity == Decimal("50")


def test_eating_out_generates_no_ingredients(household, admin_user, monday, planned_dinner):
    sl = shopping.create_list(household, admin_user, monday, monday)
    assert sl.items.exists()
    planning.update_meal_details(
        planned_dinner, admin_user, mode=MealMode.EAT_OUT, notes="", locked=True, outcome="pending", outcome_notes=""
    )
    assert not sl.items.filter(is_manual=False).exists()
    assert shopping.compute_needs(household, monday, monday) == {}


@pytest.mark.parametrize("mode", [MealMode.ORDER, MealMode.FREE, MealMode.PENDING, MealMode.LEFTOVERS])
def test_other_non_cooking_modes_generate_nothing(household, admin_user, monday, planned_dinner, mode):
    planning.update_meal_details(planned_dinner, admin_user, mode=mode, notes="", locked=True, outcome="pending", outcome_notes="")
    assert shopping.compute_needs(household, monday, monday) == {}


def test_purchased_item_no_longer_needed_becomes_surplus(household, admin_user, monday, planned_dinner):
    sl = shopping.create_list(household, admin_user, monday, monday)
    pasta_item = sl.items.get(name="Espaguetis")
    shopping.set_purchased(pasta_item, admin_user, Decimal("200"))

    planning.remove_recipe(planned_dinner.recipes.get(), admin_user)

    pasta_item.refresh_from_db()
    assert pasta_item.needed_quantity == 0
    assert pasta_item.purchased_quantity == Decimal("200")
    assert pasta_item.is_surplus
    # Unpurchased computed items disappear.
    assert not sl.items.filter(name="Tomate triturado").exists()


def test_same_ingredient_merges_and_incompatible_units_stay_apart(household, admin_user, monday):
    make_diner(household, "Ana")
    r1 = make_recipe(household, "A", [("Harina de trigo", "0.5", "kg"), ("Huevo", 2, "unit")], base_servings=1)
    r2 = make_recipe(household, "B", [("Harina de trigo", 250, "g"), ("Leche entera", 1, "tbsp"), ("Leche entera", "0.2", "l")], base_servings=1)
    meal, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    planning.add_recipe(meal, r1, admin_user)
    planning.add_recipe(meal, r2, admin_user)
    needs = shopping.compute_needs(household, monday, monday)

    flour = needs[shopping.item_key(ingredient("Harina de trigo").pk, "g")]
    milk = needs[shopping.item_key(ingredient("Leche entera").pk, "ml")]
    assert flour.quantity == Decimal("750")
    assert milk.quantity == Decimal("215")
    assert shopping.item_key(ingredient("Huevo").pk, "unit") in needs


def test_count_units_are_never_converted():
    assert to_base(Decimal("2"), "clove") == ("clove", Decimal("2"))
    assert to_base(Decimal("1.5"), "kg")[1] == Decimal("1500")
    assert format_quantity(Decimal("1500"), "g") == "1,5 kg"
    assert format_quantity(Decimal("3"), "unit") == "3 unidades"


def test_manual_quantity_correction_is_used(household, admin_user, monday, planned_dinner):
    line = planned_dinner.recipes.get().ingredients.get(ingredient__name="Ajo")
    planning.set_manual_quantity(line, admin_user, Decimal("3"))
    needs = shopping.compute_needs(household, monday, monday)
    assert needs[shopping.item_key(line.ingredient_id, "clove")].quantity == Decimal("3")


def test_suggested_purchase_rounds_pieces_up_only():
    eggs = ShoppingItem(unit="unit", needed_quantity=Decimal("1.9"), purchased_quantity=Decimal("0"))
    assert eggs.suggested_purchase == Decimal("2")
    eggs.purchased_quantity = Decimal("1")
    assert eggs.suggested_purchase == Decimal("1")  # 0.9 still pending
    assert ShoppingItem(unit="unit", needed_quantity=Decimal("3")).suggested_purchase is None
    assert ShoppingItem(unit="g", needed_quantity=Decimal("150.5")).suggested_purchase is None
    assert ShoppingItem(unit="unit", needed_quantity=Decimal("1.5"), is_manual=True).suggested_purchase is None


def test_list_for_other_range_is_not_touched(household, admin_user, monday, planned_dinner):
    other = shopping.create_list(household, admin_user, monday + timedelta(days=10), monday + timedelta(days=12))
    assert not ShoppingItem.objects.filter(shopping_list=other).exists()
