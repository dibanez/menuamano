import pytest
from django.test import override_settings
from django.urls import reverse

from accounts.models import User
from core.checks import legal_owner_check
from core.legal import LEGAL_VERSION

from .factories import PASSWORD, make_user

SIGNUP = {"email": "nueva@example.com", "display_name": "Nueva", "password1": "cocina-casera-2030",
          "password2": "cocina-casera-2030"}
OWNER = dict(LEGAL_OWNER_NAME="Menú a Mano S.L.", LEGAL_OWNER_TAX_ID="B00000000",
             LEGAL_OWNER_ADDRESS="Calle Mayor 1, 36201 Vigo", LEGAL_CONTACT_EMAIL="privacidad@menuamano.com")


@pytest.mark.parametrize("slug", ["aviso-legal", "privacidad", "cookies", "condiciones"])
def test_legal_pages_are_public(client, db, slug):
    response = client.get(reverse("core:legal_page", args=[slug]))
    assert response.status_code == 200
    assert "Última actualización" in response.content.decode()


def test_unknown_legal_page_is_404(client, db):
    assert client.get("/legal/no-existe/").status_code == 404


@override_settings(**OWNER)
def test_owner_details_come_from_settings(client, db):
    html = client.get(reverse("core:legal_page", args=["aviso-legal"])).content.decode()
    assert "Menú a Mano S.L." in html and "B00000000" in html and "privacidad@menuamano.com" in html
    assert "pendiente]" not in html


def test_missing_owner_details_are_flagged(client, db, settings):
    html = client.get(reverse("core:legal_page", args=["privacidad"])).content.decode()
    assert "[NIF pendiente]" in html
    settings.DEBUG = False
    assert [w.id for w in legal_owner_check(None)] == ["menuamano.W001"]
    settings.DEBUG = True
    assert legal_owner_check(None) == []


def test_terms_show_current_prices(client, db):
    html = client.get(reverse("core:legal_page", args=["condiciones"])).content.decode()
    assert "4,99 €" in html and "49 €" in html and "14 días naturales" in html


def test_public_pages_link_to_legal_texts(client, db):
    for url in ["/", reverse("accounts:login"), reverse("accounts:signup")]:
        html = client.get(url).content.decode()
        assert reverse("core:legal_page", args=["privacidad"]) in html, url
        assert reverse("core:legal_page", args=["cookies"]) in html, url


def test_signup_requires_both_consents(client, db):
    response = client.post(reverse("accounts:signup"), {**SIGNUP, "accept_terms": "on"})
    assert response.status_code == 200 and not User.objects.exists()
    assert "Sin este consentimiento" in response.content.decode()
    response = client.post(reverse("accounts:signup"), {**SIGNUP, "health_consent": "on"})
    assert not User.objects.exists()


def test_signup_records_consent(client, db):
    client.post(reverse("accounts:signup"), {**SIGNUP, "accept_terms": "on", "health_consent": "on"})
    user = User.objects.get(email="nueva@example.com")
    assert user.terms_accepted_at and user.health_consent_at and user.legal_version == LEGAL_VERSION


def test_existing_users_must_accept_before_using_the_app(client, household, db):
    user = make_user("antigua@example.com", consented=False)
    from households.models import Membership, Role

    Membership.objects.create(user=user, household=household, role=Role.EDITOR)
    assert client.login(email=user.email, password=PASSWORD)
    response = client.get(reverse("planning:week"))
    assert response.status_code == 302 and response.url.startswith(reverse("accounts:legal_consent"))
    # Legal pages and logout stay reachable while consent is pending.
    assert client.get(reverse("core:legal_page", args=["privacidad"])).status_code == 200

    client.post(reverse("accounts:legal_consent") + "?next=/calendario/", {"accept_terms": "on"})
    user.refresh_from_db()
    assert user.legal_version == ""
    response = client.post(reverse("accounts:legal_consent"), {"accept_terms": "on", "health_consent": "on",
                                                              "next": reverse("planning:week")})
    assert response.url == reverse("planning:week")
    user.refresh_from_db()
    assert user.legal_version == LEGAL_VERSION
    assert client.get(reverse("planning:week")).status_code == 200


def test_outdated_legal_version_asks_again(client, household, admin_user):
    User.objects.filter(pk=admin_user.pk).update(legal_version="2000-01-01")
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert client.get("/").url.startswith(reverse("accounts:legal_consent"))
