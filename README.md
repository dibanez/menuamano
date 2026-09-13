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
| `EMAIL_PROVIDER` | `console` (local, por defecto), `smtp` (producción, por defecto) o `mailgun` (API HTTP) |
| `EMAIL_*`, `MAILGUN_*`, `DEFAULT_FROM_EMAIL`, `DJANGO_ADMINS` | Correo: ver «Correo con Mailgun» |

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
   | `EMAIL_HOST_USER` | Sí | Usuario SMTP de Mailgun, p. ej. `postmaster@mg.example.com` |
   | `EMAIL_HOST_PASSWORD` | Sí | Contraseña SMTP de ese usuario |
   | `DEFAULT_FROM_EMAIL` | Sí | Remitente, p. ej. `menuamano <no-reply@mg.example.com>` |
   | `EMAIL_HOST` | No | `smtp.mailgun.org` por defecto; en la UE, `smtp.eu.mailgun.org` |
   | `EMAIL_PORT` | No | `587` (STARTTLS) por defecto; `465` activa SSL; `2525` si el 587 está bloqueado |
   | `DJANGO_ADMINS` | Recomendada | Quién recibe los errores del servidor, p. ej. `Ana <ana@example.com>` |
   | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | Sí* | Clave secreta y secreto del webhook de Stripe |
   | `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY` | Sí* | Ids de precio de Premium (`price_…`) |
   | `SITE_URL` | Recomendada | `https://tu-dominio`: URL canónica, `sitemap.xml` y enlaces en correos enviados desde webhooks |
   | `AI_PROVIDER` | No | `demo` (por defecto) u `openai` |
   | `OPENAI_REASONING_EFFORT` | No | `low` por defecto; vacío si el modelo no razona |
   | `GTM_CONTAINER_ID` | No | `GTM-WWR8DTN8` por defecto; vacío para no cargar Tag Manager |
   | `GTM_SCOPE`, `COOKIE_CONSENT_BANNER` | No | `public` y `true`: ver «Analítica» |
   | `OPENAI_API_KEY`, `OPENAI_MODEL` | Con `openai` | Clave y modelo |
   | `GUNICORN_WORKERS`, `DJANGO_HSTS_SECONDS`, `OPENAI_TIMEOUT_SECONDS`… | No | Ajustes finos |

3. En **Domains** añade el dominio para el servicio `menuamano-web`, puerto `8000`, con HTTPS. Dokploy
   añade las etiquetas de Traefik y la red al desplegar; el compose no publica puertos.
4. Despliega. Al arrancar se aplican las migraciones y se recogen los estáticos. El healthcheck
   usa `/healthz`, que comprueba la base de datos y no pasa por la redirección HTTPS.

Para crear un superusuario: `python manage.py createsuperuser` en la terminal del contenedor `menuamano-web`
desde Dokploy. No cargues `load_demo` en producción.

### Correo con Mailgun

La aplicación envía la recuperación de contraseña, el aviso de contraseña cambiada, las
invitaciones al hogar y los errores del servidor a `DJANGO_ADMINS`. En producción el correo va por
el SMTP de Mailgun, y el despliegue no arranca si faltan el usuario, la contraseña o el remitente.
En local los correos se escriben en los logs del contenedor `web`.

1. En Mailgun, añade y verifica el dominio de envío (registros SPF, DKIM y, si quieres, el CNAME
   de seguimiento).
2. En *Sending → Domain settings → SMTP credentials* usa `postmaster@<dominio>` o crea otro
   usuario, y genera su contraseña (Mailgun solo la enseña una vez).
3. Pon en Dokploy `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL` (con una
   dirección de ese dominio). Si la cuenta es de la UE, `EMAIL_HOST=smtp.eu.mailgun.org`.

Para usar la API HTTP de Mailgun en lugar de SMTP: `EMAIL_PROVIDER=mailgun`, `MAILGUN_API_KEY`,
`MAILGUN_SENDER_DOMAIN` y, en la UE, `MAILGUN_API_URL=https://api.eu.mailgun.net/v3`.

Para comprobar el envío, desde la terminal del contenedor `menuamano-web`:
`python manage.py send_test_email tu@correo.com`.

La aplicación no tiene webhook de Mailgun: los rebotes y las quejas se consultan en el panel de
Mailgun (*Sending → Logs* y *Suppressions*). Si en Mailgun quedan webhooks apuntando a
`/anymail/…`, bórralos: la aplicación les responde 406 para que Mailgun no reintente.

### App instalable (PWA)

menuamano se puede instalar en el móvil y en el ordenador («Añadir a pantalla de inicio» en
Safari, «Instalar app» en Chrome o Edge) y arranca a pantalla completa, sin la barra del navegador.

- `/manifest.webmanifest`: nombre, colores, iconos (también el adaptable de Android) y accesos
  directos a Hoy, Calendario, Compra y Asistente.
- `/sw.js`: el service worker. Solo guarda en caché los estáticos y la página «Sin conexión»
  (`/offline/`). Las páginas nunca se guardan: llevan los datos de cada hogar y cambian a cada rato.
  La caché cambia de nombre en cada despliegue que toca los estáticos, así que no hay que vaciarla
  a mano.

Hace falta HTTPS (o `localhost`) para que el navegador registre el service worker.

### Recordatorios (notificaciones)

Avisos en el móvil con lo que hay mañana (y lo que hay que preparar la víspera) y, los domingos,
si la semana siguiente está sin planificar. Cada persona los activa en «Recordatorios» del menú.

1. Genera las claves una vez: `docker compose exec web python manage.py generate_vapid_keys`.
2. Copia `VAPID_PUBLIC_KEY` y `VAPID_PRIVATE_KEY` en Environment de Dokploy (la privada es
   secreta; si cambias el par, cada dispositivo tiene que volver a activarlos). Opcional:
   `VAPID_SUBJECT=mailto:…` (por defecto, `LEGAL_CONTACT_EMAIL`).
3. Redespliega. El servicio `menuamano-reminders` los envía cada cinco minutos; sin claves no
   envía nada.

En iPhone y iPad solo llegan con la app instalada (iOS 16.4 o posterior).

### Pagos con Stripe

Planes: **Gratis** (planificación completa, 7 peticiones de prueba al asistente con IA, que no se
renuevan, y hasta 2 personas con cuenta) y **Premium**
(4,99 €/mes o 49 €/año por hogar: asistente con IA con 150 peticiones al mes y hasta 8 personas
con cuenta). Los límites se cambian con `FREE_MAX_MEMBERS`, `FREE_MAX_OWNED_HOUSEHOLDS` (hogares que puede crear una
cuenta gratuita; administrar un hogar Premium quita el límite), `FREE_AI_TOTAL_LIMIT`
(peticiones de prueba en total; 0 quita el asistente del plan gratuito), `PREMIUM_MAX_MEMBERS` y `PREMIUM_AI_MONTHLY_LIMIT`. En producción la facturación está activa por defecto (`*` en la tabla:
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

### Textos legales

Hay cuatro páginas públicas en `/legal/`: aviso legal (LSSI-CE), política de privacidad (RGPD y
LOPDGDD), política de cookies y condiciones de uso y contratación (precios, renovación, cancelación
y derecho de desistimiento).

- **Datos del titular**: se rellenan con `LEGAL_OWNER_NAME`, `LEGAL_OWNER_TAX_ID`,
  `LEGAL_OWNER_ADDRESS` y `LEGAL_CONTACT_EMAIL` (y, si aplica, `LEGAL_REGISTRY` y
  `LEGAL_HOSTING_PROVIDER`). Mientras falten, las páginas muestran huecos resaltados y
  `manage.py check` avisa (`menuamano.W001`).
- **Consentimiento al registrarse**: hay que aceptar las condiciones y la privacidad (a partir de
  14 años) y dar el **consentimiento explícito para datos de salud** (alergias, intolerancias,
  dietas y peso). Se guardan la fecha y la versión aceptada.
- **Si cambian los textos**: al cambiar `core.legal.LEGAL_VERSION`, todas las personas tienen que
  aceptarlos de nuevo antes de seguir usando la app.
- **Revisión legal**: los textos describen lo que hace el código, pero conviene que los revise un
  profesional antes de cobrar. Comprueba también que los precios de Stripe llevan los impuestos
  incluidos, como indican las condiciones.

### Analítica (Google Tag Manager)

Con `GTM_CONTAINER_ID` se carga el contenedor de Tag Manager.

- **Consentimiento**: el Consent Mode v2 empieza con analítica y publicidad **denegadas** y un
  banner propio pide permiso. La elección se guarda en el navegador y se puede cambiar desde el
  enlace «Cookies» del pie de la landing. Configura en GTM los tags de Google con la comprobación
  de consentimiento integrada. Si prefieres un CMP (Cookiebot, etc.) dentro de GTM, pon
  `COOKIE_CONSENT_BANNER=false`.
- **Alcance**: por defecto (`GTM_SCOPE=public`) solo se carga para visitantes sin sesión: landing,
  acceso, registro y recuperación de contraseña. Dentro de la app los títulos y las rutas contienen
  nombres y datos de salud (peso, alergias), así que `GTM_SCOPE=all` solo si tienes base legal y
  configuras GTM para no enviarlos.
- No se incluye el `<noscript>` de GTM, porque cargaría tags sin consentimiento.
- La política de cookies está en `/legal/cookies/` y el banner la enlaza.

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

Inventario automático, congelador, lotes de sobras, precios, nutrición e integraciones con
supermercados. La despensa recoge lo que anotáis: lo comprado se guarda desde la lista con su
caducidad y el asistente lo usa antes de que caduque, pero nada se gasta solo («Gastado»).
