from django.db import connection
from django.db.utils import DatabaseError
from django.http import HttpResponse

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
