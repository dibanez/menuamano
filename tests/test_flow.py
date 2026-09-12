"""End-to-end flow through HTTP:
create household -> add diners -> create recipes -> plan a week -> generate shopping list
-> change one dinner -> verify the list is updated."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from diners.models import Diner
from households.models import Household
from planning.models import Meal, MealMode
from recipes.models import Recipe
from shopping.models import ShoppingItem, ShoppingList

from .factories import ingredient

MONDAY = date(2030, 1, 7)


def recipe_payload(name, lines, servings=4, tags="cena"):
    data = {
        "name": name, "description": "", "base_servings": servings, "prep_minutes": 10, "cook_minutes": 10,
        "difficulty": "easy", "equipment": "", "tags": tags,
        "ing-TOTAL_FORMS": len(lines), "ing-INITIAL_FORMS": 0, "ing-MIN_NUM_FORMS": 0, "ing-MAX_NUM_FORMS": 1000,
        "steps-TOTAL_FORMS": 1, "steps-INITIAL_FORMS": 0, "steps-MIN_NUM_FORMS": 0, "steps-MAX_NUM_FORMS": 1000,
        "steps-0-text": "Cocinar con cariño.",
    }
    for i, (ing_name, qty, unit) in enumerate(lines):
        data[f"ing-{i}-ingredient"] = ingredient(ing_name).pk
        data[f"ing-{i}-quantity"] = qty
        data[f"ing-{i}-unit"] = unit
    return data


@pytest.mark.django_db
def test_main_flow(client):
    # Sign up and create a household.
    response = client.post(reverse("accounts:signup"), {
        "email": "familia@example.com", "display_name": "Familia", "password1": "cocina-casera-2030", "password2": "cocina-casera-2030",
    })
    assert response.status_code == 302
    client.post(reverse("households:onboarding"), {"name": "Casa Pruebas"})
    household = Household.objects.get(name="Casa Pruebas")
    household.enabled_meal_types = ["lunch", "dinner"]
    household.save()

    # Diners, one with an egg allergy.
    for alias, portion in [("Marta", "1"), ("Jon", "1"), ("Iker", "0.5")]:
        client.post(reverse("diners:create"), {"alias": alias, "portion_factor": portion, "is_active": "on"})
    iker = Diner.objects.get(household=household, alias="Iker")
    client.post(reverse("diners:restriction_add", args=[iker.pk]), {"r-kind": "allergy", "r-trait": "egg"})
    assert iker.restrictions.count() == 1

    # Recipes.
    client.post(reverse("recipes:create"), recipe_payload("Arroz con verduras", [("Arroz", "400", "g"), ("Calabacín", "2", "unit")]))
    client.post(reverse("recipes:create"), recipe_payload("Crema de calabaza", [("Calabaza", "800", "g"), ("Puerro", "1", "unit")]))
    client.post(reverse("recipes:create"), recipe_payload("Tortilla francesa", [("Huevo", "4", "unit")]))
    assert Recipe.objects.filter(household=household).count() == 3

    # Plan the week by regenerating it.
    response = client.post(reverse("planning:regenerate"), {"start": MONDAY.isoformat(), "end": (MONDAY + timedelta(days=6)).isoformat()})
    assert response.status_code == 302
    dinners = Meal.objects.filter(household=household, meal_type="dinner", date__gte=MONDAY)
    assert dinners.count() == 7
    assert not any(mr.name == "Tortilla francesa" for m in dinners for mr in m.recipes.all())

    # Generate the shopping list.
    client.post(reverse("shopping:create"), {"start": MONDAY.isoformat(), "end": (MONDAY + timedelta(days=6)).isoformat()})
    shopping_list = ShoppingList.objects.get(household=household)
    assert shopping_list.items.exists()
    detail = client.get(reverse("shopping:detail", args=[shopping_list.pk]))
    assert detail.status_code == 200

    # Change Wednesday's dinner: eat out. Its ingredients leave the list.
    wednesday = dinners.get(date=MONDAY + timedelta(days=2))
    wednesday_recipe = wednesday.recipes.get()
    needs_before = _needed(shopping_list)
    response = client.post(reverse("planning:meal_update", args=[wednesday.pk]), {
        "mode": MealMode.EAT_OUT, "notes": "Cumpleaños", "locked": "on", "outcome": "pending", "outcome_notes": "",
    })
    assert response.status_code == 302
    needs_after = _needed(shopping_list)
    changed = [name for name in needs_before if needs_before[name] != needs_after.get(name, Decimal("0"))]
    assert changed, "the list must react to the modified dinner"
    first_line = wednesday_recipe.ingredients.first()
    assert needs_after.get(first_line.ingredient.name, Decimal("0")) < needs_before[first_line.ingredient.name]

    # Trying to add the egg recipe to a dinner Iker attends is refused.
    thursday = dinners.get(date=MONDAY + timedelta(days=3))
    tortilla = Recipe.objects.get(household=household, name="Tortilla francesa")
    client.post(reverse("planning:meal_add_recipe", args=[thursday.pk]), {"recipe": tortilla.pk})
    assert not thursday.recipes.filter(name="Tortilla francesa").exists()

    # All main pages render with real data.
    for url in [reverse("core:home"), reverse("planning:week") + f"?fecha={MONDAY}", reverse("planning:month") + f"?fecha={MONDAY}",
                reverse("planning:day", args=[MONDAY.isoformat()]), reverse("planning:meal", args=[thursday.pk]),
                reverse("recipes:list"), reverse("recipes:detail", args=[tortilla.pk]), reverse("diners:list"),
                reverse("diners:detail", args=[iker.pk]), reverse("foods:list"), reverse("planning:rules"),
                reverse("households:settings"), reverse("shopping:index"), reverse("assistant:chat")]:
        assert client.get(url).status_code == 200, url


def _needed(shopping_list):
    return {i.name: i.needed_quantity for i in ShoppingItem.objects.filter(shopping_list=shopping_list, is_manual=False)}
