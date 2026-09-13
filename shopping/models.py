from decimal import ROUND_CEILING, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from foods.models import UNIT_INFO, Category, Dimension, Unit


class ShoppingList(models.Model):
    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="shopping_lists")
    name = models.CharField("nombre", max_length=80, blank=True)
    start_date = models.DateField("desde")
    end_date = models.DateField("hasta")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    recalculated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "lista de compra"
        verbose_name_plural = "listas de compra"
        ordering = ["-start_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=models.F("start_date")), name="shopping_range_valid")
        ]

    def __str__(self):
        return self.name or f"Compra {self.start_date:%d/%m} – {self.end_date:%d/%m}"


class ShoppingItem(models.Model):
    shopping_list = models.ForeignKey(ShoppingList, on_delete=models.CASCADE, related_name="items")
    # Aggregation key of computed items (ingredient + unit family). Empty for manual items.
    key = models.CharField(max_length=120, blank=True)
    ingredient = models.ForeignKey("foods.Ingredient", null=True, blank=True, on_delete=models.PROTECT)
    name = models.CharField("artículo", max_length=100)
    category = models.CharField("categoría", max_length=24, choices=Category.choices, default=Category.OTHER)
    unit = models.CharField("unidad", max_length=8, choices=Unit.choices, blank=True)
    needed_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    purchased_quantity = models.DecimalField(
        "comprado", max_digits=12, decimal_places=3, default=Decimal("0"), validators=[MinValueValidator(Decimal("0"))]
    )
    is_manual = models.BooleanField(default=False)
    # True when part of the quantity comes from an approximate piece/volume ↔ grams equivalence.
    is_approximate = models.BooleanField(default=False)
    # Pantry: staples («siempre en casa») are listed apart, to check whether some is left;
    # `pantry_quantity` is the part of the plan's need already at home, not in `needed_quantity`.
    is_staple = models.BooleanField(default=False)
    pantry_quantity = models.DecimalField(max_digits=12, decimal_places=3, default=Decimal("0"))
    manual_note = models.CharField("nota", max_length=120, blank=True)
    sources = models.JSONField(default=list, blank=True)
    purchased_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    purchased_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "name"]
        constraints = [
            # Makes recalculation idempotent: one computed row per aggregation key.
            models.UniqueConstraint(fields=["shopping_list", "key"], condition=~Q(key=""), name="unique_item_key"),
        ]

    def __str__(self):
        return self.name

    @property
    def pending_quantity(self):
        return max(self.needed_quantity - self.purchased_quantity, Decimal("0"))

    @property
    def surplus_quantity(self):
        return max(self.purchased_quantity - self.needed_quantity, Decimal("0"))

    @property
    def is_done(self):
        if self.needed_quantity > 0:
            return self.purchased_quantity >= self.needed_quantity
        # Manual items without quantity are simply ticked; surplus rows are already bought.
        return self.purchased_quantity > 0

    @property
    def suggested_purchase(self):
        """Whole number to buy for pieces (1.9 eggs → 2). None when it adds nothing."""
        if self.is_manual or self.unit not in Unit.values:
            return None
        if UNIT_INFO[Unit(self.unit)][0] != Dimension.COUNT:
            return None
        pending = self.pending_quantity
        rounded = pending.to_integral_value(rounding=ROUND_CEILING)
        if pending <= 0 or rounded == pending:
            return None
        return rounded

    @property
    def is_surplus(self):
        """Bought but no longer needed by the plan (kept, never deleted)."""
        return not self.is_manual and self.surplus_quantity > 0

    @property
    def is_covered(self):
        """Everything the plan needs is already at home, and nothing was bought."""
        return (
            not self.is_manual and self.needed_quantity == 0 and self.pantry_quantity > 0
            and self.purchased_quantity == 0
        )


class PantryItem(models.Model):
    """What a household has at home. Typed by people; nothing is consumed automatically."""

    class Kind(models.TextChoices):
        STAPLE = "staple", "Siempre en casa"
        STOCK = "stock", "Tenemos una cantidad"

    household = models.ForeignKey("households.Household", on_delete=models.CASCADE, related_name="pantry_items")
    ingredient = models.ForeignKey("foods.Ingredient", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField("cómo", max_length=10, choices=Kind.choices, default=Kind.STAPLE)
    quantity = models.DecimalField(
        "cantidad", max_digits=10, decimal_places=3, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit = models.CharField("unidad", max_length=8, choices=Unit.choices, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "artículo de la despensa"
        verbose_name_plural = "despensa"
        ordering = ["ingredient__name"]
        constraints = [models.UniqueConstraint(fields=["household", "ingredient"], name="unique_pantry_ingredient")]

    def __str__(self):
        return f"{self.ingredient} ({self.household})"
