import pytest
from django.urls import reverse

from .factories import PASSWORD

GTM = "GTM-WWR8DTN8"


@pytest.fixture
def gtm(settings):
    settings.GTM_CONTAINER_ID = GTM
    settings.GTM_SCOPE = "public"
    settings.COOKIE_CONSENT_BANNER = True
    return settings


def test_not_loaded_without_container(client, db):
    html = client.get("/").content.decode()
    assert "googletagmanager" not in html and "consent-banner" not in html


def test_marketing_pages_load_gtm_with_consent_denied_first(client, db, gtm):
    for url in ["/", reverse("core:install"), reverse("core:legal_page", args=["privacidad"])]:
        html = client.get(url).content.decode()
        assert f'"{GTM}"' in html, url
        assert html.index('gtag("consent", "default"') < html.index("googletagmanager.com/gtm.js"), url
        assert 'id="consent-banner"' in html


def test_pages_with_passwords_or_tokens_never_load_gtm(client, db, gtm):
    for url in [reverse("accounts:login"), reverse("accounts:signup"), reverse("accounts:password_reset")]:
        assert "googletagmanager" not in client.get(url).content.decode(), url


def test_signed_in_pages_do_not_load_gtm_by_default(client, household, admin_user, gtm):
    assert client.login(email=admin_user.email, password=PASSWORD)
    for url in ["/", reverse("diners:list"), reverse("planning:week")]:
        assert "googletagmanager" not in client.get(url).content.decode(), url


def test_scope_all_loads_gtm_everywhere(client, household, admin_user, gtm):
    gtm.GTM_SCOPE = "all"
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert "googletagmanager" in client.get(reverse("planning:week")).content.decode()


def test_banner_can_be_disabled_for_an_external_cmp(client, db, gtm):
    gtm.COOKIE_CONSENT_BANNER = False
    html = client.get("/").content.decode()
    assert "googletagmanager" in html and 'id="consent-banner"' not in html


@pytest.mark.parametrize("value", ["UA-12345-1", 'GTM-X";alert(1);//', "gtm-lowercase"])
def test_invalid_container_ids_are_ignored(client, db, settings, value):
    settings.GTM_CONTAINER_ID = value
    assert "googletagmanager" not in client.get("/").content.decode()
