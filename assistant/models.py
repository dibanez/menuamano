from django.conf import settings
from django.db import models


class AIRequestLog(models.Model):
    """Usage and latency of each provider call. Stores no prompt or response content."""

    class Status(models.TextChoices):
        OK = "ok", "Correcta"
        REFUSED = "refused", "Rechazada por el modelo"
        INCOMPLETE = "incomplete", "Incompleta"
        INVALID = "invalid", "Esquema inválido"
        ERROR = "error", "Error del proveedor"
        TIMEOUT = "timeout", "Tiempo agotado"
        NOT_CONFIGURED = "not_configured", "Sin configurar"

    class KeySource(models.TextChoices):
        SERVER = "server", "Clave del servidor"
        DEVICE = "device", "Clave del dispositivo"

    household = models.ForeignKey("households.Household", null=True, on_delete=models.SET_NULL, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    provider = models.CharField(max_length=16)
    # Only server calls cost money and count against the Premium quota; device calls use a person's own key.
    key_source = models.CharField(max_length=8, choices=KeySource.choices, default=KeySource.SERVER)
    model = models.CharField(max_length=80, blank=True)
    operation = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=Status.choices)
    error_code = models.CharField(max_length=64, blank=True)
    latency_ms = models.PositiveIntegerField(default=0)
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    request_id = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class Proposal(models.Model):
    """Reviewable set of changes suggested by the assistant. Applied only on explicit request."""

    class Operation(models.TextChoices):
        PLAN_RANGE = "plan_range", "Proponer menú"
        REPLACE_MEAL = "replace_meal", "Reemplazar comida"
        GENERATE_RECIPE = "generate_recipe", "Generar receta"
        IMPORT_RECIPE = "import_recipe", "Importar receta"
        CHAT = "chat", "Chat"

    class Status(models.TextChoices):
        PENDING = "pending", "Pendiente de revisar"
        APPLIED = "applied", "Aplicada"
        DISCARDED = "discarded", "Descartada"
        STALE = "stale", "Desactualizada"

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="proposals")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    operation = models.CharField(max_length=20, choices=Operation.choices)
    provider = models.CharField(max_length=16)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    summary = models.TextField(blank=True)
    # Normalised, server-validated changes. See assistant.services for the item format.
    items = models.JSONField(default=list)
    new_recipes = models.JSONField(default=list, blank=True)
    # Meal versions observed when the proposal was generated, keyed by "YYYY-MM-DD|meal_type".
    base_versions = models.JSONField(default=dict)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    result_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "Tú"
        ASSISTANT = "assistant", "Asistente"

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="chat_messages")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    role = models.CharField(max_length=10, choices=Role.choices)
    text = models.TextField()
    proposal = models.ForeignKey(Proposal, null=True, blank=True, on_delete=models.SET_NULL, related_name="messages")
    is_error = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
