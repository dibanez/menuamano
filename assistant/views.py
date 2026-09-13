from datetime import date, timedelta

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from households.models import Role
from households.permissions import household_required
from planning.forms import RangeForm
from planning.models import Meal

from . import services
from .models import ChatMessage, Proposal

CHAT_WINDOW_DAYS = 14


def _proposal(request, pk):
    return get_object_or_404(Proposal, pk=pk, household=request.household)


@household_required()
def chat(request):
    history = ChatMessage.objects.filter(household=request.household).select_related("proposal").order_by("-created_at")[:30]
    context = {
        "chat_messages": list(reversed(history)),
        "pending": Proposal.objects.filter(household=request.household, status=Proposal.Status.PENDING)[:5],
    }
    return render(request, "assistant/chat.html", context)


@household_required(Role.EDITOR)
@require_POST
def chat_send(request):
    text = request.POST.get("message", "").strip()[:1000]
    if not text:
        messages.error(request, "Escribe qué quieres cambiar.")
        return redirect("assistant:chat")
    previous = ChatMessage.objects.filter(household=request.household, is_error=False).order_by("-created_at")[:6]
    history = [(m.role, m.text) for m in reversed(previous)]
    user_message = ChatMessage.objects.create(household=request.household, user=request.user, role=ChatMessage.Role.USER, text=text)
    today = timezone.localdate()
    try:
        proposal = services.request_proposal(
            request.household, request.user, "chat", today, today + timedelta(days=CHAT_WINDOW_DAYS - 1),
            text=text, history=history,
        )
    except services.AssistantError as exc:
        reply = ChatMessage.objects.create(
            household=request.household, role=ChatMessage.Role.ASSISTANT, text=exc.message, is_error=True
        )
    else:
        reply = ChatMessage.objects.create(
            household=request.household, role=ChatMessage.Role.ASSISTANT, text=proposal.summary, proposal=proposal
        )
    if request.htmx:
        return render(request, "assistant/_messages.html", {"chat_messages": [user_message, reply]})
    return redirect("assistant:chat")


@household_required(Role.EDITOR)
@require_POST
def plan_range(request):
    form = RangeForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Revisa las fechas del intervalo.")
        return redirect("planning:week")
    start, end = form.cleaned_data["start"], form.cleaned_data["end"]
    try:
        proposal = services.request_proposal(
            request.household, request.user, "plan_range", start, end, text=request.POST.get("message", "")[:500]
        )
    except services.AssistantError as exc:
        messages.error(request, exc.message)
        return redirect(f"{reverse('planning:week')}?fecha={start.isoformat()}")
    return redirect("assistant:proposal", proposal.pk)


@household_required(Role.EDITOR)
@require_POST
def replace_meal(request, pk):
    meal = get_object_or_404(Meal, pk=pk, household=request.household)
    try:
        proposal = services.request_proposal(
            request.household, request.user, "replace_meal", meal.date, meal.date,
            text=request.POST.get("message", "")[:500] or "Propón una alternativa para esta comida.",
            focus=(meal.date, meal.meal_type),
        )
    except services.AssistantError as exc:
        messages.error(request, exc.message)
        return redirect("planning:meal", meal.pk)
    return redirect("assistant:proposal", proposal.pk)


@household_required(Role.EDITOR)
@require_POST
def generate_recipe(request):
    text = request.POST.get("message", "").strip()[:500] or "Una receta sencilla para toda la familia."
    today = timezone.localdate()
    try:
        proposal = services.request_proposal(request.household, request.user, "generate_recipe", today, today, text=text)
    except services.AssistantError as exc:
        messages.error(request, exc.message)
        return redirect("recipes:list")
    return redirect("assistant:proposal", proposal.pk)


@household_required(Role.EDITOR)
@require_POST
def import_recipe(request):
    url = request.POST.get("url", "").strip()[:500]
    if not url:
        messages.error(request, "Pega el enlace de la receta.")
        return redirect("recipes:list")
    try:
        proposal = services.request_import(request.household, request.user, url)
    except services.AssistantError as exc:
        messages.error(request, exc.message)
        return redirect("recipes:list")
    return redirect("assistant:proposal", proposal.pk)


@household_required()
def proposal_detail(request, pk):
    proposal = _proposal(request, pk)
    items = []
    for item in proposal.items:
        row = dict(item)
        try:
            row["date_obj"] = date.fromisoformat(item["date"])
        except ValueError:
            row["date_obj"] = None
        items.append(row)
    context = {
        "proposal": proposal,
        "items": items,
        "applicable": sum(1 for i in proposal.items if i["status"] in (services.ITEM_OK, services.ITEM_REVIEW)),
    }
    return render(request, "assistant/proposal.html", context)


@household_required(Role.EDITOR)
@require_POST
def proposal_apply(request, pk):
    proposal = _proposal(request, pk)
    accepted = request.POST.getlist("accept")
    result = services.apply_proposal(proposal, request.user, accepted_review=accepted)
    if result.already_done:
        messages.info(request, "Esta propuesta ya se había aplicado o descartado. No se ha repetido nada.")
        return redirect("assistant:proposal", proposal.pk)
    if result.stale:
        messages.error(request, "El plan ha cambiado desde que se generó la propuesta. Pide una nueva para no pisar esos cambios.")
        return redirect("assistant:proposal", proposal.pk)
    text = f"Propuesta aplicada: {result.applied} comida{'s' if result.applied != 1 else ''} actualizada{'s' if result.applied != 1 else ''}."
    if result.recipes_created:
        text += f" {len(result.recipes_created)} receta(s) nueva(s) pendiente(s) de revisión."
    messages.success(request, text)
    for skipped in result.skipped[:6]:
        messages.warning(request, f"Omitido: {skipped}")
    if proposal.operation == "replace_meal" and proposal.items:
        # Back to the meal the person was planning, applied or not: the messages say what happened.
        return redirect("planning:slot", proposal.items[0]["date"], proposal.items[0]["meal_type"])
    if result.recipes_created and not result.applied:
        return redirect("recipes:detail", result.recipes_created[0].pk)
    start = proposal.start_date or timezone.localdate()
    return redirect(f"{reverse('planning:week')}?fecha={start.isoformat()}")


@household_required(Role.EDITOR)
@require_POST
def proposal_discard(request, pk):
    services.discard_proposal(_proposal(request, pk))
    messages.info(request, "Propuesta descartada. El calendario no ha cambiado.")
    return redirect("assistant:chat")
