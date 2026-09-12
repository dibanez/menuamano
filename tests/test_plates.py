"""Different plates for different people in the same meal (e.g. two breakfasts)."""

from decimal import Decimal

import pytest
from django.urls import reverse

from core.choices import MealType
from foods.models import Trait
from planning import services as planning
from planning.models import Meal, SafetyStatus
from shopping import services as shopping

from .factories import PASSWORD, ingredient, make_diner, make_recipe


@pytest.fixture
def breakfast(household, admin_user, monday):
    ana = make_diner(household, "Ana")
    nora = make_diner(household, "Nora", portion="0.5", traits=[Trait.EGG])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    meal = planning.set_attendees(meal, admin_user, [ana, nora], {ana.pk: Decimal("1"), nora.pk: Decimal("0.5")})
    tortilla = make_recipe(household, "Tortilla", [("Huevo", 2, "unit")], base_servings=1)
    arroz = make_recipe(household, "Arroz", [("Arroz", 100, "g")], base_servings=1)
    attendee = {a.diner.alias: a for a in Meal.objects.get(pk=meal.pk).attendees.all()}
    return Meal.objects.get(pk=meal.pk), attendee, tortilla, arroz


def test_a_recipe_for_one_person_is_checked_only_against_them(breakfast, admin_user):
    meal, attendee, tortilla, arroz = breakfast
    with pytest.raises(planning.IncompatibleRecipe):  # egg for everyone: Nora is allergic
        planning.add_recipe(meal, tortilla, admin_user)
    meal, _ = planning.add_recipe(meal, tortilla, admin_user, eaters=[attendee["Ana"].pk])
    meal, _ = planning.add_recipe(meal, arroz, admin_user, eaters=[attendee["Nora"].pk])
    assert meal.safety_status == SafetyStatus.OK
    plates = {mr.name: [a.short_label for a in mr.eaters.all()] for mr in Meal.objects.get(pk=meal.pk).recipes.all()}
    assert plates == {"Tortilla": ["Ana"], "Arroz": ["Nora"]}


def test_each_plate_is_cooked_for_its_eaters(breakfast, admin_user, monday, household):
    meal, attendee, tortilla, arroz = breakfast
    planning.add_recipe(meal, tortilla, admin_user, eaters=[attendee["Ana"].pk])
    planning.add_recipe(meal, arroz, admin_user)  # for everyone: 1 + 0.5 servings
    needs = shopping.compute_needs(household, monday, monday)
    assert needs[shopping.item_key(ingredient("Huevo").pk, "unit")].quantity == Decimal("2")
    assert needs[shopping.item_key(ingredient("Arroz").pk, "g")].quantity == Decimal("150")


def test_everyone_or_nobody_picked_means_the_whole_meal(breakfast, admin_user):
    meal, attendee, _, arroz = breakfast
    meal, _ = planning.add_recipe(meal, arroz, admin_user, eaters=[a.pk for a in attendee.values()])
    assert not Meal.objects.get(pk=meal.pk).recipes.get().eaters.exists()


def test_giving_a_plate_to_someone_allergic_is_refused(breakfast, admin_user):
    meal, attendee, tortilla, _ = breakfast
    planning.add_recipe(meal, tortilla, admin_user, eaters=[attendee["Ana"].pk])
    plate = Meal.objects.get(pk=meal.pk).recipes.get()
    with pytest.raises(planning.IncompatibleRecipe):
        planning.set_recipe_eaters(plate, admin_user, [attendee["Ana"].pk, attendee["Nora"].pk])
    assert [a.short_label for a in plate.eaters.all()] == ["Ana"]


def test_when_the_only_eater_leaves_the_plate_is_checked_for_everyone(breakfast, admin_user):
    meal, attendee, tortilla, _ = breakfast
    planning.add_recipe(meal, tortilla, admin_user, eaters=[attendee["Ana"].pk])
    meal = planning.set_attendees(meal, admin_user, [attendee["Nora"].diner])
    assert meal.safety_status == SafetyStatus.CONFLICT  # never silently fine


def test_copying_a_meal_keeps_who_eats_what(breakfast, admin_user, monday):
    meal, attendee, tortilla, arroz = breakfast
    planning.add_recipe(meal, tortilla, admin_user, eaters=[attendee["Ana"].pk])
    planning.add_recipe(meal, arroz, admin_user, eaters=[attendee["Nora"].pk])
    copy = planning.move_or_copy(meal, admin_user, monday.replace(day=monday.day + 1), MealType.DINNER, copy=True)
    plates = {mr.name: [a.short_label for a in mr.eaters.all()] for mr in copy.recipes.all()}
    assert plates == {"Tortilla": ["Ana"], "Arroz": ["Nora"]}
    assert all(a.meal_id == copy.pk for mr in copy.recipes.all() for a in mr.eaters.all())


def test_meal_page_and_calendar_show_the_plates(client, breakfast, admin_user, monday):
    meal, attendee, tortilla, arroz = breakfast
    assert client.login(email=admin_user.email, password=PASSWORD)
    add_url = reverse("planning:meal_add_recipe", args=[meal.pk])
    client.post(add_url, {"recipe": tortilla.pk, "eaters": [attendee["Ana"].pk]})
    client.post(add_url, {"recipe": arroz.pk, "eaters": [attendee["Nora"].pk]})
    page = client.get(reverse("planning:meal", args=[meal.pk])).content.decode()
    assert "Para <strong>Ana</strong>" in page and "Para <strong>Nora</strong>" in page
    week = client.get(reverse("planning:week") + f"?fecha={monday.isoformat()}").content.decode()
    assert "Tortilla (Ana), Arroz (Nora)" in week

    plate = Meal.objects.get(pk=meal.pk).recipes.get(name="Arroz")
    client.post(reverse("planning:meal_recipe_eaters", args=[meal.pk, plate.pk]), {"eaters": []})
    assert not plate.eaters.exists()  # back to everyone
