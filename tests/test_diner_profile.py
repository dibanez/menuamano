from unittest import mock

import pytest
from django.urls import reverse

from core.choices import MealType
from diners.models import DinerPreference, DinerRestriction
from foods.models import Ingredient, Trait
from households.models import Role
from planning import services as planning
from planning.models import Meal, SafetyStatus

from .factories import PASSWORD, add_member, ingredient, make_diner, make_household, make_recipe, make_user


@pytest.fixture
def ana(household):
    return make_diner(household, "Ana")


@pytest.fixture
def logged(client, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    return client


def ids(*names):
    return [ingredient(n).pk for n in names]


def save_restrictions(client, diner, traits=(), ingredients=(), kind="allergy", label=""):
    return client.post(reverse("diners:restrictions_save", args=[diner.pk]), {
        "r-traits": list(traits), "r-ingredients": list(ingredients), "r-kind": kind, "r-label": label,
    }, follow=True)


def test_several_restrictions_are_checked_at_once(logged, ana):
    response = save_restrictions(logged, ana, traits=[Trait.EGG, Trait.GLUTEN], ingredients=ids("Kiwi", "Apio"))
    assert "añadidas" in response.content.decode()
    assert {r.trait for r in ana.restrictions.exclude(trait="")} == {"egg", "gluten"}
    assert {r.ingredient.name for r in ana.restrictions.filter(ingredient__isnull=False)} == {"Kiwi", "Apio"}
    assert set(ana.restrictions.values_list("kind", flat=True)) == {"allergy"}


def test_unchecking_removes_and_keeps_the_rest(logged, ana):
    save_restrictions(logged, ana, traits=[Trait.EGG, Trait.GLUTEN], ingredients=ids("Kiwi"))
    response = save_restrictions(logged, ana, traits=[Trait.EGG], kind="intolerance")
    assert "quitadas: Gluten, Kiwi" in response.content.decode()
    remaining = ana.restrictions.get()
    assert remaining.trait == "egg" and remaining.kind == "allergy"  # existing ones keep their type


def test_meals_are_revalidated_once_per_save(logged, household, admin_user, ana, monday):
    tortilla = make_recipe(household, "Tortilla", [("Huevo", 4, "unit")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, tortilla, admin_user)
    with mock.patch("planning.services.revalidate_upcoming", wraps=planning.revalidate_upcoming) as spy:
        save_restrictions(logged, ana, traits=[Trait.EGG, Trait.GLUTEN, Trait.SESAME, Trait.SOY])
    assert spy.call_count == 1
    assert Meal.objects.get(pk=meal.pk).safety_status == SafetyStatus.CONFLICT


def test_several_dislikes_and_likes_at_once(logged, ana):
    url = reverse("diners:preferences_save", args=[ana.pk])
    logged.post(url, {"p-dislikes": ids("Brócoli", "Lechuga", "Tomate"), "p-likes": ids("Espaguetis")})
    dislikes = set(ana.preferences.filter(kind="dislike").values_list("ingredient__name", flat=True))
    assert dislikes == {"Brócoli", "Lechuga", "Tomate"}
    assert list(ana.preferences.filter(kind="like").values_list("ingredient__name", flat=True)) == ["Espaguetis"]

    DinerPreference.objects.create(diner=ana, kind="like", text="platos de cuchara")
    logged.post(url, {"p-dislikes": ids("Tomate")})
    assert set(ana.preferences.filter(ingredient__isnull=False).values_list("ingredient__name", flat=True)) == {"Tomate"}
    assert ana.preferences.filter(text="platos de cuchara").exists()  # text preferences are untouched


def test_same_ingredient_cannot_be_liked_and_disliked(logged, ana):
    response = logged.post(reverse("diners:preferences_save", args=[ana.pk]),
                           {"p-dislikes": ids("Tomate"), "p-likes": ids("Tomate")}, follow=True)
    assert "a la vez" in response.content.decode()
    assert not ana.preferences.exists()


def test_checked_entries_are_listed_first(logged, ana):
    logged.post(reverse("diners:preferences_save", args=[ana.pk]), {"p-dislikes": ids("Tomate")})
    html = logged.get(reverse("diners:detail", args=[ana.pk])).content.decode()
    dislikes_block = html.split("No le gusta</legend>")[1]
    assert dislikes_block.index("Tomate") < dislikes_block.index("Aceite de oliva")


def test_foreign_ingredients_are_rejected(logged, ana):
    other = make_household("Otra", admin=make_user("otra@example.com"))
    secret = Ingredient.objects.create(household=other, name="Secreto")
    save_restrictions(logged, ana, ingredients=[secret.pk])
    logged.post(reverse("diners:preferences_save", args=[ana.pk]), {"p-dislikes": [secret.pk]})
    assert not DinerRestriction.objects.filter(ingredient=secret).exists()
    assert not DinerPreference.objects.filter(ingredient=secret).exists()


def test_readers_cannot_edit(client, household, ana):
    reader = make_user("reader@example.com")
    add_member(household, reader, Role.READER)
    assert client.login(email=reader.email, password=PASSWORD)
    assert client.post(reverse("diners:restrictions_save", args=[ana.pk]), {"r-traits": ["egg"], "r-kind": "allergy"}).status_code == 403
    assert client.post(reverse("diners:preferences_save", args=[ana.pk]), {"p-dislikes": ids("Tomate")}).status_code == 403
    assert not ana.restrictions.exists() and not ana.preferences.exists()


def test_text_preference_still_works(logged, ana):
    logged.post(reverse("diners:preference_add", args=[ana.pk]), {"t-kind": "like", "t-text": "platos de cuchara"})
    assert ana.preferences.get().text == "platos de cuchara"
