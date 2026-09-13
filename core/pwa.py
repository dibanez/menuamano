"""Installable web app: manifest, service worker and offline page.

The service worker caches only static files and the offline page. Pages carry each household's
data and change all the time, so they always come from the network.
"""

import hashlib
import json

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.urls import reverse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

THEME_COLOR = "#2c7a4b"
BACKGROUND_COLOR = "#f5f7f1"
# Bump when the service worker's own logic changes; static changes bump the cache by themselves.
SW_REVISION = "3"
SHELL = ["css/app.css", "js/app.js", "js/htmx.min.js", "img/favicon.svg", "img/icon-192.png"]


def _icon(name, size, purpose="any"):
    return {"src": static(f"img/{name}"), "sizes": f"{size}x{size}", "type": "image/png", "purpose": purpose}


@require_GET
@cache_control(max_age=3600, public=True)
def manifest(request):
    shortcut = [_icon("icon-192.png", 192)]
    data = {
        "id": "/",
        "name": "menuamano",
        "short_name": "menuamano",
        "description": "Las comidas de casa, con las alergias de cada persona y la lista de la compra.",
        "lang": "es",
        "dir": "ltr",
        "start_url": reverse("core:home"),
        "scope": "/",
        "display": "standalone",
        "background_color": BACKGROUND_COLOR,
        "theme_color": THEME_COLOR,
        "categories": ["food", "lifestyle"],
        "icons": [
            _icon("icon-192.png", 192),
            _icon("icon-512.png", 512),
            _icon("icon-maskable-512.png", 512, "maskable"),
        ],
        "shortcuts": [
            {"name": "Hoy", "url": reverse("core:home"), "icons": shortcut},
            {"name": "Calendario", "url": reverse("planning:week"), "icons": shortcut},
            {"name": "Compra", "url": reverse("shopping:current"), "icons": shortcut},
            {"name": "Asistente", "url": reverse("assistant:chat"), "icons": shortcut},
        ],
    }
    return JsonResponse(data, content_type="application/manifest+json", json_dumps_params={"ensure_ascii": False})


@require_GET
def service_worker(request):
    offline_url = reverse("core:offline")
    precache = [offline_url, *(static(path) for path in SHELL)]
    # Hashed static URLs change on every deploy that touches them, and so does the cache name.
    version = hashlib.sha256("|".join([SW_REVISION, *precache]).encode()).hexdigest()[:12]
    body = render_to_string("pwa/sw.js", {
        "cache_name": f"menuamano-{version}", "precache": json.dumps(precache), "offline_url": json.dumps(offline_url),
        "icon_url": json.dumps(static("img/icon-192.png")),
    })
    response = HttpResponse(body, content_type="text/javascript; charset=utf-8")
    response["Cache-Control"] = "no-cache"  # browsers must check for a new worker on every visit
    response["Service-Worker-Allowed"] = "/"
    return response


@require_GET
def install(request):
    """How to install the app on each kind of device. Public, so it can be shared as a link."""
    return render(request, "pwa/install.html", {
        "seo_title": "Instalar menuamano en el móvil o el ordenador",
        "seo_description": (
            "Cómo instalar menuamano como app en iPhone, Android y el ordenador: se abre a pantalla "
            "completa, con su icono, sin buscarla en el navegador."
        ),
    })


@require_GET
@cache_control(no_cache=True)
def offline(request):
    """Shown by the service worker without connection. Never includes the visitor's data.

    Not kept in the HTTP cache: the worker stores its own copy, and it must be the current one.
    """
    return render(request, "pwa/offline.html", {"theme_color": THEME_COLOR})
