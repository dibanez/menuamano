"""The «Instalar la app» page: public, indexable and linked from the menu and the landing."""

import re

from django.urls import reverse

from .factories import PASSWORD

URL = "/instalar/"


def test_the_install_page_explains_every_device(client, db):
    response = client.get(URL)
    assert response.status_code == 200
    html = response.content.decode()
    for device in ('data-os="ios"', 'data-os="android"', 'data-os="desktop"'):
        assert device in html
    assert "Añadir a pantalla de inicio" in html and "Instalar app" in html
    # The direct install button only appears where the browser offers it (set up by app.js).
    assert re.search(r"<section[^>]*data-install-now[^>]*hidden", html)


def test_the_install_page_is_indexable_and_in_the_sitemap(client, db, settings):
    settings.SITE_URL = "https://www.menuamano.com"
    head = client.get(URL).content.decode().split("</head>", 1)[0]
    assert '<meta name="robots" content="index, follow">' in head
    assert '<link rel="canonical" href="https://www.menuamano.com/instalar/">' in head
    assert "<loc>https://www.menuamano.com/instalar/</loc>" in client.get("/sitemap.xml").content.decode()


def test_the_landing_invites_to_install_the_app(client, db):
    html = client.get("/").content.decode()
    assert 'class="install-hint hide-in-app"' in html and "En el móvil, como una app" in html
    # The direct button waits for the browser to offer installing; the steps are always linked.
    assert re.search(r"<button[^>]*data-install-direct[^>]*hidden", html)
    assert f'href="{reverse("core:install")}" data-install-guide' in html
    assert "¿Hay app para el móvil?" in html.split("</head>", 1)[0]  # also in the FAQ structured data


def test_the_install_page_is_linked_from_the_menu_and_the_landing(client, household, admin_user):
    assert f'href="{reverse("core:install")}">Instalar la app' in client.get("/").content.decode()  # landing
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert f'href="{reverse("core:install")}">Instalar la app' in client.get(reverse("planning:week")).content.decode()
