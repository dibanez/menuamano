from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from core.choices import MealType, Weekday
from foods.models import DIET_PRESETS
from households.models import Role
from households.permissions import household_required

from .forms import DietPresetForm, DinerForm, GrantForm, PreferenceForm, RestrictionForm, WeightForm
from .models import AttendancePattern, Diner, DinerPreference, DinerRestriction, HealthDataAccess
from .permissions import can_manage_health_access, can_view_health


def _diner(request, pk):
    # Always scoped to the active household: ids from another household return 404.
    return get_object_or_404(Diner, pk=pk, household=request.household)


@household_required()
def diner_list(request):
    diners = request.household.diners.prefetch_related("restrictions__ingredient", "preferences__ingredient")
    return render(request, "diners/list.html", {"diners": diners})


@household_required(Role.EDITOR)
def diner_create(request):
    form = DinerForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        diner = form.save(commit=False)
        diner.household = request.household
        diner.save()
        messages.success(request, f"{diner.alias} añadido. Indica ahora sus alergias o restricciones, si las tiene.")
        return redirect("diners:detail", diner.pk)
    return render(request, "diners/form.html", {"form": form})


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
    context = {
        "diner": diner,
        "restrictions": diner.restrictions.select_related("ingredient"),
        "preferences": diner.preferences.select_related("ingredient"),
        "restriction_form": RestrictionForm(household=household, prefix="r"),
        "preset_form": DietPresetForm(prefix="p"),
        "preference_form": PreferenceForm(household=household, prefix="pref"),
        "grid": _attendance_grid(diner, household),
        "meal_types": [MealType(mt) for mt in household.meal_types],
        "can_view_health": can_view_health(request.user, diner),
    }
    return render(request, "diners/detail.html", context)


def _form_errors_to_messages(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


@household_required(Role.EDITOR)
@require_POST
def restriction_add(request, pk):
    diner = _diner(request, pk)
    form = RestrictionForm(request.POST, household=request.household, prefix="r")
    if form.is_valid():
        restriction = form.save(commit=False)
        restriction.diner = diner
        restriction.save()
        messages.success(request, "Restricción añadida. Las comidas previstas se han vuelto a comprobar.")
    else:
        _form_errors_to_messages(request, form)
    return redirect("diners:detail", diner.pk)


@household_required(Role.EDITOR)
@require_POST
def preset_add(request, pk):
    diner = _diner(request, pk)
    form = DietPresetForm(request.POST, prefix="p")
    if form.is_valid():
        label, traits = DIET_PRESETS[form.cleaned_data["preset"]]
        with transaction.atomic():
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
def preference_add(request, pk):
    diner = _diner(request, pk)
    form = PreferenceForm(request.POST, household=request.household, prefix="pref")
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
