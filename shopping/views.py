from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.choices import MealType
from households.models import Role
from households.permissions import household_required

from . import services
from .forms import ManualItemForm, NewListForm
from .models import ShoppingItem, ShoppingList

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
    for _, items in groups:
        for item in items:
            decorate(item)
    for item in surplus:
        decorate(item)
    all_items = [item for _, items in groups for item in items]
    done = sum(1 for item in all_items if item.is_done)
    context = {
        "shopping_list": shopping_list,
        "groups": groups,
        "surplus": surplus,
        "done": done,
        "total": len(all_items),
        "percent": int(done * 100 / len(all_items)) if all_items else 0,
        "manual_form": ManualItemForm(),
        "meal_labels": MEAL_LABELS,
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
        return render(request, "shopping/_item.html", {"item": decorate(item), "can_edit": True})
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
