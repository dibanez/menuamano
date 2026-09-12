from datetime import date
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from core.choices import MealType, Weekday
from foods.models import Trait


class Diner(models.Model):
    """Person food is prepared for. May or may not have a user account."""

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="diners")
    alias = models.CharField("nombre o alias", max_length=60)
    birth_date = models.DateField("fecha de nacimiento", null=True, blank=True)
    portion_factor = models.DecimalField(
        "tamaño de ración", max_digits=4, decimal_places=2, default=Decimal("1.00"),
        validators=[MinValueValidator(Decimal("0.10")), MaxValueValidator(Decimal("5.00"))],
        help_text="1 = ración estándar de adulto; 0,5 = media ración.",
    )
    height_cm = models.DecimalField(
        "altura (cm)", max_digits=5, decimal_places=1, null=True, blank=True,
        validators=[MinValueValidator(Decimal("30")), MaxValueValidator(Decimal("250"))],
    )
    notes = models.TextField(
        "otras observaciones", blank=True,
        help_text="Texto libre. No se comprueba automáticamente: no lo uses para alergias.",
    )
    linked_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="diner_profiles",
        verbose_name="cuenta vinculada",
    )
    is_active = models.BooleanField("activo", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "comensal"
        verbose_name_plural = "comensales"
        ordering = ["alias"]

    def __str__(self):
        return self.alias

    @property
    def age(self):
        if not self.birth_date:
            return None
        today = date.today()
        years = today.year - self.birth_date.year
        if (today.month, today.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    @property
    def is_minor(self):
        return self.age is not None and self.age < 18

    @property
    def age_group(self):
        """Coarse group, enough context for menu generation without exact dates."""
        age = self.age
        if age is None:
            return "sin especificar"
        if age < 3:
            return "bebé"
        if age < 12:
            return "infantil"
        if age < 18:
            return "adolescente"
        if age < 65:
            return "adulto"
        return "mayor"


class DinerRestriction(models.Model):
    """Mandatory restriction. Never relaxed to complete a plan."""

    class Kind(models.TextChoices):
        ALLERGY = "allergy", "Alergia"
        INTOLERANCE = "intolerance", "Intolerancia"
        DIET = "diet", "Dieta o creencia"
        OTHER = "other", "Otra restricción"

    diner = models.ForeignKey(Diner, on_delete=models.CASCADE, related_name="restrictions")
    kind = models.CharField("tipo", max_length=12, choices=Kind.choices)
    trait = models.CharField("rasgo", max_length=16, choices=Trait.choices, blank=True)
    ingredient = models.ForeignKey(
        "foods.Ingredient", null=True, blank=True, on_delete=models.CASCADE, verbose_name="ingrediente concreto"
    )
    label = models.CharField("descripción", max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "restricción"
        verbose_name_plural = "restricciones"
        constraints = [
            models.CheckConstraint(
                condition=~Q(trait="") | Q(ingredient__isnull=False), name="restriction_has_target"
            )
        ]

    def __str__(self):
        return self.describe()

    def describe(self):
        target = self.get_trait_display() if self.trait else str(self.ingredient)
        text = f"{self.get_kind_display()}: {target}"
        return f"{text} ({self.label})" if self.label else text


class DinerPreference(models.Model):
    """Negotiable preference. Influences suggestions but never blocks a meal."""

    class Kind(models.TextChoices):
        DISLIKE = "dislike", "No le gusta"
        LIKE = "like", "Le gusta"

    diner = models.ForeignKey(Diner, on_delete=models.CASCADE, related_name="preferences")
    kind = models.CharField("tipo", max_length=8, choices=Kind.choices)
    ingredient = models.ForeignKey("foods.Ingredient", null=True, blank=True, on_delete=models.CASCADE)
    text = models.CharField("detalle", max_length=80, blank=True, help_text="Por ejemplo: «platos de cuchara».")

    class Meta:
        verbose_name = "preferencia"
        verbose_name_plural = "preferencias"
        constraints = [
            models.CheckConstraint(
                condition=~Q(text="") | Q(ingredient__isnull=False), name="preference_has_target"
            )
        ]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.ingredient or self.text}"


class AttendancePattern(models.Model):
    """Usual attendance by weekday and meal type. Missing rows mean the diner attends."""

    diner = models.ForeignKey(Diner, on_delete=models.CASCADE, related_name="attendance_patterns")
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    meal_type = models.CharField(max_length=16, choices=MealType.choices)
    attends = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["diner", "weekday", "meal_type"], name="unique_attendance_pattern")
        ]


class WeightMeasurement(models.Model):
    """Append-only weight history. Access is controlled by `diners.permissions`."""

    diner = models.ForeignKey(Diner, on_delete=models.CASCADE, related_name="weights")
    measured_on = models.DateField("fecha")
    weight_kg = models.DecimalField(
        "peso (kg)", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("1")), MaxValueValidator(Decimal("400"))],
    )
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-measured_on", "-created_at"]


class HealthDataAccess(models.Model):
    """Explicit grant to view and record a diner's weight history."""

    diner = models.ForeignKey(Diner, on_delete=models.CASCADE, related_name="health_access")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="health_access")
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["diner", "user"], name="unique_health_access")]
