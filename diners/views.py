from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.choices import MealType, Weekday
from foods.compatibility import LABEL_REMINDER
from foods.models import DIET_PRESETS
from households.models import Role
from households.permissions import household_required

from . import services
from .forms import (
    DietPresetForm,
    DinerForm,
    DinerWizardForm,
    GrantForm,
    PreferencesForm,
    RestrictionsForm,
    TextPreferenceForm,
    WeightForm,
)
from .models import AttendancePattern, Diner, DinerPreference, DinerRestriction, HealthDataAccess
from .permissions import can_manage_health_access, can_view_health
from .signals import batch_restriction_changes


def _diner(request, pk):
    # Always scoped to the active household: ids from another household return 404.
    return get_object_or_404(Diner, pk=pk, household=request.household)


@household_required()
def diner_list(request):
    diners = request.household.diners.prefetch_related("restrictions__ingredient", "preferences__ingredient")
    return render(request, "diners/list.html", {"diners": diners})


# The configurator's steps and their fields: after a failed save it opens on the first step with errors.
WIZARD_STEPS = (("alias", "birth_date", "portion"), ("diet", "extras"), ("allergies",), ("intolerances", "ingredients"), ("diabetes",))


def _configure(request, diner=None):
    form = DinerWizardForm(request.POST or None, household=request.household, diner=diner)
    if request.method == "POST" and form.is_valid():
        saved = services.save_profile(diner or Diner(household=request.household), form.cleaned_data)
        if diner is None:
            messages.success(request, f"{saved.alias} añadido. Se tendrá en cuenta en cada comida en la que esté.")
        else:
            messages.success(request, "Perfil guardado. Las comidas previstas se han vuelto a comprobar.")
        return redirect("diners:detail", saved.pk)
    start = next((i for i, fields in enumerate(WIZARD_STEPS) if any(f in form.errors for f in fields)), 0)
    context = {"form": form, "diner": diner, "start_step": start, "label_reminder": LABEL_REMINDER}
    return render(request, "diners/wizard.html", context)


@household_required(Role.EDITOR)
def diner_create(request):
    return _configure(request)


@household_required(Role.EDITOR)
def diner_setup(request, pk):
    return _configure(request, _diner(request, pk))


@household_required(Role.EDITOR)
def diner_edit(request, pk):
    diner = _diner(request, pk)
    form = DinerForm(request.POST or None, instance=diner, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Perfil guardado.")
        return redirect("diners:detail", diner.pk)
    return render(request, "diners/form.html", {"form": form, "diner": diner})


def _attendance_grid(diner, household):
    patterns = {(p.weekday, p.meal_type): p.attends for p in diner.attendance_patterns.all()}
    return [
        {
            "weekday": weekday,
            "label": label,
            "cells": [(mt, patterns.get((weekday, mt), True)) for mt in household.meal_types],
        }
        for weekday, label in Weekday.choices
    ]


@household_required()
def diner_detail(request, pk):
    diner = _diner(request, pk)
    household = request.household
    preferences = list(diner.preferences.select_related("ingredient").order_by("ingredient__name", "text"))
    grid = _attendance_grid(diner, household)
    context = {
        "diner": diner,
        "restrictions": diner.restrictions.select_related("ingredient"),
        # Ingredient preferences go in the summary; free-text ones are listed with a remove button.
        "dislikes": [p for p in preferences if p.ingredient_id and p.kind == DinerPreference.Kind.DISLIKE],
        "likes": [p for p in preferences if p.ingredient_id and p.kind == DinerPreference.Kind.LIKE],
        "text_preferences": [p for p in preferences if not p.ingredient_id],
        "restrictions_form": RestrictionsForm(diner=diner, prefix="r"),
        "preferences_form": PreferencesForm(diner=diner, prefix="p"),
        "text_preference_form": TextPreferenceForm(prefix="t"),
        "preset_form": DietPresetForm(prefix="d"),
        "grid": grid,
        "attendance_count": sum(1 for row in grid for _, checked in row["cells"] if checked),
        "meal_types": [MealType(mt) for mt in household.meal_types],
        "can_view_health": can_view_health(request.user, diner),
    }
    return render(request, "diners/detail.html", context)


def _form_errors_to_messages(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


def _names(items):
    return ", ".join(items)


@household_required(Role.EDITOR)
@require_POST
def restrictions_save(request, pk):
    diner = _diner(request, pk)
    form = RestrictionsForm(request.POST, diner=diner, prefix="r")
    if not form.is_valid():
        _form_errors_to_messages(request, form)
        return redirect("diners:detail", diner.pk)
    data = form.cleaned_data
    added, removed = services.sync_restrictions(diner, data["traits"], data["ingredients"], data["kind"], data["label"])
    if not added and not removed:
        messages.info(request, "No había cambios en las restricciones.")
        return redirect("diners:detail", diner.pk)
    parts = []
    if added:
        parts.append(f"añadidas: {_names(added)}")
    if removed:
        parts.append(f"quitadas: {_names(removed)}")
    messages.success(request, f"Restricciones guardadas ({'; '.join(parts)}). Las comidas previstas se han vuelto a comprobar.")
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def preset_add(request, pk):
    diner = _diner(request, pk)
    form = DietPresetForm(request.POST, prefix="d")
    if form.is_valid():
        label, traits = DIET_PRESETS[form.cleaned_data["preset"]]
        with transaction.atomic(), batch_restriction_changes(diner.household):
            for trait in traits:
                if not diner.restrictions.filter(trait=trait).exists():
                    DinerRestriction.objects.create(diner=diner, kind=DinerRestriction.Kind.DIET, trait=trait, label=label)
        messages.success(request, f"{label} aplicada.")
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def restriction_delete(request, pk, rid):
    diner = _diner(request, pk)
    get_object_or_404(DinerRestriction, pk=rid, diner=diner).delete()
    messages.success(request, "Restricción eliminada.")
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def preferences_save(request, pk):
    diner = _diner(request, pk)
    form = PreferencesForm(request.POST, diner=diner, prefix="p")
    if form.is_valid():
        added, removed = services.sync_preferences(diner, form.cleaned_data["dislikes"], form.cleaned_data["likes"])
        if added or removed:
            messages.success(request, "Gustos guardados.")
        else:
            messages.info(request, "No había cambios en los gustos.")
    else:
        _form_errors_to_messages(request, form)
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def preference_add(request, pk):
    diner = _diner(request, pk)
    form = TextPreferenceForm(request.POST, prefix="t")
    if form.is_valid():
        preference = form.save(commit=False)
        preference.diner = diner
        preference.save()
        messages.success(request, "Preferencia guardada.")
    else:
        _form_errors_to_messages(request, form)
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def preference_delete(request, pk, prid):
    diner = _diner(request, pk)
    get_object_or_404(DinerPreference, pk=prid, diner=diner).delete()
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def attendance_save(request, pk):
    diner = _diner(request, pk)
    with transaction.atomic():
        for weekday in Weekday.values:
            for meal_type in request.household.meal_types:
                attends = request.POST.get(f"att-{weekday}-{meal_type}") == "on"
                AttendancePattern.objects.update_or_create(
                    diner=diner, weekday=weekday, meal_type=meal_type, defaults={"attends": attends}
                )
    messages.success(request, "Asistencia habitual guardada. Se aplica a las comidas que se creen o regeneren.")
    return redirect("diners:detail", diner.pk)


# --- Weight: every endpoint checks health permissions in the backend ------------------------


def _health_diner(request, pk):
    diner = _diner(request, pk)
    if not can_view_health(request.user, diner):
        raise PermissionDenied("No access to this diner's health data")
    return diner


@household_required()
def weight(request, pk):
    diner = _health_diner(request, pk)
    context = {
        "diner": diner,
        "weights": diner.weights.all(),
        "form": WeightForm(),
        "can_manage": can_manage_health_access(request.user, diner),
        "grants": diner.health_access.select_related("user"),
        "grant_form": GrantForm(diner=diner),
    }
    return render(request, "diners/weight.html", context)


@household_required()
@require_POST
def weight_add(request, pk):
    diner = _health_diner(request, pk)
    form = WeightForm(request.POST)
    if form.is_valid():
        measurement = form.save(commit=False)
        measurement.diner = diner
        measurement.recorded_by = request.user
        measurement.save()
        messages.success(request, "Medición registrada.")
    else:
        _form_errors_to_messages(request, form)
    return redirect("diners:weight", diner.pk)


@household_required()
@require_POST
def grant_add(request, pk):
    diner = _diner(request, pk)
    if not can_manage_health_access(request.user, diner):
        raise PermissionDenied("Cannot manage health access for this diner")
    form = GrantForm(request.POST, diner=diner)
    if form.is_valid():
        HealthDataAccess.objects.get_or_create(diner=diner, user=form.cleaned_data["user"], defaults={"granted_by": request.user})
        messages.success(request, "Acceso concedido.")
    else:
        _form_errors_to_messages(request, form)
    return redirect("diners:weight", diner.pk)


@household_required()
@require_POST
def grant_remove(request, pk, gid):
    diner = _diner(request, pk)
    if not can_manage_health_access(request.user, diner):
        raise PermissionDenied("Cannot manage health access for this diner")
    get_object_or_404(HealthDataAccess, pk=gid, diner=diner).delete()
    messages.success(request, "Acceso retirado.")
    return redirect("diners:weight", diner.pk)
