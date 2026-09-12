from django.conf import settings
from django.db import models

# Stripe subscription statuses that keep Premium features. "past_due" keeps them while Stripe
# retries the payment; "unpaid", "canceled", "incomplete*" and "paused" do not.
PREMIUM_STATUSES = frozenset({"active", "trialing", "past_due"})


class Subscription(models.Model):
    """Premium subscription of a household (one per household, paid by one of its admins)."""

    household = models.OneToOneField("households.Household", on_delete=models.CASCADE, related_name="subscription")
    stripe_customer_id = models.CharField(max_length=64, blank=True, db_index=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, db_index=True)
    status = models.CharField("estado", max_length=24, blank=True)
    price_id = models.CharField(max_length=64, blank=True)
    interval = models.CharField("periodo", max_length=8, blank=True)  # "month" or "year"
    current_period_end = models.DateTimeField("renovación", null=True, blank=True)
    cancel_at_period_end = models.BooleanField("se cancela al final del periodo", default=False)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "suscripción"
        verbose_name_plural = "suscripciones"

    def __str__(self):
        return f"{self.household} ({self.status or 'sin suscripción'})"

    @property
    def is_premium(self):
        return self.status in PREMIUM_STATUSES


class StripeEvent(models.Model):
    """Processed Stripe webhook events, so retries and duplicates are ignored."""

    event_id = models.CharField(max_length=255, unique=True)
    event_type = models.CharField(max_length=80)
    livemode = models.BooleanField(default=False)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-received_at"]
