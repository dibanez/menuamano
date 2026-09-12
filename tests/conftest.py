from datetime import date

import pytest

from households.models import Role

from .factories import make_household, make_user


@pytest.fixture
def admin_user(db):
    return make_user("admin@example.com")


@pytest.fixture
def household(admin_user):
    return make_household("Casa Uno", admin=admin_user, role=Role.ADMIN)


@pytest.fixture
def monday():
    # A fixed Monday far in the future, so "upcoming" revalidation always includes it.
    return date(2030, 1, 7)
