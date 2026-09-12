"""Assistant: invalid or failing providers never modify data; valid proposals are re-validated."""

from datetime import timedelta
from types import SimpleNamespace

import httpx2
import openai
import pytest
from django.test import override_settings
from django.urls import reverse

from assistant import services
from assistant.context import build_context
from assistant.models import AIRequestLog, Proposal
from assistant.providers import DemoProvider, OpenAIProvider, ProviderSchemaError
from assistant.schemas import AssistantOutput, MealChange, NewIngredientLine, NewRecipe
from core.choices import MealType
from diners.models import DinerRestriction, WeightMeasurement
from foods.models import Trait
from planning import services as planning
from planning.models import Meal
from recipes.models import Recipe

from .factories import PASSWORD, make_diner, make_household, make_recipe, make_user


@pytest.fixture
def home(household, admin_user, monday):
    household.enabled_meal_types = [MealType.DINNER]
    household.save()
    nora = make_diner(household, "Nora Real", traits=[Trait.EGG], birth_date=monday.replace(year=2021))
    ana = make_diner(household, "Ana Real")
    tortilla = make_recipe(household, "Tortilla", [("Huevo", 4, "unit"), ("Patata", 500, "g")], tags=["cena"], minutes=(10, 25))
    arroz = make_recipe(household, "Arroz", [("Arroz", 300, "g")], tags=["cena"], minutes=(5, 10))
    crema = make_recipe(household, "Crema", [("Calabacín", 3, "unit"), ("Caldo de verduras", 500, "ml")], tags=["cena"])
    return SimpleNamespace(household=household, user=admin_user, nora=nora, ana=ana, tortilla=tortilla, arroz=arroz, crema=crema, monday=monday)


class FakeProvider:
    name = "fake"

    def __init__(self, output=None, error=None):
        self.output, self.error, self.calls = output, error, 0

    def generate(self, context, user_id=None):
        self.calls += 1
        if self.error:
            raise self.error
        from assistant.providers import ProviderResult

        return ProviderResult(output=self.output, provider=self.name, model="fake", input_tokens=10, output_tokens=5)


def use_provider(monkeypatch, provider):
    monkeypatch.setattr(services, "get_provider", lambda: provider)


def change(day, recipe_ids=(), mode="cook", attendees=None, refs=()):
    return MealChange(date=day.isoformat(), meal_type="dinner", mode=mode, recipe_ids=list(recipe_ids),
                      new_recipe_refs=list(refs), attendee_codes=attendees, notes="", reason="")


def snapshot_meals(household):
    return sorted((m.date, m.meal_type, m.version, m.mode) for m in Meal.objects.filter(household=household))


def test_invalid_ai_response_does_not_modify_data(monkeypatch, home):
    before = snapshot_meals(home.household)
    use_provider(monkeypatch, FakeProvider(error=ProviderSchemaError("schema", "Formato no válido.")))
    with pytest.raises(services.AssistantError):
        services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    assert snapshot_meals(home.household) == before
    assert not Proposal.objects.exists()
    assert AIRequestLog.objects.get().status == "invalid"


def test_valid_json_with_wrong_content_is_rejected_by_business_rules(monkeypatch, home):
    other = make_household("Otra", admin=make_user("other@example.com"))
    foreign = make_recipe(other, "Ajena", [("Arroz", 100, "g")])
    locked, _ = planning.get_or_create_meal(home.household, home.monday, "dinner")
    planning.add_recipe(locked, home.arroz, home.user)  # manual edit → locked
    output = AssistantOutput(summary="ok", warnings=[], new_recipes=[], changes=[
        change(home.monday, [home.crema.pk]),                          # locked slot
        change(home.monday + timedelta(days=1), [foreign.pk]),         # foreign recipe id
        change(home.monday + timedelta(days=30), [home.arroz.pk]),     # out of range
        change(home.monday + timedelta(days=2), [home.tortilla.pk]),   # egg for Nora → conflict
        change(home.monday + timedelta(days=3), [home.arroz.pk], attendees=["C99"]),  # unknown person
    ])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    statuses = [i["status"] for i in proposal.items]
    assert statuses == ["rejected", "rejected", "rejected", "conflict", "rejected"]

    result = services.apply_proposal(proposal, home.user, accepted_review=[i.get("slot") for i in proposal.items])
    assert result.applied == 0
    assert not Meal.objects.filter(household=home.household, recipes__recipe=home.tortilla).exists()
    assert not Meal.objects.filter(household=home.household, recipes__recipe=foreign).exists()


def test_unknown_compatibility_requires_explicit_confirmation(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(tuesday, [home.crema.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    assert proposal.items[0]["status"] == "review"

    result = services.apply_proposal(proposal, home.user)
    assert result.applied == 0

    proposal2 = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    result = services.apply_proposal(proposal2, home.user, accepted_review=[proposal2.items[0]["slot"]])
    assert result.applied == 1


def test_proposal_is_not_applied_if_plan_changed_meanwhile(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(tuesday, [home.arroz.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))

    meal, _ = planning.get_or_create_meal(home.household, tuesday, "dinner")  # someone plans it manually
    result = services.apply_proposal(proposal, home.user)

    assert result.stale and result.applied == 0
    proposal.refresh_from_db()
    assert proposal.status == Proposal.Status.STALE
    assert not meal.recipes.exists()


def test_applying_twice_does_not_duplicate(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(tuesday, [home.arroz.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    first = services.apply_proposal(proposal, home.user)
    second = services.apply_proposal(proposal, home.user)
    assert first.applied == 1 and second.already_done
    meal = Meal.objects.get(household=home.household, date=tuesday)
    assert meal.recipes.count() == 1
    assert meal.source == Meal.Source.AI and not meal.locked


def test_restriction_added_after_proposal_is_enforced_on_apply(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[], changes=[change(tuesday, [home.arroz.pk])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    DinerRestriction.objects.create(diner=home.ana, kind="other", ingredient=home.arroz.ingredients.get().ingredient)
    result = services.apply_proposal(proposal, home.user)
    assert result.applied == 0
    assert "incompatible" in result.skipped[0]


def test_new_ai_recipe_is_saved_for_review_with_unknown_ingredients(monkeypatch, home):
    recipe = NewRecipe(ref="N1", name="Guiso nuevo", description="", base_servings=4, prep_minutes=10, cook_minutes=30,
                       difficulty="easy", tags=["cena"], equipment="", steps=["Cocinar."],
                       ingredients=[NewIngredientLine(name="patatas", quantity=500, unit="g", optional=False),
                                    NewIngredientLine(name="Salsa exótica", quantity=50, unit="ml", optional=False)])
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(summary="", warnings=[], new_recipes=[recipe], changes=[change(tuesday, refs=["N1"])])
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))
    assert proposal.new_recipes[0]["ingredients"][0]["name"] == "Patata"  # matched through alias
    assert proposal.items[0]["status"] == "review"  # unmatched ingredient → unknown for Nora
    services.apply_proposal(proposal, home.user, accepted_review=[proposal.items[0]["slot"]])
    created = Recipe.objects.get(name="Guiso nuevo")
    assert created.origin == Recipe.Origin.AI and created.review_status == Recipe.ReviewStatus.NEEDS_REVIEW
    new_ingredient = created.ingredients.get(ingredient__name="Salsa exótica").ingredient
    assert new_ingredient.household == home.household and not new_ingredient.trait_info_complete


def test_context_is_pseudonymised(home):
    WeightMeasurement.objects.create(diner=home.ana, measured_on=home.monday, weight_kg="61.5")
    ctx = build_context(home.household, home.monday, home.monday + timedelta(days=6), "plan_range")
    text = str(ctx.data)
    assert "Nora Real" not in text and "Ana Real" not in text
    assert "61.5" not in text and "2021" not in text
    assert {p["code"] for p in ctx.data["people"]} == {"C1", "C2"}
    tortilla_row = next(r for r in ctx.data["recipes"] if r["name"] == "Tortilla")
    assert tortilla_row["blocked_for"] == [ctx.diner_to_code[home.nora.pk]]


def test_demo_provider_is_deterministic_and_respects_restrictions(home):
    ctx = build_context(home.household, home.monday, home.monday + timedelta(days=6), "chat",
                        user_request="Cambia la cena del jueves por algo que lleve menos de veinte minutos")
    first = DemoProvider().generate(ctx.data).output
    second = DemoProvider().generate(ctx.data).output
    assert first == second
    assert len(first.changes) == 1
    assert first.changes[0].recipe_ids == [home.arroz.pk]  # 15 min, compatible with everyone
    assert first.summary.startswith("Modo demostración")


def fake_openai_client(result=None, error=None):
    def parse(**kwargs):
        if error:
            raise error
        return result

    return SimpleNamespace(responses=SimpleNamespace(parse=parse))


REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


@pytest.mark.parametrize("error, status", [
    (openai.APITimeoutError(request=REQUEST), "timeout"),
    (openai.APIConnectionError(request=REQUEST), "error"),
])
def test_openai_failures_are_reported_and_manual_flows_keep_working(monkeypatch, client, home, error, status):
    provider = OpenAIProvider("sk-test", "test-model", 1, 0, 100, client=fake_openai_client(error=error))
    use_provider(monkeypatch, provider)
    assert client.login(email=home.user.email, password=PASSWORD)
    response = client.post(reverse("assistant:chat_send"), {"message": "Organiza la semana"}, follow=True)
    assert response.status_code == 200
    assert AIRequestLog.objects.get().status == status
    assert not Proposal.objects.exists()

    # Manual planning still works right after the failure.
    meal, _ = planning.get_or_create_meal(home.household, home.monday, "dinner")
    response = client.post(reverse("planning:meal_add_recipe", args=[meal.pk]), {"recipe": home.arroz.pk})
    assert response.status_code == 302
    assert meal.recipes.filter(name="Arroz").exists()


def test_openai_incomplete_and_refusal_are_handled(home):
    incomplete = SimpleNamespace(status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"),
                                 output=[], output_parsed=None, usage=None, _request_id="req_1")
    refusal = SimpleNamespace(status="completed", incomplete_details=None, output_parsed=None, usage=None, _request_id="req_2",
                              output=[SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal", refusal="no")])])
    for response, expected in [(incomplete, "incomplete"), (refusal, "refused")]:
        provider = OpenAIProvider("sk-test", "test-model", 1, 0, 100, client=fake_openai_client(result=response))
        with pytest.raises(Exception) as exc:
            provider.generate({"operation": "chat"})
        assert exc.value.status == expected


def test_openai_success_path_parses_structured_output(home):
    output = AssistantOutput(summary="Hecho", changes=[], new_recipes=[], warnings=[])
    response = SimpleNamespace(status="completed", incomplete_details=None, output=[], output_parsed=output, model="test-model",
                               usage=SimpleNamespace(input_tokens=120, output_tokens=30), _request_id="req_3")
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return response

    provider = OpenAIProvider("sk-test", "test-model", 1, 0, 100, client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    result = provider.generate({"operation": "chat"}, user_id=1)
    assert result.output.summary == "Hecho" and result.input_tokens == 120
    assert captured["text_format"] is AssistantOutput and captured["store"] is False
    assert captured["model"] == "test-model"


def test_reasoning_effort_is_sent_when_configured(home):
    captured = {}

    def parse(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(status="completed", incomplete_details=None, output=[], model="gpt-5.6-luna", usage=None,
                               output_parsed=AssistantOutput(summary="", changes=[], new_recipes=[], warnings=[]))

    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    OpenAIProvider("sk-test", "gpt-5.6-luna", 1, 0, 16000, client=client, reasoning_effort="low").generate({})
    assert captured["reasoning"] == {"effort": "low"} and captured["max_output_tokens"] == 16000
    captured.clear()
    OpenAIProvider("sk-test", "other-model", 1, 0, 100, client=client).generate({})
    assert "reasoning" not in captured


@override_settings(AI_PROVIDER="openai", OPENAI_API_KEY="", OPENAI_MODEL="")
def test_missing_credentials_disable_assistant_without_breaking_pages(client, home):
    assert client.login(email=home.user.email, password=PASSWORD)
    page = client.get(reverse("assistant:chat"))
    assert "IA sin configurar" in page.content.decode()
    client.post(reverse("assistant:chat_send"), {"message": "hola"})
    assert AIRequestLog.objects.get().status == "not_configured"
    assert client.get(reverse("planning:week")).status_code == 200


def test_chat_creates_proposal_without_touching_calendar(client, home):
    assert client.login(email=home.user.email, password=PASSWORD)
    before = snapshot_meals(home.household)
    response = client.post(reverse("assistant:chat_send"), {"message": "Mantén los desayunos y modifica solo las cenas"}, HTTP_HX_REQUEST="true")
    assert response.status_code == 200
    assert "Revisar la propuesta" in response.content.decode()
    assert snapshot_meals(home.household) == before
    proposal = Proposal.objects.get()
    assert proposal.provider == "demo"
    page = client.get(reverse("assistant:proposal", args=[proposal.pk]))
    assert "Modo demostración" in page.content.decode()
    client.post(reverse("assistant:proposal_apply", args=[proposal.pk]))
    assert snapshot_meals(home.household) != before
