from django.conf import settings

from .entitlements import household_plan


def billing(request):
    household = getattr(request, "household", None)
    context = {"billing_enabled": settings.BILLING_ENABLED}
    if household is not None:
        context["billing_plan"] = household_plan(household)
    return context
