"""Rate limits for actions that can be abused: signing in, sending emails, importing recipes.

Attempts live in the database, so every gunicorn worker counts the same ones.
"""

import random
from datetime import timedelta
from functools import wraps

from django.shortcuts import render
from django.utils import timezone

from .models import ThrottleEvent

KEEP = timedelta(days=2)  # longer than any window in use


def client_ip(request):
    """The visitor's address. Traefik sets X-Real-Ip and replaces any value the client sent."""
    return (request.headers.get("X-Real-Ip") or request.META.get("REMOTE_ADDR") or "unknown").strip()[:64]


def exceeded(key, limit, window):
    return ThrottleEvent.objects.filter(key=key, created_at__gte=timezone.now() - window).count() >= limit


def record(*keys):
    ThrottleEvent.objects.bulk_create([ThrottleEvent(key=key[:200]) for key in keys])
    if random.random() < 0.01:  # noqa: S311 - occasional housekeeping, not a security decision
        ThrottleEvent.objects.filter(created_at__lt=timezone.now() - KEEP).delete()


def allow(key, limit, window):
    """Record an attempt, unless `limit` attempts already happened within `window`."""
    if exceeded(key, limit, window):
        return False
    record(key)
    return True


def too_many(request):
    return render(request, "core/throttled.html", status=429)


def limit_failed_logins(view, account_limit=10, ip_limit=30, window=timedelta(minutes=15)):
    """Wrap a login view: after too many failed attempts for an account or from an address, wait.

    A failed login answers 200 (the form again); a successful one redirects.
    """

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.method != "POST":
            return view(request, *args, **kwargs)
        limits = {f"login:ip:{client_ip(request)}": ip_limit}
        account = (request.POST.get("username") or "").strip().lower()[:150]
        if account:
            limits[f"login:account:{account}"] = account_limit
        if any(exceeded(key, limit, window) for key, limit in limits.items()):
            return too_many(request)
        response = view(request, *args, **kwargs)
        if response.status_code == 200:
            record(*limits)
        return response

    return wrapper
