import json
import re

import pytest
from django.urls import reverse

from .factories import PASSWORD

SITE = "https://menuamano.example.com"


@pytest.fixture
def site(settings):
    settings.SITE_URL = SITE


def head(html):
    return html.split("</head>", 1)[0]


def json_ld(html):
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S).group(1))


def test_landing_is_indexable_with_canonical_and_social_cards(client, db, site):
    page = head(client.get("/").content.decode())
    assert '<meta name="robots" content="index, follow">' in page
    assert f'<link rel="canonical" href="{SITE}/">' in page
    assert '<meta name="description" content="Planifica las comidas de casa' in page
    for tag in ('property="og:title"', 'property="og:image" content="https://menuamano.example.com/static/img/og-menuamano.png"',
                'name="twitter:card" content="summary_large_image"'):
        assert tag in page


def test_landing_structured_data_matches_prices_and_faq(client, db, site):
    html = client.get("/").content.decode()
    graph = {node["@type"]: node for node in json_ld(html)["@graph"]}
    app = graph["WebApplication"]
    assert app["url"] == f"{SITE}/"
    assert [o["price"] for o in app["offers"]] == ["0", "4.99", "49"]
    questions = [q["name"] for q in graph["FAQPage"]["mainEntity"]]
    assert len(questions) == 7
    for question in questions:
        assert question in html  # the visible FAQ is the same list


def test_private_pages_are_not_indexed(client, household, admin_user):
    assert '<meta name="robots" content="noindex, nofollow">' in client.get(reverse("accounts:login")).content.decode()
    assert client.login(email=admin_user.email, password=PASSWORD)
    for url in ("/", reverse("planning:week")):
        response = client.get(url)
        assert response.status_code == 200
        page = head(response.content.decode())
        assert 'content="noindex, nofollow"' in page and 'rel="canonical"' not in page


def test_legal_pages_and_signup_are_indexable(client, db, site):
    for url in (reverse("core:legal"), reverse("core:legal_page", args=["privacidad"]), reverse("accounts:signup")):
        page = head(client.get(url).content.decode())
        assert '<meta name="robots" content="index, follow">' in page
        assert f'<link rel="canonical" href="{SITE}{url}">' in page


def test_robots_txt_blocks_private_areas_and_points_to_the_sitemap(client, db, site):
    response = client.get("/robots.txt")
    body = response.content.decode()
    assert response["Content-Type"].startswith("text/plain")
    assert "Disallow: /calendario/" in body and "Disallow: /admin/" in body and "Allow: /cuenta/registro/" in body
    assert f"Sitemap: {SITE}/sitemap.xml" in body


def test_sitemap_lists_the_public_pages(client, db, site):
    response = client.get("/sitemap.xml")
    body = response.content.decode()
    assert response["Content-Type"].startswith("application/xml")
    locs = re.findall(r"<loc>(.*?)</loc>", body)
    assert f"{SITE}/" in locs and f"{SITE}/cuenta/registro/" in locs and f"{SITE}/legal/privacidad/" in locs
    assert not any("/calendario/" in loc for loc in locs)
    assert "<lastmod>2026-09-12</lastmod>" in body


def test_without_site_url_the_request_host_is_used(client, db, settings):
    settings.SITE_URL = ""
    assert '<link rel="canonical" href="http://testserver/">' in client.get("/").content.decode()
