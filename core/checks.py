from django.conf import settings
from django.core.checks import Warning, register

from .legal import missing_owner_settings


@register()
def legal_owner_check(app_configs, **kwargs):
    """Warn in deployed environments when the legal pages would show placeholders."""
    if settings.DEBUG:
        return []
    missing = missing_owner_settings()
    if not missing:
        return []
    return [
        Warning(
            "Legal owner details are missing: the legal notice and privacy policy show placeholders.",
            hint="Set " + ", ".join(missing) + ".",
            id="menuamano.W001",
        )
    ]
