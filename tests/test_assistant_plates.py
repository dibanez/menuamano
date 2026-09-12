"""The assistant can give different recipes to different people in the same meal."""

from assistant import services
from assistant.context import build_context
from assistant.providers import INSTRUCTIONS
from assistant.schemas import AssistantOutput, Plate
from planning import services as planning
from planning.models import Meal, SafetyStatus

from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)
from .test_assistant_new_recipe import new_recipe


def codes(home):
    ctx = build_context(home.household, home.monday, home.monday, "chat")
    return ctx.diner_to_code[home.ana.pk], ctx.diner_to_code[home.nora.pk]


def propose(monkeypatch, home, *changes, recipes=()):
    output = AssistantOutput(summary="", warnings=[], new_recipes=list(recipes), changes=list(changes))
    use_provider(monkeypatch, FakeProvider(output))
    return services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday)


def plate(recipe_id=None, ref=None, *eaters):
    return Plate(recipe_id=recipe_id, new_recipe_ref=ref, eater_codes=list(eaters))


def test_plates_are_proposed_checked_per_eater_and_applied(monkeypatch, home):
    ana, nora = codes(home)
    proposal = propose(monkeypatch, home, change(
        home.monday, [home.tortilla.pk, home.arroz.pk],
        plates=[plate(home.tortilla.pk, None, ana), plate(home.arroz.pk, None, nora)],
    ))
    item = proposal.items[0]
    assert item["status"] == "ok"  # the egg omelette is only for Ana
    assert item["recipe_names"] == ["Tortilla (Ana Real)", "Arroz (Nora Real)"]

    assert services.apply_proposal(proposal, home.user).applied == 1
    meal = Meal.objects.get(household=home.household, date=home.monday)
    assert {mr.name: [a.diner_id for a in mr.eaters.all()] for mr in meal.recipes.all()} == {
        "Tortilla": [home.ana.pk], "Arroz": [home.nora.pk],
    }
    assert meal.safety_status == SafetyStatus.OK


def test_a_plate_for_someone_allergic_is_a_conflict(monkeypatch, home):
    _, nora = codes(home)
    proposal = propose(monkeypatch, home, change(home.monday, [home.tortilla.pk], plates=[plate(home.tortilla.pk, None, nora)]))
    assert proposal.items[0]["status"] == "conflict"
    assert services.apply_proposal(proposal, home.user).applied == 0


def test_plates_must_point_to_recipes_and_people_of_the_meal(monkeypatch, home):
    ana, _ = codes(home)
    proposal = propose(
        monkeypatch, home,
        change(home.monday, [home.arroz.pk], plates=[plate(home.crema.pk, None, ana)]),      # recipe not in the change
    )
    assert proposal.items[0]["status"] == "rejected"
    proposal = propose(monkeypatch, home, change(home.monday, [home.arroz.pk], plates=[plate(home.arroz.pk, None, "C99")]))
    assert proposal.items[0]["status"] == "rejected"
    proposal = propose(
        monkeypatch, home, change(home.monday, [home.arroz.pk], attendees=[ana], plates=[plate(home.arroz.pk, None, codes(home)[1])]),
    )
    assert proposal.items[0]["status"] == "rejected"  # Nora does not attend that meal


def test_a_plate_for_everyone_is_the_whole_meal(monkeypatch, home):
    ana, nora = codes(home)
    proposal = propose(monkeypatch, home, change(home.monday, [home.arroz.pk], plates=[plate(home.arroz.pk, None, ana, nora)]))
    assert proposal.items[0]["plates"] == []
    services.apply_proposal(proposal, home.user)
    assert not Meal.objects.get(household=home.household, date=home.monday).recipes.get().eaters.exists()


def test_a_new_recipe_can_be_a_plate(monkeypatch, home):
    ana, _ = codes(home)
    proposal = propose(
        monkeypatch, home,
        change(home.monday, [home.arroz.pk], refs=["N1"], plates=[plate(None, "N1", ana)]),
        recipes=[new_recipe()],
    )
    assert proposal.items[0]["recipe_names"] == ["Arroz", "Arroz con verduras (Ana Real)"]
    services.apply_proposal(proposal, home.user)
    plates = {mr.name: [a.diner_id for a in mr.eaters.all()] for mr in Meal.objects.get(date=home.monday).recipes.all()}
    assert plates == {"Arroz": [], "Arroz con verduras": [home.ana.pk]}


def test_context_shows_current_plates_and_the_model_is_told_how_to_use_them(home):
    meal, _ = planning.get_or_create_meal(home.household, home.monday, "dinner")
    attendee = {a.diner_id: a for a in meal.attendees.all()}
    planning.add_recipe(meal, home.tortilla, home.user, eaters=[attendee[home.ana.pk].pk])
    ctx = build_context(home.household, home.monday, home.monday, "chat")
    slot = ctx.data["slots"][0]
    assert slot["plates"] == [
        {"recipe_id": home.tortilla.pk, "recipe_name": "Tortilla", "eater_codes": [ctx.diner_to_code[home.ana.pk]]},
    ]
    assert "`plates`" in INSTRUCTIONS
