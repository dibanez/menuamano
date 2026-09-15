"""The assistant with each person's own AI key, kept only on their device.

The key never reaches the server. A request takes two steps from the browser:

1. prepare: the server builds the same anonymised context it would send to its own provider and
   returns it with the instructions, the output schema and a signed token describing the request;
2. the browser sends that to the provider with the key and posts the answer back with the token.

The answer is untrusted like any provider output: it is parsed against the schema and validated
again against the household's data before it becomes a proposal. The token ties it to the request
that was prepared (household, person, operation, dates, text) and keeps the meal versions seen
then, so changes made while the provider was answering are still detected.
"""

import hashlib
import json
from dataclasses import dataclass
from functools import cache

import pydantic
from django.conf import settings
from django.core import signing
from openai.lib._pydantic import to_strict_json_schema

from .providers import INSTRUCTIONS, ProviderError, ProviderResult, ProviderSchemaError
from .schemas import AssistantOutput

PREPARE = "prepare"  # stage sentinel: build the request for the browser instead of answering it
STAGE_HEADER = "X-AI-Stage"
TOKEN_SALT = "assistant.device"
TOKEN_MAX_AGE = 15 * 60  # seconds from preparing a request to posting its answer
MAX_OUTPUT_CHARS = 200_000
SCHEMA_NAME = "assistant_output"

# Providers the browser can call directly with a key; static/js/app.js knows how to talk to each.
# Model names are suggestions: people can type any model their account offers.
PROVIDERS = {
    "openai": {
        "label": "OpenAI",
        "models": ["gpt-5.6-luna", "gpt-5.6-terra"],
        "keys_url": "https://platform.openai.com/api-keys",
    },
    "anthropic": {
        "label": "Anthropic (Claude)",
        "models": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"],
        "keys_url": "https://console.anthropic.com/settings/keys",
    },
    "gemini": {
        "label": "Google Gemini",
        "models": ["gemini-flash-latest", "gemini-pro-latest"],
        "keys_url": "https://aistudio.google.com/apikey",
    },
    "mistral": {
        "label": "Mistral",
        "models": ["mistral-medium-latest", "mistral-large-latest", "mistral-small-latest"],
        "keys_url": "https://console.mistral.ai/api-keys",
    },
    "openrouter": {
        "label": "OpenRouter",
        "models": [],
        "keys_url": "https://openrouter.ai/keys",
    },
}


def wants_prepare(request):
    return request.headers.get(STAGE_HEADER) == PREPARE


def _inline_refs(schema):
    """The schema with every $ref replaced by its definition: not every provider resolves them."""
    definitions = schema.pop("$defs", {})

    def resolve(node):
        if isinstance(node, list):
            return [resolve(value) for value in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            target = definitions[node["$ref"].rsplit("/", 1)[-1]]
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            return resolve({**target, **siblings})
        return {key: resolve(value) for key, value in node.items()}

    return resolve(schema)


@cache
def output_schema():
    """AssistantOutput as a strict JSON schema without references."""
    return _inline_refs(to_strict_json_schema(AssistantOutput))


def _claims(household, user, operation, start, end, text, focus):
    return {
        "h": household.pk,
        "u": user.pk if user else None,
        "op": str(operation),
        "s": start.isoformat(),
        "e": end.isoformat(),
        "f": [focus[0].isoformat(), str(focus[1])] if focus else None,
        "t": hashlib.sha256((text or "").encode()).hexdigest()[:24],
    }


def prepared(household, user, operation, start, end, context_data, text="", focus=None, base_versions=None, source=None):
    """What the browser sends to its provider, and the token to post the answer with."""
    claims = _claims(household, user, operation, start, end, text, focus)
    claims.update(v=base_versions or {}, src=source or {})
    return {
        "token": signing.dumps(claims, salt=TOKEN_SALT, compress=True),
        "instructions": INSTRUCTIONS,
        "input": json.dumps(context_data, ensure_ascii=False),
        "schema_name": SCHEMA_NAME,
        "schema": output_schema(),
        "max_output_tokens": settings.OPENAI_MAX_OUTPUT_TOKENS,
    }


def _count(value, limit):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= limit else None


@dataclass
class DeviceReply:
    """An answer the browser got from its provider with the person's own key."""

    token: str
    output: str
    provider: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None

    key_source = "device"

    @property
    def name(self):
        return self.provider

    @classmethod
    def from_post(cls, data):
        """The answer posted with a form, or None when the form was not sent through a device key."""
        if not data.get("ai_token"):
            return None
        provider = data.get("ai_provider", "")
        return cls(
            token=data["ai_token"],
            output=data.get("ai_output", "")[:MAX_OUTPUT_CHARS],
            provider=provider if provider in PROVIDERS else "other",
            model=data.get("ai_model", "").strip()[:80],
            input_tokens=_count(data.get("ai_input_tokens"), 10_000_000),
            output_tokens=_count(data.get("ai_output_tokens"), 10_000_000),
            latency_ms=_count(data.get("ai_latency_ms"), 3_600_000),
        )

    def claims(self, household, user, operation, start, end, text="", focus=None):
        """The signed request this answer belongs to, once checked against the current one."""
        try:
            claims = signing.loads(self.token, salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
        except signing.SignatureExpired as exc:
            raise ProviderError("token_expired", "La petición ha caducado. Vuelve a intentarlo.") from exc
        except signing.BadSignature as exc:
            raise ProviderError("token_invalid", "La respuesta no corresponde a esta petición. Vuelve a intentarlo.") from exc
        expected = _claims(household, user, operation, start, end, text, focus)
        if any(claims.get(key) != value for key, value in expected.items()):
            raise ProviderError("token_mismatch", "La respuesta no corresponde a esta petición. Vuelve a intentarlo.")
        return claims

    def generate(self, context, user_id=None):
        try:
            output = AssistantOutput.model_validate_json(self.output)
        except (pydantic.ValidationError, ValueError) as exc:
            raise ProviderSchemaError("schema", "La respuesta de la IA no tenía el formato esperado. No se ha cambiado nada.") from exc
        return ProviderResult(
            output=output, provider=self.provider, model=self.model,
            input_tokens=self.input_tokens, output_tokens=self.output_tokens,
        )
