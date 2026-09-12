from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from core.choices import MealType
from foods.models import Trait
from planning import services as planning
from planning.models import Meal, MealMode, SafetyStatus
from shopping import services as shopping

from .factories import PASSWORD, ingredient, make_diner, make_recipe


@pytest.fixture
def setup(household, admin_user, monday):
    ana = make_diner(household, "Ana")
    luis = make_diner(household, "Luis")
    lentejas = make_recipe(household, "Lentejas", [("Lentejas", 400, "g")], base_servings=4)
    sunday, _ = planning.get_or_create_meal(household, monday, MealType.LUNCH)
    planning.set_attendees(sunday, admin_user, [ana, luis])
    planning.add_recipe(sunday, lentejas, admin_user)
    tuesday = monday + timedelta(days=1)
    leftovers, _ = planning.get_or_create_meal(household, tuesday, MealType.DINNER)
    planning.set_attendees(leftovers, admin_user, [ana])
    planning.update_meal_details(leftovers, admin_user, mode=MealMode.LEFTOVERS, notes="", locked=True,
                                 outcome="pending", outcome_notes="")
    return {"ana": ana, "luis": luis, "source": sunday, "leftovers": Meal.objects.get(pk=leftovers.pk),
            "lentejas": lentejas, "monday": monday, "tuesday": tuesday}


def test_linking_leftovers_makes_the_source_cook_extra(household, admin_user, setup):
    sl = shopping.create_list(household, admin_user, setup["monday"], setup["tuesday"])
    assert sl.items.get(name="Lentejas").needed_quantity == Decimal("200")  # two servings

    meal, _ = planning.set_leftovers_source(setup["leftovers"], setup["source"], admin_user)

    assert meal.mode == MealMode.LEFTOVERS and meal.leftovers_from_id == setup["source"].pk
    assert sl.items.get(name="Lentejas").needed_quantity == Decimal("300")  # + Ana's leftovers portion
    # The leftovers meal itself never adds ingredients.
    assert shopping.compute_needs(household, setup["tuesday"], setup["tuesday"]) == {}


def test_leftovers_attendance_changes_update_the_source_list(household, admin_user, setup):
    planning.set_leftovers_source(setup["leftovers"], setup["source"], admin_user)
    # A list that only covers the source date must react to changes made on the leftovers date.
    sl = shopping.create_list(household, admin_user, setup["monday"], setup["monday"])
    planning.set_attendees(setup["leftovers"], admin_user, [setup["ana"], setup["luis"]])
    assert sl.items.get(name="Lentejas").needed_quantity == Decimal("400")


def test_leftovers_with_incompatible_source_are_refused(household, admin_user, setup):
    nora = make_diner(household, "Nora", traits=[Trait.EGG])
    tortilla = make_recipe(household, "Tortilla", [("Huevo", 6, "unit")])
    source2, _ = planning.get_or_create_meal(household, setup["monday"], MealType.DINNER)
    planning.set_attendees(source2, admin_user, [setup["ana"]])
    planning.add_recipe(source2, tortilla, admin_user)
    planning.set_attendees(setup["leftovers"], admin_user, [nora])

    with pytest.raises(planning.IncompatibleRecipe):
        planning.set_leftovers_source(setup["leftovers"], source2, admin_user)
    assert Meal.objects.get(pk=setup["leftovers"].pk).leftovers_from is None


def test_changes_in_source_revalidate_leftovers(household, admin_user, setup):
    planning.set_leftovers_source(setup["leftovers"], setup["source"], admin_user)
    line = setup["source"].recipes.get().ingredients.get()
    planning.substitute_ingredient(line, ingredient("Garbanzos cocidos"), admin_user)
    from diners.models import DinerRestriction

    DinerRestriction.objects.create(diner=setup["ana"], kind="allergy", trait=Trait.GLUTEN)
    assert Meal.objects.get(pk=setup["leftovers"].pk).safety_status == SafetyStatus.UNKNOWN

    planning.update_meal_details(setup["source"], admin_user, mode=MealMode.EAT_OUT, notes="", locked=True,
                                 outcome="pending", outcome_notes="")
    leftovers = Meal.objects.get(pk=setup["leftovers"].pk)
    assert leftovers.safety_status == SafetyStatus.UNKNOWN
    assert "ya no se cocina" in leftovers.safety_issues[0]["message"]


@pytest.mark.parametrize("case", ["later", "too_old", "not_cooked", "has_recipes", "self"])
def test_invalid_sources_are_rejected(household, admin_user, setup, case):
    leftovers, source = setup["leftovers"], setup["source"]
    if case == "later":
        source, _ = planning.get_or_create_meal(household, setup["tuesday"] + timedelta(days=1), MealType.LUNCH)
        planning.add_recipe(source, setup["lentejas"], admin_user)
    elif case == "too_old":
        source, _ = planning.get_or_create_meal(household, setup["tuesday"] - timedelta(days=6), MealType.LUNCH)
        planning.add_recipe(source, setup["lentejas"], admin_user)
    elif case == "not_cooked":
        planning.update_meal_details(source, admin_user, mode=MealMode.ORDER, notes="", locked=True,
                                     outcome="pending", outcome_notes="")
    elif case == "has_recipes":
        planning.add_recipe(leftovers, setup["lentejas"], admin_user)
        planning.update_meal_details(leftovers, admin_user, mode=MealMode.LEFTOVERS, notes="", locked=True,
                                     outcome="pending", outcome_notes="")
    elif case == "self":
        source = leftovers
    with pytest.raises(planning.PlanningError):
        planning.set_leftovers_source(Meal.objects.get(pk=leftovers.pk), Meal.objects.get(pk=source.pk), admin_user)


def test_moving_the_source_keeps_the_link_and_leaving_leftovers_mode_clears_it(household, admin_user, setup):
    planning.set_leftovers_source(setup["leftovers"], setup["source"], admin_user)
    moved = planning.move_or_copy(setup["source"], admin_user, setup["monday"], MealType.DINNER)
    leftovers = Meal.objects.get(pk=setup["leftovers"].pk)
    assert leftovers.leftovers_from_id == moved.pk

    planning.update_meal_details(leftovers, admin_user, mode=MealMode.FREE, notes="", locked=True,
                                 outcome="pending", outcome_notes="")
    assert Meal.objects.get(pk=leftovers.pk).leftovers_from is None


def test_leftovers_views(client, household, admin_user, setup):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("planning:meal", args=[setup["leftovers"].pk])
    page = client.get(url).content.decode()
    assert "Usar sus sobras" in page
    client.post(reverse("planning:meal_leftovers", args=[setup["leftovers"].pk]), {"source": setup["source"].pk})
    assert "Quitar el enlace" in client.get(url).content.decode()
    assert "Cocina de más" in client.get(reverse("planning:meal", args=[setup["source"].pk])).content.decode()
    week = client.get(reverse("planning:week") + f"?fecha={setup['monday']}").content.decode()
    assert "Sobras: Lentejas" in week
