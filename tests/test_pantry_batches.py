"""Pantry batches: bought items saved with their expiry date, used by the assistant before they expire."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from assistant import services as assistant
from assistant.context import build_context
from core.choices import MealType
from households.models import Membership
from planning import services as planning
from reminders import services as reminders
from shopping import services as shopping
from shopping.models import PantryBatch

from .factories import PASSWORD, ingredient, make_diner, make_recipe


@pytest.fixture
def shopping_list(household, admin_user, monday):
    make_diner(household, "Ana")
    make_diner(household, "Luis")
    recipe = make_recipe(household, "Espaguetis con tomate", [("Espaguetis", 400, "g"), ("Ajo", 2, "clove")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, recipe, admin_user)
    return shopping.create_list(household, admin_user, monday, monday + timedelta(days=6))


def in_days(days):
    return timezone.localdate() + timedelta(days=days)


def test_a_bought_item_is_saved_with_its_expiry_and_not_taken_off_again(client, household, admin_user, shopping_list):
    pasta = shopping_list.items.get(name="Espaguetis")
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("shopping:item_toggle", args=[pasta.pk]))
    response = client.post(
        reverse("shopping:item_store", args=[pasta.pk]), {"expires_on": in_days(5).isoformat()}, HTTP_HX_REQUEST="true",
    )
    assert "En la despensa, caduca en 5 días." in response.content.decode()
    batch = PantryBatch.objects.get()
    assert batch.shopping_item == pasta and batch.quantity == Decimal("200") and batch.unit == "g"
    assert batch.expires_on == in_days(5)
    # Bought for this plan: it counts as bought, never as «already at home» on top.
    shopping.recalculate(shopping_list)
    pasta.refresh_from_db()
    assert pasta.needed_quantity == Decimal("200") and pasta.pantry_quantity == 0
    # Saving again updates the same batch.
    client.post(reverse("shopping:item_store", args=[pasta.pk]), {"expires_on": ""})
    assert PantryBatch.objects.count() == 1 and PantryBatch.objects.get().expires_on is None


def test_expired_or_used_batches_are_not_taken_off(household, admin_user, shopping_list):
    shopping.add_batch(household, admin_user, ingredient("Espaguetis"), Decimal("150"), "g", expires_on=in_days(-1))
    assert shopping_list.items.get(name="Espaguetis").needed_quantity == Decimal("200")
    fresh = shopping.add_batch(household, admin_user, ingredient("Espaguetis"), Decimal("150"), "g")
    assert shopping_list.items.get(name="Espaguetis").needed_quantity == Decimal("50")
    shopping.use_batch(fresh)
    assert shopping_list.items.get(name="Espaguetis").needed_quantity == Decimal("200")


def test_the_pantry_page_warns_about_what_expires_and_marks_it_used(client, household, admin_user):
    batch = shopping.add_batch(household, admin_user, ingredient("Calabacín"), Decimal("2"), "unit", expires_on=in_days(1))
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("shopping:pantry")).content.decode()
    assert "Caduca pronto" in html and "Calabacín (2 unidades): caduca mañana." in html
    client.post(reverse("shopping:batch_used", args=[batch.pk]))
    batch.refresh_from_db()
    assert batch.used_at is not None
    html = client.get(reverse("shopping:pantry")).content.decode()
    assert "Caduca pronto" not in html and 'class="batch"' not in html


def test_the_assistant_knows_what_is_at_home_and_when_it_expires(household, admin_user, monday):
    shopping.add_batch(household, admin_user, ingredient("Calabacín"), Decimal("2"), "unit", expires_on=in_days(2))
    shopping.add_batch(household, admin_user, ingredient("Arroz"), Decimal("500"), "g")
    shopping.add_batch(household, admin_user, ingredient("Ajo"), expires_on=in_days(-1))  # expired: left out
    used = shopping.add_batch(household, admin_user, ingredient("Espaguetis"), Decimal("400"), "g")
    shopping.use_batch(used)
    shopping.set_pantry_item(household, admin_user, ingredient("Sal"))
    data = build_context(household, monday, monday, "chat").data
    assert data["pantry"] == [
        {"ingredient": "Calabacín", "quantity": "2 unidades", "expires_in_days": 2},
        {"ingredient": "Arroz", "quantity": "500 g", "expires_in_days": None},
    ]
    assert data["always_at_home"] == ["Sal"]


def test_the_demo_assistant_uses_first_what_expires(household, admin_user, monday):
    household.enabled_meal_types = [MealType.DINNER]
    household.save()
    make_diner(household, "Ana")
    make_recipe(household, "Arroz blanco", [("Arroz", 300, "g")], tags=["cena"])
    courgette = make_recipe(household, "Calabacín a la plancha", [("Calabacín", 2, "unit")], tags=["cena"])
    shopping.add_batch(household, admin_user, ingredient("Calabacín"), Decimal("2"), "unit", expires_on=in_days(1))
    proposal = assistant.request_proposal(household, admin_user, "plan_range", monday, monday)
    assert proposal.items[0]["recipe_ids"] == [courgette.pk]
    assert "Aprovecha lo que caduca pronto: Calabacín." in proposal.items[0]["reason"]


def test_the_evening_reminder_says_what_expires(household, admin_user):
    shopping.add_batch(household, admin_user, ingredient("Calabacín"), Decimal("2"), "unit", expires_on=in_days(1))
    membership = Membership.objects.get(user=admin_user, household=household)
    message = reminders.tomorrow_message(membership, in_days(1))
    assert message["body"] == "Caduca mañana: Calabacín"
