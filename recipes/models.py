from decimal import Decimal

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models

from foods.models import Unit


class Recipe(models.Model):
    class Difficulty(models.TextChoices):
        EASY = "easy", "Fácil"
        MEDIUM = "medium", "Media"
        HARD = "hard", "Elaborada"

    class Origin(models.TextChoices):
        MANUAL = "manual", "Manual"
        DEMO = "demo", "Demostración"
        AI = "ai", "Generada por IA"
        IMPORTED = "imported", "Importada de la web"

    class ReviewStatus(models.TextChoices):
        REVIEWED = "reviewed", "Revisada"
        NEEDS_REVIEW = "needs_review", "Pendiente de revisión"

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="recipes")
    name = models.CharField("nombre", max_length=120)
    description = models.TextField("descripción", blank=True)
    base_servings = models.PositiveSmallIntegerField("raciones base", default=4, validators=[MinValueValidator(1)])
    prep_minutes = models.PositiveSmallIntegerField("preparación (min)", default=0)
    cook_minutes = models.PositiveSmallIntegerField("cocción (min)", default=0)
    equipment = models.CharField("equipamiento", max_length=200, blank=True)
    advance_note = models.CharField(
        "preparar la víspera", max_length=120, blank=True,
        help_text="Por ejemplo: poner los garbanzos en remojo, sacar el pescado del congelador. Sale en el recordatorio del día anterior.",
    )
    difficulty = models.CharField("dificultad", max_length=8, choices=Difficulty.choices, default=Difficulty.EASY)
    tags = ArrayField(models.CharField(max_length=30), default=list, blank=True, verbose_name="etiquetas")
    origin = models.CharField("origen", max_length=8, choices=Origin.choices, default=Origin.MANUAL)
    source_url = models.URLField("receta original", max_length=500, blank=True, help_text="Enlace a la página de donde viene.")
    review_status = models.CharField(
        "estado de revisión", max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.REVIEWED
    )
    version = models.PositiveIntegerField(default=1)
    is_archived = models.BooleanField("archivada", default=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "receta"
        verbose_name_plural = "recetas"
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def total_minutes(self):
        return self.prep_minutes + self.cook_minutes


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey("foods.Ingredient", on_delete=models.PROTECT, related_name="recipe_uses")
    quantity = models.DecimalField(
        "cantidad", max_digits=10, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))], help_text="Vacío = al gusto (no se añade a la compra).",
    )
    unit = models.CharField("unidad", max_length=8, choices=Unit.choices, default=Unit.G)
    note = models.CharField("nota", max_length=80, blank=True)
    optional = models.BooleanField("opcional", default=False)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]


class RecipeStep(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField(default=0)
    text = models.TextField("paso")

    class Meta:
        ordering = ["order", "id"]


class RecipeFavorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorite_recipes")
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="favorites")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "recipe"], name="unique_favorite")]
