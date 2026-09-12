from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render

from households.models import Role
from households.permissions import household_required

from .forms import IngredientForm
from .models import Ingredient


@household_required()
def ingredient_list(request):
    q = request.GET.get("q", "").strip()
    ingredients = Ingredient.objects.for_household(request.household)
    if q:
        ingredients = ingredients.filter(Q(name__icontains=q) | Q(aliases__icontains=q))
    if request.GET.get("revisar"):
        ingredients = ingredients.filter(trait_info_complete=False)
    return render(request, "foods/list.html", {"ingredients": ingredients.order_by("name"), "q": q})


@household_required(Role.EDITOR)
def ingredient_create(request):
    form = IngredientForm(request.POST or None, household=request.household)
    if request.method == "POST" and form.is_valid():
        ingredient = form.save(commit=False)
        ingredient.household = request.household
        ingredient.source = Ingredient.Source.MANUAL
        ingredient.save()
        messages.success(request, f"«{ingredient.name}» añadido.")
        return redirect("foods:list")
    return render(request, "foods/form.html", {"form": form})


@household_required(Role.EDITOR)
def ingredient_edit(request, pk):
    # Only the household's own ingredients are editable here; the shared catalogue is read-only.
    ingredient = get_object_or_404(Ingredient, pk=pk, household=request.household)
    form = IngredientForm(request.POST or None, instance=ingredient, household=request.household)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Ingrediente guardado. Las comidas previstas que lo usan se han vuelto a comprobar.")
        return redirect("foods:list")
    return render(request, "foods/form.html", {"form": form, "ingredient": ingredient})
