"""Household isolation, roles and health-data permissions, exercised through HTTP."""

from datetime import date

import pytest
from django.urls import reverse

from diners.models import HealthDataAccess, WeightMeasurement
from households.models import Role
from households.permissions import SESSION_KEY
from planning import services as planning
from shopping import services as shopping

from .factories import PASSWORD, add_member, ingredient, make_diner, make_household, make_recipe, make_user

DAY = date(2030, 1, 8)


@pytest.fixture
def two_homes(db):
    alice = make_user("alice@example.com")
    bob = make_user("bob@example.com")
    home_a = make_household("A", admin=alice)
    home_b = make_household("B", admin=bob)
    diner_b = make_diner(home_b, "Bea")
    recipe_b = make_recipe(home_b, "Receta B", [("Arroz", 100, "g")])
    meal_b, _ = planning.get_or_create_meal(home_b, DAY, "dinner")
    planning.add_recipe(meal_b, recipe_b, bob)
    list_b = shopping.create_list(home_b, bob, DAY, DAY)
    return {"alice": alice, "bob": bob, "home_a": home_a, "home_b": home_b, "diner_b": diner_b,
            "recipe_b": recipe_b, "meal_b": meal_b, "list_b": list_b, "item_b": list_b.items.first()}


def login(client, user):
    assert client.login(email=user.email, password=PASSWORD)


def test_cannot_read_other_household_objects_by_id(client, two_homes):
    login(client, two_homes["alice"])
    urls = [
        reverse("diners:detail", args=[two_homes["diner_b"].pk]),
        reverse("diners:weight", args=[two_homes["diner_b"].pk]),
        reverse("recipes:detail", args=[two_homes["recipe_b"].pk]),
        reverse("planning:meal", args=[two_homes["meal_b"].pk]),
        reverse("shopping:detail", args=[two_homes["list_b"].pk]),
    ]
    for url in urls:
        assert client.get(url).status_code == 404, url


def test_cannot_modify_other_household_objects_by_id(client, two_homes):
    login(client, two_homes["alice"])
    meal_b, item_b = two_homes["meal_b"], two_homes["item_b"]
    posts = [
        (reverse("planning:meal_update", args=[meal_b.pk]), {"mode": "free"}),
        (reverse("planning:meal_delete", args=[meal_b.pk]), {}),
        (reverse("shopping:item_toggle", args=[item_b.pk]), {}),
        (reverse("diners:restrictions_save", args=[two_homes["diner_b"].pk]), {"r-kind": "allergy", "r-traits": ["egg"]}),
        (reverse("recipes:edit", args=[two_homes["recipe_b"].pk]), {"name": "Hackeada"}),
    ]
    for url, data in posts:
        assert client.post(url, data).status_code == 404, url
    meal_b.refresh_from_db()
    item_b.refresh_from_db()
    assert meal_b.mode == "cook"
    assert item_b.purchased_quantity == 0
    assert two_homes["diner_b"].restrictions.count() == 0


def test_cannot_plan_other_household_recipe_into_own_meal(client, two_homes):
    login(client, two_homes["alice"])
    make_diner(two_homes["home_a"], "Alicia")
    meal_a, _ = planning.get_or_create_meal(two_homes["home_a"], DAY, "dinner")
    response = client.post(reverse("planning:meal_add_recipe", args=[meal_a.pk]), {"recipe": two_homes["recipe_b"].pk})
    assert response.status_code == 404
    assert not meal_a.recipes.exists()


def test_tampered_session_household_is_ignored(client, two_homes):
    login(client, two_homes["alice"])
    session = client.session
    session[SESSION_KEY] = two_homes["home_b"].pk
    session.save()
    assert client.get(reverse("planning:meal", args=[two_homes["meal_b"].pk])).status_code == 404
    response = client.get(reverse("core:home"))
    assert response.context["household"] == two_homes["home_a"]


def test_cannot_switch_to_foreign_household(client, two_homes):
    login(client, two_homes["alice"])
    response = client.post(reverse("households:switch"), {"household": two_homes["home_b"].pk})
    assert response.status_code == 403


def test_recipe_form_rejects_foreign_ingredient(client, two_homes):
    from foods.models import Ingredient

    secret = Ingredient.objects.create(household=two_homes["home_b"], name="Especia secreta")
    login(client, two_homes["alice"])
    data = {
        "name": "Intento", "base_servings": 2, "prep_minutes": 0, "cook_minutes": 0, "difficulty": "easy",
        "ing-TOTAL_FORMS": 1, "ing-INITIAL_FORMS": 0, "ing-MIN_NUM_FORMS": 0, "ing-MAX_NUM_FORMS": 1000,
        "ing-0-ingredient": secret.pk, "ing-0-quantity": "1", "ing-0-unit": "g",
        "steps-TOTAL_FORMS": 0, "steps-INITIAL_FORMS": 0, "steps-MIN_NUM_FORMS": 0, "steps-MAX_NUM_FORMS": 1000,
    }
    response = client.post(reverse("recipes:create"), data)
    assert response.status_code == 200  # form re-rendered with errors
    assert not two_homes["home_a"].recipes.exists()


def test_reader_can_read_but_not_edit(client, household, monday):
    reader = make_user("reader@example.com")
    add_member(household, reader, Role.READER)
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, "dinner")
    login(client, reader)
    assert client.get(reverse("planning:meal", args=[meal.pk])).status_code == 200
    assert client.get(reverse("planning:week")).status_code == 200
    assert client.post(reverse("planning:meal_update", args=[meal.pk]), {"mode": "free"}).status_code == 403
    assert client.get(reverse("recipes:create")).status_code == 403
    assert client.post(reverse("households:add_member"), {"m-email": "x@example.com"}).status_code == 403


# --- Weight -----------------------------------------------------------------------------------------


@pytest.fixture
def weight_setup(household, admin_user):
    owner = make_user("owner@example.com")
    editor = make_user("editor@example.com")
    add_member(household, owner, Role.EDITOR)
    add_member(household, editor, Role.EDITOR)
    adult = make_diner(household, "Olga", linked_user=owner)
    child = make_diner(household, "Nico", birth_date=date(2020, 5, 1))
    WeightMeasurement.objects.create(diner=adult, measured_on=date(2026, 1, 1), weight_kg="70")
    return {"admin": admin_user, "owner": owner, "editor": editor, "adult": adult, "child": child}


def test_household_admin_cannot_see_linked_adult_weight(client, weight_setup):
    login(client, weight_setup["admin"])
    adult = weight_setup["adult"]
    assert client.get(reverse("diners:weight", args=[adult.pk])).status_code == 403
    response = client.post(reverse("diners:weight_add", args=[adult.pk]), {"measured_on": "2026-02-01", "weight_kg": "71"})
    assert response.status_code == 403
    assert adult.weights.count() == 1
    detail = client.get(reverse("diners:detail", args=[adult.pk]))
    assert b"Seguimiento de peso" not in detail.content
    # Admin cannot grant themselves access to a diner who has their own account.
    grant = client.post(reverse("diners:grant_add", args=[adult.pk]), {"user": weight_setup["admin"].pk})
    assert grant.status_code == 403


def test_owner_sees_weight_and_history_is_append_only(client, weight_setup):
    login(client, weight_setup["owner"])
    adult = weight_setup["adult"]
    assert client.get(reverse("diners:weight", args=[adult.pk])).status_code == 200
    client.post(reverse("diners:weight_add", args=[adult.pk]), {"measured_on": "2026-02-01", "weight_kg": "71"})
    client.post(reverse("diners:weight_add", args=[adult.pk]), {"measured_on": "2026-02-01", "weight_kg": "70.5"})
    assert adult.weights.count() == 3


def test_owner_grants_access_explicitly(client, weight_setup):
    adult, editor = weight_setup["adult"], weight_setup["editor"]
    login(client, weight_setup["owner"])
    client.post(reverse("diners:grant_add", args=[adult.pk]), {"user": editor.pk})
    assert HealthDataAccess.objects.filter(diner=adult, user=editor).exists()
    client.logout()
    login(client, editor)
    assert client.get(reverse("diners:weight", args=[adult.pk])).status_code == 200


def test_child_weight_requires_explicit_grant_managed_by_admin(client, weight_setup):
    child, editor = weight_setup["child"], weight_setup["editor"]
    login(client, editor)
    assert client.get(reverse("diners:weight", args=[child.pk])).status_code == 403
    assert client.post(reverse("diners:grant_add", args=[child.pk]), {"user": editor.pk}).status_code == 403
    client.logout()
    login(client, weight_setup["admin"])
    assert client.get(reverse("diners:weight", args=[child.pk])).status_code == 403  # admin role alone is not enough
    client.post(reverse("diners:grant_add", args=[child.pk]), {"user": editor.pk})
    client.logout()
    login(client, editor)
    assert client.get(reverse("diners:weight", args=[child.pk])).status_code == 200


def test_ingredient_catalogue_is_shared_but_not_editable(client, household, admin_user):
    login(client, admin_user)
    assert client.get(reverse("foods:edit", args=[ingredient("Huevo").pk])).status_code == 404
