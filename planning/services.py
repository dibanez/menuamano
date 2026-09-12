"""Meal planning rules: defaults from patterns, recurring rules and exceptions; edits that keep
dietary validation and shopping needs in sync; range regeneration that respects locks."""

import hashlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import F, Prefetch
from django.utils import timezone

from core.choices import MEAL_TYPE_ORDER
from diners.models import Diner, DinerRestriction
from foods import compatibility
from foods.compatibility import evaluate, facts_for_ingredient, rules_for_attendee, rules_for_diner
from recipes import services as recipe_services

from .models import (
    MODES_WITH_RECIPES,
    DateException,
    Meal,
    MealAttendee,
    MealMode,
    MealRecipe,
    MealRecipeIngredient,
    RecurringRule,
    SafetyStatus,
)
from .signals import meals_changed


LEFTOVERS_MAX_DAYS = 4


class PlanningError(Exception):
    """User-facing planning error (message in Spanish)."""


class IncompatibleRecipe(PlanningError):
    def __init__(self, result, alternatives=()):
        self.result = result
        self.alternatives = list(alternatives)
        super().__init__("La receta es incompatible con las restricciones de los asistentes.")


def daterange(start, end):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


def slot_key(day, meal_type):
    return f"{day.isoformat()}|{meal_type}"


# --- Queries ------------------------------------------------------------------------------


def diners_queryset(household):
    return (
        Diner.objects.filter(household=household, is_active=True)
        .prefetch_related(
            "attendance_patterns",
            Prefetch("restrictions", queryset=DinerRestriction.objects.select_related("ingredient")),
            "preferences",
        )
    )


def meals_queryset(household):
    return Meal.objects.filter(household=household).prefetch_related(
        Prefetch(
            "attendees",
            queryset=MealAttendee.objects.select_related("diner").prefetch_related(
                Prefetch("diner__restrictions", queryset=DinerRestriction.objects.select_related("ingredient"))
            ),
        ),
        Prefetch(
            "recipes",
            queryset=MealRecipe.objects.select_related("recipe").prefetch_related(
                Prefetch(
                    "ingredients",
                    queryset=MealRecipeIngredient.objects.select_related("ingredient", "substituted_for"),
                )
            ),
        ),
        Prefetch("leftover_meals", queryset=Meal.objects.prefetch_related("attendees")),
        "leftovers_from__recipes",
    ).select_related("leftovers_from")


def meals_by_slot(household, start, end):
    meals = meals_queryset(household).filter(date__gte=start, date__lte=end)
    return {slot_key(m.date, m.meal_type): m for m in meals}


# --- Defaults: patterns, recurring rules and explicit exceptions ---------------------------


@dataclass
class SlotDefaults:
    mode: str
    diners: list
    notes: str = ""
    source: str = "pattern"  # "pattern", "rule" or "exception"
    mode_is_explicit: bool = False

    @property
    def mode_label(self):
        return MealMode(self.mode).label


@dataclass
class PlanningContext:
    household: object
    diners: list
    rules: list
    exceptions: dict = field(default_factory=dict)

    @classmethod
    def load(cls, household, start, end):
        exceptions = {
            slot_key(e.date, e.meal_type): e
            for e in DateException.objects.filter(household=household, date__gte=start, date__lte=end)
            .prefetch_related("attendees")
        }
        return cls(
            household=household,
            diners=list(diners_queryset(household)),
            rules=list(RecurringRule.objects.filter(household=household, is_active=True)),
            exceptions=exceptions,
        )

    def defaults(self, day, meal_type):
        exception = self.exceptions.get(slot_key(day, meal_type))
        rule = next((r for r in self.rules if r.meal_type == meal_type and r.applies_to(day)), None)

        attendees = [d for d in self.diners if _attends(d, day.weekday(), meal_type)]
        mode, notes, source, explicit = MealMode.COOK, "", "pattern", False
        if rule is not None:
            mode, notes, source, explicit = rule.mode, rule.notes, "rule", True
        # Explicit exceptions for a date always win over recurring rules.
        if exception is not None:
            source = "exception"
            if exception.mode:
                mode, explicit = exception.mode, True
            if exception.notes:
                notes = exception.notes
            if exception.override_attendance:
                chosen = {d.pk for d in exception.attendees.all()}
                attendees = [d for d in self.diners if d.pk in chosen]
        return SlotDefaults(mode=mode, diners=attendees, notes=notes, source=source, mode_is_explicit=explicit)


def _attends(diner, weekday, meal_type):
    for pattern in diner.attendance_patterns.all():
        if pattern.weekday == weekday and pattern.meal_type == meal_type:
            return pattern.attends
    return True


# --- Validation ---------------------------------------------------------------------------


def people_for_meal(meal):
    return [rules_for_attendee(a) for a in meal.attendees.all()]


def meal_ingredient_facts(meal):
    facts = []
    for meal_recipe in meal.recipes.all():
        for line in meal_recipe.ingredients.all():
            facts.append(facts_for_ingredient(line.ingredient, optional=line.optional, substituted_for=line.substituted_for))
    return facts


def _issue(level, message):
    return {"level": level, "person": "", "ingredient": "", "message": message, "trait": ""}


def _leftovers_check(meal):
    """Leftovers are checked against the ingredients of the meal they come from."""
    source = meals_queryset(meal.household).get(pk=meal.leftovers_from_id)
    if source.mode != MealMode.COOK or not source.recipes.all():
        return SafetyStatus.UNKNOWN, [
            _issue("unknown", "La comida de origen ya no se cocina en casa: revisa de dónde salen estas sobras.")
        ]
    result = evaluate(meal_ingredient_facts(source), people_for_meal(meal))
    issues = result.issues_as_dicts()
    gap = (meal.date - source.date).days
    if gap < 0:
        issues.append(_issue("warning", "La comida de origen es posterior a esta: revisa las fechas."))
    elif gap > LEFTOVERS_MAX_DAYS:
        issues.append(_issue("warning", f"Las sobras vienen de hace {gap} días: comprueba que siguen en buen estado."))
    return result.status, issues


def revalidate_meal(meal):
    """Re-run dietary checks on the meal as it is now and persist the outcome."""
    meal = meals_queryset(meal.household).get(pk=meal.pk)
    if meal.mode == MealMode.LEFTOVERS and meal.leftovers_from_id:
        status, issues = _leftovers_check(meal)
    elif meal.mode in MODES_WITH_RECIPES and meal.recipes.all():
        result = evaluate(meal_ingredient_facts(meal), people_for_meal(meal))
        status, issues = result.status, result.issues_as_dicts()
    else:
        status, issues = SafetyStatus.NOT_APPLICABLE, []
    Meal.objects.filter(pk=meal.pk).update(
        safety_status=status, safety_issues=issues, safety_checked_at=timezone.now()
    )
    meal.safety_status, meal.safety_issues = status, issues
    # Leftovers depending on this meal eat what it cooks: check them again too.
    for dependent in meal.leftover_meals.all():
        revalidate_meal(dependent)
    return meal


def planned_servings(meal):
    """Servings to cook: attendees plus the linked leftovers meals (needs meals_queryset prefetch)."""
    extra = sum(
        (dependent.servings for dependent in meal.leftover_meals.all() if dependent.mode == MealMode.LEFTOVERS),
        Decimal("0"),
    )
    return meal.servings + extra


def leftovers_candidates(meal):
    """Cooked meals with recipes from the previous days that can provide leftovers."""
    order = {str(m): i for i, m in enumerate(MEAL_TYPE_ORDER)}
    meals = (
        Meal.objects.filter(
            household=meal.household, mode=MealMode.COOK, recipes__isnull=False,
            date__gte=meal.date - timedelta(days=LEFTOVERS_MAX_DAYS), date__lte=meal.date,
        )
        .exclude(pk=meal.pk)
        .distinct()
        .prefetch_related("recipes")
        .order_by("-date", "meal_type")
    )
    return [
        m for m in meals
        if m.date < meal.date or order.get(m.meal_type, 0) < order.get(meal.meal_type, 0)
    ]


def revalidate_upcoming(household, since=None):
    """Revalidate meals from `since` (today by default) after restrictions or ingredients change."""
    since = since or timezone.localdate()
    ids = list(Meal.objects.filter(household=household, date__gte=since).values_list("pk", flat=True))
    for meal in Meal.objects.filter(pk__in=ids).select_related("household"):
        revalidate_meal(meal)
    return len(ids)


def compatible_alternatives(household, people, meal_type=None, exclude_ids=(), limit=5):
    """Recipes that are compatible (OK first, then UNKNOWN) for the given people."""
    ok, unknown = [], []
    for recipe in recipe_services.recipes_for_household(household):
        if recipe.pk in exclude_ids:
            continue
        if meal_type and not recipe_services.fits_meal_type(recipe, meal_type):
            continue
        status = recipe_services.check_recipe(recipe, people).status
        if status == compatibility.OK:
            ok.append(recipe)
        elif status == compatibility.UNKNOWN:
            unknown.append(recipe)
    return (ok + unknown)[:limit]


# --- Edits --------------------------------------------------------------------------------


def _touch(meal, user, lock=True):
    """Bump the version after a manual change. Manual changes are protected by default."""
    fields = {"version": F("version") + 1, "updated_by": user, "updated_at": timezone.now()}
    if lock:
        fields["locked"] = True
    Meal.objects.filter(pk=meal.pk).update(**fields)
    meal.refresh_from_db()


def _changed(household, *days):
    days = [d for d in days if d]
    # Leftovers change what their source meal cooks, so its date is affected too.
    source_days = Meal.objects.filter(
        household=household, date__in=days, mode=MealMode.LEFTOVERS, leftovers_from__isnull=False
    ).values_list("leftovers_from__date", flat=True)
    meals_changed.send(sender=Meal, household=household, dates=days + list(source_days))


@transaction.atomic
def get_or_create_meal(household, day, meal_type, context=None, user=None):
    meal = Meal.objects.select_for_update().filter(household=household, date=day, meal_type=meal_type).first()
    if meal is not None:
        return meal, False
    context = context or PlanningContext.load(household, day, day)
    defaults = context.defaults(day, meal_type)
    meal = Meal.objects.create(
        household=household,
        date=day,
        meal_type=meal_type,
        mode=defaults.mode if defaults.mode_is_explicit else MealMode.PENDING,
        notes=defaults.notes,
        updated_by=user,
    )
    MealAttendee.objects.bulk_create(
        MealAttendee(meal=meal, diner=d, portion=d.portion_factor) for d in defaults.diners
    )
    return meal, True


@transaction.atomic
def update_meal_details(meal, user, *, mode, notes, locked, outcome, outcome_notes):
    old_source_date = meal.leftovers_from.date if meal.leftovers_from_id else None
    meal.mode, meal.notes, meal.outcome, meal.outcome_notes = mode, notes, outcome, outcome_notes
    if mode != MealMode.LEFTOVERS:
        meal.leftovers_from = None
    meal.save(update_fields=["mode", "notes", "outcome", "outcome_notes", "leftovers_from", "updated_at"])
    _touch(meal, user, lock=False)
    Meal.objects.filter(pk=meal.pk).update(locked=locked)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date, old_source_date)
    return meal


@transaction.atomic
def set_leftovers_source(meal, source, user):
    """Mark the meal as leftovers of an earlier cooked meal, which then cooks extra servings."""
    if source.household_id != meal.household_id:
        raise PlanningError("La comida de origen no es de este hogar.")
    if source.pk == meal.pk:
        raise PlanningError("Una comida no puede ser sobras de sí misma.")
    if source not in leftovers_candidates(meal):
        raise PlanningError(
            f"Elige una comida anterior, cocinada en casa y con recetas, de los últimos {LEFTOVERS_MAX_DAYS} días."
        )
    if meal.recipes.exists():
        raise PlanningError("Quita antes las recetas de esta comida: las sobras usan las de la comida de origen.")
    if meal.leftover_meals.exists():
        raise PlanningError("De esta comida salen sobras para otra, así que no puede ser sobras a su vez.")
    current = meals_queryset(meal.household).get(pk=meal.pk)
    origin = meals_queryset(meal.household).get(pk=source.pk)
    result = evaluate(meal_ingredient_facts(origin), people_for_meal(current))
    if result.status == compatibility.CONFLICT:
        raise IncompatibleRecipe(result)
    Meal.objects.filter(pk=meal.pk).update(mode=MealMode.LEFTOVERS, leftovers_from=source)
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date, source.date)
    return meal, result


@transaction.atomic
def clear_leftovers_source(meal, user):
    old_source_date = meal.leftovers_from.date if meal.leftovers_from_id else None
    Meal.objects.filter(pk=meal.pk).update(leftovers_from=None)
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date, old_source_date)
    return meal


@transaction.atomic
def set_locked(meal, user, locked):
    Meal.objects.filter(pk=meal.pk).update(locked=locked, version=F("version") + 1, updated_by=user)
    meal.refresh_from_db()
    return meal


@transaction.atomic
def set_attendees(meal, user, diners, portions=None, lock=True):
    """Replace household attendees (guests are kept). Recomputes servings and revalidates."""
    portions = portions or {}
    wanted = {d.pk: d for d in diners}
    meal.attendees.filter(diner__isnull=False).exclude(diner_id__in=wanted).delete()
    existing = {a.diner_id: a for a in meal.attendees.filter(diner__isnull=False)}
    for diner_id, diner in wanted.items():
        portion = portions.get(diner_id, diner.portion_factor)
        if diner_id in existing:
            attendee = existing[diner_id]
            if attendee.portion != portion:
                attendee.portion = portion
                attendee.save(update_fields=["portion"])
        else:
            MealAttendee.objects.create(meal=meal, diner=diner, portion=portion)
    _touch(meal, user, lock=lock)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal


@transaction.atomic
def add_guest(meal, user, name, traits, notes="", portion=Decimal("1")):
    MealAttendee.objects.create(meal=meal, guest_name=name, guest_traits=list(traits), guest_notes=notes, portion=portion)
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal


@transaction.atomic
def remove_attendee(meal, user, attendee_id):
    meal.attendees.filter(pk=attendee_id).delete()
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal


def check_recipe_for_meal(meal, recipe):
    meal = meals_queryset(meal.household).get(pk=meal.pk)
    return recipe_services.check_recipe(recipe, people_for_meal(meal))


@transaction.atomic
def add_recipe(meal, recipe, user, servings_override=None, lock=True):
    """Add a recipe snapshot. Incompatible recipes are refused, never relaxed."""
    if recipe.household_id != meal.household_id:
        raise PlanningError("La receta no pertenece a este hogar.")
    meal = meals_queryset(meal.household).get(pk=meal.pk)
    people = people_for_meal(meal)
    result = recipe_services.check_recipe(recipe, people)
    if result.status == compatibility.CONFLICT:
        alternatives = compatible_alternatives(meal.household, people, meal.meal_type, exclude_ids={recipe.pk})
        raise IncompatibleRecipe(result, alternatives)
    recipe_services.snapshot_into_meal(meal, recipe, servings_override=servings_override)
    if meal.mode not in MODES_WITH_RECIPES:
        Meal.objects.filter(pk=meal.pk).update(mode=MealMode.COOK)
    _touch(meal, user, lock=lock)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal, result


@transaction.atomic
def remove_recipe(meal_recipe, user):
    meal = meal_recipe.meal
    meal_recipe.delete()
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal


@transaction.atomic
def update_meal_recipe_servings(meal_recipe, user, servings_override):
    meal_recipe.servings_override = servings_override
    meal_recipe.save(update_fields=["servings_override"])
    _touch(meal_recipe.meal, user)
    _changed(meal_recipe.meal.household, meal_recipe.meal.date)


@transaction.atomic
def set_manual_quantity(line, user, quantity):
    line.manual_quantity = quantity
    line.save(update_fields=["manual_quantity"])
    meal = line.meal_recipe.meal
    _touch(meal, user)
    _changed(meal.household, meal.date)


@transaction.atomic
def substitute_ingredient(line, new_ingredient, user):
    """Swap one ingredient of the meal copy. The substitute is validated like any ingredient."""
    meal = meals_queryset(line.meal_recipe.meal.household).get(pk=line.meal_recipe.meal_id)
    people = people_for_meal(meal)
    original = line.substituted_for or line.ingredient
    result = evaluate([facts_for_ingredient(new_ingredient, optional=line.optional, substituted_for=original)], people)
    if result.status == compatibility.CONFLICT:
        raise IncompatibleRecipe(result)
    line.substituted_for = original if new_ingredient.pk != original.pk else None
    line.ingredient = new_ingredient
    line.save(update_fields=["ingredient", "substituted_for"])
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal, result


@transaction.atomic
def refresh_meal_recipe(meal_recipe, user):
    recipe_services.refresh_snapshot(meal_recipe)
    meal = meal_recipe.meal
    _touch(meal, user)
    meal = revalidate_meal(meal)
    _changed(meal.household, meal.date)
    return meal


@transaction.atomic
def move_or_copy(meal, user, target_date, target_type, copy=False, overwrite=False):
    """Move (or copy) a meal to another slot, keeping attendees, recipes and notes."""
    household = meal.household
    if target_type not in household.enabled_meal_types:
        raise PlanningError("Ese tipo de comida no está activo en el hogar.")
    if target_date == meal.date and target_type == meal.meal_type:
        raise PlanningError("El destino es la misma comida.")
    target = Meal.objects.select_for_update().filter(household=household, date=target_date, meal_type=target_type).first()
    if target is not None:
        if target.locked:
            raise PlanningError("La comida de destino está protegida. Desprotégela antes de sustituirla.")
        if not overwrite:
            raise PlanningError("Ya hay una comida en el destino. Marca «sustituir» para reemplazarla.")
        orphaned = list(target.leftover_meals.all())
        target.delete()
        for dependent in orphaned:
            revalidate_meal(dependent)

    source = meals_queryset(household).get(pk=meal.pk)
    new_meal = Meal.objects.create(
        household=household, date=target_date, meal_type=target_type, mode=source.mode, notes=source.notes,
        locked=True, source=Meal.Source.MANUAL, updated_by=user, leftovers_from=source.leftovers_from,
    )
    if not copy:
        # Leftovers planned from the moved meal keep pointing at it.
        Meal.objects.filter(leftovers_from=meal).update(leftovers_from=new_meal)
    for attendee in source.attendees.all():
        MealAttendee.objects.create(
            meal=new_meal, diner=attendee.diner, guest_name=attendee.guest_name,
            guest_traits=attendee.guest_traits, guest_notes=attendee.guest_notes, portion=attendee.portion,
        )
    for meal_recipe in source.recipes.all():
        copy_recipe = MealRecipe.objects.create(
            meal=new_meal, recipe=meal_recipe.recipe, recipe_version=meal_recipe.recipe_version,
            name=meal_recipe.name, base_servings=meal_recipe.base_servings,
            servings_override=meal_recipe.servings_override, prep_minutes=meal_recipe.prep_minutes,
            cook_minutes=meal_recipe.cook_minutes, steps=meal_recipe.steps, order=meal_recipe.order,
        )
        MealRecipeIngredient.objects.bulk_create(
            MealRecipeIngredient(
                meal_recipe=copy_recipe, ingredient=line.ingredient, quantity=line.quantity, unit=line.unit,
                note=line.note, optional=line.optional, substituted_for=line.substituted_for,
                manual_quantity=line.manual_quantity, order=line.order,
            )
            for line in meal_recipe.ingredients.all()
        )
    if not copy:
        meal.delete()
    new_meal = revalidate_meal(new_meal)
    _changed(household, target_date, None if copy else source.date)
    return new_meal


# --- Regeneration -------------------------------------------------------------------------


@dataclass
class RegenerationReport:
    created: int = 0
    updated: int = 0
    kept_locked: int = 0
    without_recipe: list = field(default_factory=list)


def _stable_rank(*parts):
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def choose_recipe(candidates, people, day, meal_type, usage, dislikes):
    """Deterministic choice among compatible recipes, favouring variety and preferences."""
    scored = []
    for recipe in candidates:
        result = recipe_services.check_recipe(recipe, people)
        if result.status != compatibility.OK:
            continue  # regeneration never auto-accepts unknown or conflicting recipes
        disliked = sum(1 for ri in recipe.ingredients.all() if ri.ingredient_id in dislikes)
        scored.append((usage[recipe.pk], disliked, _stable_rank(day, meal_type, recipe.pk), recipe))
    if not scored:
        return None
    scored.sort(key=lambda item: item[:3])
    return scored[0][3]


def regenerate_range(household, start, end, user):
    """Rebuild unlocked meals from rules and household recipes.

    Locked meals are never touched. Date exceptions and recurring rules decide mode and
    attendees. Recipes are only assigned when their compatibility is OK.
    """
    report = RegenerationReport()
    context = PlanningContext.load(household, start, end)
    existing = meals_by_slot(household, start - timedelta(days=7), end)
    candidates = list(recipe_services.recipes_for_household(household))
    usage = Counter()
    for meal in existing.values():
        for meal_recipe in meal.recipes.all():
            if meal_recipe.recipe_id:
                usage[meal_recipe.recipe_id] += 1

    for day in daterange(start, end):
        for meal_type in household.meal_types:
            meal = existing.get(slot_key(day, meal_type))
            if meal is not None and meal.locked:
                report.kept_locked += 1
                continue
            defaults = context.defaults(day, meal_type)
            people = [rules_for_diner(d) for d in defaults.diners]
            dislikes = {p.ingredient_id for d in defaults.diners for p in d.preferences.all() if p.kind == "dislike" and p.ingredient_id}
            recipe = None
            if defaults.mode == MealMode.COOK and defaults.diners:
                fitting = [r for r in candidates if recipe_services.fits_meal_type(r, meal_type)]
                recipe = choose_recipe(fitting, people, day, meal_type, usage, dislikes)
                if recipe is not None:
                    usage[recipe.pk] += 1
            with transaction.atomic():
                if meal is None:
                    meal = Meal.objects.create(household=household, date=day, meal_type=meal_type, updated_by=user)
                    report.created += 1
                else:
                    report.updated += 1
                meal.recipes.all().delete()
                meal.attendees.all().delete()
                MealAttendee.objects.bulk_create(
                    MealAttendee(meal=meal, diner=d, portion=d.portion_factor) for d in defaults.diners
                )
                mode = defaults.mode
                notes = defaults.notes
                if mode == MealMode.COOK and recipe is None:
                    mode = MealMode.PENDING
                    if defaults.diners:
                        notes = (notes + " " if notes else "") + "No hay recetas compatibles: elige una a mano."
                        report.without_recipe.append(slot_key(day, meal_type))
                Meal.objects.filter(pk=meal.pk).update(
                    mode=mode, notes=notes, source=Meal.Source.GENERATED, version=F("version") + 1,
                    updated_by=user, updated_at=timezone.now(), outcome=Meal.Outcome.PENDING, leftovers_from=None,
                )
                if recipe is not None:
                    recipe_services.snapshot_into_meal(meal, recipe)
                revalidate_meal(meal)
    _changed(household, *daterange(start, end))
    return report
