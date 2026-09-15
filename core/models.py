from django.db import models


class EmailEvent(models.Model):
    """Delivery event reported by the email provider through its webhook (bounce, complaint…)."""

    event_type = models.CharField("tipo", max_length=20)
    recipient = models.EmailField("destinatario", blank=True)
    message_id = models.CharField(max_length=255, blank=True)
    # Provider event id; used to ignore webhook retries.
    event_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    reject_reason = models.CharField("motivo", max_length=20, blank=True)
    description = models.CharField("detalle", max_length=500, blank=True)
    esp_name = models.CharField("proveedor", max_length=30, blank=True)
    occurred_at = models.DateTimeField("fecha del evento", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "evento de correo"
        verbose_name_plural = "eventos de correo"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} → {self.recipient}"


class ThrottleEvent(models.Model):
    """One attempt at a rate-limited action: signing in, sending an email, importing a recipe…"""

    key = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["key", "created_at"])]
