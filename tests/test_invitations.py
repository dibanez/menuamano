from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from households.models import Invitation, Membership, Role, hash_token

from .factories import PASSWORD, add_member, make_user


def login(client, user):
    assert client.login(email=user.email, password=PASSWORD)


def create_link(client, admin_user, role=Role.EDITOR):
    login(client, admin_user)
    client.post(reverse("households:invitation_create"), {"role": role})
    page = client.get(reverse("households:settings"))
    link = page.context["new_link"]
    client.logout()
    return link


def token_from(link):
    return link.rstrip("/").rsplit("/", 1)[-1]


def test_admin_creates_single_use_link_and_only_hash_is_stored(client, household, admin_user):
    link = create_link(client, admin_user)
    token = token_from(link)
    invitation = Invitation.objects.get()
    assert invitation.token_hash == hash_token(token)
    assert token not in invitation.token_hash

    guest = make_user("guest@example.com")
    login(client, guest)
    response = client.post(reverse("households:invitation", args=[token]))
    assert response.status_code == 302
    assert Membership.objects.get(user=guest, household=household).role == Role.EDITOR
    assert client.session["active_household_id"] == household.pk

    other = make_user("other@example.com")
    client.logout()
    login(client, other)
    response = client.post(reverse("households:invitation", args=[token]))
    assert response.status_code == 410
    assert not Membership.objects.filter(user=other).exists()


def test_link_is_shown_only_once(client, household, admin_user):
    create_link(client, admin_user)
    login(client, admin_user)
    assert client.get(reverse("households:settings")).context["new_link"] is None


def test_expired_and_revoked_invitations_are_refused(client, household, admin_user):
    expired, expired_token = Invitation.issue(household, Role.READER, admin_user)
    Invitation.objects.filter(pk=expired.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
    revoked, revoked_token = Invitation.issue(household, Role.READER, admin_user)
    login(client, admin_user)
    client.post(reverse("households:invitation_revoke", args=[revoked.pk]))
    client.logout()

    guest = make_user("guest@example.com")
    login(client, guest)
    assert client.post(reverse("households:invitation", args=[expired_token])).status_code == 410
    assert client.post(reverse("households:invitation", args=[revoked_token])).status_code == 410
    assert client.get(reverse("households:invitation", args=["not-a-real-token"])).status_code == 404
    assert not Membership.objects.filter(user=guest).exists()


def test_existing_member_keeps_role_and_link_stays_usable(client, household, admin_user):
    member = make_user("member@example.com")
    add_member(household, member, Role.READER)
    invitation, token = Invitation.issue(household, Role.ADMIN, admin_user)
    login(client, member)
    client.post(reverse("households:invitation", args=[token]))
    assert Membership.objects.get(user=member, household=household).role == Role.READER
    invitation.refresh_from_db()
    assert invitation.is_usable


def test_only_admins_manage_invitations(client, household, admin_user):
    editor = make_user("editor@example.com")
    add_member(household, editor, Role.EDITOR)
    invitation, _ = Invitation.issue(household, Role.READER, admin_user)
    login(client, editor)
    assert client.post(reverse("households:invitation_create"), {"role": Role.ADMIN}).status_code == 403
    assert client.post(reverse("households:invitation_revoke", args=[invitation.pk])).status_code == 403
    assert Invitation.objects.count() == 1


@pytest.mark.django_db
def test_new_person_signs_up_from_link_and_joins(client, household, admin_user):
    _, token = Invitation.issue(household, Role.READER, admin_user)
    path = reverse("households:invitation", args=[token])
    page = client.get(path)
    assert page.status_code == 200 and "Crear una cuenta" in page.content.decode()

    response = client.post(reverse("accounts:signup") + f"?next={path}", {
        "email": "nueva@example.com", "display_name": "Nueva", "password1": "cocina-casera-2030",
        "password2": "cocina-casera-2030", "next": path, "accept_terms": "on", "health_consent": "on",
    })
    assert response.status_code == 302 and response.url == path
    client.post(path)
    assert Membership.objects.get(user__email="nueva@example.com").role == Role.READER


def test_signup_ignores_external_next(client, db):
    response = client.post(reverse("accounts:signup"), {
        "email": "x@example.com", "display_name": "", "password1": "cocina-casera-2030",
        "password2": "cocina-casera-2030", "next": "https://evil.example.com/", "accept_terms": "on", "health_consent": "on",
    })
    assert response.url == reverse("households:onboarding")
