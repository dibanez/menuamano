from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from households.permissions import household_required
from planning.calendar import calendar_days
from planning.models import Meal, SafetyStatus
from shopping.models import ShoppingList


@household_required()
def home(request):
    household = request.household
    today = timezone.localdate()
    tomorrow = today + timedelta(days=1)
    alerts = Meal.objects.filter(
        household=household, date__gte=today, date__lte=today + timedelta(days=7),
        safety_status__in=[SafetyStatus.CONFLICT, SafetyStatus.UNKNOWN],
    ).order_by("date", "meal_type")
    shopping_list = (
        ShoppingList.objects.filter(household=household, start_date__lte=today, end_date__gte=today).first()
        or ShoppingList.objects.filter(household=household, end_date__gte=today).order_by("start_date").first()
    )
    pending = 0
    if shopping_list:
        pending = sum(1 for item in shopping_list.items.all() if not item.is_done and item.needed_quantity > 0)
    days = calendar_days(household, today, tomorrow)
    context = {
        "today": today,
        "day": days[0],
        "tomorrow": days[1],
        "alerts": alerts,
        "shopping_list": shopping_list,
        "pending": pending,
        "diner_count": household.diners.filter(is_active=True).count(),
        "recipe_count": household.recipes.filter(is_archived=False).count(),
    }
    return render(request, "core/home.html", context)
