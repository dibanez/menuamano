"""The chat may change a meal edited by hand once confirmed; rejections are logged with their reason."""

import logging

from assistant import services
from assistant.schemas import AssistantOutput
from planning.models import Meal

from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)
from .test_assistant_locked import locked_meal


def ask(monkeypatch, home, operation):
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(home.monday, [home.arroz.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    return services.request_proposal(home.household, home.user, operation, home.monday, home.monday)


def test_the_chat_can_change_a_locked_meal_only_once_confirmed(monkeypatch, home):
    meal = locked_meal(home, home.monday, home.crema)
    proposal = ask(monkeypatch, home, "chat")
    item = proposal.items[0]
    assert item["status"] == "review"
    assert any("editaste a mano" in issue for issue in item["issues"])
    assert services.apply_proposal(proposal, home.user).applied == 0  # not confirmed

    proposal = ask(monkeypatch, home, "chat")
    assert services.apply_proposal(proposal, home.user, accepted_review=[proposal.items[0]["slot"]]).applied == 1
    meal = Meal.objects.get(pk=meal.pk)
    assert [mr.name for mr in meal.recipes.all()] == ["Arroz"] and meal.locked


def test_week_proposals_still_leave_locked_meals_alone(monkeypatch, home):
    locked_meal(home, home.monday, home.crema)
    proposal = ask(monkeypatch, home, "plan_range")
    assert proposal.items[0]["status"] == "rejected"


def test_rejections_are_logged_with_their_fixed_reason(monkeypatch, home, caplog):
    locked_meal(home, home.monday, home.crema)
    with caplog.at_level(logging.INFO, logger="assistant.services"):
        proposal = ask(monkeypatch, home, "plan_range")
        services.apply_proposal(proposal, home.user)
    lines = [r.getMessage() for r in caplog.records if "assistant proposal" in r.getMessage()]
    created = next(line for line in lines if " created: " in line)
    applied = next(line for line in lines if " applied: " in line)
    assert "'rejected': 1" in created and "La comida está protegida" in created
    assert "rejected: La comida está protegida" in applied
    assert not any("Nora" in line or "Ana" in line for line in lines)
