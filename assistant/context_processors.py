from .config import ai_status


def ai_mode(request):
    return {"ai_status": ai_status()}
