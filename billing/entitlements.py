"""What each household may use according to its plan. Checked in the backend, not just hidden."""

from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from .models import Subscription
from .plans import FREE, PREMIUM, get_plan

# AI calls that reached the provider and therefore cost money.
BILLABLE_AI_STATUSES = ("ok", "incomplete", "invalid", "refused")


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


def ai_calls_this_month(household):
    from assistant.models import AIRequestLog

    return (
        AIRequestLog.objects.filter(household=household, created_at__gte=month_start(), status__in=BILLABLE_AI_STATUSES)
        .exclude(provider="demo")
        .count()
    )


def check_ai(household):
    """(allowed, message). The demo provider is free and never counts against the quota."""
    plan = household_plan(household)
    if not plan.has_ai:
        return False, "El asistente con IA forma parte del plan Premium."
    if ai_calls_this_month(household) >= plan.ai_monthly_limit:
        message = f"Habéis usado las {plan.ai_monthly_limit} peticiones al asistente de este mes. El cupo se renueva el día 1."
        if plan.code == FREE:
            message += f" Con Premium tenéis {get_plan(PREMIUM).ai_monthly_limit} al mes."
        return False, message
    return True, ""


def can_add_member(household):
    return household.memberships.count() < household_plan(household).max_members


def member_limit_message(household):
    plan = household_plan(household)
    if plan.code == FREE:
        return f"El plan gratuito admite hasta {plan.max_members} personas con cuenta. Con Premium podéis ser hasta {get_plan(PREMIUM).max_members}."
    return f"El hogar ya tiene el máximo de {plan.max_members} personas con cuenta."


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
