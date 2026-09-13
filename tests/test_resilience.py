"""Repeated or expired forms, the favicon and the assistant's apply log."""

import logging
from datetime import timedelta

from django.test import Client
from django.urls import reverse

from assistant import services
from assistant.schemas import AssistantOutput
from planning import services as planning

from .factories import PASSWORD
from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)


def csrf_client():
    return Client(enforce_csrf_checks=True)


def test_a_login_sent_twice_lands_where_it_was_going(db, admin_user):
    client = csrf_client()
    client.force_login(admin_user)  # the first submission already signed in; the second one has a stale token
    response = client.post(reverse("accounts:login") + "?next=/calendario/", {"username": admin_user.email, "password": PASSWORD})
    assert response.status_code == 302 and response.url == "/calendario/"


def test_a_repeated_login_never_follows_an_outside_next(db, admin_user):
    client = csrf_client()
    client.force_login(admin_user)
    response = client.post(reverse("accounts:login") + "?next=https://evil.example.com/", {})
    assert response.status_code == 302 and response.url == reverse("core:home")


def test_an_expired_form_gets_a_friendly_page_back_to_where_it_was(db):
    response = csrf_client().post(
        reverse("accounts:login"), {"username": "x", "password": "y"}, HTTP_REFERER="http://testserver/cuenta/entrar/",
    )
    assert response.status_code == 403
    html = response.content.decode()
    assert "La página ha caducado" in html and 'href="http://testserver/cuenta/entrar/"' in html


def test_an_outside_referer_is_not_offered_as_the_way_back(db):
    response = csrf_client().post(reverse("accounts:login"), {}, HTTP_REFERER="https://evil.example.com/")
    assert 'href="/"' in response.content.decode()


def test_the_favicon_is_served_and_linked(client, db):
    response = client.get("/favicon.ico")
    assert response.status_code == 302 and response.url.endswith("img/favicon.ico")
    head = client.get("/").content.decode().split("</head>", 1)[0]
    assert "img/favicon.svg" in head and "img/favicon-48.png" in head and 'rel="apple-touch-icon"' in head


def test_applying_a_proposal_is_logged_without_personal_data(monkeypatch, home, caplog):
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[
        change(home.monday, [home.crema.pk]), change(tuesday, [home.arroz.pk]),
    ])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, tuesday)
    assert [i["status"] for i in proposal.items] == ["review", "ok"]  # unknown ingredient for Nora
    with caplog.at_level(logging.INFO, logger="assistant.services"):
        services.apply_proposal(proposal, home.user)
    message = next(r.getMessage() for r in caplog.records if " applied: " in r.getMessage())
    assert "applied=1" in message and "review_not_confirmed" in message
    assert "Nora" not in message


def test_replacing_a_meal_goes_back_to_it_even_when_nothing_applies(client, monkeypatch, home):
    planning.get_or_create_meal(home.household, home.monday, "dinner")
    # Egg for Nora: incompatible, never applied. (A change that only needs review stays on the proposal.)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(home.monday, [home.tortilla.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(
        home.household, home.user, "replace_meal", home.monday, home.monday, focus=(home.monday, "dinner"),
    )
    assert client.login(email=home.user.email, password=PASSWORD)
    response = client.post(reverse("assistant:proposal_apply", args=[proposal.pk]))
    assert response.url == reverse("planning:slot", args=[home.monday.isoformat(), "dinner"])
