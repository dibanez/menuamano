"""Revalidate upcoming meals whenever mandatory restrictions change."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import DinerRestriction


@receiver([post_save, post_delete], sender=DinerRestriction, dispatch_uid="revalidate_on_restriction_change")
def revalidate_on_restriction_change(sender, instance, **kwargs):
    from planning.services import revalidate_upcoming

    revalidate_upcoming(instance.diner.household)
