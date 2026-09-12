"""Transactional email: text + HTML templates under templates/emails/."""

import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_email(template, to, subject, context):
    """Send `emails/<template>.txt|.html` to one address.

    Returns True when the provider accepted the message. Never raises: a provider outage must not
    break the flow that triggered the email (callers tell the person what happened instead).
    """
    context = {"brand": "menuamano", **context}
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(f"emails/{template}.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to],
    )
    message.attach_alternative(render_to_string(f"emails/{template}.html", context), "text/html")
    message.tags = [template]  # Mailgun tag through Anymail; ignored by other backends
    try:
        message.send()
    except Exception:  # noqa: BLE001 - any provider/network error is reported, not propagated
        logger.exception("Email %r could not be sent (recipient domain %s)", template, to.rpartition("@")[2])
        return False
    return True
