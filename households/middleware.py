from .permissions import resolve_membership


class ActiveHouseholdMiddleware:
    """Attach `request.membership` and `request.household` (validated on each request)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        membership = resolve_membership(request)
        request.membership = membership
        request.household = membership.household if membership else None
        return self.get_response(request)
