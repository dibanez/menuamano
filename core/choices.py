"""Vocabulary shared by several apps."""

from django.db import models


class MealType(models.TextChoices):
    BREAKFAST = "breakfast", "Desayuno"
    LUNCH = "lunch", "Comida"
    SNACK = "snack", "Merienda"
    DINNER = "dinner", "Cena"


MEAL_TYPE_ORDER = [MealType.BREAKFAST, MealType.LUNCH, MealType.SNACK, MealType.DINNER]


def default_meal_types():
    return [str(m) for m in MEAL_TYPE_ORDER]


class Weekday(models.IntegerChoices):
    MONDAY = 0, "Lunes"
    TUESDAY = 1, "Martes"
    WEDNESDAY = 2, "Miércoles"
    THURSDAY = 3, "Jueves"
    FRIDAY = 4, "Viernes"
    SATURDAY = 5, "Sábado"
    SUNDAY = 6, "Domingo"


def sort_meal_types(values):
    order = {str(m): i for i, m in enumerate(MEAL_TYPE_ORDER)}
    return sorted(values, key=lambda v: order.get(str(v), 99))
