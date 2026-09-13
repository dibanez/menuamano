"""Minimal, pseudonymised household context for the assistant.

Diners are sent as codes (C1, C2…) with an age group, never with names, exact birth dates,
weight history or free-text notes. Recipes carry precomputed compatibility per code so the
model can avoid blocked options, but the server re-checks everything afterwards.
"""

import re
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from core.choices import MealType, Weekday
from foods import compatibility
from foods.compatibility import rules_for_diner
from foods.models import Ingredient, Trait, Unit
from foods.reviews import reviews_for
from planning.services import PlanningContext, daterange, diners_queryset, meals_by_slot, slot_key
from recipes import services as recipe_services

MAX_RECIPES = 80
MAX_HISTORY = 6
# How far before and after the range planned recipes count as a repeat.
REPEAT_WINDOW_DAYS = 14
TRAIT_LABELS = dict(Trait.choices)
WEEKDAY_LABELS = dict(Weekday.choices)
CODE_RE = re.compile(r"\bC\d+\b")


def pseudonymize(text, code_to_diner):
    """Replace diner names typed by people with their codes before anything leaves the server."""
    for code, diner in sorted(code_to_diner.items(), key=lambda item: -len(item[1].alias)):
        alias = diner.alias.strip()
        if alias:
            text = re.sub(rf"(?<!\w){re.escape(alias)}(?!\w)", code, text, flags=re.IGNORECASE)
    return text


def depseudonymize(text, code_to_diner):
    """Show codes returned by the provider as the diners' names."""
    return CODE_RE.sub(lambda m: code_to_diner[m.group(0)].alias if m.group(0) in code_to_diner else m.group(0), text)


@dataclass
class AssistantContext:
    data: dict
    code_to_diner: dict
    diner_to_code: dict

    def diner_for_code(self, code):
        return self.code_to_diner.get(code)

    def humanize(self, text):
        return depseudonymize(text or "", self.code_to_diner)


def build_context(household, start, end, operation, user_request="", focus=None, history=()):
    today = timezone.localdate()
    diners = list(diners_queryset(household))
    code_to_diner = {f"C{i + 1}": d for i, d in enumerate(diners)}
    diner_to_code = {d.pk: code for code, d in code_to_diner.items()}

    people = []
    for code, diner in code_to_diner.items():
        rules = rules_for_diner(diner)
        people.append(
            {
                "code": code,
                "age_group": diner.age_group,
                "portion": float(diner.portion_factor),
                "restrictions": sorted(TRAIT_LABELS.get(t, t) for t in rules.traits),
                "avoid_ingredients": sorted(rules.ingredient_names),
                "dislikes": sorted(
                    p.ingredient.name if p.ingredient_id else p.text for p in diner.preferences.all() if p.kind == "dislike"
                ),
                "likes": sorted(
                    p.ingredient.name if p.ingredient_id else p.text for p in diner.preferences.all() if p.kind == "like"
                ),
            }
        )

    planning = PlanningContext.load(household, start, end)
    meals = meals_by_slot(household, start, end)
    slots = []
    for day in daterange(start, end):
        for meal_type in household.meal_types:
            meal = meals.get(slot_key(day, meal_type))
            defaults = planning.defaults(day, meal_type)
            if meal is not None:
                attendees = [diner_to_code[a.diner_id] for a in meal.attendees.all() if a.diner_id in diner_to_code]
                guests = len([a for a in meal.attendees.all() if not a.diner_id])
                slot = {
                    "exists": True, "mode": meal.mode, "locked": meal.locked,
                    "recipe_ids": [mr.recipe_id for mr in meal.recipes.all() if mr.recipe_id],
                    "recipe_names": [mr.name for mr in meal.recipes.all()],
                    "attendee_codes": attendees, "guests": guests,
                    "plates": [
                        {
                            "recipe_id": mr.recipe_id, "recipe_name": mr.name,
                            "eater_codes": [diner_to_code[a.diner_id] for a in mr.eaters.all() if a.diner_id in diner_to_code],
                        }
                        for mr in meal.recipes.all() if mr.eaters.all()
                    ],
                }
            else:
                slot = {
                    "exists": False, "mode": defaults.mode if defaults.mode_is_explicit else "pending", "locked": False,
                    "recipe_ids": [], "recipe_names": [],
                    "attendee_codes": [diner_to_code[d.pk] for d in defaults.diners], "guests": 0, "plates": [],
                }
            slot.update(
                {
                    "date": day.isoformat(),
                    "weekday": WEEKDAY_LABELS[day.weekday()],
                    "meal_type": meal_type,
                    "rule": defaults.mode if defaults.mode_is_explicit else None,
                    "rule_source": defaults.source,
                }
            )
            if focus and (day, meal_type) == (focus[0], focus[1]):
                # The person asked about this very meal: its lock only guards against regenerations.
                slot["locked"] = False
            slots.append(slot)

    recipes = (
        recipe_services.recipes_for_household(household)
        .annotate(uses=Count("meal_uses"))
        .order_by("-uses", "name")[:MAX_RECIPES]
    )
    person_rules = {code: rules_for_diner(d) for code, d in code_to_diner.items()}
    reviews = reviews_for(household)
    recipe_rows = []
    for recipe in recipes:
        facts = recipe_services.recipe_facts(recipe, reviews)
        blocked, review = [], []
        for code, rules in person_rules.items():
            status = compatibility.evaluate(facts, [rules]).status
            if status == compatibility.CONFLICT:
                blocked.append(code)
            elif status == compatibility.UNKNOWN:
                review.append(code)
        recipe_rows.append(
            {
                "id": recipe.pk,
                "name": recipe.name,
                "tags": recipe.tags,
                "minutes": recipe.total_minutes,
                "difficulty": recipe.difficulty,
                "ingredients": [ri.ingredient.name for ri in recipe.ingredients.all()],
                "blocked_for": blocked,
                "review_for": review,
            }
        )

    # Recipes already in the calendar just before and after the range: the model avoids repeating them.
    recent = meals_by_slot(household, start - timedelta(days=REPEAT_WINDOW_DAYS), start - timedelta(days=1))
    recent_ids = sorted({mr.recipe_id for m in recent.values() for mr in m.recipes.all() if mr.recipe_id})
    upcoming = meals_by_slot(household, end + timedelta(days=1), end + timedelta(days=REPEAT_WINDOW_DAYS))
    upcoming_ids = sorted({mr.recipe_id for m in upcoming.values() for mr in m.recipes.all() if mr.recipe_id})

    data = {
        "today": today.isoformat(),
        "operation": operation,
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "focus_slot": {"date": focus[0].isoformat(), "meal_type": focus[1]} if focus else None,
        "enabled_meal_types": {mt: MealType(mt).label for mt in household.meal_types},
        "people": people,
        "slots": slots,
        "recipes": recipe_rows,
        "recent_recipe_ids": recent_ids,
        "upcoming_recipe_ids": upcoming_ids,
        "known_ingredients": list(
            Ingredient.objects.for_household(household).order_by("name").values_list("name", flat=True)
        ),
        "units": [u.value for u in Unit],
        "conversation": [
            {"role": role, "text": pseudonymize(text, code_to_diner)[:500]} for role, text in list(history)[-MAX_HISTORY:]
        ],
        "user_request": pseudonymize(user_request, code_to_diner)[:1000],
    }
    return AssistantContext(data=data, code_to_diner=code_to_diner, diner_to_code=diner_to_code)
