"""The assistant with a device's own AI key: the server prepares, the browser asks, the server validates.

The browser's call to the provider is not run here; its answer is posted the way app.js posts it.
"""

import json

from django.db.models import F
from django.urls import reverse

from assistant import device, services
from assistant.models import AIRequestLog, ChatMessage, Proposal
from assistant.schemas import AssistantOutput, NewIngredientLine, NewRecipe
from billing import entitlements
from planning import services as planning
from planning.models import Meal
from recipes import importer

from .factories import PASSWORD
from .test_assistant import change, home  # noqa: F401 (home is a fixture)
from .test_billing import billing_on  # noqa: F401 (billing_on is a fixture)


def login(client, home):
    assert client.login(email=home.user.email, password=PASSWORD)


def prepare(client, url, data):
    response = client.post(url, data, HTTP_X_AI_STAGE=device.PREPARE)
    assert response.status_code == 200, response.content
    return response.json()


def answer(output, token, **extra):
    data = {
        "ai_token": token,
        "ai_output": output if isinstance(output, str) else output.model_dump_json(),
        "ai_provider": "anthropic", "ai_model": "claude-sonnet-5",
        "ai_input_tokens": "1200", "ai_output_tokens": "300", "ai_latency_ms": "4200",
    }
    data.update(extra)
    return data


def recipe_output():
    recipe = NewRecipe(
        ref="N1", name="Crema de calabacín", description="Suave.", base_servings=4, prep_minutes=10, cook_minutes=20,
        difficulty="easy", tags=["cena"], equipment="",
        ingredients=[NewIngredientLine(name="Calabacín", quantity=3, unit="unit", optional=False)],
        steps=["Cuece el calabacín.", "Tritúralo."],
    )
    return AssistantOutput(summary="Una crema suave.", changes=[], new_recipes=[recipe], warnings=[])


def test_the_output_schema_needs_no_references():
    schema = device.output_schema()
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"summary", "changes", "new_recipes", "warnings"}


def test_prepare_returns_the_anonymised_request_and_stores_nothing(billing_on, client, home):
    login(client, home)
    job = prepare(client, reverse("assistant:chat_send"), {"message": "Cambia la cena de Nora Real"})
    assert set(job) == {"token", "instructions", "input", "schema_name", "schema", "max_output_tokens"}
    assert "Nora Real" not in job["input"] and json.loads(job["input"])["operation"] == "chat"
    assert not ChatMessage.objects.exists() and not AIRequestLog.objects.exists() and not Proposal.objects.exists()


def test_a_device_answer_becomes_a_proposal_that_costs_the_server_nothing(billing_on, client, home):
    login(client, home)
    url = reverse("assistant:generate_recipe")
    job = prepare(client, url, {"message": "Una crema"})
    response = client.post(url, {"message": "Una crema", **answer(recipe_output(), job["token"])})
    proposal = Proposal.objects.get()
    assert response.url == reverse("assistant:proposal", args=[proposal.pk])
    assert proposal.provider == "anthropic" and proposal.new_recipes[0]["name"] == "Crema de calabacín"
    log = AIRequestLog.objects.get()
    assert (log.key_source, log.provider, log.model, log.status) == ("device", "anthropic", "claude-sonnet-5", "ok")
    assert (log.latency_ms, log.input_tokens, log.output_tokens) == (4200, 1200, 300)
    assert entitlements.ai_calls_this_month(home.household) == 0


def test_the_chat_takes_the_device_answer(billing_on, client, home):
    login(client, home)
    url, text = reverse("assistant:chat_send"), "Cambia la cena del lunes"
    job = prepare(client, url, {"message": text})
    output = AssistantOutput(summary="Arroz el lunes.", changes=[change(home.monday, [home.arroz.pk])], new_recipes=[], warnings=[])
    response = client.post(url, {"message": text, **answer(output, job["token"])}, HTTP_HX_REQUEST="true")
    assert "Arroz el lunes." in response.content.decode()
    assert ChatMessage.objects.count() == 2 and Proposal.objects.get().provider == "anthropic"


def test_an_answer_only_fits_the_request_it_was_prepared_for(billing_on, client, home, monkeypatch):
    login(client, home)
    url = reverse("assistant:generate_recipe")
    job = prepare(client, url, {"message": "Una crema"})
    client.post(url, {"message": "Otra cosa", **answer(recipe_output(), job["token"])})
    day = home.monday.isoformat()
    client.post(reverse("assistant:plan_range"), {"start": day, "end": day, **answer(recipe_output(), job["token"])})
    forged = client.post(url, {"message": "Una crema", **answer(recipe_output(), "forged")}, follow=True)
    assert "La respuesta no corresponde a esta petición" in forged.content.decode()
    monkeypatch.setattr(device, "TOKEN_MAX_AGE", -1)
    late = client.post(url, {"message": "Una crema", **answer(recipe_output(), job["token"])}, follow=True)
    assert "La petición ha caducado" in late.content.decode()
    assert not Proposal.objects.exists() and not AIRequestLog.objects.exists()


def test_a_malformed_answer_changes_nothing(billing_on, client, home):
    login(client, home)
    url = reverse("assistant:generate_recipe")
    job = prepare(client, url, {"message": "Una crema"})
    response = client.post(url, {"message": "Una crema", **answer("{not json", job["token"])}, follow=True)
    assert "no tenía el formato esperado" in response.content.decode()
    assert not Proposal.objects.exists()
    log = AIRequestLog.objects.get()
    assert (log.status, log.key_source) == ("invalid", "device")


def test_free_households_cannot_use_the_server_key(billing_on, client, home, monkeypatch):
    monkeypatch.setattr(services, "get_provider", lambda operation=None: (_ for _ in ()).throw(AssertionError("server provider used")))
    login(client, home)
    response = client.post(reverse("assistant:generate_recipe"), {"message": "Una crema"}, follow=True)
    assert "tu propia clave de IA" in response.content.decode()
    assert not Proposal.objects.exists()


def test_meals_changed_while_the_provider_answered_are_not_overwritten(billing_on, client, home):
    planning.regenerate_range(home.household, home.monday, home.monday, home.user)
    meal = Meal.objects.get(household=home.household, date=home.monday, meal_type="dinner")
    login(client, home)
    url = reverse("assistant:replace_meal", args=[meal.pk])
    job = prepare(client, url, {})
    Meal.objects.filter(pk=meal.pk).update(version=F("version") + 1)  # someone edits it meanwhile
    output = AssistantOutput(summary="Otra cena.", changes=[change(home.monday, [home.crema.pk])], new_recipes=[], warnings=[])
    client.post(url, answer(output, job["token"]))
    proposal = Proposal.objects.get()
    assert proposal.base_versions == {planning.slot_key(meal.date, meal.meal_type): meal.version}
    assert services.apply_proposal(proposal, home.user).stale


def test_importing_with_a_device_key_reads_the_page_once(billing_on, client, home, monkeypatch):
    calls = []

    def read(url):
        calls.append(url)
        return {
            "url": url, "format": "schema.org", "name": "Crema", "description": "", "servings": 4,
            "prep_minutes": 10, "cook_minutes": 20, "ingredients": ["3 calabacines"], "instructions": ["Cuece", "Tritura"],
        }

    monkeypatch.setattr(importer, "read_recipe", read)
    login(client, home)
    url, page = reverse("assistant:import_recipe"), "https://recetas.example.com/crema"
    job = prepare(client, url, {"url": page})
    assert json.loads(job["input"])["source"]["name"] == "Crema"
    client.post(url, {"url": page, **answer(recipe_output(), job["token"])})
    proposal = Proposal.objects.get()
    assert calls == [page] and proposal.new_recipes[0]["source_url"] == page


def test_the_key_page_keeps_the_key_in_the_browser(billing_on, client, home):
    login(client, home)
    html = client.get(reverse("assistant:device_key")).content.decode()
    start = html.index("<form data-ai-key-form")
    form = html[start:html.index("</form>", start)]
    assert "name=" not in form and "action=" not in form and 'type="password"' in form
    assert 'id="ai-providers"' in html and "Anthropic (Claude)" in html
