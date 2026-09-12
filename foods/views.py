from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from households.models import Role
from households.permissions import household_required

from . import reviews
from .forms import ConversionForm, IngredientForm, IngredientReviewForm
from .models import Ingredient, IngredientReview, UnitConversion


@household_required()
def ingredient_list(request):
    q = request.GET.get("q", "").strip()
    ingredients = Ingredient.objects.for_household(request.household)
    if q:
        ingredients = ingredients.filter(Q(name__icontains=q) | Q(aliases__icontains=q))
    household_reviews = reviews.reviews_for(request.household)
    if request.GET.get("revisar"):
        ingredients = ingredients.filter(trait_info_complete=False).exclude(pk__in=household_reviews)
    context = {"ingredients": ingredients.order_by("name"), "q": q, "reviews": household_reviews}
    return render(request, "foods/list.html", context)


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


def _recalculate_open_lists(household):
    """Equivalences change how quantities merge: refresh the lists still in use."""
    from shopping.models import ShoppingList
    from shopping.services import recalculate

    for shopping_list in ShoppingList.objects.filter(household=household, end_date__gte=timezone.localdate()):
        recalculate(shopping_list)


@household_required()
def equivalences(request, pk):
    ingredient = get_object_or_404(Ingredient.objects.for_household(request.household), pk=pk)
    form = ConversionForm(request.POST or None)
    if request.method == "POST":
        if not request.membership.can_edit:
            raise PermissionDenied("Editors only")
        if form.is_valid():
            data = form.cleaned_data
            # Always stored for this household: it never changes the shared catalogue or other homes.
            UnitConversion.objects.update_or_create(
                ingredient=ingredient, household=request.household, unit=data["unit"],
                defaults={"grams": data["grams"], "note": data["note"]},
            )
            _recalculate_open_lists(request.household)
            messages.success(request, "Equivalencia guardada. Las listas de compra abiertas se han recalculado.")
            return redirect("foods:equivalences", ingredient.pk)
    rows = UnitConversion.objects.filter(ingredient=ingredient).filter(
        Q(household__isnull=True) | Q(household=request.household)
    )
    own_units = {r.unit for r in rows if r.household_id}
    context = {
        "ingredient": ingredient,
        "rows": [{"row": r, "overridden": r.household_id is None and r.unit in own_units} for r in rows],
        "form": form,
    }
    return render(request, "foods/equivalences.html", context)


@household_required(Role.EDITOR)
@require_POST
def equivalence_delete(request, pk, cid):
    conversion = get_object_or_404(UnitConversion, pk=cid, ingredient_id=pk, household=request.household)
    conversion.delete()
    _recalculate_open_lists(request.household)
    messages.success(request, "Equivalencia eliminada.")
    return redirect("foods:equivalences", pk)


def _safe_next(request, default):
    target = request.POST.get("next") or request.GET.get("next") or ""
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return target
    return default


@household_required()
def ingredient_review(request, pk):
    """Record what the label of the product this household buys says it contains."""
    ingredient = get_object_or_404(Ingredient.objects.for_household(request.household), pk=pk)
    review = IngredientReview.objects.filter(household=request.household, ingredient=ingredient).first()
    next_url = _safe_next(request, reverse("foods:list"))
    initial = {"traits": (review.traits if review else ingredient.traits), "note": review.note if review else ""}
    form = IngredientReviewForm(request.POST or None, initial=initial)
    if request.method == "POST":
        if not request.membership.can_edit:
            raise PermissionDenied("Editors only")
        if form.is_valid():
            reviews.save_review(
                request.household, ingredient, request.user, form.cleaned_data["traits"], form.cleaned_data["note"]
            )
            messages.success(request, f"Etiqueta de «{ingredient.name}» revisada. Las comidas previstas se han vuelto a comprobar.")
            return redirect(next_url)
    return render(request, "foods/review.html", {"ingredient": ingredient, "review": review, "form": form, "next": next_url})


@household_required(Role.EDITOR)
@require_POST
def ingredient_review_delete(request, pk):
    review = get_object_or_404(IngredientReview, ingredient_id=pk, household=request.household)
    reviews.delete_review(review)
    messages.success(request, "Revisión eliminada: se vuelve a usar la información del catálogo.")
    return redirect("foods:review", pk)
