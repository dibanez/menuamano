"""The menu in calendar apps: a private iCalendar link per person and household."""

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.urls import reverse
from django.utils import timezone

from core.choices import MealType
from households.models import Membership
from planning import feeds
from planning import services as planning
from planning.models import CalendarFeed

from .factories import PASSWORD, make_diner, make_recipe


@pytest.fixture
def tomorrow_dinner(household, admin_user):
    make_diner(household, "Ana")
    make_diner(household, "Luis")
    recipe = make_recipe(household, "Lentejas estofadas", [("Ajo", 2, "clove")])
    meal, _ = planning.get_or_create_meal(household, timezone.localdate() + timedelta(days=1), MealType.DINNER)
    meal, _ = planning.add_recipe(meal, recipe, admin_user)
    return meal


@pytest.fixture
def feed(household, admin_user):
    return CalendarFeed.objects.create(user=admin_user, household=household, token="a-long-secret-token")


def test_the_feed_lists_planned_meals_without_names(client, household, feed, tomorrow_dinner):
    response = client.get(reverse("planning:feed", args=[feed.token]))  # no session: calendar apps
    assert response.status_code == 200 and response["Content-Type"].startswith("text/calendar")
    body = response.content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Cena: Lentejas estofadas\r\n" in body and "Para 2 personas." in body
    assert "Ana" not in body and "Luis" not in body
    start = datetime.combine(tomorrow_dinner.date, time(21, 0), tzinfo=ZoneInfo("Europe/Madrid"))
    assert f"DTSTART:{start.astimezone(dt_timezone.utc):%Y%m%dT%H%M%SZ}" in body
    assert f"UID:meal-{tomorrow_dinner.pk}@menuamano" in body
    feed.refresh_from_db()
    assert feed.last_fetched_at is not None


def test_unknown_links_and_people_who_left_get_nothing(client, household, admin_user, feed):
    assert client.get(reverse("planning:feed", args=["not-a-token"])).status_code == 404
    Membership.objects.filter(user=admin_user, household=household).delete()
    assert client.get(reverse("planning:feed", args=[feed.token])).status_code == 404


def test_the_subscribe_page_creates_and_replaces_the_link(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("planning:subscribe")
    assert "Crear mi enlace de calendario" in client.get(url).content.decode()
    client.post(url)
    first = CalendarFeed.objects.get(user=admin_user, household=household).token
    html = client.get(url).content.decode()
    assert f"webcal://testserver/calendario/ics/{first}.ics" in html
    client.post(url)
    second = CalendarFeed.objects.get(user=admin_user, household=household).token
    assert second != first
    assert client.get(reverse("planning:feed", args=[first])).status_code == 404
    client.post(reverse("planning:unsubscribe"))
    assert not CalendarFeed.objects.exists()


def test_the_calendar_views_offer_adding_the_menu_until_it_is_added(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    subscribe = reverse("planning:subscribe")
    for name in ("planning:week", "planning:month"):
        html = client.get(reverse(name)).content.decode()
        assert f'href="{subscribe}"' in html and "Añadir a tu calendario" in html and "calendar-cta" in html
    CalendarFeed.objects.create(user=admin_user, household=household, token="another-secret-token")
    html = client.get(reverse("planning:week")).content.decode()
    assert "En tu calendario" in html and "Añadir a tu calendario" not in html and "calendar-cta" not in html


def test_texts_are_escaped_and_long_lines_folded():
    assert feeds.escape("Pan, tomate; y\\ más\nfruta") == "Pan\\, tomate\\; y\\\\ más\\nfruta"
    folded = feeds.fold("SUMMARY:" + "Crema de calabacín y ñame " * 8)
    lines = folded.split("\r\n")
    assert len(lines) > 1 and all(len(line.encode()) <= 75 for line in lines)
    assert all(line.startswith(" ") for line in lines[1:])
    assert "".join(line[1:] if i else line for i, line in enumerate(lines)).endswith("ñame ")
