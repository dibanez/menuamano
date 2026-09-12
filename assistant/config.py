from dataclasses import dataclass

from django.conf import settings

MODE_DEMO = "demo"
MODE_OPENAI = "openai"
MODE_UNCONFIGURED = "unconfigured"


@dataclass(frozen=True)
class AIStatus:
    mode: str
    label: str
    detail: str

    @property
    def is_demo(self):
        return self.mode == MODE_DEMO

    @property
    def available(self):
        return self.mode in (MODE_DEMO, MODE_OPENAI)


def ai_status():
    provider = (settings.AI_PROVIDER or MODE_DEMO).lower()
    if provider == MODE_OPENAI:
        if settings.OPENAI_API_KEY and settings.OPENAI_MODEL:
            return AIStatus(MODE_OPENAI, "IA conectada", f"Modelo configurado: {settings.OPENAI_MODEL}")
        return AIStatus(
            MODE_UNCONFIGURED,
            "IA sin configurar",
            "Faltan OPENAI_API_KEY u OPENAI_MODEL. Los flujos manuales siguen funcionando.",
        )
    return AIStatus(
        MODE_DEMO,
        "Modo demostración",
        "Las propuestas las genera un proveedor local determinista, no una IA real.",
    )
