"""Provider abstraction: the OpenAI Responses API and a deterministic demo provider.

Providers only turn a context into an `AssistantOutput`. They never touch the database.
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

import pydantic
from django.conf import settings

from .config import MODE_DEMO, MODE_OPENAI, ai_status
from .schemas import AssistantOutput, MealChange, NewIngredientLine, NewRecipe

logger = logging.getLogger(__name__)

INSTRUCTIONS = """\
You are the meal-planning assistant of "menuamano", a household meal planner.
You receive a JSON context and must answer with the structured schema only.

Rules:
- Write every user-facing text (summary, notes, reason, warnings, recipe fields) in Spanish from Spain.
- Only propose changes for slots listed in `slots`, inside `range`, with a meal type in `enabled_meal_types`.
- Never change slots with "locked": true.
- Omit slots that should stay as they are. Keep proposals minimal and focused on the request.
- People are identified only by codes (C1, C2…), also inside `user_request` and `conversation`.
  Refer to them by code in your texts. Use `attendee_codes: null` to keep the usual attendees.
- `conversation` holds the previous chat turns (oldest first) for context; act on `user_request`.
- Mandatory restrictions can never be relaxed. Never assign a recipe whose `blocked_for` contains an attendee.
  Avoid recipes whose `review_for` contains an attendee when an alternative exists.
  If no compatible option exists, use mode "pending", no recipes, and explain it in `warnings`.
- Prefer the household's existing recipes (by id). Respect `dislikes` and `likes` when possible.
  If the request asks not to repeat recent recipes, avoid `recent_recipe_ids`.
- Only create `new_recipes` when needed or explicitly requested. New recipes must be common home cooking,
  use ingredient names from `known_ingredients` whenever possible, realistic quantities for `base_servings`,
  units from `units`, and ordered steps. Reference them from changes through `new_recipe_refs`.
- Modes: cook (cook at home), eat_out, order (takeaway), leftovers, free, pending. Only "cook" and
  "leftovers" take recipes.
- Do not invent nutritional values, calorie targets or weight-loss diets. Do not infer diets from age.
- You cannot execute code, run queries, delete data or perform actions other than proposing meal changes
  and recipes. If the request asks for anything else, return no changes and explain it in `summary`.
- Recipes are never a guarantee against traces or cross-contamination; do not claim otherwise.
"""


class ProviderError(Exception):
    """A provider call failed. `user_message` is shown in the interface (Spanish)."""

    status = "error"

    def __init__(self, code, user_message):
        self.code = code
        self.user_message = user_message
        super().__init__(code)


class ProviderNotConfigured(ProviderError):
    status = "not_configured"


class ProviderTimeout(ProviderError):
    status = "timeout"


class ProviderRefusal(ProviderError):
    status = "refused"


class ProviderIncomplete(ProviderError):
    status = "incomplete"


class ProviderSchemaError(ProviderError):
    status = "invalid"


@dataclass
class ProviderResult:
    output: AssistantOutput
    provider: str
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str = ""


class OpenAIProvider:
    name = MODE_OPENAI

    def __init__(self, api_key, model, timeout, max_retries, max_output_tokens, client=None):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_output_tokens = max_output_tokens
        self._client = client

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            # The SDK retries connection errors, 408/409/429 and 5xx with backoff, up to max_retries.
            self._client = OpenAI(api_key=self.api_key, timeout=self.timeout, max_retries=self.max_retries)
        return self._client

    def generate(self, context, user_id=None):
        import openai

        payload = json.dumps(context, ensure_ascii=False)
        kwargs = {
            "model": self.model,
            "instructions": INSTRUCTIONS,
            "input": [{"role": "user", "content": payload}],
            "text_format": AssistantOutput,
            "max_output_tokens": self.max_output_tokens,
            "store": False,
        }
        if user_id is not None:
            kwargs["safety_identifier"] = hashlib.sha256(f"{settings.SECRET_KEY}:{user_id}".encode()).hexdigest()[:32]
        try:
            response = self._get_client().responses.parse(**kwargs)
        except openai.APITimeoutError as exc:
            raise ProviderTimeout("timeout", "La IA ha tardado demasiado en responder. Inténtalo de nuevo más tarde.") from exc
        except openai.AuthenticationError as exc:
            raise ProviderError("auth", "La clave de OpenAI no es válida. Revisa la configuración del servidor.") from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderError("permission", "La cuenta de OpenAI no tiene acceso a este modelo.") from exc
        except openai.RateLimitError as exc:
            raise ProviderError("rate_limit", "La IA está saturada o se ha alcanzado el límite de uso. Prueba en unos minutos.") from exc
        except openai.APIConnectionError as exc:
            raise ProviderError("connection", "No se ha podido conectar con la IA. Revisa la conexión del servidor.") from exc
        except (openai.LengthFinishReasonError, openai.ContentFilterFinishReasonError) as exc:
            raise ProviderIncomplete("finish_reason", "La respuesta de la IA llegó incompleta. Prueba con una petición más acotada.") from exc
        except openai.BadRequestError as exc:
            raise ProviderError("bad_request", "La IA ha rechazado la petición. Revisa el modelo configurado.") from exc
        except openai.APIStatusError as exc:
            raise ProviderError(f"status_{exc.status_code}", "La IA ha devuelto un error. Inténtalo de nuevo más tarde.") from exc
        except (pydantic.ValidationError, openai.APIResponseValidationError, json.JSONDecodeError) as exc:
            raise ProviderSchemaError("schema", "La respuesta de la IA no tenía el formato esperado. No se ha cambiado nada.") from exc

        request_id = getattr(response, "_request_id", "") or ""
        if getattr(response, "status", None) == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", "unknown") if details else "unknown"
            raise ProviderIncomplete(f"incomplete_{reason}", "La respuesta de la IA llegó incompleta. No se ha cambiado nada.")
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", None) != "message":
                continue
            for part in getattr(item, "content", None) or []:
                if getattr(part, "type", None) == "refusal":
                    raise ProviderRefusal("refusal", "La IA no ha querido responder a esta petición.")
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise ProviderSchemaError("empty", "La IA no ha devuelto una propuesta válida. No se ha cambiado nada.")
        usage = getattr(response, "usage", None)
        return ProviderResult(
            output=parsed,
            provider=self.name,
            model=getattr(response, "model", self.model) or self.model,
            input_tokens=getattr(usage, "input_tokens", None) if usage else None,
            output_tokens=getattr(usage, "output_tokens", None) if usage else None,
            request_id=request_id,
        )


# --- Demo provider --------------------------------------------------------------------------------

WEEKDAYS = {
    "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2, "jueves": 3, "viernes": 4,
    "sábado": 5, "sabado": 5, "domingo": 6,
}
MEAL_WORDS = {
    "desayuno": "breakfast", "desayunos": "breakfast", "comida": "lunch", "comidas": "lunch",
    "almuerzo": "lunch", "merienda": "snack", "meriendas": "snack", "cena": "dinner", "cenas": "dinner",
}
VERB_MEALS = {"cenamos": "dinner", "comemos": "lunch", "desayunamos": "breakfast", "merendamos": "snack"}
NUMBERS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "diez": 10, "quince": 15, "veinte": 20, "veinticinco": 25, "treinta": 30, "cuarenta": 40, "cuarenta y cinco": 45,
}
MEAL_TAGS = {"breakfast": "desayuno", "lunch": "comida", "snack": "merienda", "dinner": "cena"}


def _number(token):
    token = token.strip()
    if token.isdigit():
        return int(token)
    return NUMBERS.get(token)


def _rank(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


class DemoProvider:
    """Deterministic, offline provider. Clearly labelled as demo mode in the interface.

    It understands a few Spanish phrasings (weekdays, meal types, "menos de N minutos",
    "solo cenamos dos", "no repitas", "mantén los desayunos") and picks recipes with simple
    rules. It is not an AI and never pretends to be one.
    """

    name = MODE_DEMO

    def generate(self, context, user_id=None):
        operation = context["operation"]
        if operation == "generate_recipe":
            output = self._recipe(context)
        else:
            output = self._plan(context)
        return ProviderResult(output=output, provider=self.name, model="demo")

    # Intent parsing -------------------------------------------------------------------------------

    def _intent(self, context):
        text = (context.get("user_request") or "").lower()
        intent = {
            "weekdays": {v for k, v in WEEKDAYS.items() if re.search(rf"\b{k}\b", text)},
            "meal_types": {v for k, v in MEAL_WORDS.items() if re.search(rf"\b{k}\b", text)},
            "keep_types": set(),
            "max_minutes": None,
            "headcount": None,
            "specific_headcount": {},
            "no_repeat": "no repitas" in text or "sin repetir" in text,
            "next_week": "próxima semana" in text or "proxima semana" in text or "semana que viene" in text
            or "siguiente semana" in text,
        }
        for match in re.finditer(r"(?:mant[ée]n|conserva)\s+(?:los|las|el|la)?\s*(\w+)", text):
            if match.group(1) in MEAL_WORDS:
                intent["keep_types"].add(MEAL_WORDS[match.group(1)])
        intent["meal_types"] -= intent["keep_types"]
        minutes = re.search(r"menos de ([\w ]+?) minutos", text)
        if minutes:
            intent["max_minutes"] = _number(minutes.group(1))
        people = re.search(r"\bpara (\w+)\b", text)
        if people and _number(people.group(1)):
            intent["headcount"] = _number(people.group(1))
        for match in re.finditer(r"(lunes|martes|mi[ée]rcoles|jueves|viernes|s[áa]bado|domingo)\s+solo\s+(\w+)\s+(\w+)", text):
            weekday = WEEKDAYS[match.group(1)]
            meal_type = VERB_MEALS.get(match.group(2))
            count = _number(match.group(3))
            if meal_type and count:
                intent["specific_headcount"][(weekday, meal_type)] = count
                intent["weekdays"].discard(weekday) if not intent["next_week"] else None
        return intent

    def _target_slots(self, context, intent):
        slots = [s for s in context["slots"] if not s["locked"]]
        if context.get("focus_slot"):
            focus = context["focus_slot"]
            return [s for s in slots if s["date"] == focus["date"] and s["meal_type"] == focus["meal_type"]]
        if context["operation"] == "chat":
            today = date.fromisoformat(context["today"])
            if intent["next_week"]:
                start = today + timedelta(days=7 - today.weekday())
                slots = [s for s in slots if start <= date.fromisoformat(s["date"]) <= start + timedelta(days=6)]
            elif intent["weekdays"]:
                seen, chosen = set(), []
                for slot in slots:
                    weekday = date.fromisoformat(slot["date"]).weekday()
                    if weekday in intent["weekdays"] and (weekday, slot["meal_type"]) not in seen:
                        seen.add((weekday, slot["meal_type"]))
                        chosen.append(slot)
                slots = chosen
            elif not intent["meal_types"] and not intent["keep_types"]:
                return None  # nothing recognisable
        if intent["meal_types"]:
            slots = [s for s in slots if s["meal_type"] in intent["meal_types"]]
        if intent["keep_types"]:
            slots = [s for s in slots if s["meal_type"] not in intent["keep_types"]]
        return slots

    # Planning -------------------------------------------------------------------------------------

    def _plan(self, context):
        intent = self._intent(context)
        slots = self._target_slots(context, intent)
        if slots is None:
            return AssistantOutput(
                summary=(
                    "Modo demostración: no he entendido la petición. Prueba con frases como «Cambia la cena del "
                    "jueves por algo de menos de veinte minutos» u «Organiza la próxima semana»."
                ),
                changes=[], new_recipes=[], warnings=[],
            )
        codes = [p["code"] for p in context["people"]]
        recipes = context["recipes"]
        exclude = set(context["recent_recipe_ids"]) if intent["no_repeat"] else set()
        used, changes, warnings = set(), [], []
        for slot in slots:
            the_date = date.fromisoformat(slot["date"])
            attendees = None
            specific = intent["specific_headcount"].get((the_date.weekday(), slot["meal_type"]))
            if specific:
                attendees = (slot["attendee_codes"] or codes)[:specific]
            elif intent["headcount"]:
                attendees = codes[: intent["headcount"]]
            if slot["rule"] and slot["rule"] not in ("cook", "leftovers") and not slot["exists"]:
                changes.append(MealChange(
                    date=slot["date"], meal_type=slot["meal_type"], mode=slot["rule"], recipe_ids=[],
                    new_recipe_refs=[], attendee_codes=attendees, notes="", reason="Se mantiene la regla del hogar.",
                ))
                continue
            people = attendees if attendees is not None else slot["attendee_codes"]
            candidates = [
                r for r in recipes
                if self._fits(r, slot["meal_type"]) and not set(r["blocked_for"]) & set(people)
                and not set(r["review_for"]) & set(people) and r["id"] not in exclude
                and r["id"] not in slot["recipe_ids"]
                and (intent["max_minutes"] is None or r["minutes"] < intent["max_minutes"])
            ]
            candidates.sort(key=lambda r: (r["id"] in used, _rank(slot["date"], slot["meal_type"], r["id"])))
            if not candidates:
                warnings.append(f"No hay recetas compatibles para {slot['weekday'].lower()} ({slot['meal_type']}).")
                changes.append(MealChange(
                    date=slot["date"], meal_type=slot["meal_type"], mode="pending", recipe_ids=[], new_recipe_refs=[],
                    attendee_codes=attendees, notes="", reason="Sin opciones compatibles con todos los asistentes.",
                ))
                continue
            recipe = candidates[0]
            used.add(recipe["id"])
            reason = f"{recipe['name']}: {recipe['minutes']} minutos, compatible con los asistentes según los datos."
            changes.append(MealChange(
                date=slot["date"], meal_type=slot["meal_type"], mode="cook", recipe_ids=[recipe["id"]],
                new_recipe_refs=[], attendee_codes=attendees, notes="", reason=reason,
            ))
        summary = f"Modo demostración: propuesta generada con reglas simples, sin IA, para {len(changes)} comida(s)."
        return AssistantOutput(summary=summary, changes=changes, new_recipes=[], warnings=warnings)

    @staticmethod
    def _fits(recipe, meal_type):
        meal_tags = {t for t in recipe["tags"] if t in MEAL_TAGS.values()}
        if not meal_tags:
            return meal_type in ("lunch", "dinner")
        return MEAL_TAGS[meal_type] in meal_tags

    def _recipe(self, context):
        known = set(context["known_ingredients"])
        lines = [
            ("Arroz", 300, "g"), ("Calabacín", 1, "unit"), ("Zanahoria", 2, "unit"),
            ("Pimiento rojo", 1, "unit"), ("Aceite de oliva", 30, "ml"), ("Sal", None, "g"),
        ]
        recipe = NewRecipe(
            ref="N1",
            name="Salteado de arroz con verduras (demo)",
            description="Receta de ejemplo del modo demostración, sin IA.",
            base_servings=4, prep_minutes=10, cook_minutes=20, difficulty="easy",
            tags=["comida", "cena"], equipment="Sartén grande",
            ingredients=[NewIngredientLine(name=n, quantity=q, unit=u, optional=False) for n, q, u in lines if n in known],
            steps=[
                "Cuece el arroz y reserva.",
                "Trocea las verduras y saltéalas en el aceite a fuego vivo.",
                "Añade el arroz, mezcla y ajusta de sal.",
            ],
        )
        return AssistantOutput(
            summary="Modo demostración: receta de ejemplo fija, sin IA. Revísala antes de usarla.",
            changes=[], new_recipes=[recipe], warnings=[],
        )


def get_provider():
    status = ai_status()
    if status.mode == MODE_DEMO:
        return DemoProvider()
    if status.mode == MODE_OPENAI:
        return OpenAIProvider(
            api_key=settings.OPENAI_API_KEY,
            model=settings.OPENAI_MODEL,
            timeout=settings.OPENAI_TIMEOUT_SECONDS,
            max_retries=settings.OPENAI_MAX_RETRIES,
            max_output_tokens=settings.OPENAI_MAX_OUTPUT_TOKENS,
        )
    raise ProviderNotConfigured("not_configured", status.detail)
