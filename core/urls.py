from django.urls import path

from . import pwa, seo, views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("favicon.ico", seo.favicon, name="favicon"),
    path("manifest.webmanifest", pwa.manifest, name="manifest"),
    path("sw.js", pwa.service_worker, name="service_worker"),
    path("offline/", pwa.offline, name="offline"),
    path("robots.txt", seo.robots_txt, name="robots"),
    path("sitemap.xml", seo.sitemap_xml, name="sitemap"),
    path("legal/", views.legal_index, name="legal"),
    path("legal/<slug:slug>/", views.legal_page, name="legal_page"),
]
