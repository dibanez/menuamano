from django.contrib import admin

from .models import Ingredient, UnitConversion


class UnitConversionInline(admin.TabularInline):
    model = UnitConversion
    extra = 0


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "category", "trait_info_complete", "is_processed", "source"]
    list_filter = ["category", "trait_info_complete", "is_processed", "source"]
    search_fields = ["name", "aliases"]
    inlines = [UnitConversionInline]
