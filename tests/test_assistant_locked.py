"""Asking the assistant about one meal works even when that meal is locked; other locks still hold."""

from datetime import timedelta

from django.urls import reverse

from assistant import services
from assistant.context import build_context
from assistant.models import Proposal
from assistant.schemas import AssistantOutput
from planning import services as planning
from planning.models import Meal

from .factories import PASSWORD
from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)


def locked_meal(home, day, recipe):
    meal, _ = planning.get_or_create_meal(home.household, day, "dinner")
    planning.add_recipe(meal, recipe, home.user)  # manual edit → locked
    meal = Meal.objects.get(pk=meal.pk)
    assert meal.locked
    return meal


def output(*changes):
    return AssistantOutput(summary="Alternativa", warnings=[], new_recipes=[], changes=list(changes))


def test_replacing_a_locked_meal_proposes_and_applies_the_change(monkeypatch, home):
    meal = locked_meal(home, home.monday, home.crema)
    use_provider(monkeypatch, FakeProvider(output(change(home.monday, [home.arroz.pk]))))
    proposal = services.request_proposal(
        home.household, home.user, "replace_meal", home.monday, home.monday, focus=(home.monday, "dinner"),
    )
    assert [i["status"] for i in proposal.items] == ["ok"]

    result = services.apply_proposal(proposal, home.user)
    assert result.applied == 1
    meal.refresh_from_db()
    assert [mr.name for mr in meal.recipes.all()] == ["Arroz"]
    assert meal.locked  # still protected from regenerations afterwards


def test_other_locked_meals_stay_protected_during_a_replacement(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    locked_meal(home, home.monday, home.crema)
    other = locked_meal(home, tuesday, home.crema)
    use_provider(monkeypatch, FakeProvider(output(change(home.monday, [home.arroz.pk]), change(tuesday, [home.arroz.pk]))))
    proposal = services.request_proposal(
        home.household, home.user, "replace_meal", home.monday, tuesday, focus=(home.monday, "dinner"),
    )
    assert [i["status"] for i in proposal.items] == ["ok", "rejected"]
    services.apply_proposal(proposal, home.user)
    assert [mr.name for mr in Meal.objects.get(pk=other.pk).recipes.all()] == ["Crema"]


def test_a_range_proposal_never_changes_a_locked_meal(monkeypatch, home):
    meal = locked_meal(home, home.monday, home.crema)
    use_provider(monkeypatch, FakeProvider(output(change(home.monday, [home.arroz.pk]))))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday)
    assert [i["status"] for i in proposal.items] == ["rejected"]
    # Even a tampered item cannot unlock it: only validation sets the flag, and only for the focus.
    assert "requested_meal" not in proposal.items[0]
    assert services.apply_proposal(proposal, home.user).applied == 0
    assert [mr.name for mr in Meal.objects.get(pk=meal.pk).recipes.all()] == ["Crema"]


def test_context_unlocks_only_the_requested_slot(home):
    tuesday = home.monday + timedelta(days=1)
    locked_meal(home, home.monday, home.crema)
    locked_meal(home, tuesday, home.crema)
    ctx = build_context(home.household, home.monday, tuesday, "replace_meal", focus=(home.monday, "dinner"))
    assert [(s["date"], s["locked"]) for s in ctx.data["slots"]] == [
        (home.monday.isoformat(), False), (tuesday.isoformat(), True),
    ]


def test_meal_page_button_reaches_a_proposal_for_a_locked_meal(client, monkeypatch, home):
    meal = locked_meal(home, home.monday, home.crema)
    use_provider(monkeypatch, FakeProvider(output(change(home.monday, [home.arroz.pk]))))
    assert client.login(email=home.user.email, password=PASSWORD)
    response = client.post(reverse("assistant:replace_meal", args=[meal.pk]))
    proposal = Proposal.objects.get()
    assert response.url == reverse("assistant:proposal", args=[proposal.pk])
    assert proposal.items[0]["status"] == "ok"
