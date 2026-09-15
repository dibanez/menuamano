"""Every feature is free: any account creates the households it needs, with or without Premium."""

from django.urls import reverse

from households.models import Household, Role

from .factories import PASSWORD
from .test_billing import billing_on  # noqa: F401 (billing_on is a fixture)

CREATE = reverse("households:onboarding")


def create(client, user, name):
    assert client.login(email=user.email, password=PASSWORD)
    return client.post(CREATE, {"name": name})


def test_a_free_account_creates_as_many_households_as_it_needs(billing_on, client, household, admin_user):
    for name in ("Segunda casa", "Tercera casa"):
        create(client, admin_user, name)
    assert Household.objects.filter(memberships__user=admin_user, memberships__role=Role.ADMIN).count() == 3


def test_plans_say_everything_is_free(billing_on, client, db):
    landing = client.get("/").content.decode()
    assert "Todas las funciones, gratis" in landing and "todos los hogares que necesites" in landing
    assert "tu propia clave" in landing and "sin configurar claves" in landing
    free_plan = landing[landing.index("<h3>Gratis</h3>"):landing.index("Empezar gratis")]
    assert "propone menús y cambios" in free_plan and "las de cualquier web" in free_plan
    terms = client.get(reverse("core:legal_page", args=["condiciones"])).content.decode()
    assert "todos los hogares que se necesiten" in terms and "menuamano no la recibe ni la guarda" in terms
    privacy = client.get(reverse("core:legal_page", args=["privacidad"])).content.decode()
    assert "Tu clave se guarda solo en tu dispositivo y menuamano no la recibe" in privacy
