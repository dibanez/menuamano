from unittest import mock

from django.db.utils import OperationalError
from django.test import override_settings


@override_settings(ALLOWED_HOSTS=["menuamano.example.com"], SECURE_SSL_REDIRECT=True)
def test_health_check_skips_host_validation_and_https_redirect(client, db):
    response = client.get("/healthz", HTTP_HOST="172.18.0.5:8000")
    assert response.status_code == 200
    assert response.content == b"ok"
    # Any other path keeps the production protections.
    assert client.get("/", HTTP_HOST="172.18.0.5:8000").status_code == 400


def test_health_check_reports_database_failure(client, db):
    with mock.patch("core.middleware.connection.ensure_connection", side_effect=OperationalError("down")):
        response = client.get("/healthz")
    assert response.status_code == 503
