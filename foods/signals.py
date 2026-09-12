"""Revalidate upcoming meals that use an ingredient whose dietary data changed."""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Ingredient


@receiver(post_save, sender=Ingredient, dispatch_uid="revalidate_on_ingredient_change")
def revalidate_on_ingredient_change(sender, instance, created, **kwargs):
    if created:
        return
    from planning.models import Meal
    from planning.services import revalidate_meal

    meals = Meal.objects.filter(
        date__gte=timezone.localdate(), recipes__ingredients__ingredient=instance
    ).select_related("household").distinct()
    for meal in meals:
        revalidate_meal(meal)
