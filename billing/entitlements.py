"""What each household may use according to its plan. Checked in the backend, not just hidden.

Every feature is free. The assistant works in one of two ways:
* server: Premium households use the server's AI key, with a monthly quota;
* device: the rest use their own key, kept in the browser of each device, which sends it straight
  to the provider. The server never receives it, and those calls cost it nothing.
"""

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from .models import Subscription
from .plans import FREE, PREMIUM, get_plan

AI_SERVER = "server"
AI_DEVICE = "device"

# AI calls that reached the provider and therefore cost money.
BILLABLE_AI_STATUSES = ("ok", "incomplete", "invalid", "refused")

DEVICE_KEY_MESSAGE = (
    "Con el plan gratuito, el asistente usa tu propia clave de IA, guardada solo en este dispositivo. "
    "Configúrala en «IA en este dispositivo» o pasad a Premium, que la incluye."
)


def subscription_for(household):
    return Subscription.objects.filter(household=household).first()


def household_plan(household):
    if not settings.BILLING_ENABLED:
        return get_plan(PREMIUM)  # local development without Stripe: everything unlocked
    subscription = subscription_for(household)
    return get_plan(PREMIUM if subscription and subscription.is_premium else FREE)


def month_start():
    now = timezone.localtime()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def ai_calls(household, since=None):
    """Calls paid with the server's key, ever or since a moment. Demo and device calls are free."""
    from assistant.models import AIRequestLog

    calls = AIRequestLog.objects.filter(
        household=household, status__in=BILLABLE_AI_STATUSES, key_source=AI_SERVER
    ).exclude(provider="demo")
    if since is not None:
        calls = calls.filter(created_at__gte=since)
    return calls.count()


def ai_calls_this_month(household):
    return ai_calls(household, since=month_start())


def ai_mode(household):
    """How the household reaches the assistant: the server's key (Premium) or each device's own key."""
    return AI_SERVER if household_plan(household).has_server_ai else AI_DEVICE


def check_ai(household):
    """(allowed, message) for a request with the server's key. Device requests never need it."""
    plan = household_plan(household)
    if not plan.has_server_ai:
        return False, DEVICE_KEY_MESSAGE
    if ai_calls_this_month(household) >= plan.ai_monthly_limit:
        return False, f"Habéis usado las {plan.ai_monthly_limit} peticiones al asistente de este mes. El cupo se renueva el día 1."
    return True, ""


def can_add_member(household):
    return household.memberships.count() < settings.HOUSEHOLD_MAX_MEMBERS


def member_limit_message():
    return f"El hogar ya tiene el máximo de {settings.HOUSEHOLD_MAX_MEMBERS} personas con cuenta."


@dataclass
class Usage:
    members: int
    max_members: int
    ai_calls: int
    ai_limit: int


def usage(household):
    plan = household_plan(household)
    return Usage(
        members=household.memberships.count(), max_members=plan.max_members,
        ai_calls=ai_calls_this_month(household), ai_limit=plan.ai_monthly_limit,
    )
