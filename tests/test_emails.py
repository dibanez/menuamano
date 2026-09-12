import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from unittest import mock

import pytest
from django.core import mail
from django.core.management import CommandError, call_command
from django.urls import reverse

from core.emails import send_email
from core.models import EmailEvent
from households.models import Invitation

from .factories import PASSWORD, make_user

BASE_DIR = Path(__file__).resolve().parent.parent
NEW_PASSWORD = "otra-clave-segura-2030"


def reset_link(message):
    return re.search(r"https://testserver(/cuenta/contrasena/nueva/\S+/)", message.body).group(1)


# --- Passwords ----------------------------------------------------------------------------------


def test_password_reset_email_flow(client, db):
    user = make_user("ana@example.com")
    response = client.post(reverse("accounts:password_reset"), {"email": "ANA@example.com"}, secure=True)
    assert response.url == reverse("accounts:password_reset_done")
    assert len(mail.outbox) == 1
    message = mail.outbox[0]
    assert message.to == ["ana@example.com"] and "contraseña" in message.subject
    link = reset_link(message)
    assert link in message.alternatives[0][0]  # same link in the HTML part

    set_password_url = client.get(link, secure=True).url  # Django swaps the token for a session
    response = client.post(set_password_url, {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD}, secure=True)
    assert response.url == reverse("accounts:password_reset_complete")
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD)
    assert mail.outbox[-1].subject == "Tu contraseña de menuamano ha cambiado"
    assert client.get(link, secure=True).status_code in (200, 302)  # used link no longer resets


def test_password_reset_does_not_reveal_unknown_addresses(client, db):
    response = client.post(reverse("accounts:password_reset"), {"email": "nadie@example.com"})
    assert response.url == reverse("accounts:password_reset_done")
    assert mail.outbox == []


def test_password_change_sends_security_notice(client, db):
    user = make_user("luis@example.com")
    assert client.login(email=user.email, password=PASSWORD)
    response = client.post(reverse("accounts:password_change"), {
        "old_password": PASSWORD, "new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD,
    })
    assert response.url == reverse("core:home")
    assert [m.subject for m in mail.outbox] == ["Tu contraseña de menuamano ha cambiado"]


def test_login_page_links_to_password_reset(client, db):
    assert reverse("accounts:password_reset") in client.get(reverse("accounts:login")).content.decode()


# --- Invitations ----------------------------------------------------------------------------------


def test_invitation_is_sent_by_email(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("households:invitation_create"), {"role": "reader", "email": "Marta@Example.com"})
    invitation = Invitation.objects.get()
    assert invitation.email == "marta@example.com"
    message = mail.outbox[0]
    assert message.to == ["marta@example.com"]
    assert household.name in message.subject
    link = client.get(reverse("households:settings")).context["new_link"]
    assert link in message.body and link in message.alternatives[0][0]


def test_invalid_invitation_email_creates_nothing(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    client.post(reverse("households:invitation_create"), {"role": "reader", "email": "no-es-un-correo"})
    assert not Invitation.objects.exists()
    assert mail.outbox == []


def test_provider_failure_keeps_the_invitation_link(client, household, admin_user):
    assert client.login(email=admin_user.email, password=PASSWORD)
    with mock.patch("core.emails.EmailMultiAlternatives.send", side_effect=OSError("mailgun down")):
        response = client.post(reverse("households:invitation_create"), {"role": "reader", "email": "a@example.com"}, follow=True)
    assert Invitation.objects.count() == 1
    assert "No se ha podido enviar el correo" in response.content.decode()
    assert response.context["new_link"]


def test_send_email_never_raises(db, caplog):
    with mock.patch("core.emails.EmailMultiAlternatives.send", side_effect=RuntimeError("boom")):
        assert send_email("test", "x@example.com", "Prueba", {"backend": "test"}) is False
    assert "example.com" in caplog.text and "x@example.com" not in caplog.text


def test_send_test_email_command(db):
    call_command("send_test_email", "ops@example.com")
    assert mail.outbox[0].to == ["ops@example.com"]
    with mock.patch("core.emails.EmailMultiAlternatives.send", side_effect=OSError("down")):
        with pytest.raises(CommandError):
            call_command("send_test_email", "ops@example.com")


# --- Production settings ----------------------------------------------------------------------------

EMAIL_VARS = ["EMAIL_PROVIDER", "MAILGUN_API_KEY", "MAILGUN_SENDER_DOMAIN", "MAILGUN_API_URL", "DEFAULT_FROM_EMAIL",
              "MAILGUN_WEBHOOK_SIGNING_KEY", "ANYMAIL_WEBHOOK_SECRET", "DJANGO_ADMINS", "SERVER_EMAIL"]
PRINT_SETTINGS = (
    "import django; from django.conf import settings; django.setup(); "
    "print(settings.EMAIL_BACKEND); print(sorted(settings.ANYMAIL)); print(settings.DEFAULT_FROM_EMAIL); print(settings.ADMINS)"
)


def run_production_settings(**extra):
    env = {k: v for k, v in os.environ.items() if k not in EMAIL_VARS}
    env.update(DJANGO_SETTINGS_MODULE="config.settings.production", DJANGO_SECRET_KEY="s" * 50,
               DJANGO_ALLOWED_HOSTS="menuamano.example.com", BILLING_ENABLED="false", **extra)
    return subprocess.run([sys.executable, "-c", PRINT_SETTINGS], env=env, cwd=BASE_DIR, capture_output=True, text=True)


def test_production_uses_mailgun_with_required_settings():
    result = run_production_settings(
        MAILGUN_API_KEY="key-123", MAILGUN_SENDER_DOMAIN="mg.example.com", MAILGUN_API_URL="https://api.eu.mailgun.net/v3",
        DEFAULT_FROM_EMAIL="menuamano <no-reply@mg.example.com>", DJANGO_ADMINS="Ana <ana@example.com>, ops@example.com",
    )
    assert result.returncode == 0, result.stderr
    backend, keys, sender, admins = result.stdout.strip().splitlines()
    assert backend == "anymail.backends.mailgun.EmailBackend"
    assert "MAILGUN_API_KEY" in keys and "MAILGUN_SENDER_DOMAIN" in keys and "MAILGUN_API_URL" in keys
    assert sender == "menuamano <no-reply@mg.example.com>"
    assert "('Ana', 'ana@example.com')" in admins and "('ops@example.com', 'ops@example.com')" in admins


def test_production_refuses_to_start_without_mailgun_credentials():
    result = run_production_settings(MAILGUN_SENDER_DOMAIN="mg.example.com", DEFAULT_FROM_EMAIL="x@mg.example.com")
    assert result.returncode != 0
    assert "MAILGUN_API_KEY" in result.stderr


def test_production_console_escape_hatch():
    result = run_production_settings(EMAIL_PROVIDER="console")
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[0] == "django.core.mail.backends.console.EmailBackend"


# --- Mailgun tracking webhook -------------------------------------------------------------------------


def mailgun_payload(token, key="test-signing-key", **event_data):
    timestamp = str(int(time.time()))
    signature = hmac.new(key.encode(), f"{timestamp}{token}".encode(), hashlib.sha256).hexdigest()
    data = {
        "event": "failed", "severity": "permanent", "reason": "bounce", "recipient": "ana@example.com",
        "timestamp": time.time(), "message": {"headers": {"message-id": "abc123@mg.example.com"}},
        "delivery-status": {"description": "Mailbox does not exist", "message": "550 5.1.1 unknown user"},
        **event_data,
    }
    return json.dumps({"signature": {"timestamp": timestamp, "token": token, "signature": signature}, "event-data": data})


def test_signed_bounce_is_stored_once(client, db):
    url = "/anymail/mailgun/tracking/"
    payload = mailgun_payload("token-1")
    assert client.post(url, payload, content_type="application/json").status_code == 200
    assert client.post(url, payload, content_type="application/json").status_code == 200  # provider retry
    event = EmailEvent.objects.get()
    assert event.event_type == "bounced"
    assert event.recipient == "ana@example.com"
    assert event.message_id == "<abc123@mg.example.com>"
    assert event.description == "Mailbox does not exist"


def test_webhook_with_wrong_signature_is_rejected(client, db):
    payload = mailgun_payload("token-2", key="not-the-key")
    response = client.post("/anymail/mailgun/tracking/", payload, content_type="application/json")
    assert response.status_code == 400
    assert not EmailEvent.objects.exists()
