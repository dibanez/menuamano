"""Reminders on people's devices (web push). Nothing is sent over the network in tests."""

import json
from datetime import datetime, timedelta

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from core.choices import MealType
from households.models import Membership, Role
from planning import services as planning
from reminders import push, services
from reminders.models import PushSubscription, ReminderPreference

from .factories import PASSWORD, add_member, make_diner, make_recipe, make_user

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


@pytest.fixture
def vapid(settings):
    settings.VAPID_PUBLIC_KEY = "public-key"
    settings.VAPID_PRIVATE_KEY = "private-key"


@pytest.fixture
def sent(monkeypatch):
    """Messages handed to the push service, as (endpoint, payload)."""
    messages = []

    def fake_post(subscription, data):
        messages.append((subscription.endpoint, json.loads(data)))
        return 201

    monkeypatch.setattr(push, "_post", fake_post)
    return messages


def at(day, hour, minute=5):
    return timezone.make_aware(datetime.combine(day, datetime.min.time()).replace(hour=hour, minute=minute))


@pytest.fixture
def subscribed(household, admin_user):
    """The tomorrow reminder only: the weekly one depends on the day the tests run."""
    PushSubscription.objects.create(user=admin_user, endpoint=ENDPOINT, p256dh="k", auth="a")
    membership = Membership.objects.get(user=admin_user, household=household)
    return ReminderPreference.objects.create(membership=membership, hour=20, week=False)


def plan_dinner(household, user, day):
    make_diner(household, "Ana")
    recipe = make_recipe(household, "Cocido", [("Ajo", 2, "clove")])
    recipe.advance_note = "pon los garbanzos en remojo"
    recipe.save()
    meal, _ = planning.get_or_create_meal(household, day, MealType.DINNER)
    planning.add_recipe(meal, recipe, user)


def test_tomorrow_is_announced_once_in_its_window(household, admin_user, subscribed, vapid, sent):
    today = timezone.localdate()
    plan_dinner(household, admin_user, today + timedelta(days=1))
    assert services.send_due(at(today, 19)) == 0  # before the chosen hour
    assert services.send_due(at(today, 20)) == 1
    assert services.send_due(at(today, 21)) == 0  # once a day
    endpoint, payload = sent[0]
    assert endpoint == ENDPOINT and payload["title"] == "Mañana en casa"
    assert payload["body"] == "Hoy: pon los garbanzos en remojo (Cocido)\nCena: Cocido"
    assert payload["url"] == reverse("planning:day", args=[(today + timedelta(days=1)).isoformat()])
    assert "Ana" not in json.dumps(payload)


def test_late_plans_do_not_wake_anybody(household, admin_user, subscribed, vapid, sent):
    today = timezone.localdate()
    plan_dinner(household, admin_user, today + timedelta(days=1))
    assert services.send_due(at(today, 22)) == 0 and sent == []  # the window closes two hours after


def test_nothing_is_sent_without_keys_or_plans(household, admin_user, subscribed, settings, sent):
    today = timezone.localdate()
    settings.VAPID_PRIVATE_KEY = ""
    plan_dinner(household, admin_user, today + timedelta(days=1))
    assert services.send_due(at(today, 20)) == 0
    settings.VAPID_PRIVATE_KEY = "private-key"
    settings.VAPID_PUBLIC_KEY = "public-key"
    subscribed.refresh_from_db()
    subscribed.last_tomorrow_on = None
    subscribed.save()
    other_day = today + timedelta(days=5)
    assert services.send_due(at(other_day, 20)) == 0  # nothing planned for the day after


def test_an_empty_next_week_is_announced_on_sunday_to_planners(household, admin_user, subscribed, vapid, sent):
    subscribed.week = True
    subscribed.save()
    today = timezone.localdate()
    sunday = today + timedelta(days=(6 - today.weekday()) or 7)
    assert services.send_due(at(sunday, 20)) == 1
    assert sent[0][1]["title"] == "La semana que viene" and "28 comidas" in sent[0][1]["body"]
    reader = make_user("lector@example.com")
    membership = add_member(household, reader, Role.READER)
    PushSubscription.objects.create(user=reader, endpoint=ENDPOINT + "-reader", p256dh="k", auth="a")
    ReminderPreference.objects.create(membership=membership, hour=20)
    assert services.send_due(at(sunday + timedelta(days=7), 20)) == 1  # the editor only


def test_devices_that_are_gone_are_forgotten(household, admin_user, subscribed, vapid, monkeypatch):
    monkeypatch.setattr(push, "_post", lambda subscription, data: 410)
    assert push.send_to_user(admin_user, {"title": "x"}) == 0
    assert not PushSubscription.objects.exists()


def test_a_device_subscribes_and_unsubscribes(client, household, admin_user, vapid):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("reminders:subscribe")
    body = {"endpoint": ENDPOINT, "keys": {"p256dh": "key", "auth": "secret"}}
    assert client.post(url, body, content_type="application/json").status_code == 200
    assert PushSubscription.objects.get().user == admin_user
    assert ReminderPreference.objects.get().membership.user == admin_user  # on by default once a device accepts
    bad = {"endpoint": "http://push.example.com/insecure", "keys": {"p256dh": "k", "auth": "a"}}
    assert client.post(url, bad, content_type="application/json").status_code == 400
    assert client.get(url).status_code == 405
    client.post(reverse("reminders:unsubscribe"), {"endpoint": ENDPOINT}, content_type="application/json")
    assert not PushSubscription.objects.exists()


def test_the_settings_page_follows_the_server_configuration(client, household, admin_user, settings):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("reminders:settings")
    assert "no están activados" in client.get(url).content.decode()
    settings.VAPID_PUBLIC_KEY = "the-public-key"
    settings.VAPID_PRIVATE_KEY = "private-key"
    html = client.get(url).content.decode()
    assert 'data-public-key="the-public-key"' in html and "private-key" not in html
    client.post(url, {"tomorrow": "on", "hour": "18", "week": "on"})
    assert ReminderPreference.objects.get().hour == 18


def test_the_service_worker_shows_reminders(client, db):
    body = client.get("/sw.js").content.decode()
    assert 'addEventListener("push"' in body and "notificationclick" in body and "icon-192" in body


def test_vapid_keys_can_be_generated(capsys):
    call_command("generate_vapid_keys")
    lines = dict(line.split("=", 1) for line in capsys.readouterr().out.strip().splitlines())
    assert len(lines["VAPID_PUBLIC_KEY"]) == 87 and len(lines["VAPID_PRIVATE_KEY"]) > 100
