import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from households.permissions import household_required

from . import push
from .forms import ReminderForm
from .models import PushSubscription, ReminderPreference


@household_required()
def settings_view(request):
    preference = ReminderPreference.objects.filter(membership=request.membership).first()
    form = ReminderForm(
        request.POST or None, instance=preference or ReminderPreference(membership=request.membership),
        can_plan=request.membership.can_edit,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Recordatorios guardados.")
        return redirect("reminders:settings")
    context = {
        "form": form,
        "configured": push.configured(),
        "public_key": settings.VAPID_PUBLIC_KEY,
        "devices": request.user.push_subscriptions.count(),
    }
    return render(request, "reminders/settings.html", context)


def _payload(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


@login_required
@require_POST
def subscribe(request):
    """Called by the page once the device accepted notifications (JSON from PushSubscription.toJSON())."""
    data = _payload(request)
    endpoint = (data or {}).get("endpoint")
    keys = (data or {}).get("keys") or {}
    if not (
        isinstance(endpoint, str) and endpoint.startswith("https://") and len(endpoint) <= 1000
        and isinstance(keys.get("p256dh"), str) and isinstance(keys.get("auth"), str)
        and len(keys["p256dh"]) <= 200 and len(keys["auth"]) <= 100
    ):
        return JsonResponse({"ok": False}, status=400)
    # One browser, one subscription: if someone else used this browser before, it is now this person's.
    PushSubscription.objects.update_or_create(
        endpoint=endpoint,
        defaults={
            "user": request.user, "p256dh": keys["p256dh"], "auth": keys["auth"], "failures": 0,
            "user_agent": request.headers.get("User-Agent", "")[:200],
        },
    )
    membership = getattr(request, "membership", None)
    if membership is not None:
        ReminderPreference.objects.get_or_create(membership=membership)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def unsubscribe(request):
    endpoint = (_payload(request) or {}).get("endpoint")
    if isinstance(endpoint, str):
        PushSubscription.objects.filter(user=request.user, endpoint=endpoint).delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def send_test(request):
    delivered = push.send_to_user(request.user, {
        "title": "menuamano", "body": "Así te llegarán los recordatorios.", "url": reverse("reminders:settings"),
        "tag": "test",
    })
    if delivered:
        messages.success(request, "Prueba enviada. Debería aparecer en unos segundos.")
    else:
        messages.error(request, "No se ha podido enviar a ningún dispositivo. Vuelve a activarlos en esta página.")
    return redirect("reminders:settings")
