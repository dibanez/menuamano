import calendar as pycalendar
import secrets
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.choices import MealType
from core.seo import site_url
from foods.compatibility import LABEL_REMINDER
from foods.models import Ingredient, Trait
from foods.reviews import reviews_for
from foods.units import scale
from households.models import Membership, Role
from households.permissions import household_required
from recipes import services as recipe_services
from recipes.models import Recipe

from . import feeds, services
from .calendar import calendar_days
from .forms import ExceptionForm, MealDetailsForm, MoveForm, RangeForm, RuleForm
from .models import (
    MODES_WITH_RECIPES,
    CalendarFeed,
    DateException,
    Meal,
    MealAttendee,
    MealRecipe,
    MealRecipeIngredient,
    RecurringRule,
    SafetyStatus,
)

MONTH_NAMES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
    "noviembre", "diciembre",
]


def _parse_date(value, default=None):
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise Http404("Invalid date")


def _meal(request, pk):
    return get_object_or_404(Meal, pk=pk, household=request.household)


def _check_meal_type(household, meal_type):
    if meal_type not in household.enabled_meal_types:
        raise Http404("Meal type not enabled")


def _decimal(value):
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None
    return number if number >= 0 else None


# --- Calendar views ---------------------------------------------------------------------------


def _has_calendar_feed(request):
    """The day, week and month views offer adding the menu to calendar apps until it is added."""
    return CalendarFeed.objects.filter(user=request.user, household=request.household).exists()


@household_required()
def week(request):
    anchor = _parse_date(request.GET.get("fecha"), timezone.localdate())
    start = anchor - timedelta(days=anchor.weekday())
    end = start + timedelta(days=6)
    context = {
        "days": calendar_days(request.household, start, end),
        "start": start,
        "end": end,
        "prev": start - timedelta(days=7),
        "next": start + timedelta(days=7),
        "view": "week",
        "nav_day": anchor,
        "range_form": RangeForm(initial={"start": start, "end": end}),
        "has_calendar_feed": _has_calendar_feed(request),
    }
    return render(request, "planning/week.html", context)


@household_required()
def day(request, day):
    the_day = _parse_date(day)
    context = {
        "day": calendar_days(request.household, the_day, the_day)[0],
        "the_day": the_day,
        "prev": the_day - timedelta(days=1),
        "next": the_day + timedelta(days=1),
        "view": "day",
        "nav_day": the_day,
        "has_calendar_feed": _has_calendar_feed(request),
    }
    return render(request, "planning/day.html", context)


@household_required()
def month(request):
    anchor = _parse_date(request.GET.get("fecha"), timezone.localdate())
    weeks = pycalendar.Calendar(firstweekday=0).monthdatescalendar(anchor.year, anchor.month)
    start, end = weeks[0][0], weeks[-1][-1]
    by_date = {d["date"]: d for d in calendar_days(request.household, start, end)}
    first = anchor.replace(day=1)
    context = {
        "weeks": [[by_date[d] for d in week_days] for week_days in weeks],
        "month": anchor.month,
        "title": f"{MONTH_NAMES[anchor.month]} de {anchor.year}",
        "prev": (first - timedelta(days=1)).replace(day=1),
        "next": (first + timedelta(days=32)).replace(day=1),
        "view": "month",
        "nav_day": anchor,
        "dows": ["L", "M", "X", "J", "V", "S", "D"],
        "today": timezone.localdate(),
        "has_calendar_feed": _has_calendar_feed(request),
    }
    return render(request, "planning/month.html", context)


@household_required()
def slot(request, day, meal_type):
    the_day = _parse_date(day)
    _check_meal_type(request.household, meal_type)
    meal = Meal.objects.filter(household=request.household, date=the_day, meal_type=meal_type).first()
    if meal is not None:
        return redirect("planning:meal", meal.pk)
    if request.method == "POST":
        if not request.membership.can_edit:
            raise Http404
        meal, _ = services.get_or_create_meal(request.household, the_day, meal_type, user=request.user)
        return redirect("planning:meal", meal.pk)
    context = services.PlanningContext.load(request.household, the_day, the_day)
    defaults = context.defaults(the_day, meal_type)
    return render(
        request, "planning/empty_slot.html",
        {"the_day": the_day, "meal_type": meal_type, "label": MealType(meal_type).label, "defaults": defaults},
    )


# --- Calendar apps (iCalendar feed) -------------------------------------------------------------


@require_GET
def calendar_feed(request, token):
    """Fetched by calendar apps without a session: the token is the key."""
    feed = CalendarFeed.objects.select_related("household", "user").filter(token=token).first()
    if feed is None or not feed.user.is_active or not Membership.objects.filter(
        user=feed.user, household=feed.household
    ).exists():
        raise Http404("Unknown calendar link")
    CalendarFeed.objects.filter(pk=feed.pk).update(last_fetched_at=timezone.now())
    response = HttpResponse(feeds.calendar(feed.household, site_url(request)), content_type="text/calendar; charset=utf-8")
    response["Content-Disposition"] = 'inline; filename="menuamano.ics"'
    response["Cache-Control"] = "private, max-age=900"
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response


@household_required()
def calendar_subscribe(request):
    feed = CalendarFeed.objects.filter(user=request.user, household=request.household).first()
    if request.method == "POST":
        token = secrets.token_urlsafe(32)
        if feed is None:
            CalendarFeed.objects.create(user=request.user, household=request.household, token=token)
            messages.success(request, "Enlace creado. Añádelo a tu calendario.")
        else:
            feed.token = token
            feed.save(update_fields=["token"])
            messages.success(request, "Enlace nuevo creado. El anterior ya no funciona: añade este a tu calendario.")
        return redirect("planning:subscribe")
    context = {"feed": feed, "meal_times": [(MealType(mt).label, start) for mt, (start, _) in feeds.MEAL_TIMES.items()]}
    if feed is not None:
        https_url = site_url(request) + reverse("planning:feed", args=[feed.token])
        webcal_url = "webcal://" + https_url.split("://", 1)[1]
        context.update({
            "https_url": https_url, "webcal_url": webcal_url,
            "google_url": "https://calendar.google.com/calendar/render?cid=" + quote(webcal_url, safe=""),
        })
    return render(request, "planning/subscribe.html", context)


@household_required()
@require_POST
def calendar_unsubscribe(request):
    CalendarFeed.objects.filter(user=request.user, household=request.household).delete()
    messages.success(request, "El enlace del calendario ya no funciona. El menú deja de verse en tu calendario.")
    return redirect("planning:subscribe")


# --- Meal detail --------------------------------------------------------------------------------


@household_required()
def meal_detail(request, pk):
    household = request.household
    meal = get_object_or_404(services.meals_queryset(household), pk=pk)
    if any(i.get("ingredient") and "ingredient_id" not in i for i in meal.safety_issues):
        # Checked before issues pointed at their ingredient: refresh so the review link can be shown.
        services.revalidate_meal(meal)
        meal = services.meals_queryset(household).get(pk=pk)
    attendees = list(meal.attendees.all())
    by_diner = {a.diner_id: a for a in attendees if a.diner_id}
    diners = [
        {"diner": d, "attendee": by_diner.get(d.pk)} for d in services.diners_queryset(household)
    ]
    servings = services.planned_servings(meal)
    blocks = []
    for meal_recipe in meal.recipes.all():
        effective = meal_recipe.effective_servings(servings)
        lines = [
            {"line": line, "scaled": scale(line.quantity, meal_recipe.base_servings, effective)}
            for line in meal_recipe.ingredients.all()
        ]
        eaters = list(meal_recipe.eaters.all())
        blocks.append({
            "mr": meal_recipe, "servings": effective, "lines": lines,
            "eaters": eaters, "eater_ids": {a.pk for a in eaters},
        })

    people = services.people_for_meal(meal)
    reviews = reviews_for(household)
    options = {"ok": [], "unknown": [], "conflict": []}
    for recipe in recipe_services.recipes_for_household(household):
        status = recipe_services.check_recipe(recipe, people, reviews).status
        options[status].append(recipe)
    alternatives = []
    if meal.safety_status == SafetyStatus.CONFLICT:
        current = {mr.recipe_id for mr in meal.recipes.all()}
        alternatives = services.compatible_alternatives(
            household, people, meal.meal_type, exclude_ids=current, reviews=reviews
        )

    context = {
        "meal": meal,
        "diners": diners,
        "attendees": attendees,
        "guests": [a for a in attendees if not a.diner_id],
        "servings": servings,
        "blocks": blocks,
        "options": options,
        "alternatives": alternatives,
        "details_form": MealDetailsForm(instance=meal),
        "move_form": MoveForm(household=household, initial={"target_date": meal.date, "target_type": meal.meal_type}),
        "ingredients": Ingredient.objects.for_household(household).order_by("name"),
        "traits": Trait.choices,
        "label_reminder": LABEL_REMINDER,
        "shows_recipes": meal.mode in MODES_WITH_RECIPES,
        "attendee_servings": meal.servings,
        "leftovers_extra": servings - meal.servings,
        "dependents": [d for d in meal.leftover_meals.all() if d.mode == "leftovers"],
        "leftovers_source": meal.leftovers_from if meal.mode == "leftovers" else None,
        "leftovers_candidates": services.leftovers_candidates(meal) if meal.mode == "leftovers" and not meal.leftovers_from_id else [],
        "leftovers_days": services.LEFTOVERS_MAX_DAYS,
        "conflicts": [i for i in meal.safety_issues if i.get("level") == "conflict"],
        "unknowns": [i for i in meal.safety_issues if i.get("level") == "unknown"],
        "warnings": [i for i in meal.safety_issues if i.get("level") == "warning"],
    }
    return render(request, "planning/meal_detail.html", context)


@household_required(Role.EDITOR)
@require_POST
def meal_update(request, pk):
    meal = _meal(request, pk)
    form = MealDetailsForm(request.POST, instance=Meal.objects.get(pk=meal.pk))
    if form.is_valid():
        data = form.cleaned_data
        services.update_meal_details(
            meal, request.user, mode=data["mode"], notes=data["notes"], locked=meal.locked,  # the lock button decides
            outcome=data["outcome"], outcome_notes=data["outcome_notes"],
        )
        messages.success(request, "Comida guardada.")
    else:
        messages.error(request, "Revisa los datos de la comida.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_leftovers(request, pk):
    meal = _meal(request, pk)
    source = get_object_or_404(Meal, pk=request.POST.get("source") or 0, household=request.household)
    try:
        services.set_leftovers_source(meal, source, request.user)
    except services.IncompatibleRecipe as exc:
        messages.error(request, "No se pueden usar esas sobras. " + " ".join(i.message for i in exc.result.conflicts[:3]))
    except services.PlanningError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Sobras enlazadas. La comida de origen cocinará esas raciones de más y la compra se ha actualizado.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_leftovers_clear(request, pk):
    meal = _meal(request, pk)
    services.clear_leftovers_source(meal, request.user)
    messages.success(request, "Enlace de sobras quitado.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_lock(request, pk):
    meal = _meal(request, pk)
    meal = services.set_locked(meal, request.user, not meal.locked)
    messages.success(request, "Comida protegida frente a regeneraciones." if meal.locked else "Comida desprotegida.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_attendees(request, pk):
    meal = _meal(request, pk)
    ids = {int(v) for v in request.POST.getlist("diners") if v.isdigit()}
    diners = list(services.diners_queryset(request.household).filter(pk__in=ids))
    portions = {}
    for diner in diners:
        value = _decimal(request.POST.get(f"portion-{diner.pk}"))
        if value is not None and value > 0:
            portions[diner.pk] = value
    guest_portions = {}
    for key, raw in request.POST.items():
        attendee_id = key.removeprefix("guest-portion-")
        if attendee_id != key and attendee_id.isdigit():
            value = _decimal(raw)
            if value is not None and 0 < value < 100:
                guest_portions[int(attendee_id)] = value
    meal = services.set_attendees(meal, request.user, diners, portions, guest_portions=guest_portions)
    _report_safety(request, meal)
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_add_guest(request, pk):
    meal = _meal(request, pk)
    name = request.POST.get("guest_name", "").strip()[:60]
    if not name:
        messages.error(request, "Escribe el nombre del invitado.")
        return redirect("planning:meal", meal.pk)
    traits = [t for t in request.POST.getlist("guest_traits") if t in Trait.values]
    portion = _decimal(request.POST.get("guest_portion")) or Decimal("1")
    meal = services.add_guest(meal, request.user, name, traits, request.POST.get("guest_notes", "")[:120], portion)
    _report_safety(request, meal)
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_remove_attendee(request, pk, aid):
    meal = _meal(request, pk)
    get_object_or_404(MealAttendee, pk=aid, meal=meal)
    services.remove_attendee(meal, request.user, aid)
    return redirect("planning:meal", meal.pk)


def _report_safety(request, meal):
    if meal.safety_status == SafetyStatus.CONFLICT:
        messages.error(request, "Atención: la comida ya no es compatible con todos los asistentes. Revisa las recetas.")
    elif meal.safety_status == SafetyStatus.UNKNOWN:
        messages.warning(request, "Hay ingredientes sin información suficiente para algún asistente. Revísalos.")


def _add_recipe(request, meal, recipe, eaters=()):
    try:
        meal, result = services.add_recipe(meal, recipe, request.user, eaters=eaters)
    except services.IncompatibleRecipe as exc:
        names = ", ".join(r.name for r in exc.alternatives[:3])
        detail = " ".join(i.message for i in exc.result.conflicts[:3])
        suggestion = f" Alternativas compatibles: {names}." if names else ""
        messages.error(request, f"No se ha añadido «{recipe.name}». {detail}{suggestion}")
        return False
    except services.PlanningError as exc:
        messages.error(request, str(exc))
        return False
    if result.status == "unknown":
        messages.warning(request, f"«{recipe.name}» añadida, pero requiere revisión: falta información de algún ingrediente.")
    else:
        messages.success(request, f"«{recipe.name}» añadida.")
    return True


@household_required(Role.EDITOR)
@require_POST
def meal_add_recipe(request, pk):
    meal = _meal(request, pk)
    recipe = get_object_or_404(Recipe, pk=request.POST.get("recipe") or 0, household=request.household)
    _add_recipe(request, meal, recipe, eaters=request.POST.getlist("eaters"))
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def add_recipe_to_slot(request):
    recipe = get_object_or_404(Recipe, pk=request.POST.get("recipe") or 0, household=request.household)
    the_day = _parse_date(request.POST.get("date"))
    meal_type = request.POST.get("meal_type")
    if the_day is None:
        raise Http404
    _check_meal_type(request.household, meal_type)
    meal, created = services.get_or_create_meal(request.household, the_day, meal_type, user=request.user)
    if not _add_recipe(request, meal, recipe) and created and not meal.recipes.exists():
        return redirect("recipes:detail", recipe.pk)
    return redirect("planning:meal", meal.pk)


def _meal_recipe(request, pk, mrid):
    meal = _meal(request, pk)
    return meal, get_object_or_404(MealRecipe, pk=mrid, meal=meal)


@household_required(Role.EDITOR)
@require_POST
def meal_remove_recipe(request, pk, mrid):
    meal, meal_recipe = _meal_recipe(request, pk, mrid)
    services.remove_recipe(meal_recipe, request.user)
    messages.success(request, "Receta quitada de la comida.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_recipe_servings(request, pk, mrid):
    meal, meal_recipe = _meal_recipe(request, pk, mrid)
    value = _decimal(request.POST.get("servings"))
    services.update_meal_recipe_servings(meal_recipe, request.user, value if value and value > 0 else None)
    messages.success(request, "Raciones actualizadas.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_recipe_eaters(request, pk, mrid):
    meal, meal_recipe = _meal_recipe(request, pk, mrid)
    try:
        meal = services.set_recipe_eaters(meal_recipe, request.user, request.POST.getlist("eaters"))
    except services.IncompatibleRecipe as exc:
        detail = " ".join(i.message for i in exc.result.conflicts[:3])
        messages.error(request, f"No se ha cambiado para quién es «{meal_recipe.name}». {detail}")
        return redirect("planning:meal", meal.pk)
    messages.success(request, f"Guardado para quién es «{meal_recipe.name}».")
    _report_safety(request, meal)
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_recipe_refresh(request, pk, mrid):
    meal, meal_recipe = _meal_recipe(request, pk, mrid)
    meal = services.refresh_meal_recipe(meal_recipe, request.user)
    messages.success(request, "Receta actualizada a la última versión.")
    _report_safety(request, meal)
    return redirect("planning:meal", meal.pk)


def _line(request, pk, lid):
    meal = _meal(request, pk)
    return meal, get_object_or_404(MealRecipeIngredient, pk=lid, meal_recipe__meal=meal)


@household_required(Role.EDITOR)
@require_POST
def line_quantity(request, pk, lid):
    meal, line = _line(request, pk, lid)
    services.set_manual_quantity(line, request.user, _decimal(request.POST.get("manual_quantity")))
    messages.success(request, "Cantidad corregida.")
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def line_substitute(request, pk, lid):
    meal, line = _line(request, pk, lid)
    ingredient = get_object_or_404(
        Ingredient.objects.for_household(request.household), pk=request.POST.get("ingredient") or 0
    )
    try:
        meal, result = services.substitute_ingredient(line, ingredient, request.user)
    except services.IncompatibleRecipe as exc:
        messages.error(request, "Sustitución rechazada. " + " ".join(i.message for i in exc.result.conflicts))
        return redirect("planning:meal", meal.pk)
    messages.success(request, f"Sustituido por {ingredient.name}.")
    _report_safety(request, meal)
    return redirect("planning:meal", meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_move(request, pk):
    meal = _meal(request, pk)
    form = MoveForm(request.POST, household=request.household)
    if not form.is_valid():
        messages.error(request, "Revisa el día y la comida de destino.")
        return redirect("planning:meal", meal.pk)
    data = form.cleaned_data
    try:
        new_meal = services.move_or_copy(
            meal, request.user, data["target_date"], data["target_type"], copy=data["action"] == "copy",
            overwrite=data["overwrite"],
        )
    except services.PlanningError as exc:
        messages.error(request, str(exc))
        return redirect("planning:meal", meal.pk)
    messages.success(request, "Comida copiada." if data["action"] == "copy" else "Comida movida.")
    _report_safety(request, new_meal)
    return redirect("planning:meal", new_meal.pk)


@household_required(Role.EDITOR)
@require_POST
def meal_delete(request, pk):
    meal = _meal(request, pk)
    day_, household = meal.date, meal.household
    source_day = meal.leftovers_from.date if meal.leftovers_from_id else None
    orphaned = list(meal.leftover_meals.all())
    meal.delete()
    for dependent in orphaned:
        services.revalidate_meal(dependent)
    services.meals_changed.send(sender=Meal, household=household, dates=[d for d in (day_, source_day) if d])
    messages.success(request, "Comida vaciada.")
    return redirect(_week_url(day_))


def _week_url(day_):
    return f"{reverse('planning:week')}?fecha={day_.isoformat()}"


@household_required(Role.EDITOR)
@require_POST
def regenerate(request):
    form = RangeForm(request.POST)
    if not form.is_valid():
        for error in form.non_field_errors() or ["Fechas no válidas."]:
            messages.error(request, error)
        return redirect("planning:week")
    start, end = form.cleaned_data["start"], form.cleaned_data["end"]
    report = services.regenerate_range(request.household, start, end, request.user)
    text = (
        f"Plan regenerado: {report.created} comidas nuevas, {report.updated} actualizadas y "
        f"{report.kept_locked} protegidas sin tocar."
    )
    messages.success(request, text)
    if report.without_recipe:
        messages.warning(
            request,
            f"{len(report.without_recipe)} comidas quedaron pendientes porque no hay recetas compatibles con todos los asistentes.",
        )
    return redirect(_week_url(start))


# --- Recurring rules and exceptions -------------------------------------------------------------


@household_required()
def rules(request):
    household = request.household
    context = {
        "rules": RecurringRule.objects.filter(household=household),
        "exceptions": DateException.objects.filter(household=household, date__gte=timezone.localdate() - timedelta(days=30))
        .prefetch_related("attendees"),
        "rule_form": RuleForm(household=household, prefix="rule"),
        "exception_form": ExceptionForm(household=household, prefix="exc", initial={"date": timezone.localdate()}),
    }
    return render(request, "planning/rules.html", context)


@household_required(Role.EDITOR)
@require_POST
def rule_add(request):
    form = RuleForm(request.POST, household=request.household, prefix="rule")
    if form.is_valid():
        rule = form.save(commit=False)
        rule.household = request.household
        rule.save()
        messages.success(request, "Regla guardada. Se aplicará al crear o regenerar comidas.")
    else:
        messages.error(request, "Revisa los datos de la regla.")
    return redirect("planning:rules")


@household_required(Role.EDITOR)
@require_POST
def rule_delete(request, pk):
    get_object_or_404(RecurringRule, pk=pk, household=request.household).delete()
    messages.success(request, "Regla eliminada.")
    return redirect("planning:rules")


@household_required(Role.EDITOR)
@require_POST
def exception_add(request):
    form = ExceptionForm(request.POST, household=request.household, prefix="exc")
    if form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            exception, _ = DateException.objects.update_or_create(
                household=request.household, date=data["date"], meal_type=data["meal_type"],
                defaults={"mode": data["mode"], "override_attendance": data["override_attendance"], "notes": data["notes"]},
            )
            exception.attendees.set(data["attendees"])
        messages.success(request, "Excepción guardada. Prevalece sobre las reglas al crear o regenerar esa comida.")
    else:
        messages.error(request, "Revisa los datos de la excepción.")
    return redirect("planning:rules")


@household_required(Role.EDITOR)
@require_POST
def exception_delete(request, pk):
    get_object_or_404(DateException, pk=pk, household=request.household).delete()
    messages.success(request, "Excepción eliminada.")
    return redirect("planning:rules")
