from .models import Membership


def household(request):
    membership = getattr(request, "membership", None)
    context = {"membership": membership, "household": getattr(request, "household", None)}
    if membership is not None:
        context["can_edit"] = membership.can_edit
        context["is_household_admin"] = membership.is_admin
        context["other_memberships"] = (
            Membership.objects.filter(user=request.user).exclude(pk=membership.pk).select_related("household")
        )
    return context
