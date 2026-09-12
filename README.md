# menuamano

Aplicación web para organizar la alimentación de un hogar: qué coméis, quién come en casa,
qué recetas encajan con las restricciones de cada persona, qué cantidades hacen falta, qué
hay que comprar y cómo se prepara cada plato. La interfaz está en español y pensada para el
móvil.

- Django 5.2 LTS, PostgreSQL 17, plantillas de Django y HTMX. Sin paso de build de frontend.
- Asistente opcional con la API de OpenAI (Responses API con salidas estructuradas), usado
  solo desde el backend. Hay un **modo demostración** determinista que no necesita clave.

## Arranque rápido con Docker

```bash
cp .env.example .env          # opcional: valores locales
docker compose up --build -d  # web en http://localhost:8010
docker compose exec web python manage.py load_demo
```

Cuentas de demostración (contraseña `menuamano-demo`):

| Cuenta | Rol |
|---|---|
| `ana@menuamano.demo` | Administración |
| `luis@menuamano.demo` | Edición |
| `lector@menuamano.demo` | Lectura |

`load_demo` crea «Casa demo», con cuatro comensales (una alergia al huevo y una intolerancia a la
lactosa), 16 recetas, una regla de «cena fuera los viernes», una excepción de un miércoles,
dos semanas planificadas y la lista de compra de esta semana. Es reproducible:
`load_demo --reset` reconstruye solo ese hogar y no toca ningún otro dato.

Los puertos se pueden cambiar con `WEB_HOST_PORT` (8010 por defecto) y `DB_HOST_PORT` (5433).
La base de datos solo se publica en `127.0.0.1`.

## Pruebas

```bash
docker compose run --rm web pytest     # dentro del contenedor
# o, con un virtualenv local y la base de datos del compose levantada:
python -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
```

Las pruebas nunca llaman a la API de pago: usan el proveedor de demostración, proveedores
falsos y un cliente de OpenAI simulado.

## Configuración

Toda la configuración llega por variables de entorno (ver `.env.example`).

| Variable | Uso |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.local` (desarrollo), `config.settings.production`, `config.settings.test` |
| `DJANGO_SECRET_KEY` | Obligatoria en producción |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Producción |
| `POSTGRES_*` | Conexión a la base de datos |
| `AI_PROVIDER` | `demo` (por defecto) u `openai` |
| `OPENAI_API_KEY` | Solo la lee el servidor. Nunca llega al navegador ni al repositorio |
| `OPENAI_MODEL` | Cualquier modelo compatible con salidas estructuradas en la Responses API. No hay valor fijo en el código |
| `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`, `OPENAI_MAX_OUTPUT_TOKENS` | Límites de cada llamada |

Si `AI_PROVIDER=openai` y falta la clave o el modelo, el asistente aparece como «IA sin
configurar» y el resto de la aplicación funciona igual.

`compose.prod.yaml` es solo una referencia de despliegue (gunicorn, `DEBUG=False`, cookies
seguras, estáticos con WhiteNoise). Este repositorio no despliega nada.

## Estructura

```
config/       settings por entorno, urls
core/         inicio, vocabulario común, filtros de plantilla, comando load_demo
accounts/     usuario (acceso por correo)
households/   hogares, miembros, roles y el middleware del hogar activo
foods/        catálogo de ingredientes, rasgos (alérgenos), unidades y motor de compatibilidad
diners/       comensales, restricciones, preferencias, asistencia habitual, peso y sus permisos
recipes/      recetas, versiones, favoritas
planning/     calendario, comidas, snapshots de recetas, reglas, excepciones y regeneración
shopping/     listas de compra calculadas
assistant/    proveedores de IA, contexto seudonimizado, propuestas y chat
templates/, static/   interfaz
tests/        pruebas (pytest)
docs/         plan de implementación y arquitectura
```

Más detalle en [`docs/architecture.md`](docs/architecture.md) y el estado del trabajo en
[`docs/implementation-plan.md`](docs/implementation-plan.md).

## Qué no hace todavía

Despensa y congelador, caducidades, lotes de sobras, precios, nutrición, códigos de barras e
integraciones con supermercados. La lista de compra lo indica: no descuenta existencias.
