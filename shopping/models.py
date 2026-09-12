from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from foods.models import Category, Unit


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
    def is_surplus(self):
        """Bought but no longer needed by the plan (kept, never deleted)."""
        return not self.is_manual and self.surplus_quantity > 0
