from datetime import timedelta

import pytest
from django.urls import reverse

from assistant.context import build_context
from core.choices import MealType
from foods.models import IngredientReview, Trait
from foods.reviews import save_review
from households.models import Role
from planning import services as planning
from planning.models import Meal, SafetyStatus

from .factories import PASSWORD, add_member, ingredient, make_diner, make_household, make_recipe, make_user

SAUCE = "Tomate triturado"  # processed, catalogue information incomplete


@pytest.fixture
def mathias(household):
    return make_diner(household, "Mathias", traits=[Trait.CRUSTACEANS, Trait.EGG, Trait.LEGUMES, Trait.MOLLUSCS, Trait.FISH])


@pytest.fixture
def pasta(household):
    return make_recipe(household, "Macarrones con tomate", [("Macarrones", 400, "g"), (SAUCE, 400, "g")], tags=["cena"])


@pytest.fixture
def meal(household, admin_user, monday, mathias, pasta):
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    meal, _ = planning.add_recipe(meal, pasta, admin_user)
    return Meal.objects.get(pk=meal.pk)


def test_unknown_issue_links_to_the_ingredient(meal):
    issue = next(i for i in meal.safety_issues if i["level"] == "unknown")
    assert meal.safety_status == SafetyStatus.UNKNOWN
    assert issue["ingredient_id"] == ingredient(SAUCE).pk


def test_review_without_matching_traits_clears_the_warning(household, admin_user, meal):
    save_review(household, ingredient(SAUCE), admin_user, traits=[])
    meal.refresh_from_db()
    assert meal.safety_status == SafetyStatus.OK
    assert not [i for i in meal.safety_issues if i["level"] == "unknown"]


def test_review_listing_a_restricted_trait_makes_it_incompatible(household, admin_user, meal):
    save_review(household, ingredient(SAUCE), admin_user, traits=[Trait.FISH])
    meal.refresh_from_db()
    assert meal.safety_status == SafetyStatus.CONFLICT


def test_review_expands_implied_traits(household, admin_user):
    review = save_review(household, ingredient(SAUCE), admin_user, traits=[Trait.SOY])
    assert set(review.traits) == {"soy", "legumes"}


def test_reviews_only_apply_to_their_household(household, admin_user, monday, meal):
    other_admin = make_user("otra@example.com")
    other = make_household("Otra", admin=other_admin)
    make_diner(other, "Lola", traits=[Trait.FISH])
    recipe = make_recipe(other, "Pasta", [(SAUCE, 200, "g")], tags=["cena"])
    other_meal, _ = planning.get_or_create_meal(other, monday, MealType.DINNER)
    planning.add_recipe(other_meal, recipe, other_admin)

    save_review(household, ingredient(SAUCE), admin_user, traits=[])

    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.OK
    assert Meal.objects.get(pk=other_meal.pk).safety_status == SafetyStatus.UNKNOWN


def test_regeneration_uses_reviewed_recipes(household, admin_user, monday, mathias, pasta):
    household.enabled_meal_types = [MealType.DINNER]
    household.save()
    planning.regenerate_range(household, monday, monday, admin_user)
    assert not Meal.objects.get(household=household, date=monday).recipes.exists()  # unknown is never auto-chosen

    save_review(household, ingredient(SAUCE), admin_user, traits=[])
    planning.regenerate_range(household, monday + timedelta(days=1), monday + timedelta(days=1), admin_user)
    assert Meal.objects.get(household=household, date=monday + timedelta(days=1)).recipes.get().name == pasta.name


def test_assistant_context_uses_reviews(household, admin_user, monday, mathias, pasta):
    rows = lambda: {r["name"]: r for r in build_context(household, monday, monday, "chat").data["recipes"]}  # noqa: E731
    assert rows()[pasta.name]["review_for"]
    save_review(household, ingredient(SAUCE), admin_user, traits=[])
    assert rows()[pasta.name]["review_for"] == [] and rows()[pasta.name]["blocked_for"] == []


def test_meal_page_offers_review_and_review_view_saves_it(client, household, admin_user, meal):
    assert client.login(email=admin_user.email, password=PASSWORD)
    meal_url = reverse("planning:meal", args=[meal.pk])
    review_url = reverse("foods:review", args=[ingredient(SAUCE).pk])
    assert review_url in client.get(meal_url).content.decode()

    response = client.post(review_url, {"traits": [], "note": "Marca Huerta", "confirm": "on", "next": meal_url})
    assert response.url == meal_url
    review = IngredientReview.objects.get(household=household)
    assert review.note == "Marca Huerta" and review.reviewed_by == admin_user
    assert "Requiere revisión" not in client.get(meal_url).content.decode()


def test_review_requires_confirmation_and_editor_role(client, household, meal):
    reader = make_user("reader@example.com")
    add_member(household, reader, Role.READER)
    review_url = reverse("foods:review", args=[ingredient(SAUCE).pk])
    assert client.login(email=reader.email, password=PASSWORD)
    assert client.get(review_url).status_code == 200
    assert client.post(review_url, {"traits": [], "confirm": "on"}).status_code == 403
    client.logout()

    editor = make_user("editor@example.com")
    add_member(household, editor, Role.EDITOR)
    assert client.login(email=editor.email, password=PASSWORD)
    client.post(review_url, {"traits": []})  # no confirmation
    assert not IngredientReview.objects.exists()


def test_deleting_a_review_restores_the_warning(client, household, admin_user, meal):
    save_review(household, ingredient(SAUCE), admin_user, traits=[])
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("foods:review_delete", args=[ingredient(SAUCE).pk]))
    assert not IngredientReview.objects.exists()
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.UNKNOWN


def test_foreign_household_ingredients_cannot_be_reviewed(client, household, admin_user):
    other = make_household("Otra", admin=make_user("otra@example.com"))
    from foods.models import Ingredient

    secret = Ingredient.objects.create(household=other, name="Salsa secreta")
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert client.get(reverse("foods:review", args=[secret.pk])).status_code == 404


def test_meals_with_old_issue_format_are_refreshed_on_view(client, household, admin_user, meal):
    Meal.objects.filter(pk=meal.pk).update(safety_issues=[{k: v for k, v in i.items() if k != "ingredient_id"} for i in meal.safety_issues])
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("planning:meal", args=[meal.pk])).content.decode()
    assert reverse("foods:review", args=[ingredient(SAUCE).pk]) in html
