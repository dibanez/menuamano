from django.contrib import admin

from .models import Ingredient


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "category", "trait_info_complete", "is_processed", "source"]
    list_filter = ["category", "trait_info_complete", "is_processed", "source"]
    search_fields = ["name", "aliases"]
