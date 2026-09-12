"""Revalidate upcoming meals whenever mandatory restrictions change."""

from contextlib import contextmanager
from contextvars import ContextVar

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import DinerRestriction

_batching = ContextVar("batching_restriction_changes", default=False)


@contextmanager
def batch_restriction_changes(household):
    """Group several restriction changes and revalidate the household's meals once."""
    token = _batching.set(True)
    try:
        yield
    finally:
        _batching.reset(token)
    from planning.services import revalidate_upcoming

    revalidate_upcoming(household)


@receiver([post_save, post_delete], sender=DinerRestriction, dispatch_uid="revalidate_on_restriction_change")
def revalidate_on_restriction_change(sender, instance, **kwargs):
    if _batching.get():
        return
    from planning.services import revalidate_upcoming

    revalidate_upcoming(instance.diner.household)
