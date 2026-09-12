from datetime import timedelta
from decimal import Decimal

from django.urls import reverse

from core.choices import MealType
from foods import conversions
from foods.models import Ingredient, UnitConversion
from households.models import Role
from planning import services as planning
from shopping import services as shopping

from .factories import PASSWORD, add_member, ingredient, make_diner, make_household, make_recipe, make_user


def plan(household, user, day, *recipes):
    make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, day, MealType.LUNCH)
    for recipe in recipes:
        planning.add_recipe(meal, recipe, user)
    return meal


def need(household, day, name, unit):
    return shopping.compute_needs(household, day, day).get(shopping.item_key(ingredient(name).pk, unit))


def egg_recipes(household, grams):
    return (
        make_recipe(household, "Tortilla", [("Huevo", 2, "unit")], base_servings=1),
        make_recipe(household, "Bizcocho", [("Huevo", grams, "g")], base_servings=1),
    )


def test_catalogue_equivalences_are_seeded(db):
    egg = UnitConversion.objects.get(ingredient=ingredient("Huevo"), household=None, unit="unit")
    assert egg.grams == Decimal("60")
    assert UnitConversion.objects.filter(ingredient=ingredient("Aceite de oliva"), household=None, unit="ml").exists()


def test_pieces_and_grams_merge_through_a_known_equivalence(household, admin_user, monday):
    # Eggs are bought in units: 2 eggs + 120 g of egg ≈ 4 eggs (1 egg ≈ 60 g).
    plan(household, admin_user, monday, *egg_recipes(household, 120))
    egg = need(household, monday, "Huevo", "unit")
    assert egg.quantity == Decimal("4") and egg.approximate
    assert need(household, monday, "Huevo", "g") is None
    assert [s["converted"] for s in egg.sources] == [False, True]
    assert egg.sources[1]["unit"] == "g" and Decimal(egg.sources[1]["quantity"]) == Decimal("120")


def test_pieces_go_to_grams_when_the_ingredient_is_bought_by_weight(household, admin_user, monday):
    recipe = make_recipe(household, "Guiso", [("Patata", 2, "unit"), ("Patata", 100, "g")], base_servings=1)
    plan(household, admin_user, monday, recipe)
    assert need(household, monday, "Patata", "g").quantity == Decimal("500")  # 1 patata ≈ 200 g


def test_volume_units_use_the_millilitre_equivalence(household, admin_user, monday):
    recipe = make_recipe(
        household, "Aliño", [("Aceite de oliva", 2, "tbsp"), ("Aceite de oliva", "27.6", "g")], base_servings=1
    )
    plan(household, admin_user, monday, recipe)
    assert need(household, monday, "Aceite de oliva", "ml").quantity == Decimal("60")  # 30 ml + 27.6 g / 0.92


def test_without_equivalence_nothing_is_converted(household, admin_user, monday):
    salsa = Ingredient.objects.create(household=household, name="Salsa casera", default_unit="ml")
    recipe = make_recipe(household, "Con salsa", [("Arroz", 100, "g")], base_servings=1)
    recipe.ingredients.create(ingredient=salsa, quantity=Decimal("50"), unit="g")
    recipe.ingredients.create(ingredient=salsa, quantity=Decimal("100"), unit="ml")
    plan(household, admin_user, monday, recipe)
    needs = shopping.compute_needs(household, monday, monday)
    assert needs[shopping.item_key(salsa.pk, "g")].quantity == Decimal("50")
    assert needs[shopping.item_key(salsa.pk, "ml")].quantity == Decimal("100")
    assert not needs[shopping.item_key(salsa.pk, "ml")].approximate


def test_household_equivalence_overrides_catalogue_only_for_that_household(household):
    other = make_household("Otra", admin=make_user("otra@example.com"))
    egg = ingredient("Huevo")
    UnitConversion.objects.create(ingredient=egg, household=household, unit="unit", grams=Decimal("40"))
    assert conversions.load(household, [egg.pk])[egg.pk]["unit"] == Decimal("40")
    assert conversions.load(other, [egg.pk])[egg.pk]["unit"] == Decimal("60")


def test_shopping_item_is_marked_approximate(client, household, admin_user, monday):
    plan(household, admin_user, monday, *egg_recipes(household, 90))
    sl = shopping.create_list(household, admin_user, monday, monday)
    item = sl.items.get(name="Huevo")
    assert item.is_approximate and item.needed_quantity == Decimal("3.5")
    assert item.suggested_purchase == Decimal("4")
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert "≈ 3,5 unidades" in client.get(reverse("shopping:detail", args=[sl.pk])).content.decode()


def test_equivalence_views_store_household_rows_and_recalculate(client, household, admin_user, monday):
    plan(household, admin_user, monday, *egg_recipes(household, 120))
    sl = shopping.create_list(household, admin_user, monday, monday + timedelta(days=6))
    egg = ingredient("Huevo")
    assert client.login(email=admin_user.email, password=PASSWORD)
    page = client.get(reverse("foods:equivalences", args=[egg.pk]))
    assert page.status_code == 200 and "Catálogo" in page.content.decode()

    client.post(reverse("foods:equivalences", args=[egg.pk]), {"unit": "unit", "grams": "40", "note": "huevo pequeño"})
    assert UnitConversion.objects.get(ingredient=egg, household=household).grams == Decimal("40")
    assert UnitConversion.objects.get(ingredient=egg, household=None).grams == Decimal("60")  # catalogue untouched
    assert sl.items.get(name="Huevo").needed_quantity == Decimal("5")  # 2 + 120 / 40

    own = UnitConversion.objects.get(ingredient=egg, household=household)
    client.post(reverse("foods:equivalence_delete", args=[egg.pk, own.pk]))
    assert sl.items.get(name="Huevo").needed_quantity == Decimal("4")


def test_equivalences_permissions(client, household, admin_user):
    reader = make_user("reader@example.com")
    add_member(household, reader, Role.READER)
    other_home = make_household("Otra", admin=make_user("otra@example.com"))
    foreign = Ingredient.objects.create(household=other_home, name="Secreto")
    catalogue_row = UnitConversion.objects.get(ingredient=ingredient("Huevo"), household=None)

    assert client.login(email=reader.email, password=PASSWORD)
    response = client.post(reverse("foods:equivalences", args=[ingredient("Huevo").pk]), {"unit": "unit", "grams": "1"})
    assert response.status_code == 403
    client.logout()
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert client.get(reverse("foods:equivalences", args=[foreign.pk])).status_code == 404
    # The shared catalogue row cannot be deleted from a household.
    response = client.post(reverse("foods:equivalence_delete", args=[catalogue_row.ingredient_id, catalogue_row.pk]))
    assert response.status_code == 404
    assert UnitConversion.objects.filter(pk=catalogue_row.pk).exists()
