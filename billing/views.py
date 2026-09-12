from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from households.models import Role
from households.permissions import household_required

from . import entitlements, services
from .plans import FREE, PREMIUM, get_plan, price_labels


@household_required()
def plan(request):
    household = request.household
    context = {
        "plan": entitlements.household_plan(household),
        "subscription": entitlements.subscription_for(household),
        "usage": entitlements.usage(household),
        "free": get_plan(FREE),
        "premium": get_plan(PREMIUM),
        "prices": price_labels(),
    }
    return render(request, "billing/plan.html", context)


def _plan_url(request):
    return request.build_absolute_uri(reverse("billing:plan"))


@household_required(Role.ADMIN)
@require_POST
def checkout(request):
    if not settings.BILLING_ENABLED:
        raise Http404("Billing disabled")
    interval = request.POST.get("interval")
    if interval not in services.PRICES:
        messages.error(request, "Elige la suscripción mensual o la anual.")
        return redirect("billing:plan")
    if entitlements.household_plan(request.household).code == PREMIUM:
        messages.info(request, "Este hogar ya tiene Premium. Puedes cambiar el periodo desde «Gestionar la suscripción».")
        return redirect("billing:plan")
    try:
        url = services.create_checkout_session(
            request.household, request.user, interval,
            # Stripe replaces {CHECKOUT_SESSION_ID} itself; it must not be URL-encoded.
            success_url=request.build_absolute_uri(reverse("billing:success")) + "?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=_plan_url(request),
        )
    except services.BillingError as exc:
        messages.error(request, exc.message)
        return redirect("billing:plan")
    return redirect(url)


@household_required(Role.ADMIN)
@require_POST
def portal(request):
    if not settings.BILLING_ENABLED:
        raise Http404("Billing disabled")
    try:
        url = services.create_portal_session(request.household, return_url=_plan_url(request))
    except services.BillingError as exc:
        messages.error(request, exc.message)
        return redirect("billing:plan")
    return redirect(url)


@household_required()
def success(request):
    session_id = request.GET.get("session_id", "")
    if settings.BILLING_ENABLED and session_id:
        try:
            # Do not wait for the webhook to show the new plan; the webhook stays the source of truth.
            services.sync_checkout_session(request.household, session_id)
        except services.BillingError:
            pass
    if entitlements.household_plan(request.household).code == PREMIUM:
        messages.success(request, "¡Listo! Vuestro hogar ya tiene Premium.")
    else:
        messages.info(request, "Estamos confirmando el pago con Stripe. En unos segundos verás Premium en esta página.")
    return redirect("billing:plan")


@csrf_exempt
@require_POST
def stripe_webhook(request):
    status = services.handle_webhook(request.body, request.headers.get("Stripe-Signature", ""))
    return HttpResponse(status=status)
