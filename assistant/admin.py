from django.contrib import admin

from .models import AIRequestLog, Proposal


@admin.register(AIRequestLog)
class AIRequestLogAdmin(admin.ModelAdmin):
    list_display = ["created_at", "provider", "model", "operation", "status", "latency_ms", "input_tokens", "output_tokens"]
    list_filter = ["provider", "status", "operation"]


@admin.register(Proposal)
class ProposalAdmin(admin.ModelAdmin):
    list_display = ["created_at", "household", "operation", "provider", "status"]
    list_filter = ["status", "operation", "provider"]
