from .config import ai_status


def ai_mode(request):
    context = {"ai_status": ai_status()}
    household = getattr(request, "household", None)
    if household is not None:
        from billing.entitlements import check_ai

        allowed, message = check_ai(household)
        context.update(ai_allowed=allowed, ai_block_message=message)
    return context
