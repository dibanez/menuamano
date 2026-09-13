from django.conf import settings
from django.db import models

HOUR_CHOICES = [(hour, f"{hour}:00") for hour in range(16, 23)]


class PushSubscription(models.Model):
    """A device (browser) where a person accepted notifications. The keys encrypt what is sent."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="push_subscriptions")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    user_agent = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    failures = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "dispositivo con notificaciones"
        verbose_name_plural = "dispositivos con notificaciones"


class ReminderPreference(models.Model):
    """Which reminders a person wants for one household, and when they were last sent."""

    membership = models.OneToOneField("households.Membership", on_delete=models.CASCADE, related_name="reminders")
    tomorrow = models.BooleanField(
        "Avisarme de lo que hay mañana", default=True,
        help_text="Con lo que hay que dejar preparado la víspera: poner en remojo, descongelar…",
    )
    hour = models.PositiveSmallIntegerField("Hora del aviso", default=20, choices=HOUR_CHOICES)
    week = models.BooleanField("Avisarme el domingo si la semana siguiente está sin planificar", default=True)
    last_tomorrow_on = models.DateField(null=True, blank=True)
    last_week_on = models.DateField(null=True, blank=True)

    class Meta:
        verbose_name = "preferencia de recordatorios"
        verbose_name_plural = "preferencias de recordatorios"
