"""Minimal, pseudonymised household context for the assistant.

Diners are sent as codes (C1, C2…) with an age group, never with names, exact birth dates,
weight history or free-text notes. Recipes carry precomputed compatibility per code so the
model can avoid blocked options, but the server re-checks everything afterwards.
"""

from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count
from django.utils import timezone

from core.choices import MealType, Weekday
from foods import compatibility
from foods.compatibility import rules_for_diner
from foods.models import Ingredient, Trait, Unit
from planning.services import PlanningContext, daterange, diners_queryset, meals_by_slot, slot_key
from recipes import services as recipe_services

MAX_RECIPES = 80
TRAIT_LABELS = dict(Trait.choices)
WEEKDAY_LABELS = dict(Weekday.choices)


@dataclass
class AssistantContext:
    data: dict
    code_to_diner: dict
    diner_to_code: dict

    def diner_for_code(self, code):
        return self.code_to_diner.get(code)


def build_context(household, start, end, operation, user_request="", focus=None):
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
                }
            else:
                slot = {
                    "exists": False, "mode": defaults.mode if defaults.mode_is_explicit else "pending", "locked": False,
                    "recipe_ids": [], "recipe_names": [],
                    "attendee_codes": [diner_to_code[d.pk] for d in defaults.diners], "guests": 0,
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
            slots.append(slot)

    recipes = (
        recipe_services.recipes_for_household(household)
        .annotate(uses=Count("meal_uses"))
        .order_by("-uses", "name")[:MAX_RECIPES]
    )
    person_rules = {code: rules_for_diner(d) for code, d in code_to_diner.items()}
    recipe_rows = []
    for recipe in recipes:
        facts = recipe_services.recipe_facts(recipe)
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

    recent_start = start - timedelta(days=7)
    recent = meals_by_slot(household, recent_start, start - timedelta(days=1))
    recent_ids = sorted({mr.recipe_id for m in recent.values() for mr in m.recipes.all() if mr.recipe_id})

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
        "known_ingredients": list(
            Ingredient.objects.for_household(household).order_by("name").values_list("name", flat=True)
        ),
        "units": [u.value for u in Unit],
        "user_request": user_request[:1000],
    }
    return AssistantContext(data=data, code_to_diner=code_to_diner, diner_to_code=diner_to_code)
