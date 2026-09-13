"""The assistant avoids repeating recipes already in the calendar, and never duplicates saved ones."""

from datetime import timedelta

from assistant import services
from assistant.context import build_context
from assistant.providers import INSTRUCTIONS, DemoProvider
from assistant.schemas import AssistantOutput
from planning import services as planning
from recipes.models import Recipe

from .factories import make_recipe
from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)
from .test_assistant_new_recipe import new_recipe


def plan(home, day, recipe):
    meal, _ = planning.get_or_create_meal(home.household, day, "dinner")
    planning.add_recipe(meal, recipe, home.user)


def propose(monkeypatch, home, *changes, recipes=(), operation="plan_range", focus=None, days=6):
    output = AssistantOutput(summary="", warnings=[], new_recipes=list(recipes), changes=list(changes))
    use_provider(monkeypatch, FakeProvider(output))
    return services.request_proposal(
        home.household, home.user, operation, home.monday, home.monday + timedelta(days=days), focus=focus,
    )


def test_context_lists_recipes_planned_two_weeks_around_the_range(home):
    sunday = home.monday + timedelta(days=6)
    plan(home, home.monday - timedelta(days=10), home.arroz)
    plan(home, sunday + timedelta(days=10), home.crema)
    plan(home, sunday + timedelta(days=20), home.arroz)  # too far after the range to count
    data = build_context(home.household, home.monday, sunday, "plan_range").data
    assert data["recent_recipe_ids"] == [home.arroz.pk]
    assert data["upcoming_recipe_ids"] == [home.crema.pk]
    assert "upcoming_recipe_ids" in INSTRUCTIONS and "Do not repeat recipes" in INSTRUCTIONS


def test_a_recipe_already_planned_is_flagged_but_not_blocked(monkeypatch, home):
    plan(home, home.monday, home.arroz)
    proposal = propose(monkeypatch, home, change(home.monday + timedelta(days=1), [home.arroz.pk]))
    item = proposal.items[0]
    assert item["status"] == "ok"
    assert item["issues"] == ["«Arroz» se repite: ya está el lunes 7 (cena)."]


def test_the_same_recipe_twice_in_a_proposal_is_flagged(monkeypatch, home):
    tuesday, wednesday = home.monday + timedelta(days=1), home.monday + timedelta(days=2)
    proposal = propose(monkeypatch, home, change(tuesday, [home.arroz.pk]), change(wednesday, [home.arroz.pk]))
    assert proposal.items[0]["issues"] == []
    assert proposal.items[1]["issues"] == ["«Arroz» se repite: también se propone el martes 8 (cena)."]


def test_replacing_a_meal_does_not_count_its_own_recipe(monkeypatch, home):
    plan(home, home.monday, home.arroz)
    proposal = propose(
        monkeypatch, home, change(home.monday, [home.arroz.pk]),
        operation="replace_meal", focus=(home.monday, "dinner"), days=0,
    )
    assert proposal.items[0]["issues"] == []


def test_a_new_recipe_that_already_exists_uses_the_saved_one(monkeypatch, home):
    before = Recipe.objects.count()
    proposal = propose(
        monkeypatch, home, change(home.monday + timedelta(days=1), refs=["N1"]), recipes=[new_recipe(name="arroz")],
    )
    item = proposal.items[0]
    assert item["recipe_ids"] == [home.arroz.pk] and item["new_recipe_refs"] == []
    assert proposal.new_recipes == []
    assert "«Arroz» ya está en tu recetario" in proposal.summary
    services.apply_proposal(proposal, home.user)
    assert Recipe.objects.count() == before


def test_demo_provider_prefers_recipes_not_yet_planned(home):
    make_recipe(home.household, "Macarrones", [("Macarrones", 100, "g")], tags=["cena"])
    make_recipe(home.household, "Patatas asadas", [("Patata", 300, "g")], tags=["cena"])
    plan(home, home.monday, home.arroz)  # manual edit: locked, stays as it is
    ctx = build_context(home.household, home.monday, home.monday + timedelta(days=6), "plan_range", user_request="Organiza la semana")
    changes = DemoProvider().generate(ctx.data).output.changes
    first_two = [rid for c in changes[:2] for rid in c.recipe_ids]
    assert first_two and home.arroz.pk not in first_two
