"""The shopping list on the device: shared as text and usable in the shop without connection."""

import json
import re
from datetime import timedelta

import pytest
from django.urls import reverse

from core.choices import MealType
from households.models import Role
from planning import services as planning
from shopping import services as shopping

from .factories import PASSWORD, add_member, make_diner, make_household, make_recipe, make_user


@pytest.fixture
def shopping_list(household, admin_user, monday):
    make_diner(household, "Ana")
    recipe = make_recipe(household, "Espaguetis con tomate", [("Espaguetis", 400, "g"), ("Ajo", 2, "clove")])
    meal, _ = planning.get_or_create_meal(household, monday, MealType.DINNER)
    planning.add_recipe(meal, recipe, admin_user)
    return shopping.create_list(household, admin_user, monday, monday + timedelta(days=6))


def snapshot(html):
    match = re.search(r'<script id="shopping-data" type="application/json">(.*?)</script>', html, re.S)
    assert match, "the list page must carry its data for the device"
    return json.loads(match.group(1))


def test_the_list_page_carries_its_data_for_the_device(client, admin_user, shopping_list):
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("shopping:detail", args=[shopping_list.pk])).content.decode()
    data = snapshot(html)
    assert data["id"] == shopping_list.pk and data["user"] == str(admin_user.pk) and data["can_edit"] is True
    items = {item["name"]: item for group in data["groups"] for item in group["items"]}
    pasta = shopping_list.items.get(name="Espaguetis")
    assert items["Espaguetis"]["amount"] == "100 g" and items["Espaguetis"]["done"] is False
    assert items["Espaguetis"]["state_url"] == reverse("shopping:item_state", args=[pasta.pk])
    assert items["Ajo"]["amount"] == "0,5 dientes, compra 1 diente"
    # The page says who is signed in, so the browser can drop a list that belongs to someone else.
    assert f'data-user="{admin_user.pk}"' in html and "data-share-list" in html


def test_readers_get_the_list_without_ticks(client, household, shopping_list):
    reader = make_user("lector@example.com")
    add_member(household, reader, Role.READER)
    client.force_login(reader)
    data = snapshot(client.get(reverse("shopping:detail", args=[shopping_list.pk])).content.decode())
    assert data["can_edit"] is False and data["user"] == str(reader.pk)


def test_ticks_sent_again_from_the_device_are_applied_once(client, admin_user, shopping_list):
    item = shopping_list.items.get(name="Espaguetis")
    url = reverse("shopping:item_state", args=[item.pk])
    assert client.login(email=admin_user.email, password=PASSWORD)
    for _ in range(2):
        assert client.post(url, {"done": "1"}).status_code == 204
    item.refresh_from_db()
    assert item.is_done and item.purchased_quantity == item.needed_quantity
    assert client.post(url, {"done": "0"}).status_code == 204
    item.refresh_from_db()
    assert not item.is_done


def test_only_editors_of_the_household_can_tick(client, household, shopping_list):
    item = shopping_list.items.get(name="Espaguetis")
    url = reverse("shopping:item_state", args=[item.pk])
    reader = make_user("lector@example.com")
    add_member(household, reader, Role.READER)
    client.force_login(reader)
    assert client.post(url, {"done": "1"}).status_code == 403
    stranger = make_user("otra@example.com")
    make_household("Otra casa", admin=stranger)
    client.force_login(stranger)
    assert client.post(url, {"done": "1"}).status_code == 404
    item.refresh_from_db()
    assert not item.is_done


def test_the_offline_page_draws_the_saved_list_but_carries_no_data(client, household, admin_user, shopping_list):
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get("/offline/").content.decode()
    assert "data-offline-list" in html and "js/app.js" in html
    assert household.name not in html and "Espaguetis" not in html and admin_user.email not in html
