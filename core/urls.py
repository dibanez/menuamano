from django.urls import path

from . import seo, views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("robots.txt", seo.robots_txt, name="robots"),
    path("sitemap.xml", seo.sitemap_xml, name="sitemap"),
    path("legal/", views.legal_index, name="legal"),
    path("legal/<slug:slug>/", views.legal_page, name="legal_page"),
]
