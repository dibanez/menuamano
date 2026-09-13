"""The bare domain sends visitors to SITE_URL's host; nothing else is redirected."""

import pytest


@pytest.fixture
def hosts(settings):
    settings.SITE_URL = "https://www.menuamano.com"
    settings.ALLOWED_HOSTS = ["menuamano.com", "www.menuamano.com", "testserver"]
    return settings


def test_the_bare_domain_redirects_to_www_keeping_the_path(client, db, hosts):
    response = client.get("/legal/?ref=x", HTTP_HOST="menuamano.com")
    assert response.status_code == 301
    assert response["Location"] == "https://www.menuamano.com/legal/?ref=x"


def test_the_canonical_host_and_unrelated_hosts_are_served(client, db, hosts):
    assert client.get("/", HTTP_HOST="www.menuamano.com").status_code == 200
    assert client.get("/").status_code == 200  # testserver is not a variant of the site's host


def test_posts_and_health_checks_are_never_redirected(client, db, hosts):
    assert client.post("/cuenta/entrar/", {}, HTTP_HOST="menuamano.com").status_code != 301
    assert client.get("/healthz", HTTP_HOST="menuamano.com").status_code == 200


def test_a_bare_canonical_host_redirects_www_to_it(client, db, hosts):
    hosts.SITE_URL = "https://menuamano.com"
    response = client.get("/", HTTP_HOST="www.menuamano.com")
    assert response.status_code == 301 and response["Location"] == "https://menuamano.com/"


def test_without_site_url_nothing_is_redirected(client, db, hosts):
    hosts.SITE_URL = ""
    assert client.get("/", HTTP_HOST="menuamano.com").status_code == 200
