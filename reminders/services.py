"""Which reminders are due, and what they say.

Run every few minutes (`manage.py send_reminders --loop 300`). Each reminder is sent once a day,
within two hours after the chosen time, so a late plan never wakes anybody up at midnight.
Messages name recipes, never people.
"""

from datetime import timedelta

from django.urls import reverse
from django.utils import timezone

from core.choices import MEAL_TYPE_ORDER
from households.models import Membership
from planning.models import MealMode
from planning.services import meals_queryset
from shopping.services import expiring_between

from . import push
from .models import ReminderPreference

WINDOW_HOURS = 2


def _order(meal):
    return MEAL_TYPE_ORDER.index(meal.meal_type) if meal.meal_type in MEAL_TYPE_ORDER else 99


def _title(membership, text):
    several = Membership.objects.filter(user_id=membership.user_id).count() > 1
    return f"{text} · {membership.household.name}" if several else text


def tomorrow_message(membership, day):
    """What is planned for `day`, with what has to be prepared the day before. None if nothing."""
    meals = sorted(meals_queryset(membership.household).filter(date=day), key=_order)
    lines, preparations = [], []
    for meal in meals:
        names = [mr.name for mr in meal.recipes.all()]
        if names:
            lines.append(f"{meal.get_meal_type_display()}: {', '.join(names)}")
        elif meal.mode != MealMode.PENDING:
            lines.append(f"{meal.get_meal_type_display()}: {meal.get_mode_display().lower()}")
        for meal_recipe in meal.recipes.all():
            note = meal_recipe.recipe.advance_note if meal_recipe.recipe_id else ""
            if note:
                preparations.append(f"Hoy: {note} ({meal_recipe.name})")
    # What expires today or tomorrow, so it is used in time.
    batches = expiring_between(membership.household, day - timedelta(days=1), day)
    expiring = []
    for label, when in (("Caduca hoy", day - timedelta(days=1)), ("Caduca mañana", day)):
        names = sorted({b.ingredient.name for b in batches if b.expires_on == when})
        if names:
            expiring.append(f"{label}: {', '.join(names)}")
    if not lines and not expiring:
        return None
    return {
        "title": _title(membership, "Mañana en casa"),
        "body": "\n".join(preparations + expiring + lines),
        "url": reverse("planning:day", args=[day.isoformat()]),
        "tag": f"tomorrow-{membership.household_id}",
    }


def week_message(membership, today):
    """On Sundays, when fewer than half of next week's meals are decided. None otherwise."""
    household = membership.household
    start = today + timedelta(days=7 - today.weekday())
    slots = 7 * len(household.meal_types)
    decided = sum(
        1 for meal in meals_queryset(household).filter(date__gte=start, date__lte=start + timedelta(days=6))
        if meal.meal_type in household.meal_types and (meal.recipes.all() or meal.mode != MealMode.PENDING)
    )
    if not slots or decided * 2 >= slots:
        return None
    left = slots - decided
    return {
        "title": _title(membership, "La semana que viene"),
        "body": f"Quedan {left} comidas por decidir. Tócalo para organizarla.",
        "url": f"{reverse('planning:week')}?fecha={start.isoformat()}",
        "tag": f"week-{household.pk}",
    }


def send_due(now=None):
    """Send the reminders that are due now. Returns how many notifications were delivered."""
    now = timezone.localtime(now or timezone.now())
    today = now.date()
    delivered = 0
    preferences = (
        ReminderPreference.objects.select_related("membership__user", "membership__household")
        .filter(membership__user__is_active=True, membership__user__push_subscriptions__isnull=False)
        .distinct()
    )
    for preference in preferences:
        if not (preference.hour <= now.hour < preference.hour + WINDOW_HOURS):
            continue
        membership = preference.membership
        changed = []
        if preference.tomorrow and preference.last_tomorrow_on != today:
            message = tomorrow_message(membership, today + timedelta(days=1))
            if message:
                delivered += push.send_to_user(membership.user, message)
                preference.last_tomorrow_on = today
                changed.append("last_tomorrow_on")
        if preference.week and membership.can_edit and today.weekday() == 6 and preference.last_week_on != today:
            message = week_message(membership, today)
            if message:
                delivered += push.send_to_user(membership.user, message)
            preference.last_week_on = today  # checked for today, planned or not
            changed.append("last_week_on")
        if changed:
            preference.save(update_fields=changed)
    return delivered
