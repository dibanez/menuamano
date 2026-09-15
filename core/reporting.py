"""Error reports emailed to DJANGO_ADMINS, without personal data."""

from django.views.debug import SafeExceptionReporterFilter


class PrivateExceptionReporterFilter(SafeExceptionReporterFilter):
    """Hide every form field and cookie: they can hold passwords, health data, AI answers or sessions."""

    def get_post_parameters(self, request):
        if request is None:
            return {}
        return {key: self.cleansed_substitute for key in request.POST}

    def get_safe_cookies(self, request):
        return {key: self.cleansed_substitute for key in getattr(request, "COOKIES", {})}
