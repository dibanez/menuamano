"""Guests appear in «Ajustar raciones» and their portions are saved like everyone else's."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse

from core.choices import MealType
from planning import services as planning
from planning.models import Meal, MealAttendee

from .factories import PASSWORD, make_diner


@pytest.fixture
def meal_with_guest(household, admin_user, monday):
    ana = make_diner(household, "Ana")
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    meal = planning.set_attendees(meal, admin_user, [ana], {ana.pk: Decimal("1")})
    planning.add_guest(meal, admin_user, "Paco", [], "", Decimal("1"))
    return Meal.objects.get(pk=meal.pk), ana, MealAttendee.objects.get(meal=meal, guest_name="Paco")


def test_guests_are_listed_in_the_portions(client, admin_user, meal_with_guest):
    meal, _, guest = meal_with_guest
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("planning:meal", args=[meal.pk])).content.decode()
    portions = html.split('id="att-portions"', 1)[1].split("</details>", 1)[0]
    assert f'name="guest-portion-{guest.pk}"' in portions and "Paco" in portions


def test_a_guest_portion_is_saved_and_counts_in_the_servings(client, admin_user, meal_with_guest):
    meal, ana, guest = meal_with_guest
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(
        reverse("planning:meal_attendees", args=[meal.pk]),
        {"diners": [ana.pk], f"portion-{ana.pk}": "1", f"guest-portion-{guest.pk}": "0,5"},
        HTTP_HX_REQUEST="true",
    )
    guest.refresh_from_db()
    assert guest.portion == Decimal("0.5")
    assert Meal.objects.get(pk=meal.pk).servings == Decimal("1.5")


def test_guests_of_other_meals_and_bad_values_are_ignored(client, admin_user, household, monday, meal_with_guest):
    meal, ana, guest = meal_with_guest
    other, _ = planning.get_or_create_meal(household, monday + timedelta(days=1), MealType.DINNER)
    planning.add_guest(other, admin_user, "Luisa", [], "", Decimal("1"))
    outsider = MealAttendee.objects.get(meal=other, guest_name="Luisa")
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(
        reverse("planning:meal_attendees", args=[meal.pk]),
        {"diners": [ana.pk], f"guest-portion-{guest.pk}": "-2", f"guest-portion-{outsider.pk}": "3"},
    )
    guest.refresh_from_db()
    outsider.refresh_from_db()
    assert guest.portion == Decimal("1")  # a negative value is ignored
    assert outsider.portion == Decimal("1")  # another meal's guest is never touched
