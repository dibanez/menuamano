import logging
import re

from django.conf import settings

logger = logging.getLogger(__name__)

GTM_ID_RE = re.compile(r"^GTM-[A-Z0-9]{4,12}$")


def analytics(request):
    """Google Tag Manager container for the current page, if any."""
    container = (settings.GTM_CONTAINER_ID or "").strip()
    if not container:
        return {}
    if not GTM_ID_RE.match(container):
        logger.warning("Ignoring invalid GTM_CONTAINER_ID")
        return {}
    user = getattr(request, "user", None)
    signed_in = bool(user and user.is_authenticated)
    if settings.GTM_SCOPE != "all" and signed_in:
        return {}  # keep names and health data of the app out of analytics
    return {"gtm_id": container, "cookie_banner": settings.COOKIE_CONSENT_BANNER}
