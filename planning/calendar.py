"""Read models for calendar screens: existing meals plus previews of unplanned slots."""

from django.utils import timezone

from core.choices import MealType

from .services import PlanningContext, daterange, meals_by_slot, slot_key


def calendar_days(household, start, end):
    today = timezone.localdate()
    meals = meals_by_slot(household, start, end)
    context = PlanningContext.load(household, start, end)
    days = []
    for day in daterange(start, end):
        slots = []
        for meal_type in household.meal_types:
            meal = meals.get(slot_key(day, meal_type))
            slots.append(
                {
                    "date": day,
                    "meal_type": meal_type,
                    "label": MealType(meal_type).label,
                    "meal": meal,
                    "defaults": None if meal else context.defaults(day, meal_type),
                }
            )
        days.append({"date": day, "slots": slots, "is_today": day == today, "is_past": day < today})
    return days
