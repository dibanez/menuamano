from datetime import timedelta

from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from billing.plans import FREE, PREMIUM, get_plan, price_labels

from . import seo
from .legal import LEGAL_UPDATED, owner

LEGAL_PAGES = {
    "aviso-legal": ("legal/aviso_legal.html", "Aviso legal"),
    "privacidad": ("legal/privacidad.html", "Política de privacidad"),
    "cookies": ("legal/cookies.html", "Política de cookies"),
    "condiciones": ("legal/condiciones.html", "Condiciones de uso y contratación"),
}


def _same_site(request, url, default):
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return default


def csrf_failure(request, reason=""):
    """Friendly answer to a repeated or expired form (CSRF_FAILURE_VIEW).

    A login sent twice fails here because signing in rotates the token: that person is already in,
    so they land where they were going.
    """
    home_url = reverse("core:home")
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and request.path == reverse("accounts:login"):
        return redirect(_same_site(request, request.GET.get("next", ""), home_url))
    back = _same_site(request, request.META.get("HTTP_REFERER", ""), home_url)
    return render(request, "csrf_failure.html", {"back": back}, status=403)


def legal_index(request):
    context = {
        "pages": LEGAL_PAGES, "updated": LEGAL_UPDATED,
        "seo_title": "Información legal · menuamano",
        "seo_description": "Información legal de menuamano: aviso legal, privacidad, cookies y condiciones de uso.",
    }
    return render(request, "legal/index.html", context)


def legal_page(request, slug):
    if slug not in LEGAL_PAGES:
        raise Http404("Unknown legal page")
    template, title = LEGAL_PAGES[slug]
    context = {
        "title": title,
        "updated": LEGAL_UPDATED,
        "owner": owner(),
        "site": request.get_host(),
        "free": get_plan(FREE),
        "premium": get_plan(PREMIUM),
        "prices": price_labels(),
        "analytics_configured": bool(settings.GTM_CONTAINER_ID),
        "pages": LEGAL_PAGES,
        "seo_title": f"{title} · menuamano",
        "seo_description": f"{title} de menuamano, la aplicación para planificar las comidas de casa y la lista de la compra.",
    }
    return render(request, template, context)
from planning.calendar import calendar_days
from planning.models import Meal, SafetyStatus
from shopping.models import ShoppingList


def landing(request):
    context = {"free": get_plan(FREE), "premium": get_plan(PREMIUM), "prices": price_labels()}
    context.update(seo.landing_seo(request, **context))
    return render(request, "core/landing.html", context)


def home(request):
    """Public landing for visitors; today's meals for signed-in members."""
    if not request.user.is_authenticated:
        return landing(request)
    if request.membership is None:
        return redirect("households:onboarding")
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
