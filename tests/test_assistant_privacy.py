import json
from datetime import timedelta

from assistant import services
from assistant.context import build_context, pseudonymize
from assistant.schemas import AssistantOutput, MealChange

from .test_assistant import FakeProvider, home, use_provider  # noqa: F401  (fixture reuse)


def test_names_typed_in_chat_are_sent_as_codes(home):  # noqa: F811
    history = [("user", "¿Qué cena ana real el lunes?"), ("assistant", "Ana Real cena arroz.")]
    ctx = build_context(home.household, home.monday, home.monday + timedelta(days=6), "chat",
                        user_request="Nora Real no cena el martes", history=history)
    payload = json.dumps(ctx.data, ensure_ascii=False)
    assert "Nora Real" not in payload and "Ana Real" not in payload.replace("ana real", "")
    assert "ana real" not in payload.lower()
    nora_code = ctx.diner_to_code[home.nora.pk]
    assert ctx.data["user_request"] == f"{nora_code} no cena el martes"
    assert len(ctx.data["conversation"]) == 2


def test_pseudonymize_matches_whole_words_only(home):  # noqa: F811
    ctx = build_context(home.household, home.monday, home.monday, "chat")
    ctx.code_to_diner[next(iter(ctx.code_to_diner))].alias = "Ana"
    assert pseudonymize("Banana para Ana", ctx.code_to_diner).startswith("Banana para C")


def test_codes_in_provider_output_are_shown_as_names(monkeypatch, home):  # noqa: F811
    ctx = build_context(home.household, home.monday, home.monday, "chat")
    nora_code = ctx.diner_to_code[home.nora.pk]
    tuesday = home.monday + timedelta(days=1)
    output = AssistantOutput(
        summary=f"{nora_code} no cenará huevo.", warnings=[f"Revisa la cena de {nora_code}."], new_recipes=[],
        changes=[MealChange(date=tuesday.isoformat(), meal_type="dinner", mode="cook", recipe_ids=[home.arroz.pk],
                            new_recipe_refs=[], attendee_codes=None, plates=[], notes="", reason=f"Apta para {nora_code}.")],
    )
    use_provider(monkeypatch, FakeProvider(output))
    proposal = services.request_proposal(home.household, home.user, "chat", home.monday, home.monday + timedelta(days=6))
    assert proposal.summary.startswith("Nora Real no cenará huevo.")
    assert "Revisa la cena de Nora Real." in proposal.summary
    assert proposal.items[0]["reason"] == "Apta para Nora Real."
