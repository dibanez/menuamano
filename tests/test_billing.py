import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest
from django.core import mail
from django.urls import reverse

from assistant import services as assistant_services
from assistant.models import AIRequestLog
from billing import entitlements, services
from billing.models import StripeEvent, Subscription
from households.models import Invitation, Role

from .factories import PASSWORD, add_member, make_household, make_user

BASE_DIR = Path(__file__).resolve().parent.parent
WEBHOOK_SECRET = "whsec_test_secret"
WEBHOOK_URL = "/plan/stripe/webhook/"


@pytest.fixture
def billing_on(settings):
    settings.BILLING_ENABLED = True
    settings.STRIPE_SECRET_KEY = "sk_test_123"
    settings.STRIPE_WEBHOOK_SECRET = WEBHOOK_SECRET
    settings.STRIPE_PRICE_MONTHLY = "price_month"
    settings.STRIPE_PRICE_YEARLY = "price_year"
    settings.FREE_MAX_MEMBERS = 2
    settings.FREE_AI_MONTHLY_LIMIT = 2
    settings.PREMIUM_MAX_MEMBERS = 8
    settings.PREMIUM_AI_MONTHLY_LIMIT = 3
    settings.SITE_URL = "https://menuamano.example.com"
    return settings


def stripe_subscription(household, status="active", sub_id="sub_1", interval="month", cancel=False):
    return {
        "id": sub_id, "object": "subscription", "status": status, "customer": "cus_1", "cancel_at_period_end": cancel,
        "metadata": {"household_id": str(household.pk)},
        "items": {"object": "list", "data": [{
            "id": "si_1", "object": "subscription_item", "current_period_end": 1900000000,
            "price": {"id": f"price_{interval}", "object": "price", "recurring": {"interval": interval}},
        }]},
    }


def make_premium(household, status="active"):
    return services.apply_subscription(stripe_subscription(household, status=status), household)


class FakeStripe:
    def __init__(self, household=None):
        self.created_customers, self.sessions, self.portals = [], [], []
        self.household = household
        self.v1 = SimpleNamespace(
            customers=SimpleNamespace(create=self._customer),
            checkout=SimpleNamespace(sessions=SimpleNamespace(create=self._session, retrieve=self._retrieve)),
            billing_portal=SimpleNamespace(sessions=SimpleNamespace(create=self._portal)),
        )

    def _customer(self, params=None, options=None):
        self.created_customers.append((params, options))
        return SimpleNamespace(id="cus_1")

    def _session(self, params=None, options=None):
        self.sessions.append(params)
        return SimpleNamespace(url="https://checkout.stripe.test/session")

    def _retrieve(self, session_id, params=None, options=None):
        return {"client_reference_id": str(self.household.pk), "subscription": stripe_subscription(self.household)}

    def _portal(self, params=None, options=None):
        self.portals.append(params)
        return SimpleNamespace(url="https://billing.stripe.test/portal")


def signed(event):
    payload = json.dumps(event)
    timestamp = int(time.time())
    signature = hmac.new(WEBHOOK_SECRET.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


def post_event(client, event_type, obj, event_id="evt_1"):
    payload, header = signed({"id": event_id, "object": "event", "type": event_type, "livemode": False,
                              "created": int(time.time()), "data": {"object": obj}})
    return client.post(WEBHOOK_URL, payload, content_type="application/json", HTTP_STRIPE_SIGNATURE=header)


# --- Plans and limits ---------------------------------------------------------------------------------


def test_without_billing_every_household_has_premium(household):
    assert entitlements.household_plan(household).code == "premium"


@pytest.mark.parametrize("status, plan", [
    ("active", "premium"), ("trialing", "premium"), ("past_due", "premium"),
    ("canceled", "free"), ("unpaid", "free"), ("incomplete", "free"),
])
def test_plan_follows_subscription_status(billing_on, household, status, plan):
    assert entitlements.household_plan(household).code == "free"
    make_premium(household, status=status)
    assert entitlements.household_plan(household).code == plan


class NeverCalled:
    name = "openai"

    def generate(self, context, user_id=None):
        raise AssertionError("the provider must not be called")


def test_free_households_get_a_small_ai_quota(billing_on, household, admin_user, monday, monkeypatch):
    assert entitlements.check_ai(household) == (True, "")
    for _ in range(2):
        AIRequestLog.objects.create(household=household, provider="openai", operation="chat", status="ok")
    allowed, message = entitlements.check_ai(household)
    assert not allowed and "2 peticiones" in message and "Con Premium tenéis 3 al mes" in message
    monkeypatch.setattr(assistant_services, "get_provider", lambda: NeverCalled())
    with pytest.raises(assistant_services.AssistantError, match="2 peticiones"):
        assistant_services.request_proposal(household, admin_user, "plan_range", monday, monday)


def test_free_ai_can_be_turned_off(billing_on, household, admin_user, monday, monkeypatch):
    billing_on.FREE_AI_MONTHLY_LIMIT = 0
    monkeypatch.setattr(assistant_services, "get_provider", lambda: NeverCalled())
    with pytest.raises(assistant_services.AssistantError, match="Premium"):
        assistant_services.request_proposal(household, admin_user, "plan_range", monday, monday)


def test_premium_ai_quota_counts_only_paid_calls(billing_on, household, admin_user, monday):
    make_premium(household)
    assert entitlements.check_ai(household)[0]
    for status in ("ok", "invalid", "error"):
        AIRequestLog.objects.create(household=household, provider="openai", operation="chat", status=status)
    AIRequestLog.objects.create(household=household, provider="demo", operation="chat", status="ok")
    assert entitlements.ai_calls_this_month(household) == 2  # "error" and demo calls are free
    AIRequestLog.objects.create(household=household, provider="openai", operation="chat", status="ok")
    allowed, message = entitlements.check_ai(household)
    assert not allowed and "3 peticiones" in message
    old = AIRequestLog.objects.create(household=household, provider="openai", operation="chat", status="ok")
    AIRequestLog.objects.filter(pk=old.pk).update(created_at=entitlements.month_start() - timedelta(days=1))
    assert entitlements.ai_calls_this_month(household) == 3


def test_free_chat_works_until_the_quota_runs_out(billing_on, client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert 'name="message"' in client.get(reverse("assistant:chat")).content.decode()
    assert "0 de 2" in client.get(reverse("billing:plan")).content.decode()
    for _ in range(2):
        AIRequestLog.objects.create(household=household, provider="openai", operation="chat", status="ok")
    page = client.get(reverse("assistant:chat")).content.decode()
    assert 'name="message"' not in page and "Con Premium tenéis 3 al mes" in page


def test_member_limit_applies_to_invitations_and_premium_raises_it(billing_on, client, household, admin_user):
    add_member(household, make_user("second@example.com"), Role.EDITOR)
    invitation, token = Invitation.issue(household, Role.READER, admin_user)
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("households:invitation_create"), {"role": "reader"})
    assert Invitation.objects.count() == 1  # no new invitation while full

    third = make_user("third@example.com")
    client.logout()
    assert client.login(email=third.email, password=PASSWORD)
    assert client.post(reverse("households:invitation", args=[token])).status_code == 409
    assert not household.memberships.filter(user=third).exists()

    make_premium(household)
    client.post(reverse("households:invitation", args=[token]))
    assert household.memberships.filter(user=third).exists()


# --- Checkout, portal and return ----------------------------------------------------------------------


def test_admin_starts_checkout_for_the_household(billing_on, client, household, admin_user):
    fake = FakeStripe(household)
    assert client.login(email=admin_user.email, password=PASSWORD)
    with mock.patch.object(services, "_client", return_value=fake):
        response = client.post(reverse("billing:checkout"), {"interval": "year"})
        client.post(reverse("billing:checkout"), {"interval": "month"})
    assert response.url == "https://checkout.stripe.test/session"
    assert len(fake.created_customers) == 1  # the customer is reused
    params = fake.sessions[0]
    assert params["mode"] == "subscription" and params["line_items"] == [{"price": "price_year", "quantity": 1}]
    assert params["client_reference_id"] == str(household.pk)
    assert params["subscription_data"]["metadata"] == {"household_id": str(household.pk)}
    assert params["success_url"].endswith("?session_id={CHECKOUT_SESSION_ID}")
    assert fake.created_customers[0][1]["idempotency_key"].endswith(str(household.pk))


def test_only_admins_pay_and_premium_households_do_not_pay_twice(billing_on, client, household, admin_user):
    editor = make_user("editor@example.com")
    add_member(household, editor, Role.EDITOR)
    fake = FakeStripe(household)
    with mock.patch.object(services, "_client", return_value=fake):
        assert client.login(email=editor.email, password=PASSWORD)
        assert client.post(reverse("billing:checkout"), {"interval": "month"}).status_code == 403
        client.logout()
        make_premium(household)
        assert client.login(email=admin_user.email, password=PASSWORD)
        client.post(reverse("billing:checkout"), {"interval": "month"})
    assert fake.sessions == []


def test_return_from_checkout_activates_premium_and_rejects_foreign_sessions(billing_on, client, household, admin_user):
    other = make_household("Otra", admin=make_user("otra@example.com"))
    assert client.login(email=admin_user.email, password=PASSWORD)
    with mock.patch.object(services, "_client", return_value=FakeStripe(other)):
        client.get(reverse("billing:success") + "?session_id=cs_foreign")
    assert entitlements.household_plan(household).code == "free"
    with mock.patch.object(services, "_client", return_value=FakeStripe(household)):
        client.get(reverse("billing:success") + "?session_id=cs_1")
    subscription = Subscription.objects.get(household=household)
    assert subscription.status == "active" and subscription.interval == "month"
    assert subscription.current_period_end.year == 2030  # read from the subscription item


def test_portal_opens_for_subscribed_households(billing_on, client, household, admin_user):
    fake = FakeStripe(household)
    assert client.login(email=admin_user.email, password=PASSWORD)
    with mock.patch.object(services, "_client", return_value=fake):
        response = client.post(reverse("billing:portal"), follow=True)
        assert "todavía no tiene una suscripción" in response.content.decode()
        make_premium(household)
        response = client.post(reverse("billing:portal"))
    assert response.url == "https://billing.stripe.test/portal"
    assert fake.portals[0]["customer"] == "cus_1"


def test_plan_page_shows_usage(billing_on, client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    page = client.get(reverse("billing:plan")).content.decode()
    assert "1 de 2" in page and "4,99 €" in page


# --- Webhooks ---------------------------------------------------------------------------------------


def test_subscription_webhooks_update_the_plan_once(billing_on, client, household):
    obj = stripe_subscription(household, interval="year", cancel=True)
    assert post_event(client, "customer.subscription.updated", obj).status_code == 200
    assert post_event(client, "customer.subscription.updated", obj).status_code == 200  # retry
    assert StripeEvent.objects.count() == 1
    subscription = Subscription.objects.get(household=household)
    assert subscription.is_premium and subscription.interval == "year" and subscription.cancel_at_period_end

    deleted = stripe_subscription(household, status="canceled")
    post_event(client, "customer.subscription.deleted", deleted, event_id="evt_2")
    assert entitlements.household_plan(household).code == "free"


def test_checkout_completed_webhook_retrieves_the_subscription(billing_on, client, household):
    session = {"object": "checkout.session", "mode": "subscription", "client_reference_id": str(household.pk),
               "subscription": "sub_1", "customer": "cus_1"}
    with mock.patch.object(services, "_retrieve_subscription", return_value=stripe_subscription(household)) as retrieve:
        assert post_event(client, "checkout.session.completed", session).status_code == 200
    retrieve.assert_called_once_with("sub_1")
    assert entitlements.household_plan(household).code == "premium"


def test_webhook_rejects_bad_signatures(billing_on, client, household):
    payload, _ = signed({"id": "evt_x", "object": "event", "type": "customer.subscription.updated",
                         "data": {"object": stripe_subscription(household)}})
    response = client.post(WEBHOOK_URL, payload, content_type="application/json", HTTP_STRIPE_SIGNATURE="t=1,v1=bad")
    assert response.status_code == 400
    assert not Subscription.objects.exists() and not StripeEvent.objects.exists()


def test_failed_processing_is_retried(billing_on, client, household):
    with mock.patch.object(services, "apply_subscription", side_effect=RuntimeError("db down")):
        assert post_event(client, "customer.subscription.updated", stripe_subscription(household)).status_code == 500
    assert not StripeEvent.objects.exists()  # rolled back, so Stripe's retry is processed
    assert post_event(client, "customer.subscription.updated", stripe_subscription(household)).status_code == 200
    assert entitlements.household_plan(household).code == "premium"


def test_payment_failure_emails_household_admins(billing_on, client, household, admin_user):
    make_premium(household)
    add_member(household, make_user("editor@example.com"), Role.EDITOR)
    post_event(client, "invoice.payment_failed", {"object": "invoice", "customer": "cus_1"})
    assert [m.to for m in mail.outbox] == [[admin_user.email]]
    assert "https://menuamano.example.com/plan/" in mail.outbox[0].body


# --- Production settings and landing ------------------------------------------------------------------

STRIPE_VARS = ["BILLING_ENABLED", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET", "STRIPE_PRICE_MONTHLY", "STRIPE_PRICE_YEARLY"]


def run_production(**extra):
    env = {k: v for k, v in os.environ.items() if k not in STRIPE_VARS}
    env.update(DJANGO_SETTINGS_MODULE="config.settings.production", DJANGO_SECRET_KEY="s" * 50,
               DJANGO_ALLOWED_HOSTS="menuamano.example.com", EMAIL_PROVIDER="console", **extra)
    code = "import django; from django.conf import settings; django.setup(); print(settings.BILLING_ENABLED)"
    return subprocess.run([sys.executable, "-c", code], env=env, cwd=BASE_DIR, capture_output=True, text=True)


def test_production_requires_stripe_unless_billing_is_disabled():
    missing = run_production()
    assert missing.returncode != 0 and "STRIPE_SECRET_KEY" in missing.stderr
    configured = run_production(STRIPE_SECRET_KEY="sk_live_x", STRIPE_WEBHOOK_SECRET="whsec_x",
                                STRIPE_PRICE_MONTHLY="price_m", STRIPE_PRICE_YEARLY="price_y")
    assert configured.returncode == 0 and configured.stdout.strip() == "True"
    assert run_production(BILLING_ENABLED="false").stdout.strip() == "False"


def test_landing_for_visitors_and_home_for_members(client, household, admin_user):
    page = client.get("/")
    assert page.status_code == 200
    html = page.content.decode()
    assert "Qué comemos, quién come y qué hay que comprar." in html and "4,99 €" in html and "49 €" in html
    assert client.login(email=admin_user.email, password=PASSWORD)
    assert "Qué comemos hoy" in client.get("/").content.decode()
