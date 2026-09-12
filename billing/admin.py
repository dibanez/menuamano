from django.contrib import admin

from .models import StripeEvent, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ["household", "status", "interval", "current_period_end", "cancel_at_period_end", "updated_at"]
    list_filter = ["status", "interval", "cancel_at_period_end"]
    search_fields = ["household__name", "stripe_customer_id", "stripe_subscription_id"]
    readonly_fields = [f.name for f in Subscription._meta.fields]


@admin.register(StripeEvent)
class StripeEventAdmin(admin.ModelAdmin):
    list_display = ["received_at", "event_type", "event_id", "livemode"]
    list_filter = ["event_type", "livemode"]
