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
    ai_monthly_limit: int = 0  # AI requests per calendar month, renewed on day 1
    ai_total_limit: int = 0  # trial AI requests for the household's whole life, never renewed

    @property
    def has_ai(self):
        return self.ai_monthly_limit > 0 or self.ai_total_limit > 0

    @property
    def ai_limit(self):
        return self.ai_monthly_limit or self.ai_total_limit

    @property
    def ai_renews(self):
        return self.ai_monthly_limit > 0


def get_plan(code):
    if code == PREMIUM:
        return Plan(PREMIUM, "Premium", settings.PREMIUM_MAX_MEMBERS, ai_monthly_limit=settings.PREMIUM_AI_MONTHLY_LIMIT)
    return Plan(FREE, "Gratis", settings.FREE_MAX_MEMBERS, ai_total_limit=settings.FREE_AI_TOTAL_LIMIT)


def price_labels():
    return {"monthly": settings.PREMIUM_PRICE_MONTHLY_LABEL, "yearly": settings.PREMIUM_PRICE_YEARLY_LABEL}
