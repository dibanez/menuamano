"""The pantry: staples are listed apart, quantities at home are taken off the shopping list."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from core.choices import MealType
from households.models import Role
from planning import services as planning
from shopping import services as shopping
from shopping.models import PantryItem

from .factories import PASSWORD, add_member, ingredient, make_diner, make_household, make_recipe, make_user


@pytest.fixture
def shopping_list(household, admin_user, monday):
    make_diner(household, "Ana")
    make_diner(household, "Luis")
    recipe = make_recipe(
        household, "Espaguetis con tomate",
        [("Espaguetis", 400, "g"), ("Tomate triturado", 400, "g"), ("Ajo", 2, "clove")],
    )
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, recipe, admin_user)
    return shopping.create_list(household, admin_user, monday, monday + timedelta(days=6))


def item(shopping_list, name):
    return shopping_list.items.get(name=name)


def test_staples_are_listed_apart_to_check_what_is_left(household, admin_user, shopping_list):
    shopping.set_pantry_item(household, admin_user, ingredient("Ajo"), PantryItem.Kind.STAPLE)
    garlic = item(shopping_list, "Ajo")
    assert garlic.is_staple and garlic.needed_quantity == Decimal("1")  # still says how much the menu uses
    groups, _ = shopping.grouped_items(shopping_list)
    assert "Ajo" not in [i.name for _, items in groups for i in items]
    staples, covered = shopping.pantry_sections(shopping_list)
    assert [i.name for i in staples] == ["Ajo"] and covered == []
    snapshot = shopping.list_snapshot(shopping_list, groups, admin_user, True, staples=staples)
    assert snapshot["groups"][-1]["label"] == shopping.STAPLES_LABEL


def test_quantities_at_home_are_taken_off_the_list(household, admin_user, shopping_list):
    shopping.set_pantry_item(household, admin_user, ingredient("Espaguetis"), PantryItem.Kind.STOCK, Decimal("150"), "g")
    pasta = item(shopping_list, "Espaguetis")
    assert pasta.needed_quantity == Decimal("50") and pasta.pantry_quantity == Decimal("150")
    # A whole kilo at home covers the 200 g of the menu: nothing to buy, listed as already at home.
    shopping.set_pantry_item(household, admin_user, ingredient("Espaguetis"), PantryItem.Kind.STOCK, Decimal("1"), "kg")
    pasta = item(shopping_list, "Espaguetis")
    assert pasta.needed_quantity == 0 and pasta.pantry_quantity == Decimal("200") and pasta.is_covered
    staples, covered = shopping.pantry_sections(shopping_list)
    assert [i.name for i in covered] == ["Espaguetis"]
    # Removing it from the pantry brings the need back.
    shopping.remove_pantry_item(PantryItem.objects.get(household=household))
    pasta = item(shopping_list, "Espaguetis")
    assert pasta.needed_quantity == Decimal("200") and pasta.pantry_quantity == 0


def test_quantities_in_units_that_do_not_convert_are_not_guessed(household, admin_user, shopping_list):
    # Pieces of pasta have no equivalence in grams: nothing is taken off.
    shopping.set_pantry_item(household, admin_user, ingredient("Espaguetis"), PantryItem.Kind.STOCK, Decimal("2"), "pack")
    assert item(shopping_list, "Espaguetis").needed_quantity == Decimal("200")


def test_another_household_pantry_changes_nothing(household, admin_user, shopping_list):
    other_admin = make_user("otra@example.com")
    other = make_household("Otra casa", admin=other_admin)
    shopping.set_pantry_item(other, other_admin, ingredient("Espaguetis"), PantryItem.Kind.STOCK, Decimal("1"), "kg")
    shopping.recalculate(shopping_list)
    assert item(shopping_list, "Espaguetis").needed_quantity == Decimal("200")


def test_an_item_becomes_a_staple_from_the_list_and_back(client, household, admin_user, shopping_list):
    garlic = item(shopping_list, "Ajo")
    url = reverse("shopping:item_pantry", args=[garlic.pk])
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert client.post(url).status_code == 302
    assert PantryItem.objects.get(household=household).kind == PantryItem.Kind.STAPLE
    assert item(shopping_list, "Ajo").is_staple
    html = client.get(reverse("shopping:detail", args=[shopping_list.pk])).content.decode()
    assert shopping.STAPLES_LABEL in html
    client.post(url)
    assert not PantryItem.objects.filter(household=household).exists()
    assert not item(shopping_list, "Ajo").is_staple


def test_the_pantry_page_adds_and_validates(client, household, admin_user, shopping_list):
    assert client.login(email=admin_user.email, password=PASSWORD)
    add = reverse("shopping:pantry_add")
    pasta = ingredient("Espaguetis")
    response = client.post(add, {"ingredient": pasta.pk, "kind": "stock", "quantity": "", "unit": ""})
    assert response.status_code == 400 and "Indica cuánto tenéis" in response.content.decode()
    response = client.post(add, {"ingredient": pasta.pk, "kind": "stock", "quantity": "150", "unit": "g"})
    assert response.status_code == 302
    assert item(shopping_list, "Espaguetis").needed_quantity == Decimal("50")
    html = client.get(reverse("shopping:pantry")).content.decode()
    assert "Espaguetis" in html and "150 g" in html


def test_readers_see_the_pantry_but_cannot_change_it(client, household, shopping_list):
    reader = make_user("lector@example.com")
    add_member(household, reader, Role.READER)
    client.force_login(reader)
    assert client.get(reverse("shopping:pantry")).status_code == 200
    response = client.post(reverse("shopping:pantry_add"), {"ingredient": ingredient("Ajo").pk, "kind": "staple"})
    assert response.status_code == 403
    assert not PantryItem.objects.exists()
