from urllib.parse import quote, urlsplit

from django.conf import settings
from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import redirect
from django.urls import reverse

from .legal import needs_consent

HEALTH_PATH = "/healthz"


class HealthCheckMiddleware:
    """Answer container health checks before host validation and the HTTPS redirect.

    Must be the first middleware: probes come over plain HTTP with an internal Host header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path != HEALTH_PATH:
            return self.get_response(request)
        try:
            connection.ensure_connection()
        except DatabaseError:
            return HttpResponse("database unavailable", status=503, content_type="text/plain")
        return HttpResponse("ok", content_type="text/plain")


RETIRED_WEBHOOK_PREFIX = "/anymail/"


class RetiredWebhookMiddleware:
    """Refuse calls to the removed Mailgun webhook quietly, so Mailgun stops sending them.

    Mailgun retries a webhook for hours after any error except 406 Not Acceptable, which it
    treats as a final rejection. The flag tells Django the response is already accounted for,
    so each call does not add a "Not Found" warning to the logs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(RETIRED_WEBHOOK_PREFIX):
            return self.get_response(request)
        response = HttpResponse("webhook removed", status=406, content_type="text/plain")
        response._has_been_logged = True
        return response


class CanonicalHostMiddleware:
    """Send the site's other host (bare domain or www) to SITE_URL's host, keeping the path.

    Only GET and HEAD are redirected, so a form or a webhook posted to the other host still works.
    Unrelated hosts are left alone.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        target = urlsplit(settings.SITE_URL) if settings.SITE_URL else None
        if target and target.netloc and request.method in ("GET", "HEAD"):
            host = request.get_host()
            if host != target.netloc and target.netloc in (f"www.{host}", host.removeprefix("www.")):
                return HttpResponsePermanentRedirect(f"{target.scheme}://{target.netloc}{request.get_full_path()}")
        return self.get_response(request)


class LegalConsentMiddleware:
    """Signed-in people must accept the current terms and the health-data consent to use the app."""

    EXEMPT_PREFIXES = (
        "/legal/", "/cuenta/condiciones/", "/cuenta/salir/", "/static/", "/admin/",
        "/plan/stripe/", HEALTH_PATH,
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if needs_consent(user) and not request.path.startswith(self.EXEMPT_PREFIXES):
            return redirect(f"{reverse('accounts:legal_consent')}?next={quote(request.get_full_path())}")
        return self.get_response(request)
