"""Store delivery events that Mailgun reports through Anymail's tracking webhook."""

import logging

from anymail.signals import tracking
from django.dispatch import receiver

from .models import EmailEvent

logger = logging.getLogger(__name__)

PROBLEM_EVENTS = {"bounced", "rejected", "failed", "complained"}


@receiver(tracking, dispatch_uid="store_email_tracking_event")
def store_tracking_event(sender, event, esp_name, **kwargs):
    # Exceptions here would make Anymail answer 400 and the provider retry: log them instead.
    try:
        values = {
            "event_type": (event.event_type or "unknown")[:20],
            "recipient": (event.recipient or "")[:254],
            "message_id": (event.message_id or "")[:255],
            "reject_reason": (event.reject_reason or "")[:20],
            "description": (event.description or event.mta_response or "")[:500],
            "esp_name": (esp_name or "")[:30],
            "occurred_at": event.timestamp,
        }
        if event.event_id:
            EmailEvent.objects.get_or_create(event_id=event.event_id[:255], defaults=values)
        else:
            EmailEvent.objects.create(**values)
        if values["event_type"] in PROBLEM_EVENTS:
            logger.warning("Email %s (%s) for domain %s", values["event_type"], values["reject_reason"] or "-",
                           values["recipient"].rpartition("@")[2])
    except Exception:  # noqa: BLE001
        logger.exception("Could not store email tracking event")
