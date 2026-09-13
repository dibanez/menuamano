"""The household's planned meals as an iCalendar feed (RFC 5545), for calendar apps.

Each meal is an event at a customary time for its meal type. Events carry the recipes and how
many people eat, never who: the link may end up in a third-party calendar.
"""

from datetime import datetime, time, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from core.choices import MealType

from .models import MealMode
from .services import meals_queryset

PAST_DAYS = 14
FUTURE_DAYS = 60
# Customary start and length (minutes) of each meal in Spain.
MEAL_TIMES = {
    MealType.BREAKFAST: (time(8, 0), 30),
    MealType.LUNCH: (time(14, 0), 60),
    MealType.SNACK: (time(17, 30), 30),
    MealType.DINNER: (time(21, 0), 60),
}


def escape(text):
    """Escape a TEXT value: backslash, semicolon, comma and line breaks."""
    return (
        str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
        .replace("\r\n", "\\n").replace("\n", "\\n")
    )


def fold(line):
    """Split a content line into chunks of at most 75 octets, never inside a character."""
    chunks, current, size = [], "", 0
    for char in line:
        width = len(char.encode())
        limit = 75 if not chunks else 74  # continuation lines start with a space
        if size + width > limit:
            chunks.append(current)
            current, size = "", 0
        current += char
        size += width
    chunks.append(current)
    return "\r\n ".join(chunks)


def _utc(value):
    return value.astimezone(dt_timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _summary(meal):
    names = [mr.name for mr in meal.recipes.all()]
    if names:
        return f"{meal.get_meal_type_display()}: {', '.join(names)}"
    return f"{meal.get_meal_type_display()}: {meal.get_mode_display()}"


def _description(meal):
    lines = [mr.name for mr in meal.recipes.all()]
    people = len(meal.attendees.all())
    if people:
        lines.append(f"Para {people} {'persona' if people == 1 else 'personas'}.")
    if meal.mode != MealMode.COOK:
        lines.append(meal.get_mode_display() + ".")
    return "\n".join(lines)


def calendar(household, base_url, today=None):
    today = today or timezone.localdate()
    zone = ZoneInfo(settings.TIME_ZONE)
    stamp = _utc(timezone.now())
    meals = meals_queryset(household).filter(
        date__gte=today - timedelta(days=PAST_DAYS), date__lte=today + timedelta(days=FUTURE_DAYS)
    ).order_by("date", "meal_type")
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//menuamano//menu//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(f'Menú de {household.name}')}",
        f"X-WR-TIMEZONE:{settings.TIME_ZONE}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT4H",
        "X-PUBLISHED-TTL:PT4H",
    ]
    for meal in meals:
        if meal.mode == MealMode.PENDING and not meal.recipes.all():
            continue  # nothing decided yet
        start_time, minutes = MEAL_TIMES.get(meal.meal_type, (time(13, 0), 60))
        start = datetime.combine(meal.date, start_time, tzinfo=zone)
        lines += [
            "BEGIN:VEVENT",
            f"UID:meal-{meal.pk}@menuamano",
            f"DTSTAMP:{stamp}",
            f"LAST-MODIFIED:{_utc(meal.updated_at)}",
            f"DTSTART:{_utc(start)}",
            f"DTEND:{_utc(start + timedelta(minutes=minutes))}",
            f"SUMMARY:{escape(_summary(meal))}",
            f"DESCRIPTION:{escape(_description(meal))}",
            f"URL:{base_url}{reverse('planning:meal', args=[meal.pk])}",
            "TRANSP:TRANSPARENT",  # meals never make people look busy
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)
