"""Free accounts create one household; administering a Premium household lifts the limit."""

from django.urls import reverse

from billing import entitlements
from households.models import Household, Role

from .factories import PASSWORD, add_member, make_household, make_user
from .test_billing import billing_on, make_premium  # noqa: F401 (billing_on is a fixture)

CREATE = reverse("households:onboarding")


def create(client, user, name):
    assert client.login(email=user.email, password=PASSWORD)
    return client.post(CREATE, {"name": name})


def test_a_new_account_can_create_its_first_household(billing_on, client, db):
    user = make_user("nueva@example.com")
    create(client, user, "Casa nueva")
    assert Household.objects.filter(name="Casa nueva", memberships__user=user, memberships__role=Role.ADMIN).exists()


def test_a_free_account_cannot_create_a_second_household(billing_on, client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    page = client.get(CREATE).content.decode()
    assert "Con el plan gratuito puedes crear un hogar" in page and 'name="name"' not in page

    response = create(client, admin_user, "Segunda casa")
    assert response.status_code == 302
    assert not Household.objects.filter(name="Segunda casa").exists()


def test_being_invited_to_another_household_does_not_count(billing_on, client, household, db):
    guest = make_user("invitada@example.com")
    add_member(household, guest, Role.EDITOR)
    create(client, guest, "Mi propia casa")
    assert Household.objects.filter(name="Mi propia casa").exists()


def test_administering_a_premium_household_lifts_the_limit(billing_on, client, household, admin_user):
    make_premium(household)
    create(client, admin_user, "Segunda casa")
    create(client, admin_user, "Tercera casa")
    assert entitlements.administered_households(admin_user).count() == 3


def test_without_billing_there_is_no_limit(client, household, admin_user, settings):
    settings.BILLING_ENABLED = False
    create(client, admin_user, "Otra casa")
    assert Household.objects.filter(name="Otra casa").exists()


def test_the_limit_is_configurable(billing_on, client, household, admin_user):
    billing_on.FREE_MAX_OWNED_HOUSEHOLDS = 2
    create(client, admin_user, "Segunda casa")
    assert Household.objects.filter(name="Segunda casa").exists()
    assert not entitlements.can_create_household(admin_user)


def test_plans_explain_the_household_limit(billing_on, client, db):
    landing = client.get("/").content.decode()
    assert "<li>Un hogar</li>" in landing and "Todos los hogares que necesites" in landing
    terms = client.get(reverse("core:legal_page", args=["condiciones"])).content.decode()
    assert "un hogar por cuenta" in terms and "crear todos los hogares que se necesiten" in terms
