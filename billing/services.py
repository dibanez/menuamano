"""Stripe integration.

* Checkout (Stripe-hosted) starts a subscription; the Customer Portal manages it.
* Webhooks keep `Subscription` in sync. Stripe is the source of truth; every event is processed
  once (`StripeEvent`), and a failure returns 500 so Stripe retries it.
* API version is the one pinned by the stripe-python SDK: billing periods live on the
  subscription items (`items.data[].current_period_end`), not on the subscription.
"""

import logging
from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.db import transaction
from django.urls import reverse

from core.emails import send_email
from households.models import Household, Role

from .models import StripeEvent, Subscription

logger = logging.getLogger(__name__)

PRICES = {"month": "STRIPE_PRICE_MONTHLY", "year": "STRIPE_PRICE_YEARLY"}
SUBSCRIPTION_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
}


class BillingError(Exception):
    """User-facing billing error (message in Spanish)."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _client():
    return stripe.StripeClient(settings.STRIPE_SECRET_KEY, max_network_retries=2)


def _get(obj, key, default=None):
    """Read a field from a StripeObject or a plain dict."""
    if obj is None:
        return default
    try:
        value = obj[key]
    except (KeyError, TypeError, IndexError):
        return default
    return default if value is None else value


def _timestamp(value):
    return datetime.fromtimestamp(int(value), tz=dt_timezone.utc) if value else None


def _object_id(value):
    return value if isinstance(value, str) else _get(value, "id", "")


# --- Checkout and portal ---------------------------------------------------------------------------


def _customer_id(household, user):
    subscription, _ = Subscription.objects.get_or_create(household=household)
    if subscription.stripe_customer_id:
        return subscription.stripe_customer_id
    customer = _client().v1.customers.create(
        params={"email": user.email, "name": household.name, "metadata": {"household_id": str(household.pk)}},
        # A double click must not create two customers for the same household.
        options={"idempotency_key": f"menuamano-customer-household-{household.pk}"},
    )
    Subscription.objects.filter(pk=subscription.pk).update(stripe_customer_id=customer.id, started_by=user)
    return customer.id


def create_checkout_session(household, user, interval, success_url, cancel_url):
    """Return the URL of a Stripe Checkout page for the Premium subscription."""
    price = getattr(settings, PRICES[interval])
    try:
        params = {
            "mode": "subscription",
            "customer": _customer_id(household, user),
            "line_items": [{"price": price, "quantity": 1}],
            "client_reference_id": str(household.pk),
            "metadata": {"household_id": str(household.pk)},
            "subscription_data": {"metadata": {"household_id": str(household.pk)}},
            "success_url": success_url,
            "cancel_url": cancel_url,
            "allow_promotion_codes": True,
            "locale": "es",
        }
        if settings.STRIPE_AUTOMATIC_TAX:
            params["automatic_tax"] = {"enabled": True}
            params["customer_update"] = {"address": "auto", "name": "auto"}
        session = _client().v1.checkout.sessions.create(params=params)
    except stripe.StripeError as exc:
        logger.warning("Stripe checkout could not be created: %s", type(exc).__name__)
        raise BillingError("No se ha podido iniciar el pago con Stripe. Inténtalo de nuevo en unos minutos.") from exc
    return session.url


def create_portal_session(household, return_url):
    subscription = Subscription.objects.filter(household=household).exclude(stripe_customer_id="").first()
    if subscription is None:
        raise BillingError("Este hogar todavía no tiene una suscripción que gestionar.")
    try:
        session = _client().v1.billing_portal.sessions.create(
            params={"customer": subscription.stripe_customer_id, "return_url": return_url, "locale": "es"}
        )
    except stripe.StripeError as exc:
        logger.warning("Stripe portal could not be opened: %s", type(exc).__name__)
        raise BillingError("No se ha podido abrir el portal de Stripe. Inténtalo de nuevo en unos minutos.") from exc
    return session.url


# --- Synchronisation -------------------------------------------------------------------------------


def _retrieve_subscription(subscription_id):
    return _client().v1.subscriptions.retrieve(subscription_id)


def apply_subscription(data, household=None):
    """Copy a Stripe subscription into the household's `Subscription` row."""
    subscription_id = _get(data, "id", "")
    customer_id = _object_id(_get(data, "customer"))
    row = Subscription.objects.filter(stripe_subscription_id=subscription_id).first() if subscription_id else None
    if row is None and household is None:
        household_id = str(_get(_get(data, "metadata", {}), "household_id", ""))
        if household_id.isdigit():
            household = Household.objects.filter(pk=int(household_id)).first()
    if row is None and household is not None:
        row, _ = Subscription.objects.get_or_create(household=household)
    if row is None and customer_id:
        row = Subscription.objects.filter(stripe_customer_id=customer_id).first()
    if row is None:
        logger.warning("Stripe subscription %s does not match any household", subscription_id)
        return None

    items = _get(_get(data, "items", {}), "data", []) or []
    item = items[0] if len(items) else None
    price = _get(item, "price")
    row.stripe_subscription_id = subscription_id
    row.stripe_customer_id = customer_id or row.stripe_customer_id
    row.status = _get(data, "status", "")
    row.cancel_at_period_end = bool(_get(data, "cancel_at_period_end", False)) or bool(_get(data, "cancel_at"))
    row.current_period_end = _timestamp(_get(item, "current_period_end"))
    row.price_id = _get(price, "id", "")
    row.interval = _get(_get(price, "recurring"), "interval", "")
    row.save()
    return row


def sync_checkout_session(household, session_id):
    """Update the plan right after Checkout, without waiting for the webhook."""
    try:
        session = _client().v1.checkout.sessions.retrieve(session_id, params={"expand": ["subscription"]})
    except stripe.StripeError as exc:
        raise BillingError("No se ha podido confirmar el pago con Stripe todavía.") from exc
    if str(_get(session, "client_reference_id", "")) != str(household.pk):
        raise BillingError("Esa sesión de pago no corresponde a este hogar.")
    subscription = _get(session, "subscription")
    if isinstance(subscription, str):
        subscription = _retrieve_subscription(subscription)
    return apply_subscription(subscription, household) if subscription else None


# --- Webhooks --------------------------------------------------------------------------------------


def handle_webhook(payload, signature):
    """Verify, deduplicate and process a Stripe event. Returns the HTTP status for Stripe."""
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError):
        logger.warning("Rejected Stripe webhook with an invalid payload or signature")
        return 400
    try:
        with transaction.atomic():
            _, created = StripeEvent.objects.get_or_create(
                event_id=event.id, defaults={"event_type": event.type, "livemode": bool(event.livemode)}
            )
            if created:
                _dispatch(event)
    except Exception:  # noqa: BLE001 - rolled back, Stripe will retry the event
        logger.exception("Stripe webhook %s could not be processed", event.type)
        return 500
    return 200


def _dispatch(event):
    obj = event.data.object
    if event.type == "checkout.session.completed":
        if _get(obj, "mode") != "subscription":
            return
        reference = str(_get(obj, "client_reference_id", ""))
        household = Household.objects.filter(pk=int(reference)).first() if reference.isdigit() else None
        subscription = _get(obj, "subscription")
        if isinstance(subscription, str):
            subscription = _retrieve_subscription(subscription)
        if subscription:
            apply_subscription(subscription, household)
    elif event.type in SUBSCRIPTION_EVENTS:
        apply_subscription(obj)
    elif event.type == "invoice.payment_failed":
        _notify_payment_failed(obj)


def _notify_payment_failed(invoice):
    customer_id = _object_id(_get(invoice, "customer"))
    row = Subscription.objects.filter(stripe_customer_id=customer_id).select_related("household").first() if customer_id else None
    if row is None:
        return
    plan_url = f"{settings.SITE_URL.rstrip('/')}{reverse('billing:plan')}" if settings.SITE_URL else ""
    admins = row.household.memberships.filter(role=Role.ADMIN).select_related("user")
    for membership in admins:
        send_email(
            "payment_failed", membership.user.email,
            f"No hemos podido cobrar Premium de «{row.household.name}»",
            {"household": row.household, "plan_url": plan_url},
        )
