"""Fixes from the security review: health-data links, throttling, headers, push, imports, webhooks…"""

import json
import re
import time
from unittest import mock

import pytest
from django.urls import reverse

from assistant import services as assistant_services
from assistant.device import PREPARE
from billing import entitlements
from core import throttle
from core.gunicorn_logging import redact
from core.reporting import PrivateExceptionReporterFilter
from diners.models import HealthDataAccess
from households.models import Invitation, Role
from planning.feeds import escape
from recipes import importer
from reminders import push
from reminders.models import PushSubscription

from .factories import PASSWORD, add_member, make_user
from .test_billing import WEBHOOK_URL, billing_on, signed, stripe_subscription  # noqa: F401 (billing_on is a fixture)
from .test_permissions import weight_setup  # noqa: F401 (fixture)


def login(client, user):
    assert client.login(email=user.email, password=PASSWORD)


def edit_diner(client, diner, **extra):
    data = {"alias": diner.alias, "portion_factor": "1", "is_active": "on"}
    data.update(extra)
    return client.post(reverse("diners:edit", args=[diner.pk]), data)


# --- Who controls a diner's health data ------------------------------------------------------------


def test_editors_cannot_take_over_a_diners_health_data(client, weight_setup):
    adult, editor = weight_setup["adult"], weight_setup["editor"]
    login(client, editor)
    edit_diner(client, adult, linked_user=editor.pk)
    client.post(reverse("diners:setup", args=[adult.pk]), {
        "alias": "Olga", "portion": "1.00", "diet": "omnivore", "diabetes": "no", "linked_user": editor.pk,
    })
    adult.refresh_from_db()
    assert adult.linked_user == weight_setup["owner"]
    assert client.get(reverse("diners:weight", args=[adult.pk])).status_code == 403


def test_editors_cannot_link_themselves_to_an_existing_diner(client, weight_setup):
    child, editor = weight_setup["child"], weight_setup["editor"]
    login(client, editor)
    edit_diner(client, child, linked_user=editor.pk)
    child.refresh_from_db()
    assert child.linked_user is None


def test_the_linked_person_can_unlink_and_admins_can_link(client, weight_setup):
    adult, child, owner = weight_setup["adult"], weight_setup["child"], weight_setup["owner"]
    login(client, owner)
    edit_diner(client, adult, linked_user="")
    adult.refresh_from_db()
    assert adult.linked_user is None
    client.logout()
    login(client, weight_setup["admin"])
    edit_diner(client, child, linked_user=owner.pk)
    child.refresh_from_db()
    assert child.linked_user == owner


def test_removing_a_member_hands_their_diner_to_the_admins(client, weight_setup):
    adult, owner, editor = weight_setup["adult"], weight_setup["owner"], weight_setup["editor"]
    HealthDataAccess.objects.create(diner=adult, user=editor, granted_by=owner)
    login(client, weight_setup["admin"])
    membership = adult.household.memberships.get(user=owner)
    client.post(reverse("households:remove_member", args=[membership.pk]))
    adult.refresh_from_db()
    assert adult.linked_user is None and not HealthDataAccess.objects.filter(diner=adult).exists()


# --- Households and invitations ----------------------------------------------------------------------


def test_switching_to_a_malformed_household_is_refused(client, household, admin_user):
    login(client, admin_user)
    assert client.post(reverse("households:switch"), {"household": "abc"}).status_code == 403


def test_invitations_sent_to_an_address_are_for_that_account_only(client, household, admin_user):
    _, token = Invitation.issue(household, Role.EDITOR, admin_user, email="lucia@example.com")
    stranger = make_user("otro@example.com")
    login(client, stranger)
    assert client.post(reverse("households:invitation", args=[token])).status_code == 403
    assert not household.memberships.filter(user=stranger).exists()
    client.logout()
    lucia = make_user("lucia@example.com")
    login(client, lucia)
    client.post(reverse("households:invitation", args=[token]))
    assert household.memberships.filter(user=lucia).exists()


def test_invitation_emails_are_limited_per_household(client, household, admin_user):
    login(client, admin_user)
    for _ in range(20):
        throttle.record(f"invite:household:{household.pk}")
    client.post(reverse("households:invitation_create"), {"role": "reader", "email": "nueva@example.com"})
    assert not Invitation.objects.exists()


# --- Throttling --------------------------------------------------------------------------------------


def test_logins_wait_after_repeated_failures(client, admin_user):
    url = reverse("accounts:login")
    for _ in range(10):
        assert client.post(url, {"username": admin_user.email, "password": "mal"}).status_code == 200
    assert client.post(url, {"username": admin_user.email, "password": PASSWORD}).status_code == 429


def test_signups_and_password_resets_are_limited(client, admin_user):
    for _ in range(10):
        client.post(reverse("accounts:signup"), {"email": "x"})
    assert client.post(reverse("accounts:signup"), {"email": "x"}).status_code == 429
    url = reverse("accounts:password_reset")
    for _ in range(3):
        assert client.post(url, {"email": admin_user.email}).status_code == 302
    assert client.post(url, {"email": admin_user.email}).status_code == 429


def test_recipe_imports_are_limited(household, admin_user):
    for _ in range(assistant_services.IMPORTS_PER_HOUR):
        throttle.record(f"import:user:{admin_user.pk}")
    with pytest.raises(assistant_services.AssistantError, match="muchas recetas"):
        assistant_services.request_import(household, admin_user, "https://recetas.example.com/r", device=PREPARE)


# --- Headers, analytics and error reports ---------------------------------------------------------------


def test_pages_carry_a_content_security_policy(client, household, admin_user, settings):
    settings.GTM_CONTAINER_ID = "GTM-TEST1"
    landing = client.get("/")
    policy = landing["Content-Security-Policy"]
    assert "googletagmanager" in policy and "api.openai.com" not in policy and "frame-ancestors 'none'" in policy
    nonce = re.search(r"'nonce-([^']+)'", policy).group(1)
    assert f'nonce="{nonce}"' in landing.content.decode()
    assert "camera=(self)" in landing["Permissions-Policy"]
    login(client, admin_user)
    policy = client.get(reverse("assistant:chat"))["Content-Security-Policy"]
    assert "https://api.anthropic.com" in policy and "googletagmanager" not in policy


def test_tag_manager_only_loads_on_marketing_pages(client, db, settings):
    settings.GTM_CONTAINER_ID = "GTM-TEST1"
    assert "GTM-TEST1" in client.get("/").content.decode()
    assert "GTM-TEST1" in client.get(reverse("core:legal_page", args=["privacidad"])).content.decode()
    for url in (reverse("accounts:login"), reverse("accounts:signup"), reverse("accounts:password_reset")):
        assert "GTM-TEST1" not in client.get(url).content.decode()


def test_error_reports_hide_form_data_and_cookies(rf):
    request = rf.post("/cuenta/registro/", {"password1": "secreta", "message": "Nora tiene diabetes"})
    request.COOKIES["sessionid"] = "abc"
    reporter = PrivateExceptionReporterFilter()
    assert set(reporter.get_post_parameters(request).values()) == {reporter.cleansed_substitute}
    assert reporter.get_safe_cookies(request) == {"sessionid": reporter.cleansed_substitute}


def test_access_logs_hide_url_tokens():
    assert redact("GET /calendario/ics/abcDEF123.ics HTTP/1.1") == "GET /calendario/ics/<token>.ics HTTP/1.1"
    assert redact("GET /hogar/invitacion/tok_123/ HTTP/1.1") == "GET /hogar/invitacion/<token>/ HTTP/1.1"
    assert redact("GET /cuenta/contrasena/nueva/MQ/abc-123/ HTTP/1.1") == "GET /cuenta/contrasena/nueva/<token>/ HTTP/1.1"


# --- Push notifications ------------------------------------------------------------------------------

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc"


def subscribe(client, endpoint=ENDPOINT, auth="secret"):
    body = json.dumps({"endpoint": endpoint, "keys": {"p256dh": "public-key", "auth": auth}})
    return client.post(reverse("reminders:subscribe"), body, content_type="application/json")


def test_devices_cannot_be_taken_over_or_point_elsewhere(client, household, admin_user):
    login(client, admin_user)
    assert subscribe(client).status_code == 200
    other = make_user("otra@example.com")
    add_member(household, other, Role.EDITOR)
    client.logout()
    login(client, other)
    assert subscribe(client, auth="guessed").status_code == 403
    assert PushSubscription.objects.get(endpoint=ENDPOINT).user == admin_user
    assert subscribe(client).status_code == 200  # the same browser and keys: now it is theirs
    assert PushSubscription.objects.get(endpoint=ENDPOINT).user == other
    for endpoint in ("https://10.0.0.5/push", "https://evil.example.com/x", "https://fcm.googleapis.com:8443/x",
                     "http://fcm.googleapis.com/x", "https://user@fcm.googleapis.com/x"):
        assert subscribe(client, endpoint=endpoint).status_code == 400


def test_each_person_keeps_at_most_ten_devices(client, household, admin_user):
    login(client, admin_user)
    for number in range(12):
        subscribe(client, endpoint=f"https://updates.push.services.mozilla.com/wpush/v2/{number}")
    assert admin_user.push_subscriptions.count() == push.MAX_DEVICES


def test_saved_devices_outside_push_services_are_dropped(household, admin_user, settings):
    settings.VAPID_PUBLIC_KEY = settings.VAPID_PRIVATE_KEY = "key"
    old = PushSubscription.objects.create(user=admin_user, endpoint="https://10.0.0.5/x", p256dh="k", auth="a")
    with mock.patch("pywebpush.webpush") as webpush:
        assert not push.send(old, {"title": "menuamano"})
    webpush.assert_not_called()
    assert not PushSubscription.objects.filter(pk=old.pk).exists()


# --- Recipe importer and calendar feed -------------------------------------------------------------------


@pytest.mark.parametrize("address", [
    "10.0.0.1", "169.254.169.254", "::1", "::127.0.0.1", "::ffff:10.0.0.1", "64:ff9b::a9fe:a9fe", "2002:7f00:1::1",
])
def test_the_importer_refuses_internal_addresses(address):
    with mock.patch("socket.getaddrinfo", return_value=[(None, None, None, "", (address, 80))]):
        with pytest.raises(importer.RecipeImportError):
            importer.public_address("recetas.example.com", 80)


def test_the_importer_survives_hostile_pages():
    nested = '<script type="application/ld+json">' + "[" * 100_000 + "]" * 100_000 + "</script>"
    assert importer.extract(nested + "<p>" + "texto " * 60 + "</p>")["format"] == "text"
    assert importer._decode(b"hola", "base64") == importer._decode(b"hola", "no-such-charset") == "hola"

    class Trickle:
        def read1(self, size):
            return b"x"

    with pytest.raises(importer.RecipeImportError, match="tarda demasiado"):
        importer._read(Trickle(), deadline=time.monotonic() - 1)


def test_calendar_text_cannot_start_a_new_line():
    assert escape("Lentejas\rURL:https://evil BEGIN:VALARM\x00") == "Lentejas\\nURL:https://evil\\nBEGIN:VALARM"
    assert escape("a;b,c\\d\r\ne") == "a\\;b\\,c\\\\d\\ne"


# --- Stripe --------------------------------------------------------------------------------------------


def test_older_stripe_events_do_not_undo_newer_ones(billing_on, client, household):
    now = int(time.time())

    def send(event_type, obj, event_id, created):
        payload, header = signed({"id": event_id, "object": "event", "type": event_type, "livemode": False,
                                  "created": created, "data": {"object": obj}})
        return client.post(WEBHOOK_URL, payload, content_type="application/json", HTTP_STRIPE_SIGNATURE=header)

    assert send("customer.subscription.deleted", stripe_subscription(household, status="canceled"), "evt_new", now).status_code == 200
    assert send("customer.subscription.updated", stripe_subscription(household), "evt_old", now - 60).status_code == 200
    assert entitlements.household_plan(household).code == "free"
