"""Legal texts metadata and consent records."""

from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

# Bump when the legal texts change in a way that requires accepting them again.
LEGAL_VERSION = "2026-09-12"
LEGAL_UPDATED = date(2026, 9, 15)

REQUIRED_OWNER_SETTINGS = ["LEGAL_OWNER_NAME", "LEGAL_OWNER_TAX_ID", "LEGAL_OWNER_ADDRESS", "LEGAL_CONTACT_EMAIL"]


def owner():
    return {
        "name": settings.LEGAL_OWNER_NAME,
        "tax_id": settings.LEGAL_OWNER_TAX_ID,
        "address": settings.LEGAL_OWNER_ADDRESS,
        "email": settings.LEGAL_CONTACT_EMAIL,
        "registry": settings.LEGAL_REGISTRY,
        "hosting": settings.LEGAL_HOSTING_PROVIDER,
    }


def missing_owner_settings():
    return [name for name in REQUIRED_OWNER_SETTINGS if not getattr(settings, name, "")]


def needs_consent(user):
    return bool(user and user.is_authenticated) and (
        user.legal_version != LEGAL_VERSION or user.health_consent_at is None or user.terms_accepted_at is None
    )


def record_consent(user):
    now = timezone.now()
    # request.user is a lazy wrapper, so do not rely on type(user) to find the model.
    get_user_model().objects.filter(pk=user.pk).update(
        terms_accepted_at=now, health_consent_at=now, legal_version=LEGAL_VERSION
    )
    user.terms_accepted_at = user.health_consent_at = now
    user.legal_version = LEGAL_VERSION
