from .config import DEVICE_STATUS, ai_status


def ai_mode(request):
    household = getattr(request, "household", None)
    if household is None:
        return {"ai_status": ai_status()}
    from billing import entitlements

    if entitlements.ai_mode(household) == entitlements.AI_DEVICE:
        # Whether this device has a key is only known in the browser, which asks for one if missing.
        return {"ai_status": DEVICE_STATUS, "ai_allowed": True, "ai_block_message": ""}
    allowed, message = entitlements.check_ai(household)
    return {"ai_status": ai_status(), "ai_allowed": allowed, "ai_block_message": message}
