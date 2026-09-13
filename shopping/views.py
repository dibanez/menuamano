from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.choices import MealType
from households.models import Role
from households.permissions import household_required

from foods.units import format_quantity

from . import services
from .forms import ManualItemForm, NewListForm, PantryForm
from .models import PantryItem, ShoppingItem, ShoppingList

MEAL_LABELS = dict(MealType.choices)


def _list(request, pk):
    return get_object_or_404(ShoppingList, pk=pk, household=request.household)


def _item(request, pk):
    # The item must belong to a list of the active household; ids from elsewhere give 404.
    return get_object_or_404(ShoppingItem, pk=pk, shopping_list__household=request.household)


def decorate(item):
    item.source_rows = []
    for source in item.sources:
        try:
            source_date = date.fromisoformat(source["date"])
        except (KeyError, ValueError):
            source_date = None
        item.source_rows.append({**source, "date": source_date, "quantity": Decimal(source.get("quantity", "0"))})
    return item


@household_required()
def current(request):
    today = timezone.localdate()
    lists = ShoppingList.objects.filter(household=request.household)
    shopping_list = lists.filter(start_date__lte=today, end_date__gte=today).first() or lists.filter(end_date__gte=today).order_by("start_date").first()
    if shopping_list:
        return redirect("shopping:detail", shopping_list.pk)
    return redirect("shopping:index")


@household_required()
def index(request):
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    form = NewListForm(initial={"start": monday, "end": monday + timedelta(days=6)})
    lists = ShoppingList.objects.filter(household=request.household)[:30]
    return render(request, "shopping/index.html", {"form": form, "lists": lists})


@household_required(Role.EDITOR)
@require_POST
def create(request):
    form = NewListForm(request.POST)
    if not form.is_valid():
        lists = ShoppingList.objects.filter(household=request.household)[:30]
        return render(request, "shopping/index.html", {"form": form, "lists": lists}, status=400)
    data = form.cleaned_data
    shopping_list = services.create_list(request.household, request.user, data["start"], data["end"], data["name"])
    messages.success(request, "Lista creada a partir del menú.")
    return redirect("shopping:detail", shopping_list.pk)


@household_required()
def detail(request, pk):
    shopping_list = _list(request, pk)
    groups, surplus = services.grouped_items(shopping_list)
    staples, covered = services.pantry_sections(shopping_list)
    for item in [*(i for _, items in groups for i in items), *surplus, *staples, *covered]:
        decorate(item)
    all_items = [item for _, items in groups for item in items]
    services.attach_label_checks(request.household, [*all_items, *staples])
    done = sum(1 for item in all_items if item.is_done)
    context = {
        "shopping_list": shopping_list,
        "groups": groups,
        "surplus": surplus,
        "staples": staples,
        "covered": covered,
        "staples_label": services.STAPLES_LABEL,
        "done": done,
        "total": len(all_items),
        "percent": int(done * 100 / len(all_items)) if all_items else 0,
        "manual_form": ManualItemForm(),
        "meal_labels": MEAL_LABELS,
        "snapshot": services.list_snapshot(
            shopping_list, groups, request.user, request.membership.can_edit, staples=staples
        ),
    }
    return render(request, "shopping/detail.html", context)


@household_required(Role.EDITOR)
@require_POST
def recalculate(request, pk):
    shopping_list = _list(request, pk)
    stats = services.recalculate(shopping_list)
    messages.success(
        request,
        f"Lista recalculada: {stats.created} artículos nuevos, {stats.updated} actualizados. "
        "Se han conservado las compras anotadas y los artículos añadidos a mano.",
    )
    return redirect("shopping:detail", shopping_list.pk)


@household_required(Role.EDITOR)
@require_POST
def delete(request, pk):
    _list(request, pk).delete()
    messages.success(request, "Lista eliminada.")
    return redirect("shopping:index")


def _respond_item(request, item):
    if request.htmx:
        services.attach_label_checks(request.household, [decorate(item)])
        return render(request, "shopping/_item.html", {"item": item, "can_edit": True})
    return redirect("shopping:detail", item.shopping_list_id)


@household_required(Role.EDITOR)
@require_POST
def item_toggle(request, pk):
    item = _item(request, pk)
    if item.is_done:
        quantity = Decimal("0")
    else:
        quantity = item.needed_quantity if item.needed_quantity > 0 else Decimal("1")
    services.set_purchased(item, request.user, quantity)
    return _respond_item(request, item)


@household_required(Role.EDITOR)
@require_POST
def item_purchased(request, pk):
    item = _item(request, pk)
    try:
        quantity = Decimal(request.POST.get("purchased", "").replace(",", "."))
    except InvalidOperation:
        messages.error(request, "Escribe una cantidad válida.")
        return redirect("shopping:detail", item.shopping_list_id)
    services.set_purchased(item, request.user, quantity)
    return _respond_item(request, item)


@household_required(Role.EDITOR)
@require_POST
def item_state(request, pk):
    """Set an item as bought or not. Idempotent: ticks made offline are sent again when back online."""
    item = _item(request, pk)
    done = request.POST.get("done") == "1"
    if done != item.is_done:
        quantity = (item.needed_quantity if item.needed_quantity > 0 else Decimal("1")) if done else Decimal("0")
        services.set_purchased(item, request.user, quantity)
    return HttpResponse(status=204)


@household_required(Role.EDITOR)
@require_POST
def item_pantry(request, pk):
    """From the list: the item's ingredient is always at home (listed apart), or no longer."""
    item = _item(request, pk)
    if item.ingredient_id is None:
        messages.error(request, "Solo los ingredientes que vienen del menú pueden ir a la despensa.")
        return redirect("shopping:detail", item.shopping_list_id)
    entry = PantryItem.objects.filter(household=request.household, ingredient_id=item.ingredient_id).first()
    if entry is not None and entry.kind == PantryItem.Kind.STAPLE:
        services.remove_pantry_item(entry)
        messages.success(request, f"«{item.name}» vuelve a la lista como un artículo más.")
    else:
        services.set_pantry_item(request.household, request.user, item.ingredient, PantryItem.Kind.STAPLE)
        messages.success(request, f"«{item.name}» es un básico de la despensa: sale aparte para que mires si os queda.")
    return redirect("shopping:detail", item.shopping_list_id)


def _pantry_context(request, form):
    entries = PantryItem.objects.filter(household=request.household).select_related("ingredient")
    return {
        "staples": [e for e in entries if e.kind == PantryItem.Kind.STAPLE],
        "stock": [e for e in entries if e.kind == PantryItem.Kind.STOCK],
        "form": form,
        "suggestions": services.pantry_suggestions(request.household),
    }


@household_required()
def pantry(request):
    return render(request, "shopping/pantry.html", _pantry_context(request, PantryForm(household=request.household)))


@household_required(Role.EDITOR)
@require_POST
def pantry_add(request):
    form = PantryForm(request.POST, household=request.household)
    if not form.is_valid():
        return render(request, "shopping/pantry.html", _pantry_context(request, form), status=400)
    data = form.cleaned_data
    entry = services.set_pantry_item(
        request.household, request.user, data["ingredient"], data["kind"], data["quantity"], data["unit"]
    )
    if entry.kind == PantryItem.Kind.STAPLE:
        messages.success(request, f"«{entry.ingredient.name}» es un básico: sale aparte en la lista para que mires si os queda.")
    else:
        messages.success(
            request, f"Anotado: {format_quantity(entry.quantity, entry.unit)} de {entry.ingredient.name}. Se descuenta de la compra."
        )
    return redirect("shopping:pantry")


@household_required(Role.EDITOR)
@require_POST
def pantry_delete(request, pk):
    entry = get_object_or_404(PantryItem.objects.select_related("ingredient"), pk=pk, household=request.household)
    services.remove_pantry_item(entry)
    messages.success(request, f"«{entry.ingredient.name}» ya no está en la despensa.")
    return redirect("shopping:pantry")


@household_required(Role.EDITOR)
@require_POST
def item_delete(request, pk):
    item = _item(request, pk)
    if not item.is_manual:
        messages.error(request, "Los artículos calculados desde el menú se quitan cambiando el menú.")
    else:
        item.delete()
    return redirect("shopping:detail", item.shopping_list_id)


@household_required(Role.EDITOR)
@require_POST
def manual_add(request, pk):
    shopping_list = _list(request, pk)
    form = ManualItemForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        services.add_manual_item(
            shopping_list, data["name"], data["quantity"], data["unit"], data["note"], data["category"]
        )
        messages.success(request, f"«{data['name']}» añadido a la lista.")
    else:
        messages.error(request, "Revisa el artículo: el nombre es obligatorio.")
    return redirect("shopping:detail", shopping_list.pk)
