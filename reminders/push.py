"""Web push: send a notification to a person's devices.

Messages are encrypted for each device and signed with the server's VAPID key; the browser's push
service (Google, Apple, Mozilla) only relays them. Devices that are gone are forgotten.
"""

import json
import logging

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

TTL_SECONDS = 6 * 60 * 60  # a reminder that arrives much later is no longer useful
TIMEOUT_SECONDS = 10
MAX_FAILURES = 5
GONE = {404, 410}


def configured():
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def subject():
    """Contact for the push services: VAPID_SUBJECT, the legal contact or the site."""
    if settings.VAPID_SUBJECT:
        return settings.VAPID_SUBJECT
    if settings.LEGAL_CONTACT_EMAIL:
        return f"mailto:{settings.LEGAL_CONTACT_EMAIL}"
    return settings.SITE_URL or "mailto:no-reply@localhost"


def _post(subscription, data):
    """Deliver one message. Returns the push service's HTTP status (0 when unreachable)."""
    from pywebpush import WebPushException, webpush

    try:
        response = webpush(
            subscription_info={"endpoint": subscription.endpoint, "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth}},
            data=data, vapid_private_key=settings.VAPID_PRIVATE_KEY, vapid_claims={"sub": subject()},
            ttl=TTL_SECONDS, timeout=TIMEOUT_SECONDS,
        )
    except WebPushException as exc:
        return getattr(exc.response, "status_code", 0) or 0
    except (OSError, ValueError) as exc:  # network errors (requests' included) and malformed keys
        logger.warning("push delivery error: %s", type(exc).__name__)
        return 0
    return response.status_code


def send(subscription, payload):
    status = _post(subscription, json.dumps(payload, ensure_ascii=False))
    if 200 <= status < 300:
        subscription.last_success_at = timezone.now()
        subscription.failures = 0
        subscription.save(update_fields=["last_success_at", "failures"])
        return True
    subscription.failures += 1
    if status in GONE or subscription.failures >= MAX_FAILURES:
        logger.info("push subscription %s removed: status=%s failures=%s", subscription.pk, status, subscription.failures)
        subscription.delete()
    else:
        logger.warning("push subscription %s failed: status=%s", subscription.pk, status)
        subscription.save(update_fields=["failures"])
    return False


def send_to_user(user, payload):
    """Send to every device of the person. Returns how many received it."""
    if not configured():
        return 0
    return sum(send(subscription, payload) for subscription in list(user.push_subscriptions.all()))
