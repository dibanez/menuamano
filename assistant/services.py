"""Assistant workflow: request → validate → persist proposal → review → apply.

* Network calls happen outside database transactions.
* Provider output is validated again against household data: ids must belong to the household,
  slots must be in range and not locked, and every recipe is checked by the dietary rules.
* Proposals are applied explicitly, once (row lock + status), and only if the affected meals
  did not change since the proposal was generated.
"""

import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.formats import date_format

from billing import entitlements
from core.choices import MealType
from diners.models import Diner
from foods import compatibility
from foods.compatibility import evaluate, facts_for_ingredient, rules_for_attendee, rules_for_diner
from foods.models import Category, Ingredient, Unit, normalize_name
from foods.reviews import reviews_for
from planning import services as planning
from planning.models import MODES_WITH_RECIPES, Meal, MealAttendee, MealMode
from recipes import importer
from recipes import services as recipe_services
from recipes.models import Recipe, RecipeIngredient, RecipeStep

from .context import build_context
from .models import AIRequestLog, Proposal
from .providers import ProviderError, get_provider
from .schemas import MealChange

logger = logging.getLogger(__name__)

MAX_CHANGES = 62
MAX_NEW_RECIPES = 5
MAX_INGREDIENTS = 40
MAX_STEPS = 30

ITEM_OK = "ok"
ITEM_REVIEW = "review"
ITEM_CONFLICT = "conflict"
ITEM_REJECTED = "rejected"


class AssistantError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(message)


# --- Request ------------------------------------------------------------------------------------


def _log(household, user, provider_name, operation, status, started, result=None, error_code=""):
    AIRequestLog.objects.create(
        household=household, user=user, provider=provider_name, operation=operation, status=status,
        error_code=error_code[:64], latency_ms=int((time.monotonic() - started) * 1000),
        model=(result.model if result else "")[:80],
        input_tokens=result.input_tokens if result else None,
        output_tokens=result.output_tokens if result else None,
        request_id=(result.request_id if result else "")[:80],
    )


def request_proposal(household, user, operation, start, end, text="", focus=None, history=()):
    """Ask the provider for changes and store them as a pending proposal. Never edits meals."""
    allowed, message = entitlements.check_ai(household)
    if not allowed:
        raise AssistantError(message)  # enforced here too, not only by hiding buttons
    started = time.monotonic()
    try:
        provider = get_provider(operation)
    except ProviderError as exc:
        _log(household, user, "none", operation, exc.status, started, error_code=exc.code)
        raise AssistantError(exc.user_message) from exc

    context = build_context(household, start, end, operation, user_request=text, focus=focus, history=history)
    base_versions = {
        planning.slot_key(m.date, m.meal_type): m.version
        for m in Meal.objects.filter(household=household, date__gte=start, date__lte=end)
    }

    try:
        result = provider.generate(context.data, user_id=user.pk if user else None)  # outside any transaction
    except ProviderError as exc:
        logger.warning("assistant provider error: provider=%s code=%s", provider.name, exc.code)
        _log(household, user, provider.name, operation, exc.status, started, error_code=exc.code)
        raise AssistantError(exc.user_message) from exc

    items, new_recipes, notes = validate_output(household, context, result.output, start, end)
    _log(household, user, provider.name, operation, AIRequestLog.Status.OK, started, result=result)
    with transaction.atomic():
        proposal = Proposal.objects.create(
            household=household, created_by=user, operation=operation, provider=provider.name,
            summary=_summary(context.humanize(result.output.summary), notes), items=items, new_recipes=new_recipes,
            base_versions=base_versions, start_date=start, end_date=end,
        )
    # Statuses and fixed rejection messages only: never names, allergies or the request text.
    logger.info(
        "assistant proposal %s created: operation=%s provider=%s model=%s items=%s statuses=%s rejected=%s new_recipes=%s",
        proposal.pk, operation, provider.name, result.model, len(items), dict(Counter(i["status"] for i in items)),
        sorted({i["rejected_reason"] for i in items if i.get("rejected_reason")}), len(new_recipes),
    )
    return proposal


def request_import(household, user, url):
    """Read a recipe from a web page and store it as a proposal to review. Never saves the recipe."""
    allowed, message = entitlements.check_ai(household)
    if not allowed:
        raise AssistantError(message)
    try:
        source = importer.read_recipe(url)  # network: outside any transaction
    except importer.RecipeImportError as exc:
        raise AssistantError(exc.message) from exc
    operation = Proposal.Operation.IMPORT_RECIPE
    started = time.monotonic()
    try:
        provider = get_provider(operation)
    except ProviderError as exc:
        _log(household, user, "none", operation, exc.status, started, error_code=exc.code)
        raise AssistantError(exc.user_message) from exc
    # The page and the ingredient names only: nothing about the people of the household.
    context = {
        "operation": str(operation),
        "source": source,
        "known_ingredients": list(
            Ingredient.objects.for_household(household).order_by("name").values_list("name", flat=True)
        ),
        "units": [u.value for u in Unit],
    }
    try:
        result = provider.generate(context, user_id=user.pk if user else None)
    except ProviderError as exc:
        logger.warning("assistant provider error: provider=%s code=%s", provider.name, exc.code)
        _log(household, user, provider.name, operation, exc.status, started, error_code=exc.code)
        raise AssistantError(exc.user_message) from exc
    _log(household, user, provider.name, operation, AIRequestLog.Status.OK, started, result=result)

    recipes = [_validate_new_recipe(household, raw) for raw in result.output.new_recipes[:1]]
    if not recipes:
        raise AssistantError(result.output.summary.strip()[:300] or "No se ha encontrado ninguna receta en esa página.")
    everyone = [rules_for_diner(d) for d in planning.diners_queryset(household)]
    reviews = reviews_for(household)
    for recipe in recipes:
        recipe["ref"] = recipe["ref"] or "N1"
        recipe["source_url"] = source["url"]
        recipe["origin"] = Recipe.Origin.IMPORTED
        check = evaluate(_new_recipe_facts(recipe, reviews), everyone)
        recipe["status"] = {compatibility.OK: ITEM_OK, compatibility.UNKNOWN: ITEM_REVIEW}.get(check.status, ITEM_CONFLICT)
        recipe["issues"] = [i.message for i in check.issues if i.level != "warning"][:10]
    today = timezone.localdate()
    with transaction.atomic():
        proposal = Proposal.objects.create(
            household=household, created_by=user, operation=operation, provider=provider.name,
            summary=_summary(result.output.summary, []), items=[], new_recipes=recipes, base_versions={},
            start_date=today, end_date=today,
        )
    logger.info(
        "assistant proposal %s created: operation=%s provider=%s source=%s new_recipes=%s",
        proposal.pk, operation, provider.name, source["format"], len(recipes),
    )
    return proposal


def _summary(summary, notes):
    text = (summary or "").strip()[:2000]
    if notes:
        text += "\n" + "\n".join(f"• {n}" for n in notes[:20])
    return text


# --- Validation ---------------------------------------------------------------------------------


def _match_ingredient(household, name):
    key = normalize_name(name)
    if not key:
        return None
    candidates = Ingredient.objects.for_household(household)
    found = candidates.filter(normalized_name=key).first()
    if found:
        return found
    for ingredient in candidates.exclude(aliases=[]):
        if key in {normalize_name(a) for a in ingredient.aliases}:
            return ingredient
    return None


def _validate_new_recipe(household, raw):
    problems = []
    lines = []
    for line in raw.ingredients[:MAX_INGREDIENTS]:
        name = line.name.strip()[:100]
        if not name:
            continue
        ingredient = _match_ingredient(household, name)
        quantity = None
        if line.quantity is not None:
            if line.quantity < 0 or line.quantity > 100000:
                problems.append(f"Cantidad no válida para {name}.")
                continue
            quantity = str(Decimal(str(line.quantity)).quantize(Decimal("0.001")))
        lines.append(
            {
                "name": ingredient.name if ingredient else name,
                "ingredient_id": ingredient.pk if ingredient else None,
                "quantity": quantity,
                "unit": line.unit if line.unit in Unit.values else Unit.G,
                "optional": bool(line.optional),
            }
        )
    steps = [s.strip()[:1000] for s in raw.steps if s.strip()][:MAX_STEPS]
    if not lines:
        problems.append("La receta no tiene ingredientes válidos.")
    if not steps:
        problems.append("La receta no tiene pasos.")
    recipe = {
        "ref": raw.ref.strip()[:20],
        "name": raw.name.strip()[:120] or "Receta sin nombre",
        "description": raw.description.strip()[:1000],
        "base_servings": min(max(int(raw.base_servings), 1), 20),
        "prep_minutes": min(max(int(raw.prep_minutes), 0), 600),
        "cook_minutes": min(max(int(raw.cook_minutes), 0), 600),
        "difficulty": raw.difficulty,
        "tags": sorted({t.strip().lower()[:30] for t in raw.tags if t.strip()})[:10],
        "equipment": raw.equipment.strip()[:200],
        "ingredients": lines,
        "steps": steps,
        "unmatched": [ln["name"] for ln in lines if ln["ingredient_id"] is None],
        "problems": problems,
    }
    return recipe


def _new_recipe_facts(recipe, reviews):
    """Facts for a proposed recipe. Unmatched ingredients are unknown by definition."""
    facts = []
    ids = [ln["ingredient_id"] for ln in recipe["ingredients"] if ln["ingredient_id"]]
    by_id = Ingredient.objects.in_bulk(ids)
    for line in recipe["ingredients"]:
        ingredient = by_id.get(line["ingredient_id"])
        if ingredient:
            facts.append(facts_for_ingredient(ingredient, optional=line["optional"], review=reviews.get(ingredient.pk)))
        else:
            facts.append(compatibility.IngredientFacts(None, line["name"], frozenset(), False, False, line["optional"]))
    return facts


def _people_for_slot(meal, attendee_diners, default_diners):
    """Rules for the people who will attend after the change (guests of an existing meal stay)."""
    people = []
    guests = []
    if meal is not None:
        guests = [a for a in meal.attendees.all() if not a.diner_id]
    if attendee_diners is not None:
        people = [rules_for_diner(d) for d in attendee_diners]
    elif meal is not None:
        people = [rules_for_attendee(a) for a in meal.attendees.all() if a.diner_id]
    else:
        people = [rules_for_diner(d) for d in default_diners]
    return people + [rules_for_attendee(g) for g in guests]


def _link_new_recipes_to_focus(changes, new_recipes, focus):
    """A request about one meal that returns a new recipe means that recipe is for that meal.

    Models sometimes return the recipe without referencing it from the meal change; applying
    would then only save it in the recipe book. Link the first unreferenced recipe to the focus
    meal, unless the model already chose recipes for it.
    """
    referenced = {ref for change in changes for ref in change.new_recipe_refs}
    unlinked = [ref for ref in new_recipes if ref not in referenced]
    if not unlinked:
        return changes
    key = (focus["date"], focus["meal_type"])
    for index, change in enumerate(changes):
        if (change.date, change.meal_type) == key:
            if change.mode in MODES_WITH_RECIPES and not change.recipe_ids and not change.new_recipe_refs:
                changes[index] = change.model_copy(update={"new_recipe_refs": unlinked[:1]})
            return changes
    return [*changes, MealChange(
        date=key[0], meal_type=key[1], mode=MealMode.COOK, recipe_ids=[], new_recipe_refs=unlinked[:1],
        attendee_codes=None, plates=[], notes="", reason="Receta nueva para esta comida.",
    )]


def _resolve_new_recipe_refs(changes, new_recipes, saved_by_name):
    """Point every change at a new recipe that exists, forgiving how the model wrote the reference.

    Models sometimes reference a new recipe with other case or spacing, by its name instead of its
    ref, or name a recipe of the book as if it were new. A ref that still matches nothing stays as
    it is, and the change is rejected as before.
    """
    by_key = {ref.strip().lower(): ref for ref in new_recipes}
    by_name = {normalize_name(recipe["name"]): ref for ref, recipe in new_recipes.items()}
    only = next(iter(new_recipes)) if len(new_recipes) == 1 else None

    def resolve(ref):
        """(new recipe ref, None), (None, saved recipe id) or (the ref as it was, None)."""
        if ref is None or ref in new_recipes:
            return ref, None
        found = by_key.get(ref.strip().lower()) or by_name.get(normalize_name(ref))
        if found:
            return found, None
        saved = saved_by_name.get(normalize_name(ref))
        if saved is not None:
            return None, saved.pk
        return (only, None) if only else (ref, None)  # one new recipe: an unknown ref can only be it

    out = []
    for change in changes:
        refs, ids = [], list(change.recipe_ids)
        for ref in change.new_recipe_refs:
            new_ref, saved_id = resolve(ref)
            if saved_id is not None:
                ids.append(saved_id)
            elif new_ref is not None:
                refs.append(new_ref)
        plates = []
        for plate in change.plates:
            new_ref, saved_id = resolve(plate.new_recipe_ref)
            if saved_id is not None:
                plates.append(plate.model_copy(update={"recipe_id": saved_id, "new_recipe_ref": None}))
            else:
                plates.append(plate.model_copy(update={"new_recipe_ref": new_ref}))
        out.append(change.model_copy(update={
            "new_recipe_refs": list(dict.fromkeys(refs)), "recipe_ids": list(dict.fromkeys(ids)), "plates": plates,
        }))
    return out


def _plate_key(plate):
    """("id", recipe id) or ("ref", new recipe ref), from a schema Plate or a stored item plate."""
    recipe_id = plate["recipe_id"] if isinstance(plate, dict) else plate.recipe_id
    ref = plate["new_recipe_ref"] if isinstance(plate, dict) else plate.new_recipe_ref
    return ("id", recipe_id) if recipe_id is not None else ("ref", ref)


def _validate_plates(change, item, context, slot_diners):
    """Who eats each recipe of a change. Returns ({key: [diners]}, error message or None)."""
    keys = {("id", rid) for rid in item["recipe_ids"]} | {("ref", ref) for ref in item["new_recipe_refs"]}
    allowed = {d.pk for d in slot_diners}
    plates = {}
    for plate in change.plates:
        key = _plate_key(plate)
        if key not in keys or key in plates:
            return {}, "La propuesta reparte una receta que no está en esa comida."
        diners = [context.diner_for_code(code) for code in dict.fromkeys(plate.eater_codes)]
        if not diners or any(d is None or d.pk not in allowed for d in diners):
            return {}, "La propuesta reparte platos entre personas que no están en esa comida."
        if len(diners) < len(allowed):  # a plate for everyone is just a recipe for the whole meal
            plates[key] = diners
    return plates, None


def _describe_plates(item, plates, existing, new_recipes):
    """Store who eats what on the item and show it next to each recipe name."""
    item["plates"] = [
        {
            "recipe_id": key[1] if key[0] == "id" else None, "new_recipe_ref": key[1] if key[0] == "ref" else None,
            "eater_ids": [d.pk for d in diners], "eater_labels": [d.alias for d in diners],
        }
        for key, diners in plates.items()
    ]

    def label(key, name):
        diners = plates.get(key)
        return f"{name} ({', '.join(d.alias for d in diners)})" if diners else name

    item["recipe_names"] = [label(("id", rid), existing[rid].name) for rid in item["recipe_ids"]] + [
        label(("ref", ref), new_recipes[ref]["name"]) for ref in item["new_recipe_refs"]
    ]


REPEAT_WINDOW_DAYS = 14


def _reuse_saved_recipes(changes, reused):
    """Point changes at the saved recipe when a "new" one only duplicates it ({ref: recipe id})."""
    if not reused:
        return changes
    out = []
    for change in changes:
        refs = [ref for ref in change.new_recipe_refs if ref in reused]
        if not refs:
            out.append(change)
            continue
        plates = [
            plate.model_copy(update={"recipe_id": reused[plate.new_recipe_ref], "new_recipe_ref": None})
            if plate.new_recipe_ref in reused else plate
            for plate in change.plates
        ]
        out.append(change.model_copy(update={
            "recipe_ids": [*change.recipe_ids, *(reused[ref] for ref in refs)],
            "new_recipe_refs": [ref for ref in change.new_recipe_refs if ref not in reused],
            "plates": plates,
        }))
    return out


def _planned_recipes(household, start, end):
    """{recipe id: [(date, meal type)]} in the calendar around the range, to spot repeats."""
    window = planning.meals_by_slot(
        household, start - timedelta(days=REPEAT_WINDOW_DAYS), end + timedelta(days=REPEAT_WINDOW_DAYS),
    )
    planned = {}
    for meal in window.values():
        for meal_recipe in meal.recipes.all():
            if meal_recipe.recipe_id:
                planned.setdefault(meal_recipe.recipe_id, []).append((meal.date, meal.meal_type))
    return planned


def _slot_label(day, meal_type):
    return f"el {date_format(day, 'l j')} ({MealType(meal_type).label.lower()})"


def _repeat_notes(item, the_date, meal_type, planned, changed_slots, proposed, existing):
    """Soft warnings for recipes already planned nearby or proposed twice: variety is a preference."""
    notes = []
    for rid in item["recipe_ids"]:
        # Slots this proposal changes do not count: their current recipes are being replaced.
        elsewhere = [(day, mt) for day, mt in planned.get(rid, []) if (day.isoformat(), mt) not in changed_slots]
        if elsewhere:
            day, mt = min(elsewhere, key=lambda slot: abs((slot[0] - the_date).days))
            notes.append(f"«{existing[rid].name}» se repite: ya está {_slot_label(day, mt)}.")
        elif rid in proposed:
            notes.append(f"«{existing[rid].name}» se repite: también se propone {_slot_label(*proposed[rid])}.")
        proposed.setdefault(rid, (the_date, meal_type))
    return notes


def validate_output(household, context, output, start, end):
    """Turn provider output into reviewable items. Invalid parts are rejected, never applied."""
    notes = [context.humanize(w.strip())[:300] for w in output.warnings if w.strip()]
    new_recipes = {}
    for index, raw in enumerate(output.new_recipes[:MAX_NEW_RECIPES], start=1):
        recipe = _validate_new_recipe(household, raw)
        recipe["ref"] = recipe["ref"] or f"N{index}"  # a recipe without ref is still usable
        if recipe["ref"] not in new_recipes:
            new_recipes[recipe["ref"]] = recipe

    existing = {
        r.pk: r for r in recipe_services.recipes_for_household(household)
    }
    reviews = reviews_for(household)
    focus = context.data.get("focus_slot") or {}
    saved_by_name = {normalize_name(r.name): r for r in existing.values()}
    changes = _resolve_new_recipe_refs(list(output.changes[:MAX_CHANGES]), new_recipes, saved_by_name)
    if focus:
        changes = _link_new_recipes_to_focus(changes, new_recipes, focus)
    # A "new" recipe named like a saved one is that recipe: reuse it instead of creating a duplicate.
    reused = {}
    for ref, recipe in list(new_recipes.items()):
        saved = saved_by_name.get(normalize_name(recipe["name"]))
        if saved is not None:
            reused[ref] = saved.pk
            del new_recipes[ref]
            notes.append(f"«{saved.name}» ya está en tu recetario: se usa la receta guardada.")
    changes = _reuse_saved_recipes(changes, reused)
    planned = _planned_recipes(household, start, end)
    changed_slots = {(c.date, c.meal_type) for c in changes}
    proposed = {}
    meals = planning.meals_by_slot(household, start, end)
    planning_context = planning.PlanningContext.load(household, start, end)
    items, seen = [], set()
    for change in changes:
        item = {
            "date": change.date, "meal_type": change.meal_type, "mode": change.mode, "recipe_ids": [],
            "recipe_names": [], "new_recipe_refs": [], "attendee_ids": None, "attendee_labels": [],
            "notes": context.humanize(change.notes.strip())[:300], "reason": context.humanize(change.reason.strip())[:300],
            "status": ITEM_OK,
            "issues": [], "current": None, "plates": [],
        }
        items.append(item)
        try:
            the_date = date.fromisoformat(change.date)
        except ValueError:
            _reject(item, "Fecha no válida.")
            continue
        if not (start <= the_date <= end):
            _reject(item, "La fecha está fuera del intervalo solicitado.")
            continue
        if change.meal_type not in household.enabled_meal_types:
            _reject(item, "Ese tipo de comida no está activo en el hogar.")
            continue
        key = planning.slot_key(the_date, change.meal_type)
        item["slot"] = key
        if key in seen:
            _reject(item, "Cambio duplicado para la misma comida.")
            continue
        seen.add(key)
        meal = meals.get(key)
        if meal is not None:
            item["current"] = {
                "mode": meal.get_mode_display(), "recipes": [mr.name for mr in meal.recipes.all()],
                "attendees": [a.label for a in meal.attendees.all()],
            }
            if meal.locked:
                is_focus = (change.date, change.meal_type) == (focus.get("date"), focus.get("meal_type"))
                if not is_focus and context.data.get("operation") != "chat":
                    _reject(item, "La comida está protegida; no se puede cambiar desde una propuesta.")
                    continue
                if not is_focus:
                    # Asked for in the chat: a meal edited by hand may change, but only once confirmed.
                    item["status"] = ITEM_REVIEW
                    item["issues"].append(
                        "Esta comida la editaste a mano y está protegida: marca la casilla si quieres cambiarla."
                    )
                # Set only here, never from provider output: a locked meal the person asked about.
                item["requested_meal"] = True

        if change.attendee_codes is not None:
            diners = []
            for code in change.attendee_codes:
                diner = context.diner_for_code(code)
                if diner is None:
                    break
                diners.append(diner)
            else:
                item["attendee_ids"] = sorted({d.pk for d in diners})
                item["attendee_labels"] = [d.alias for d in diners]
            if item["attendee_ids"] is None:
                _reject(item, "La propuesta menciona asistentes desconocidos.")
                continue
            attendee_diners = [d for d in diners]
        else:
            attendee_diners = None

        if change.mode in MODES_WITH_RECIPES:
            unknown_ids = [rid for rid in change.recipe_ids if rid not in existing]
            if unknown_ids:
                _reject(item, "La propuesta usa recetas que no son de este hogar.")
                continue
            missing_refs = [ref for ref in change.new_recipe_refs if ref not in new_recipes]
            if missing_refs:
                _reject(item, "La propuesta usa una receta nueva que no está definida.")
                continue
            item["recipe_ids"] = list(dict.fromkeys(change.recipe_ids))[:4]
            item["new_recipe_refs"] = list(dict.fromkeys(change.new_recipe_refs))[:4]
            item["recipe_names"] = [existing[rid].name for rid in item["recipe_ids"]] + [
                new_recipes[ref]["name"] for ref in item["new_recipe_refs"]
            ]
            if any(new_recipes[ref]["problems"] for ref in item["new_recipe_refs"]):
                _reject(item, "La receta nueva propuesta está incompleta.")
                continue
            if change.mode != MealMode.LEFTOVERS:  # leftovers eat the same dish on purpose
                item["issues"].extend(
                    _repeat_notes(item, the_date, change.meal_type, planned, changed_slots, proposed, existing)
                )
        elif change.recipe_ids or change.new_recipe_refs:
            item["issues"].append("Esta modalidad no lleva recetas; se ignoran las propuestas.")

        defaults = planning_context.defaults(the_date, change.meal_type)
        plates = {}
        if change.mode in MODES_WITH_RECIPES and change.plates:
            if attendee_diners is not None:
                slot_diners = attendee_diners
            elif meal is not None:
                slot_diners = [a.diner for a in meal.attendees.all() if a.diner_id]
            else:
                slot_diners = list(defaults.diners)
            plates, error = _validate_plates(change, item, context, slot_diners)
            if error:
                _reject(item, error)
                continue
            _describe_plates(item, plates, existing, new_recipes)

        # Dietary rules are applied here, whatever the provider claimed: each recipe against its eaters.
        people = _people_for_slot(meal, attendee_diners, defaults.diners)
        results = []
        for rid in item["recipe_ids"]:
            eaters = plates.get(("id", rid))
            results.append(evaluate(
                recipe_services.recipe_facts(existing[rid], reviews), [rules_for_diner(d) for d in eaters] if eaters else people,
            ))
        for ref in item["new_recipe_refs"]:
            eaters = plates.get(("ref", ref))
            results.append(evaluate(
                _new_recipe_facts(new_recipes[ref], reviews), [rules_for_diner(d) for d in eaters] if eaters else people,
            ))
        conflicts = [i for result in results for i in result.conflicts]
        unknowns = [i for result in results for i in result.unknowns]
        if conflicts:
            item["status"] = ITEM_CONFLICT
            item["issues"].extend(i.message for i in conflicts)
        elif unknowns:
            item["status"] = ITEM_REVIEW
            item["issues"].extend(i.message for i in unknowns)
        if change.mode in MODES_WITH_RECIPES and not (item["recipe_ids"] or item["new_recipe_refs"]):
            item["issues"].append("Sin receta asignada.")

    # Standalone new recipes (e.g. "genera una receta…") are checked against every diner.
    everyone = [rules_for_diner(d) for d in context.code_to_diner.values()]
    recipes_out = []
    for recipe in new_recipes.values():
        result = evaluate(_new_recipe_facts(recipe, reviews), everyone)
        recipe["status"] = {compatibility.OK: ITEM_OK, compatibility.UNKNOWN: ITEM_REVIEW}.get(result.status, ITEM_CONFLICT)
        recipe["issues"] = [i.message for i in result.issues if i.level != "warning"][:10]
        recipes_out.append(recipe)
    return items, recipes_out, notes


def _reject(item, reason):
    item["status"] = ITEM_REJECTED
    item["issues"].append(reason)
    item["rejected_reason"] = reason  # always a fixed message, so it can go to the logs


# --- Apply --------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    applied: int = 0
    skipped: list = field(default_factory=list)
    recipes_created: list = field(default_factory=list)
    stale: bool = False
    already_done: bool = False
    # Every change waits for «He revisado los avisos» and none was ticked: nothing was done.
    needs_confirmation: bool = False


def _create_recipe(household, user, data):
    recipe = Recipe.objects.create(
        household=household, name=data["name"], description=data["description"],
        base_servings=data["base_servings"], prep_minutes=data["prep_minutes"], cook_minutes=data["cook_minutes"],
        difficulty=data["difficulty"], tags=data["tags"], equipment=data["equipment"],
        origin=data.get("origin", Recipe.Origin.AI), source_url=data.get("source_url", ""),
        review_status=Recipe.ReviewStatus.NEEDS_REVIEW, created_by=user,
    )
    for order, line in enumerate(data["ingredients"]):
        ingredient = None
        if line["ingredient_id"]:
            ingredient = Ingredient.objects.for_household(household).filter(pk=line["ingredient_id"]).first()
        if ingredient is None:
            # Unknown to the catalogue: stable identity for shopping, but unreviewed (compatibility unknown).
            ingredient = _match_ingredient(household, line["name"]) or Ingredient.objects.create(
                household=household, name=line["name"], source=Ingredient.Source.AI, category=Category.OTHER,
                default_unit=line["unit"], trait_info_complete=False,
            )
        RecipeIngredient.objects.create(
            recipe=recipe, ingredient=ingredient, unit=line["unit"], optional=line["optional"], order=order,
            quantity=Decimal(line["quantity"]) if line["quantity"] is not None else None,
        )
    for order, text in enumerate(data["steps"]):
        RecipeStep.objects.create(recipe=recipe, order=order, text=text)
    return recipe


def _is_stale(proposal):
    current = {
        planning.slot_key(m.date, m.meal_type): m.version
        for m in Meal.objects.filter(
            household=proposal.household, date__gte=proposal.start_date, date__lte=proposal.end_date
        )
    }
    return current != proposal.base_versions


def apply_proposal(proposal, user, accepted_review=()):
    """Apply valid items once. Conflicting or rejected items are never applied."""
    accepted_review = set(accepted_review)
    result = ApplyResult()
    touched_dates = []
    with transaction.atomic():
        proposal = Proposal.objects.select_for_update().get(pk=proposal.pk)
        if proposal.status != Proposal.Status.PENDING:
            result.already_done = True
            return result
        if _is_stale(proposal):
            proposal.status = Proposal.Status.STALE
            proposal.result_message = "El plan cambió después de generar la propuesta."
            proposal.save(update_fields=["status", "result_message"])
            result.stale = True
            logger.info("assistant proposal %s not applied: the plan changed (operation=%s)", proposal.pk, proposal.operation)
            return result

        # Applying would change nothing because every change waits for a confirmation: keep the
        # proposal pending, so the person can tick it instead of losing it.
        waiting = [i for i in proposal.items if i["status"] == ITEM_REVIEW and i.get("slot") not in accepted_review]
        if waiting and not any(_applicable(i, accepted_review) for i in proposal.items):
            result.needs_confirmation = True
            logger.info(
                "assistant proposal %s not applied: %s change(s) wait for review confirmation (operation=%s)",
                proposal.pk, len(waiting), proposal.operation,
            )
            return result

        household = proposal.household
        created = {}
        needed_refs = {
            ref for item in proposal.items if _applicable(item, accepted_review) for ref in item["new_recipe_refs"]
        }
        # Recipes of changes left for review are kept in the recipe book (pending review), never lost.
        kept_refs = {ref for item in waiting for ref in item["new_recipe_refs"]}
        for data in proposal.new_recipes:
            standalone = data["ref"] not in {r for i in proposal.items for r in i["new_recipe_refs"]}
            if data["problems"] or not (data["ref"] in needed_refs or data["ref"] in kept_refs or standalone):
                continue
            # An imported recipe was asked for by name: it is kept even if not everyone can eat it
            # (plates per diner exist for that), and its status is shown on the recipe.
            if standalone and data["status"] == ITEM_CONFLICT and proposal.operation != Proposal.Operation.IMPORT_RECIPE:
                result.skipped.append(f"Receta «{data['name']}»: incompatible con algún comensal.")
                continue
            created[data["ref"]] = _create_recipe(household, user, data)
            result.recipes_created.append(created[data["ref"]])

        # Why items were left out, for the logs: statuses and fixed reasons only, never names or allergies.
        reasons = Counter()
        for item in proposal.items:
            try:
                label = _slot_label(date.fromisoformat(item["date"]), item["meal_type"])
            except (ValueError, KeyError):
                label = f"{item['date']} {item['meal_type']}"
            if not _applicable(item, accepted_review):
                if item["status"] == ITEM_REVIEW:
                    kept = [created[ref].name for ref in item["new_recipe_refs"] if ref in created]
                    result.skipped.append(
                        f"{label}: requiere revisión y no se marcó «He revisado los avisos»."
                        + (f" «{kept[0]}» queda en el recetario, pendiente de revisión." if kept else "")
                    )
                    reasons["review_not_confirmed"] += 1
                elif item["status"] in (ITEM_CONFLICT, ITEM_REJECTED):
                    result.skipped.append(f"{label}: {'; '.join(item['issues'][:2])}")
                    # Rejections carry fixed messages; conflict messages name people, so only the status is logged.
                    if item["status"] == ITEM_REJECTED:
                        reasons[f"rejected: {item.get('rejected_reason', '?')}"] += 1
                    else:
                        reasons[ITEM_CONFLICT] += 1
                continue
            outcome = _apply_item(household, user, item, created, accepted_review)
            if outcome is None:
                result.applied += 1
                touched_dates.append(date.fromisoformat(item["date"]))
            else:
                result.skipped.append(f"{label}: {outcome}")
                reasons[outcome.rstrip(".")] += 1
        logger.info(
            "assistant proposal %s applied: operation=%s provider=%s items=%s applied=%s recipes_created=%s skipped=%s",
            proposal.pk, proposal.operation, proposal.provider, len(proposal.items), result.applied,
            len(result.recipes_created), dict(reasons),
        )

        proposal.status = Proposal.Status.APPLIED
        proposal.applied_at = timezone.now()
        proposal.applied_by = user
        proposal.result_message = f"{result.applied} cambios aplicados; {len(result.skipped)} omitidos."
        proposal.save(update_fields=["status", "applied_at", "applied_by", "result_message"])
        if touched_dates:
            planning.meals_changed.send(sender=Meal, household=household, dates=touched_dates)
    return result


def _applicable(item, accepted_review):
    if item["status"] == ITEM_OK:
        return True
    return item["status"] == ITEM_REVIEW and item.get("slot") in accepted_review


def _apply_item(household, user, item, created, accepted_review):
    """Apply one change after re-checking it against current data. Returns an error or None."""
    the_date = date.fromisoformat(item["date"])
    meal, _ = planning.get_or_create_meal(household, the_date, item["meal_type"], user=user)
    if meal.locked and not item.get("requested_meal"):
        return "la comida está protegida."
    diners = None
    if item["attendee_ids"] is not None:
        diners = list(Diner.objects.filter(household=household, is_active=True, pk__in=item["attendee_ids"]))
    by_id = Recipe.objects.filter(household=household).in_bulk(item["recipe_ids"])
    recipes = [(("id", rid), by_id[rid]) for rid in item["recipe_ids"] if rid in by_id]
    recipes += [(("ref", ref), created[ref]) for ref in item["new_recipe_refs"] if ref in created]
    if item["mode"] in MODES_WITH_RECIPES and len(recipes) != len(item["recipe_ids"]) + len(item["new_recipe_refs"]):
        return "alguna receta ya no existe."
    plate_eaters = {_plate_key(p): p["eater_ids"] for p in item.get("plates", [])}

    # Revalidate with current restrictions: they may have changed since the proposal.
    meal = planning.meals_queryset(household).get(pk=meal.pk)
    people = _people_for_slot(meal, diners, [a.diner for a in meal.attendees.all() if a.diner_id])
    reviews = reviews_for(household)
    statuses = set()
    if item["mode"] in MODES_WITH_RECIPES:
        for key, recipe in recipes:
            eater_ids = plate_eaters.get(key)
            eaters = [rules_for_diner(d) for d in Diner.objects.filter(household=household, pk__in=eater_ids)] if eater_ids else people
            statuses.add(evaluate(recipe_services.recipe_facts(recipe, reviews), eaters).status)
    if compatibility.CONFLICT in statuses:
        return "ahora es incompatible con algún asistente."
    if compatibility.UNKNOWN in statuses and item.get("slot") not in accepted_review:
        return "requiere revisión y no se ha confirmado."

    with transaction.atomic():
        if diners is not None:
            planning.set_attendees(meal, user, diners, lock=False)
        meal.recipes.all().delete()
        if item["mode"] in MODES_WITH_RECIPES:
            for key, recipe in recipes:
                meal_recipe = recipe_services.snapshot_into_meal(meal, recipe)
                if plate_eaters.get(key):
                    meal_recipe.eaters.set(MealAttendee.objects.filter(meal=meal, diner_id__in=plate_eaters[key]))
        Meal.objects.filter(pk=meal.pk).update(
            mode=item["mode"] if item["mode"] in MealMode.values else MealMode.PENDING,
            notes=item["notes"] or meal.notes, source=Meal.Source.AI, version=F("version") + 1,
            updated_by=user, updated_at=timezone.now(),
        )
        planning.revalidate_meal(meal)
    return None


def discard_proposal(proposal):
    Proposal.objects.filter(pk=proposal.pk, status=Proposal.Status.PENDING).update(status=Proposal.Status.DISCARDED)
