from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from foods.compatibility import LABEL_REMINDER, rules_for_diner
from foods.units import scale
from households.models import Role
from households.permissions import household_required
from planning.models import MealRecipe
from planning.services import diners_queryset

from . import services
from .forms import AddToMealForm, RecipeForm, RecipeIngredientFormSet, RecipeStepFormSet
from .models import Recipe, RecipeFavorite


def _recipe(request, pk):
    return get_object_or_404(Recipe, pk=pk, household=request.household)


def _favorite_ids(request):
    return set(
        RecipeFavorite.objects.filter(user=request.user, recipe__household=request.household).values_list("recipe_id", flat=True)
    )


@household_required()
def recipe_list(request):
    q = request.GET.get("q", "").strip()
    only_favorites = bool(request.GET.get("favoritas"))
    archived = bool(request.GET.get("archivadas"))
    recipes = Recipe.objects.filter(household=request.household, is_archived=archived)
    if q:
        recipes = recipes.filter(Q(name__icontains=q) | Q(description__icontains=q) | Q(tags__contains=[q.lower()]))
    favorites = _favorite_ids(request)
    if only_favorites:
        recipes = recipes.filter(pk__in=favorites)
    recipes = recipes.annotate(times_used=Count("meal_uses"), last_used=Max("meal_uses__meal__date"))
    return render(
        request, "recipes/list.html",
        {"recipes": recipes, "q": q, "favorites": favorites, "only_favorites": only_favorites, "archived": archived},
    )


def _parse_servings(value, default):
    try:
        servings = Decimal(value)
    except (InvalidOperation, TypeError):
        return Decimal(default)
    return min(max(servings, Decimal("0.5")), Decimal("50"))


@household_required()
def recipe_detail(request, pk):
    recipe = get_object_or_404(services.recipes_for_household(request.household, include_archived=True), pk=pk)
    servings = _parse_servings(request.GET.get("raciones"), recipe.base_servings)
    lines = [(ri, scale(ri.quantity, recipe.base_servings, servings)) for ri in recipe.ingredients.all()]
    if request.htmx and "raciones" in request.GET:
        return render(request, "recipes/_ingredients.html", {"recipe": recipe, "lines": lines, "servings": servings})
    diners = list(diners_queryset(request.household))
    compatibility = [(diner, services.check_recipe(recipe, [rules_for_diner(diner)])) for diner in diners]
    history = (
        MealRecipe.objects.filter(recipe=recipe, meal__household=request.household)
        .select_related("meal").order_by("-meal__date")[:8]
    )
    context = {
        "recipe": recipe,
        "lines": lines,
        "servings": servings,
        "steps": recipe.steps.all(),
        "compatibility": compatibility,
        "is_favorite": recipe.pk in _favorite_ids(request),
        "history": history,
        "add_form": AddToMealForm(household=request.household, initial={"date": timezone.localdate()}),
        "label_reminder": LABEL_REMINDER,
    }
    return render(request, "recipes/detail.html", context)


def _save_ordered(formset, recipe):
    for index, form in enumerate(formset.forms):
        if form in formset.deleted_forms:
            if form.instance.pk:
                form.instance.delete()
            continue
        if not form.has_changed() and form.instance.pk is None:
            continue
        obj = form.save(commit=False)
        obj.recipe = recipe
        obj.order = index
        obj.save()


def _recipe_form(request, recipe=None):
    household = request.household
    instance = recipe or Recipe(household=household)
    data = request.POST if request.method == "POST" else None
    form = RecipeForm(data, instance=recipe)
    ingredients = RecipeIngredientFormSet(data, instance=instance, prefix="ing", form_kwargs={"household": household})
    steps = RecipeStepFormSet(data, instance=instance, prefix="steps")
    if data is not None and form.is_valid() and ingredients.is_valid() and steps.is_valid():
        changed = form.has_changed() or ingredients.has_changed() or steps.has_changed()
        with transaction.atomic():
            obj = form.save(commit=False)
            obj.household = household
            if recipe is None:
                obj.created_by = request.user
                obj.origin = Recipe.Origin.MANUAL
            obj.save()
            _save_ordered(ingredients, obj)
            _save_ordered(steps, obj)
            if recipe is not None and changed:
                services.bump_version(obj)
        if recipe is not None and changed:
            messages.success(request, "Receta guardada. Las comidas ya planificadas conservan la versión que usaban.")
        else:
            messages.success(request, "Receta guardada.")
        return redirect("recipes:detail", obj.pk)
    return render(
        request, "recipes/form.html", {"form": form, "ingredients": ingredients, "steps": steps, "recipe": recipe}
    )


@household_required(Role.EDITOR)
def recipe_create(request):
    return _recipe_form(request)


@household_required(Role.EDITOR)
def recipe_edit(request, pk):
    return _recipe_form(request, _recipe(request, pk))


@household_required()
@require_POST
def favorite_toggle(request, pk):
    recipe = _recipe(request, pk)
    favorite, created = RecipeFavorite.objects.get_or_create(user=request.user, recipe=recipe)
    if not created:
        favorite.delete()
    if request.htmx:
        return render(request, "recipes/_favorite.html", {"recipe": recipe, "is_favorite": created})
    return redirect("recipes:detail", recipe.pk)


@household_required(Role.EDITOR)
@require_POST
def archive_toggle(request, pk):
    recipe = _recipe(request, pk)
    recipe.is_archived = not recipe.is_archived
    recipe.save(update_fields=["is_archived", "updated_at"])
    messages.success(request, "Receta archivada." if recipe.is_archived else "Receta recuperada.")
    return redirect("recipes:detail", recipe.pk)


@household_required(Role.EDITOR)
@require_POST
def mark_reviewed(request, pk):
    recipe = _recipe(request, pk)
    recipe.review_status = Recipe.ReviewStatus.REVIEWED
    recipe.save(update_fields=["review_status", "updated_at"])
    messages.success(request, "Receta marcada como revisada.")
    return redirect("recipes:detail", recipe.pk)
