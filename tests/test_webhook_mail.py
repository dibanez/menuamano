"""The public Mailgun webhook must never send email, whatever reaches it."""

import base64
import json

import pytest
from django.core import mail

from core.models import EmailEvent

from .test_emails import mailgun_payload

URL = "/anymail/mailgun/tracking/"
JSON = "application/json"


@pytest.fixture
def admins(settings):
    settings.ADMINS = [("Ops", "ops@example.com")]
    settings.MANAGERS = settings.ADMINS


def basic_auth(value):
    return {"HTTP_AUTHORIZATION": "Basic " + base64.b64encode(value.encode()).decode()}


def test_missing_basic_auth_is_rejected_quietly(client, db, admins, settings):
    # The production case: ANYMAIL_WEBHOOK_SECRET set, but the Mailgun URL carries no credentials.
    settings.ANYMAIL = {**settings.ANYMAIL, "WEBHOOK_SECRET": "user:secret"}
    assert client.post(URL, mailgun_payload("t-auth"), content_type=JSON).status_code == 400
    assert client.post(URL, mailgun_payload("t-auth2"), content_type=JSON, **basic_auth("user:wrong")).status_code == 400
    assert mail.outbox == []
    # With the right credentials the event goes through.
    assert client.post(URL, mailgun_payload("t-auth3"), content_type=JSON, **basic_auth("user:secret")).status_code == 200
    assert mail.outbox == []


@pytest.mark.parametrize("body, content_type", [
    (mailgun_payload("t-sig", key="not-the-key"), JSON),                 # wrong signature
    ("{not json", JSON),                                                 # unreadable body
    (json.dumps({"event-data": {"event": "failed"}}), JSON),             # no signature block
    ("event=failed&recipient=ana%40example.com", "application/x-www-form-urlencoded"),  # legacy, unsigned
])
def test_invalid_calls_are_rejected_quietly(client, db, admins, body, content_type):
    assert client.post(URL, body, content_type=content_type).status_code == 400
    assert mail.outbox == [] and not EmailEvent.objects.exists()


def test_other_methods_send_nothing(client, db, admins):
    assert client.get(URL).status_code == 405
    assert client.head(URL).status_code == 200  # Anymail answers HEAD for Mailgun's URL check
    assert mail.outbox == []


@pytest.mark.parametrize("event", ["failed", "complained", "delivered", "opened"])
def test_signed_events_are_stored_without_emailing_anyone(client, db, admins, event):
    assert client.post(URL, mailgun_payload(f"t-{event}", event=event), content_type=JSON).status_code == 200
    assert EmailEvent.objects.count() == 1
    assert mail.outbox == []


def test_signed_but_malformed_event_sends_nothing(client, db, admins):
    payload = json.loads(mailgun_payload("t-bad"))
    payload["event-data"] = {"event": "failed"}  # valid signature, almost no data
    client.post(URL, json.dumps(payload), content_type=JSON)
    assert mail.outbox == []
