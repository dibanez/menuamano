from django.contrib import admin

from .models import EmailEvent


@admin.register(EmailEvent)
class EmailEventAdmin(admin.ModelAdmin):
    list_display = ["created_at", "event_type", "recipient", "reject_reason", "esp_name"]
    list_filter = ["event_type", "reject_reason", "esp_name"]
    search_fields = ["recipient", "message_id"]
    readonly_fields = [f.name for f in EmailEvent._meta.fields]
