import logging
import re

from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

GTM_ID_RE = re.compile(r"^GTM-[A-Z0-9]{4,12}$")


def _marketing_page(path):
    """The landing, the legal pages and «Instalar la app»: never sign-in, sign-up or invitation pages."""
    return path in (reverse("core:home"), reverse("core:install")) or path.startswith(reverse("core:legal"))


def analytics(request):
    """Google Tag Manager container for the current page, if any.

    With the default scope it only loads for signed-out visitors on marketing pages: the app
    carries names and health data, sign-in pages carry passwords and invitation links carry tokens.
    """
    container = (settings.GTM_CONTAINER_ID or "").strip()
    if not container:
        return {}
    if not GTM_ID_RE.match(container):
        logger.warning("Ignoring invalid GTM_CONTAINER_ID")
        return {}
    user = getattr(request, "user", None)
    signed_in = bool(user and user.is_authenticated)
    if settings.GTM_SCOPE != "all" and (signed_in or not _marketing_page(request.path)):
        return {}
    request.loads_tag_manager = True  # the Content-Security-Policy allows Google's tag hosts
    return {"gtm_id": container, "cookie_banner": settings.COOKIE_CONSENT_BANNER}


def security(request):
    return {"csp_nonce": getattr(request, "csp_nonce", "")}
