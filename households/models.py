from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.db import models

from core.choices import MealType, default_meal_types, sort_meal_types


class Household(models.Model):
    name = models.CharField("nombre", max_length=80)
    enabled_meal_types = ArrayField(
        models.CharField(max_length=16, choices=MealType.choices),
        default=default_meal_types,
        verbose_name="tipos de comida activos",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "hogar"
        verbose_name_plural = "hogares"

    def __str__(self):
        return self.name

    @property
    def meal_types(self):
        """Enabled meal types in canonical day order."""
        return sort_meal_types(self.enabled_meal_types)


class Role(models.TextChoices):
    ADMIN = "admin", "Administrador"
    EDITOR = "editor", "Editor"
    READER = "reader", "Lector"


class Membership(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    household = models.ForeignKey(Household, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField("rol", max_length=10, choices=Role.choices, default=Role.READER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "miembro"
        verbose_name_plural = "miembros"
        constraints = [models.UniqueConstraint(fields=["user", "household"], name="unique_membership")]

    def __str__(self):
        return f"{self.user} @ {self.household} ({self.role})"

    @property
    def is_admin(self):
        return self.role == Role.ADMIN

    @property
    def can_edit(self):
        return self.role in (Role.ADMIN, Role.EDITOR)
