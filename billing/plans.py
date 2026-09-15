"""Plan catalogue. Stripe charges the prices; the labels here are only for display.

Every feature is free. What Premium adds is the assistant with the server's AI key, so nobody has
to bring their own.
"""

from dataclasses import dataclass

from django.conf import settings

FREE = "free"
PREMIUM = "premium"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    ai_monthly_limit: int = 0  # requests with the server's AI key per calendar month, renewed on day 1

    @property
    def max_members(self):
        return settings.HOUSEHOLD_MAX_MEMBERS

    @property
    def has_server_ai(self):
        return self.ai_monthly_limit > 0


def get_plan(code):
    if code == PREMIUM:
        return Plan(PREMIUM, "Premium", ai_monthly_limit=settings.PREMIUM_AI_MONTHLY_LIMIT)
    return Plan(FREE, "Gratis")


def price_labels():
    return {"monthly": settings.PREMIUM_PRICE_MONTHLY_LABEL, "yearly": settings.PREMIUM_PRICE_YEARLY_LABEL}
