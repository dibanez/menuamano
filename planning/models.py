from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from core.choices import MealType, Weekday
from foods.models import Trait, Unit


class MealMode(models.TextChoices):
    COOK = "cook", "Cocinar en casa"
    EAT_OUT = "eat_out", "Comer fuera"
    ORDER = "order", "Pedir comida"
    LEFTOVERS = "leftovers", "Aprovechar sobras"
    FREE = "free", "Libre"
    PENDING = "pending", "Pendiente"


# Only these modes add ingredients to the shopping list.
MODES_WITH_SHOPPING = frozenset({MealMode.COOK})
# Modes where recipes make sense (leftovers may reference what is being reused).
MODES_WITH_RECIPES = frozenset({MealMode.COOK, MealMode.LEFTOVERS})


class SafetyStatus(models.TextChoices):
    OK = "ok", "Compatible según los datos"
    UNKNOWN = "unknown", "Requiere revisión"
    CONFLICT = "conflict", "Incompatible"
    NOT_APPLICABLE = "na", "Sin recetas"


class Meal(models.Model):
    class Source(models.TextChoices):
        MANUAL = "manual", "Manual"
        GENERATED = "generated", "Generada"
        AI = "ai", "Propuesta de IA"

    class Outcome(models.TextChoices):
        PENDING = "pending", "Sin registrar"
        AS_PLANNED = "as_planned", "Como estaba previsto"
        CHANGED = "changed", "Se comió otra cosa"
        SKIPPED = "skipped", "No se hizo"

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="meals")
    date = models.DateField("fecha")
    meal_type = models.CharField("tipo", max_length=16, choices=MealType.choices)
    mode = models.CharField("modalidad", max_length=10, choices=MealMode.choices, default=MealMode.PENDING)
    notes = models.TextField("notas", blank=True)
    locked = models.BooleanField(
        "protegida", default=False, help_text="Las regeneraciones no modifican una comida protegida."
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    # Optimistic concurrency token: bumped on every change so stale AI proposals are detected.
    version = models.PositiveIntegerField(default=1)
    safety_status = models.CharField(max_length=10, choices=SafetyStatus.choices, default=SafetyStatus.NOT_APPLICABLE)
    safety_issues = models.JSONField(default=list, blank=True)
    safety_checked_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField("qué se comió", max_length=12, choices=Outcome.choices, default=Outcome.PENDING)
    outcome_notes = models.CharField("detalle de lo consumido", max_length=200, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "comida"
        verbose_name_plural = "comidas"
        ordering = ["date", "meal_type"]
        constraints = [
            models.UniqueConstraint(fields=["household", "date", "meal_type"], name="unique_meal_slot")
        ]

    def __str__(self):
        return f"{self.get_meal_type_display()} {self.date:%d/%m/%Y}"

    @property
    def servings(self):
        return sum((a.portion for a in self.attendees.all()), Decimal("0"))

    @property
    def needs_shopping(self):
        return self.mode in MODES_WITH_SHOPPING


class MealAttendee(models.Model):
    """A household diner or a guest attending a meal."""

    meal = models.ForeignKey(Meal, on_delete=models.CASCADE, related_name="attendees")
    diner = models.ForeignKey("diners.Diner", null=True, blank=True, on_delete=models.CASCADE)
    guest_name = models.CharField("invitado", max_length=60, blank=True)
    guest_traits = ArrayField(
        models.CharField(max_length=16, choices=Trait.choices), default=list, blank=True,
        verbose_name="restricciones del invitado",
    )
    guest_notes = models.CharField("otras restricciones del invitado", max_length=120, blank=True)
    portion = models.DecimalField(
        max_digits=4, decimal_places=2, default=Decimal("1.00"), validators=[MinValueValidator(Decimal("0.1"))]
    )

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(diner__isnull=False) | ~Q(guest_name=""), name="attendee_is_someone"),
            models.UniqueConstraint(
                fields=["meal", "diner"], condition=Q(diner__isnull=False), name="unique_meal_diner"
            ),
        ]

    @property
    def label(self):
        return self.diner.alias if self.diner_id else f"{self.guest_name} (invitado)"


class MealRecipe(models.Model):
    """Copy of a recipe as used in a meal. Editing the recipe never changes it silently."""

    meal = models.ForeignKey(Meal, on_delete=models.CASCADE, related_name="recipes")
    recipe = models.ForeignKey("recipes.Recipe", null=True, blank=True, on_delete=models.SET_NULL, related_name="meal_uses")
    recipe_version = models.PositiveIntegerField(default=1)
    name = models.CharField(max_length=120)
    base_servings = models.PositiveSmallIntegerField(default=4)
    servings_override = models.DecimalField(
        "raciones", max_digits=5, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.1"))],
        help_text="Vacío = las raciones de los asistentes.",
    )
    prep_minutes = models.PositiveSmallIntegerField(default=0)
    cook_minutes = models.PositiveSmallIntegerField(default=0)
    steps = models.JSONField(default=list, blank=True)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return self.name

    def effective_servings(self, meal_servings=None):
        if self.servings_override is not None:
            return self.servings_override
        return meal_servings if meal_servings is not None else self.meal.servings

    @property
    def is_outdated(self):
        return self.recipe_id is not None and self.recipe.version > self.recipe_version


class MealRecipeIngredient(models.Model):
    meal_recipe = models.ForeignKey(MealRecipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey("foods.Ingredient", on_delete=models.PROTECT, related_name="+")
    # Quantity for the recipe's base servings. Null = "to taste".
    quantity = models.DecimalField(max_digits=10, decimal_places=3, null=True, blank=True)
    unit = models.CharField(max_length=8, choices=Unit.choices)
    note = models.CharField(max_length=80, blank=True)
    optional = models.BooleanField(default=False)
    substituted_for = models.ForeignKey(
        "foods.Ingredient", null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="Ingrediente original de la receta si esta línea es una sustitución.",
    )
    # Total quantity for this meal typed by a person, replacing the scaled value.
    manual_quantity = models.DecimalField(
        "cantidad corregida", max_digits=10, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class RecurringRule(models.Model):
    """Weekly rule, e.g. «cenamos fuera todos los viernes». Date exceptions take precedence."""

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="recurring_rules")
    weekday = models.PositiveSmallIntegerField("día", choices=Weekday.choices)
    meal_type = models.CharField("comida", max_length=16, choices=MealType.choices)
    mode = models.CharField("modalidad", max_length=10, choices=MealMode.choices)
    notes = models.CharField("nota", max_length=120, blank=True)
    valid_from = models.DateField("desde", null=True, blank=True)
    valid_until = models.DateField("hasta", null=True, blank=True)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        ordering = ["weekday", "meal_type"]

    def applies_to(self, day):
        if not self.is_active or day.weekday() != self.weekday:
            return False
        if self.valid_from and day < self.valid_from:
            return False
        if self.valid_until and day > self.valid_until:
            return False
        return True


class DateException(models.Model):
    """Explicit override for one date and meal type. Always wins over recurring rules."""

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="date_exceptions")
    date = models.DateField("fecha")
    meal_type = models.CharField("comida", max_length=16, choices=MealType.choices)
    mode = models.CharField("modalidad", max_length=10, choices=MealMode.choices, blank=True)
    override_attendance = models.BooleanField("fijar asistentes", default=False)
    attendees = models.ManyToManyField("diners.Diner", blank=True, verbose_name="asistentes")
    notes = models.CharField("nota", max_length=120, blank=True)

    class Meta:
        ordering = ["date", "meal_type"]
        constraints = [
            models.UniqueConstraint(fields=["household", "date", "meal_type"], name="unique_date_exception")
        ]
