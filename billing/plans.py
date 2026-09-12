"""Plan catalogue. Stripe charges the prices; the labels here are only for display."""

from dataclasses import dataclass

from django.conf import settings

FREE = "free"
PREMIUM = "premium"


@dataclass(frozen=True)
class Plan:
    code: str
    name: str
    max_members: int
    ai_monthly_limit: int  # 0 = no AI assistant

    @property
    def has_ai(self):
        return self.ai_monthly_limit > 0


def get_plan(code):
    if code == PREMIUM:
        return Plan(PREMIUM, "Premium", settings.PREMIUM_MAX_MEMBERS, settings.PREMIUM_AI_MONTHLY_LIMIT)
    return Plan(FREE, "Gratis", settings.FREE_MAX_MEMBERS, 0)


def price_labels():
    return {"monthly": settings.PREMIUM_PRICE_MONTHLY_LABEL, "yearly": settings.PREMIUM_PRICE_YEARLY_LABEL}
