"""The assistant forgives how the model references new recipes; each kind of request has its own model."""

from assistant import providers

from .test_assistant import change, home  # noqa: F401 (home is a fixture)
from .test_assistant_new_recipe import ask, new_recipe

SOUP = "Crema de calabaza"


def plan(monkeypatch, home, refs, recipes):
    proposal = ask(monkeypatch, home, change(home.monday, refs=refs), recipes=recipes, operation="plan_range")
    return proposal.items[0]


def test_refs_with_other_case_or_spacing_find_their_recipe(monkeypatch, home):
    item = plan(monkeypatch, home, [" n2 "], [new_recipe(), new_recipe("N2", SOUP)])
    assert item["new_recipe_refs"] == ["N2"] and item["status"] != "rejected"


def test_a_new_recipe_can_be_referenced_by_its_name(monkeypatch, home):
    item = plan(monkeypatch, home, [SOUP], [new_recipe(), new_recipe("N2", SOUP)])
    assert item["new_recipe_refs"] == ["N2"] and item["status"] != "rejected"


def test_with_one_new_recipe_any_unknown_ref_is_that_one(monkeypatch, home):
    item = plan(monkeypatch, home, ["receta-1"], [new_recipe()])
    assert item["new_recipe_refs"] == ["N1"] and item["status"] != "rejected"


def test_a_saved_recipe_named_as_new_is_the_saved_one(monkeypatch, home):
    item = plan(monkeypatch, home, [home.arroz.name.upper()], [])
    assert item["recipe_ids"] == [home.arroz.pk] and item["new_recipe_refs"] == []
    assert item["status"] != "rejected"


def test_a_new_recipe_without_ref_gets_one(monkeypatch, home):
    item = plan(monkeypatch, home, ["N1"], [new_recipe(ref="", name=SOUP), new_recipe("N2")])
    assert item["new_recipe_refs"] == ["N1"] and item["recipe_names"] == [SOUP]


def test_refs_that_match_nothing_are_still_rejected(monkeypatch, home):
    item = plan(monkeypatch, home, ["X9"], [new_recipe(), new_recipe("N2", SOUP)])
    assert item["status"] == "rejected"
    assert item["rejected_reason"] == "La propuesta usa una receta nueva que no está definida."


def test_each_kind_of_request_can_use_its_own_model(settings):
    settings.OPENAI_MODEL = "gpt-5.6-luna"
    settings.OPENAI_MODEL_PLANNING = "gpt-5.6-terra"
    settings.OPENAI_MODEL_RECIPES = ""
    for operation in ("plan_range", "replace_meal", "chat"):
        assert providers.model_for(operation) == "gpt-5.6-terra"
    assert providers.model_for("import_recipe") == "gpt-5.6-luna" and providers.model_for(None) == "gpt-5.6-luna"


def test_the_provider_gets_the_model_of_the_request(settings):
    settings.AI_PROVIDER = "openai"
    settings.OPENAI_API_KEY = "sk-test"
    settings.OPENAI_MODEL = "gpt-5.6-luna"
    settings.OPENAI_MODEL_PLANNING = "gpt-5.6-terra"
    settings.OPENAI_MODEL_RECIPES = ""
    assert providers.get_provider("replace_meal").model == "gpt-5.6-terra"
    assert providers.get_provider("generate_recipe").model == "gpt-5.6-luna"
