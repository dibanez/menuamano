from django.contrib import admin

from .models import Recipe, RecipeIngredient, RecipeStep


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    extra = 0


class RecipeStepInline(admin.TabularInline):
    model = RecipeStep
    extra = 0


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ["name", "household", "origin", "review_status", "version"]
    list_filter = ["origin", "review_status"]
    search_fields = ["name"]
    inlines = [RecipeIngredientInline, RecipeStepInline]
