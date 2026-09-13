"""The site installs as a web app: manifest, service worker and offline page."""

import json

from django.urls import reverse

from .factories import PASSWORD, make_user


def test_the_manifest_describes_an_installable_app(client, db):
    response = client.get("/manifest.webmanifest")
    assert response.status_code == 200 and response["Content-Type"].startswith("application/manifest+json")
    data = json.loads(response.content)
    assert data["name"] == "menuamano" and data["display"] == "standalone" and data["start_url"] == "/"
    assert data["theme_color"] == "#2c7a4b" and data["lang"] == "es"
    sizes = {(icon["sizes"], icon["purpose"]) for icon in data["icons"]}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes
    assert [s["url"] for s in data["shortcuts"]] == ["/", "/calendario/", "/compra/", "/asistente/"]


def test_the_service_worker_is_served_from_the_root_and_never_stale(client, db):
    response = client.get("/sw.js")
    assert response.status_code == 200 and response["Content-Type"].startswith("text/javascript")
    assert response["Cache-Control"] == "no-cache" and response["Service-Worker-Allowed"] == "/"
    body = response.content.decode()
    assert 'const CACHE = "menuamano-' in body and '"/offline/"' in body
    assert 'request.method !== "GET"' in body  # forms are never touched
    assert 'cache: "reload"' in body  # a new worker stores current files, not the HTTP cache's


def test_the_offline_page_is_never_stale(client, db):
    assert "no-cache" in client.get("/offline/")["Cache-Control"]


def test_the_offline_page_carries_no_personal_data(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get("/offline/").content.decode()
    assert "Sin conexión" in html
    assert "csrfmiddlewaretoken" not in html and household.name not in html and admin_user.email not in html


def test_pages_link_the_manifest_and_ios_tags(client, db):
    head = client.get("/").content.decode().split("</head>", 1)[0]
    assert f'<link rel="manifest" href="{reverse("core:manifest")}">' in head
    assert 'name="apple-mobile-web-app-capable" content="yes"' in head


def test_app_files_are_served_before_the_legal_consent(client, db):
    user = make_user("pendiente@example.com", consented=False)
    client.force_login(user)
    assert client.get("/").status_code == 302  # pages still ask for consent first
    for path in ("/sw.js", "/manifest.webmanifest", "/offline/"):
        assert client.get(path).status_code == 200, path
