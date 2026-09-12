from decimal import Decimal

from django.urls import reverse

from core.choices import MealType
from foods.models import Trait, UnitConversion
from foods.reviews import save_review
from planning import services as planning
from planning.models import Meal
from shopping import services as shopping

from .factories import PASSWORD, ingredient, make_diner, make_recipe


def plan(household, user, day, *recipes):
    meal, _ = planning.get_or_create_meal(household, day, MealType.LUNCH)
    for recipe in recipes:
        planning.add_recipe(meal, recipe, user)
    return meal


def salt_need(household, day):
    needs = shopping.compute_needs(household, day, day)
    return needs, needs.get(shopping.item_key(ingredient("Sal").pk, "g"))


def test_a_pinch_merges_with_grams(household, admin_user, monday):
    make_diner(household, "Ana")
    plan(
        household, admin_user, monday,
        make_recipe(household, "Huevos fritos", [("Huevo", 2, "unit"), ("Sal", 1, "pinch")], base_servings=1),
        make_recipe(household, "Pan", [("Harina de trigo", 500, "g"), ("Sal", 10, "g")], base_servings=1),
    )
    needs, salt = salt_need(household, monday)
    assert salt.quantity == Decimal("10.4") and salt.approximate
    assert shopping.item_key(ingredient("Sal").pk, "pinch") not in needs


def test_an_ingredient_pinch_equivalence_wins(household, admin_user, monday):
    make_diner(household, "Ana")
    UnitConversion.objects.create(ingredient=ingredient("Sal"), household=household, unit="pinch", grams=Decimal("1"))
    plan(household, admin_user, monday, make_recipe(household, "Sopa", [("Sal", 2, "pinch"), ("Sal", 3, "g")], base_servings=1))
    assert salt_need(household, monday)[1].quantity == Decimal("5")


def sauce_list(household, admin_user, monday, traits):
    make_diner(household, "Mathias", traits=traits)
    recipe = make_recipe(household, "Macarrones", [("Macarrones", 100, "g"), ("Tomate triturado", 100, "g")], base_servings=1)
    plan(household, admin_user, monday, recipe)
    return shopping.create_list(household, admin_user, monday, monday)


def detail(client, user, shopping_list):
    assert client.login(email=user.email, password=PASSWORD)
    return client.get(reverse("shopping:detail", args=[shopping_list.pk])).content.decode()


def test_items_to_check_for_someone_with_allergies_are_flagged(client, household, admin_user, monday):
    sl = sauce_list(household, admin_user, monday, [Trait.FISH, Trait.EGG])
    html = detail(client, admin_user, sl)
    assert "Mira la etiqueta por Mathias." in html
    assert reverse("foods:review", args=[ingredient("Tomate triturado").pk]) in html
    assert html.count("label-check") == 1  # the pasta itself needs no check


def test_nothing_is_flagged_without_restrictions(client, household, admin_user, monday):
    sl = sauce_list(household, admin_user, monday, [])
    assert "Mira la etiqueta" not in detail(client, admin_user, sl)


def test_a_reviewed_label_is_no_longer_flagged(client, household, admin_user, monday):
    sl = sauce_list(household, admin_user, monday, [Trait.FISH])
    save_review(household, ingredient("Tomate triturado"), admin_user, traits=[])
    assert "Mira la etiqueta" not in detail(client, admin_user, sl)


def test_the_flag_survives_ticking_the_item(client, household, admin_user, monday):
    sl = sauce_list(household, admin_user, monday, [Trait.FISH])
    item = sl.items.get(name="Tomate triturado")
    assert client.login(email=admin_user.email, password=PASSWORD)
    response = client.post(reverse("shopping:item_toggle", args=[item.pk]), HTTP_HX_REQUEST="true")
    assert "Mira la etiqueta por Mathias." in response.content.decode()


def test_issues_stored_without_ingredient_id_match_by_name(household, admin_user, monday):
    sl = sauce_list(household, admin_user, monday, [Trait.FISH])
    meal = Meal.objects.get(household=household, date=monday)
    Meal.objects.filter(pk=meal.pk).update(
        safety_issues=[{k: v for k, v in i.items() if k != "ingredient_id"} for i in meal.safety_issues]
    )
    items = shopping.attach_label_checks(household, list(sl.items.all()))
    assert {i.name: i.label_check for i in items}["Tomate triturado"] == "Mathias"


def test_people_are_joined_naturally():
    assert shopping._join_people({"Nora"}) == "Nora"
    assert shopping._join_people({"Nora", "Leo", "Ana"}) == "Ana, Leo y Nora"
