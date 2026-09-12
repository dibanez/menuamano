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
| `EMAIL_PROVIDER` | `console` (local, por defecto) o `mailgun` (producción, por defecto) |
| `MAILGUN_*`, `DEFAULT_FROM_EMAIL`, `DJANGO_ADMINS` | Correo: ver «Correo con Mailgun» |

Si `AI_PROVIDER=openai` y falta la clave o el modelo, el asistente aparece como «IA sin
configurar» y el resto de la aplicación funciona igual.

## Despliegue en Dokploy

`compose.prod.yaml` está preparado para Dokploy (gunicorn, `DEBUG=False`, cookies seguras, HSTS,
estáticos con WhiteNoise y PostgreSQL con volumen con nombre).

1. Crea un servicio **Docker Compose** desde el repositorio, con la ruta `./compose.prod.yaml`.
2. En **Environment** define las variables. Dokploy las escribe en un `.env` y el compose las lee
   con `${VAR}`; no hace falta `env_file`.

   | Variable | Obligatoria | Valor |
   |---|---|---|
   | `DJANGO_SECRET_KEY` | Sí | Cadena aleatoria larga |
   | `DJANGO_ALLOWED_HOSTS` | Sí | Tu dominio, p. ej. `menuamano.example.com` |
   | `POSTGRES_PASSWORD` | Sí | Contraseña de la base de datos |
   | `POSTGRES_DB`, `POSTGRES_USER` | No | `menuamano` por defecto |
   | `DJANGO_CSRF_TRUSTED_ORIGINS` | No | `https://tu-dominio` si usas otro origen |
   | `MAILGUN_API_KEY` | Sí | Clave de envío de Mailgun (mejor una *sending key* del dominio) |
   | `MAILGUN_SENDER_DOMAIN` | Sí | Dominio verificado en Mailgun, p. ej. `mg.example.com` |
   | `DEFAULT_FROM_EMAIL` | Sí | Remitente, p. ej. `menuamano <no-reply@mg.example.com>` |
   | `MAILGUN_API_URL` | No | Por defecto la región US; en la UE, `https://api.eu.mailgun.net/v3` |
   | `MAILGUN_WEBHOOK_SIGNING_KEY` | Recomendada | Activa el webhook de rebotes y quejas |
   | `DJANGO_ADMINS` | Recomendada | Quién recibe los errores del servidor, p. ej. `Ana <ana@example.com>` |
   | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Sí* | Clave secreta y secreto del webhook de Stripe |
   | `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY` | Sí* | Ids de precio de Premium (`price_…`) |
   | `SITE_URL` | Recomendada | `https://tu-dominio`, para enlaces en correos enviados desde webhooks |
   | `AI_PROVIDER` | No | `demo` (por defecto) u `openai` |
   | `OPENAI_REASONING_EFFORT` | No | `low` por defecto; vacío si el modelo no razona |
   | `OPENAI_API_KEY`, `OPENAI_MODEL` | Con `openai` | Clave y modelo |
   | `GUNICORN_WORKERS`, `DJANGO_HSTS_SECONDS`, `OPENAI_TIMEOUT_SECONDS`… | No | Ajustes finos |

3. En **Domains** añade el dominio para el servicio `web`, puerto `8000`, con HTTPS. Dokploy
   añade las etiquetas de Traefik y la red al desplegar; el compose no publica puertos.
4. Despliega. Al arrancar se aplican las migraciones y se recogen los estáticos. El healthcheck
   usa `/healthz`, que comprueba la base de datos y no pasa por la redirección HTTPS.

Para crear un superusuario: `python manage.py createsuperuser` en la terminal del contenedor `web`
desde Dokploy. No cargues `load_demo` en producción.

### Correo con Mailgun

La aplicación envía la recuperación de contraseña, el aviso de contraseña cambiada, las
invitaciones al hogar y los errores del servidor a `DJANGO_ADMINS`. En producción el correo va por
la API de Mailgun (Anymail), y el despliegue no arranca si faltan la clave, el dominio o el
remitente. En local los correos se escriben en los logs del contenedor `web`.

1. En Mailgun, añade y verifica el dominio de envío (registros SPF, DKIM y, si quieres, el CNAME
   de seguimiento) y crea una *sending API key* para ese dominio.
2. Pon en Dokploy `MAILGUN_API_KEY`, `MAILGUN_SENDER_DOMAIN`, `DEFAULT_FROM_EMAIL` (con una
   dirección de ese dominio) y, si la cuenta es de la UE, `MAILGUN_API_URL`.
3. Webhooks (recomendado): en Mailgun → *Webhooks* apunta los eventos *Permanent failure*,
   *Temporary failure* y *Spam complaints* a `https://<tu-dominio>/anymail/mailgun/tracking/`, y
   copia la *HTTP webhook signing key* en `MAILGUN_WEBHOOK_SIGNING_KEY`. Los eventos se ven en
   el admin de Django («Eventos de correo»). Sin esa clave, la ruta del webhook no existe.
4. Comprueba el envío desde la terminal del contenedor `web`:
   `python manage.py send_test_email tu@correo.com`.

### Pagos con Stripe

Planes: **Gratis** (planificación manual completa, hasta 2 personas con cuenta) y **Premium**
(4,99 €/mes o 49 €/año por hogar: asistente con IA con 150 peticiones al mes y hasta 8 personas
con cuenta). Los límites se cambian con `FREE_MAX_MEMBERS`, `PREMIUM_MAX_MEMBERS` y
`PREMIUM_AI_MONTHLY_LIMIT`. En producción la facturación está activa por defecto (`*` en la tabla:
obligatorias salvo `BILLING_ENABLED=false`).

1. En Stripe crea el producto «menuamano Premium» con dos precios recurrentes en EUR: 4,99 € al mes
   y 49 € al año. Copia sus ids en `STRIPE_PRICE_MONTHLY` y `STRIPE_PRICE_YEARLY`.
2. Activa el **portal de cliente** (Settings → Billing → Customer portal): cancelar, cambiar de
   precio entre esos dos y actualizar el método de pago.
3. Crea un endpoint de webhook a `https://<tu-dominio>/plan/stripe/webhook/` con los eventos
   `checkout.session.completed`, `customer.subscription.created`, `customer.subscription.updated`,
   `customer.subscription.deleted` e `invoice.payment_failed`. Copia su secreto en
   `STRIPE_WEBHOOK_SECRET`.
4. Pon `STRIPE_SECRET_KEY` (empieza en modo test con `sk_test_…` y la tarjeta 4242 4242 4242 4242).
   Si usas Stripe Tax para el IVA, `STRIPE_AUTOMATIC_TAX=true`.

Antes de cobrar de verdad necesitas publicar aviso legal, política de privacidad (la app trata
datos de salud: alergias y peso) y condiciones de contratación con el derecho de desistimiento.
No están incluidos en el repositorio.

`EMAIL_PROVIDER=console` desactiva el envío real en producción. Úsalo solo de forma temporal: los
correos se quedarían en los logs.

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
