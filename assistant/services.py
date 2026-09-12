"""Assistant workflow: request → validate → persist proposal → review → apply.

* Network calls happen outside database transactions.
* Provider output is validated again against household data: ids must belong to the household,
  slots must be in range and not locked, and every recipe is checked by the dietary rules.
* Proposals are applied explicitly, once (row lock + status), and only if the affected meals
  did not change since the proposal was generated.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from diners.models import Diner
from foods import compatibility
from foods.compatibility import evaluate, facts_for_ingredient, rules_for_attendee, rules_for_diner
from foods.models import Category, Ingredient, Unit, normalize_name
from planning import services as planning
from planning.models import MODES_WITH_RECIPES, Meal, MealMode
from recipes import services as recipe_services
from recipes.models import Recipe, RecipeIngredient, RecipeStep

from .context import build_context
from .models import AIRequestLog, Proposal
from .providers import ProviderError, get_provider

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
    started = time.monotonic()
    try:
        provider = get_provider()
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


def _new_recipe_facts(recipe):
    """Facts for a proposed recipe. Unmatched ingredients are unknown by definition."""
    facts = []
    ids = [ln["ingredient_id"] for ln in recipe["ingredients"] if ln["ingredient_id"]]
    by_id = Ingredient.objects.in_bulk(ids)
    for line in recipe["ingredients"]:
        ingredient = by_id.get(line["ingredient_id"])
        if ingredient:
            facts.append(facts_for_ingredient(ingredient, optional=line["optional"]))
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


def validate_output(household, context, output, start, end):
    """Turn provider output into reviewable items. Invalid parts are rejected, never applied."""
    notes = [context.humanize(w.strip())[:300] for w in output.warnings if w.strip()]
    new_recipes = {}
    for raw in output.new_recipes[:MAX_NEW_RECIPES]:
        recipe = _validate_new_recipe(household, raw)
        if recipe["ref"] and recipe["ref"] not in new_recipes:
            new_recipes[recipe["ref"]] = recipe

    existing = {
        r.pk: r for r in recipe_services.recipes_for_household(household)
    }
    meals = planning.meals_by_slot(household, start, end)
    planning_context = planning.PlanningContext.load(household, start, end)
    items, seen = [], set()
    for change in output.changes[:MAX_CHANGES]:
        item = {
            "date": change.date, "meal_type": change.meal_type, "mode": change.mode, "recipe_ids": [],
            "recipe_names": [], "new_recipe_refs": [], "attendee_ids": None, "attendee_labels": [],
            "notes": context.humanize(change.notes.strip())[:300], "reason": context.humanize(change.reason.strip())[:300],
            "status": ITEM_OK,
            "issues": [], "current": None,
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
                _reject(item, "La comida está protegida; no se puede cambiar desde una propuesta.")
                continue

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
        elif change.recipe_ids or change.new_recipe_refs:
            item["issues"].append("Esta modalidad no lleva recetas; se ignoran las propuestas.")

        # Dietary rules are applied here, whatever the provider claimed.
        defaults = planning_context.defaults(the_date, change.meal_type)
        people = _people_for_slot(meal, attendee_diners, defaults.diners)
        facts = []
        for rid in item["recipe_ids"]:
            facts.extend(recipe_services.recipe_facts(existing[rid]))
        for ref in item["new_recipe_refs"]:
            facts.extend(_new_recipe_facts(new_recipes[ref]))
        result = evaluate(facts, people)
        if result.status == compatibility.CONFLICT:
            item["status"] = ITEM_CONFLICT
            item["issues"].extend(i.message for i in result.conflicts)
        elif result.status == compatibility.UNKNOWN:
            item["status"] = ITEM_REVIEW
            item["issues"].extend(i.message for i in result.unknowns)
        if change.mode in MODES_WITH_RECIPES and not (item["recipe_ids"] or item["new_recipe_refs"]):
            item["issues"].append("Sin receta asignada.")

    # Standalone new recipes (e.g. "genera una receta…") are checked against every diner.
    everyone = [rules_for_diner(d) for d in context.code_to_diner.values()]
    recipes_out = []
    for recipe in new_recipes.values():
        result = evaluate(_new_recipe_facts(recipe), everyone)
        recipe["status"] = {compatibility.OK: ITEM_OK, compatibility.UNKNOWN: ITEM_REVIEW}.get(result.status, ITEM_CONFLICT)
        recipe["issues"] = [i.message for i in result.issues if i.level != "warning"][:10]
        recipes_out.append(recipe)
    return items, recipes_out, notes


def _reject(item, reason):
    item["status"] = ITEM_REJECTED
    item["issues"].append(reason)


# --- Apply --------------------------------------------------------------------------------------


@dataclass
class ApplyResult:
    applied: int = 0
    skipped: list = field(default_factory=list)
    recipes_created: list = field(default_factory=list)
    stale: bool = False
    already_done: bool = False


def _create_recipe(household, user, data):
    recipe = Recipe.objects.create(
        household=household, name=data["name"], description=data["description"],
        base_servings=data["base_servings"], prep_minutes=data["prep_minutes"], cook_minutes=data["cook_minutes"],
        difficulty=data["difficulty"], tags=data["tags"], equipment=data["equipment"], origin=Recipe.Origin.AI,
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
            return result

        household = proposal.household
        created = {}
        needed_refs = {
            ref for item in proposal.items if _applicable(item, accepted_review) for ref in item["new_recipe_refs"]
        }
        for data in proposal.new_recipes:
            standalone = data["ref"] not in {r for i in proposal.items for r in i["new_recipe_refs"]}
            if data["problems"] or not (data["ref"] in needed_refs or standalone):
                continue
            if standalone and data["status"] == ITEM_CONFLICT:
                result.skipped.append(f"Receta «{data['name']}»: incompatible con algún comensal.")
                continue
            created[data["ref"]] = _create_recipe(household, user, data)
            result.recipes_created.append(created[data["ref"]])

        for item in proposal.items:
            label = f"{item['date']} {item['meal_type']}"
            if not _applicable(item, accepted_review):
                if item["status"] == ITEM_REVIEW:
                    result.skipped.append(f"{label}: requiere revisión y no se ha confirmado.")
                elif item["status"] in (ITEM_CONFLICT, ITEM_REJECTED):
                    result.skipped.append(f"{label}: {'; '.join(item['issues'][:2])}")
                continue
            outcome = _apply_item(household, user, item, created, accepted_review)
            if outcome is None:
                result.applied += 1
                touched_dates.append(date.fromisoformat(item["date"]))
            else:
                result.skipped.append(f"{label}: {outcome}")

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
    if meal.locked:
        return "la comida está protegida."
    diners = None
    if item["attendee_ids"] is not None:
        diners = list(Diner.objects.filter(household=household, is_active=True, pk__in=item["attendee_ids"]))
    recipes = list(Recipe.objects.filter(household=household, pk__in=item["recipe_ids"]))
    recipes += [created[ref] for ref in item["new_recipe_refs"] if ref in created]
    if item["mode"] in MODES_WITH_RECIPES and len(recipes) != len(item["recipe_ids"]) + len(item["new_recipe_refs"]):
        return "alguna receta ya no existe."

    # Revalidate with current restrictions: they may have changed since the proposal.
    meal = planning.meals_queryset(household).get(pk=meal.pk)
    people = _people_for_slot(meal, diners, [a.diner for a in meal.attendees.all() if a.diner_id])
    facts = [f for recipe in recipes for f in recipe_services.recipe_facts(recipe)] if item["mode"] in MODES_WITH_RECIPES else []
    check = evaluate(facts, people)
    if check.status == compatibility.CONFLICT:
        return "ahora es incompatible con algún asistente."
    if check.status == compatibility.UNKNOWN and item.get("slot") not in accepted_review:
        return "requiere revisión y no se ha confirmado."

    with transaction.atomic():
        if diners is not None:
            planning.set_attendees(meal, user, diners, lock=False)
        meal.recipes.all().delete()
        if item["mode"] in MODES_WITH_RECIPES:
            for recipe in recipes:
                recipe_services.snapshot_into_meal(meal, recipe)
        Meal.objects.filter(pk=meal.pk).update(
            mode=item["mode"] if item["mode"] in MealMode.values else MealMode.PENDING,
            notes=item["notes"] or meal.notes, source=Meal.Source.AI, version=F("version") + 1,
            updated_by=user, updated_at=timezone.now(),
        )
        planning.revalidate_meal(meal)
    return None


def discard_proposal(proposal):
    Proposal.objects.filter(pk=proposal.pk, status=Proposal.Status.PENDING).update(status=Proposal.Status.DISCARDED)
