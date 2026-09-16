"""Importing a recipe: known ingredients are recognised and the proposal can always be saved."""

from unittest import mock

import pytest
from django.utils import timezone

from assistant import services
from assistant.models import Proposal
from assistant.schemas import AssistantOutput, NewIngredientLine, NewRecipe
from core.choices import MealType
from planning import services as planning
from recipes import importer
from recipes.models import Recipe

from .test_assistant import FakeProvider, home, use_provider  # noqa: F401 (home is a fixture)


def recipe_output(*lines):
    ingredients = [NewIngredientLine(name=name, quantity=quantity, unit=unit, optional=False) for name, quantity, unit in lines]
    recipe = NewRecipe(
        ref="N1", name="Arroz con pollo", description="De una web.", base_servings=2, prep_minutes=15,
        cook_minutes=20, difficulty="easy", tags=["comida"], equipment="", ingredients=ingredients,
        steps=["Sofríe.", "Añade el arroz."],
    )
    return AssistantOutput(summary="Receta transcrita.", changes=[], new_recipes=[recipe], warnings=[])


@pytest.mark.parametrize("written, expected", [
    ("Arroz", "Arroz"),
    ("Huevos", "Huevo"),
    ("Pimiento verde italiano", "Pimiento verde"),  # an extra word does not change what it contains
    ("aceite de oliva virgen extra", "Aceite de oliva"),  # an alias of the catalogue
    ("Leche sin lactosa", "Leche sin lactosa"),
    ("Leche de avena", None),  # a one-word name is never matched by its beginning
    ("Leche sin lactosa de cabra", "Leche sin lactosa"),  # «sin lactosa» is kept, only «de cabra» is extra
    ("Tomillo seco", None),  # not in the catalogue: a new ingredient
])
def test_ingredients_written_by_the_ai_find_the_catalogue(household, written, expected):
    found = services._match_ingredient(household, written)
    assert (found.name if found else None) == expected


def test_a_line_with_two_known_ingredients_becomes_two(household):
    raw = recipe_output(("Sal y pimienta", None, "g"), ("Arroz", 150, "g")).new_recipes[0]
    recipe = services._validate_new_recipe(household, raw)
    assert [line["name"] for line in recipe["ingredients"]] == ["Sal", "Pimienta negra", "Arroz"]
    assert recipe["unmatched"] == []


def test_an_imported_recipe_is_saved_even_if_the_week_changed(monkeypatch, home):  # noqa: F811
    today = timezone.localdate()
    meal, _ = planning.get_or_create_meal(home.household, today, MealType.DINNER)
    planning.add_recipe(meal, home.arroz, home.user)
    monkeypatch.setattr(importer, "read_recipe", lambda url: {
        "url": url, "format": "schema.org", "name": "Arroz con pollo", "description": "", "servings": 2,
        "prep_minutes": 15, "cook_minutes": 20, "ingredients": ["150 g de arroz"], "instructions": ["Sofríe."],
    })
    use_provider(monkeypatch, FakeProvider(recipe_output(("Arroz", 150, "g"), ("Pimiento verde italiano", 1, "unit"))))
    proposal = services.request_import(home.household, home.user, "https://recetas.example.com/arroz")

    planning.add_recipe(meal, home.crema, home.user)  # somebody plans dinner meanwhile
    result = services.apply_proposal(proposal, home.user)
    assert not result.stale and len(result.recipes_created) == 1
    saved = Recipe.objects.get(name="Arroz con pollo")
    assert [line.ingredient.name for line in saved.ingredients.all()] == ["Arroz", "Pimiento verde"]
    assert Proposal.objects.get(pk=proposal.pk).status == Proposal.Status.APPLIED


def test_a_proposal_that_changes_a_meal_is_still_blocked(monkeypatch, home):  # noqa: F811
    day = home.monday
    meal, _ = planning.get_or_create_meal(home.household, day, MealType.DINNER)
    from .test_assistant import change

    use_provider(monkeypatch, FakeProvider(AssistantOutput(
        summary="Cena nueva.", changes=[change(day, [home.arroz.pk])], new_recipes=[], warnings=[],
    )))
    proposal = services.request_proposal(home.household, home.user, "plan_range", day, day)
    planning.add_recipe(meal, home.crema, home.user)  # the meal changes after the proposal
    assert services.apply_proposal(proposal, home.user).stale
