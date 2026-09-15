from dataclasses import dataclass

from django.conf import settings

MODE_DEMO = "demo"
MODE_OPENAI = "openai"
MODE_DEVICE = "device"
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
    def is_device(self):
        return self.mode == MODE_DEVICE

    @property
    def available(self):
        return self.mode in (MODE_DEMO, MODE_OPENAI, MODE_DEVICE)


# Households without the server's key: each person's browser calls their own provider.
DEVICE_STATUS = AIStatus(
    MODE_DEVICE,
    "Con tu clave",
    "El asistente usa la clave de IA guardada en este dispositivo: tu navegador la envía directamente a tu "
    "proveedor y menuamano nunca la recibe.",
)


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
