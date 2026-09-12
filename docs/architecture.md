# Arquitectura y reglas

## Monolito modular

Un único proyecto Django con apps por dominio. Las reglas viven en módulos de servicio sin
dependencias de la interfaz (`foods/compatibility.py`, `planning/services.py`,
`shopping/services.py`, `assistant/services.py`) y las vistas solo los orquestan. No hay
colas, workers ni servicios externos aparte de PostgreSQL y, opcionalmente, OpenAI.

```
households ─┬─ diners ──┐
            ├─ recipes ─┼─ planning ── shopping
foods ──────┘           │      ▲
                        └── assistant (propone; planning aplica)
```

La lista de compra se recalcula mediante una señal (`planning.signals.meals_changed`) que
emite cualquier cambio de comida, así `planning` no depende de `shopping`.

## Autorización

- `ActiveHouseholdMiddleware` resuelve el hogar activo en **cada** petición a partir de la
  sesión, pero lo **revalida contra `Membership`**. Un id manipulado se ignora.
- Todas las consultas de objetos se filtran por `household=request.household`, de modo que un
  id de otro hogar devuelve 404. Los formularios limitan sus `queryset` al hogar y al catálogo
  compartido.
- `household_required(role)` exige iniciar sesión, tener hogar y un rol mínimo:
  lectura < edición < administración.
- **Invitaciones** (`households/invitations.py`): enlaces de un solo uso con rol y caducidad.
  Solo se guarda el SHA-256 del token; la aceptación bloquea la fila para que no se use dos veces.
  Quien ya es miembro conserva su rol y no consume el enlace.
- **Peso** (`diners/permissions.py`): lo ven y registran solo la persona vinculada al comensal
  y quien tenga una concesión explícita (`HealthDataAccess`). Las concesiones las gestiona la
  propia persona; si el comensal no tiene cuenta, la administración del hogar. El rol de
  administración no da acceso por sí mismo. Cada endpoint lo comprueba en el servidor. El
  historial solo admite altas y no se calculan objetivos.

## Restricciones alimentarias

Vocabulario cerrado de rasgos (`foods.models.Trait`): los 14 alérgenos de declaración
obligatoria en la UE más lactosa, carne, cerdo, alcohol y origen animal. Algunos rasgos
implican otros (cerdo → carne → origen animal; lactosa → leche) y se expanden al guardar.

`foods/compatibility.evaluate(ingredientes, personas)` devuelve:

| Resultado | Cuándo |
|---|---|
| **Conflicto** | Un ingrediente contiene un rasgo restringido o es un ingrediente vetado. Incluye opcionales y sustituciones. |
| **Desconocido** | La persona tiene restricciones y el ingrediente no tiene la información revisada (`trait_info_complete=False`): productos procesados, ingredientes nuevos del hogar e ingredientes creados por la IA. Deja de serlo cuando el hogar revisa la etiqueta (`IngredientReview`, por hogar): lo que marque la etiqueta sustituye a la información del catálogo. |
| **Compatible** | Compatible según los datos registrados. Nunca es una garantía: siempre se muestra el recordatorio de etiquetado y contaminación cruzada. |

Las preferencias («no le gusta») nunca bloquean, solo influyen en las propuestas. El texto
libre del perfil aparece como aviso de «no verificable automáticamente».

Dónde se aplican las reglas:
- **Añadir receta a una comida**: el conflicto se rechaza y se ofrecen alternativas compatibles.
- **Regenerar**: solo asigna recetas con resultado compatible; si no hay ninguna, deja la
  comida pendiente. Nunca relaja una restricción.
- **Cambios de asistentes, ingredientes o sustituciones**: se revalida la comida y el estado
  queda guardado en `Meal.safety_status`.
- **Cambios de restricciones o de rasgos de un ingrediente**: señales que revalidan las
  comidas futuras afectadas.
- **Propuestas de IA**: se validan al generarse y otra vez al aplicarse.

## Comidas y recetas

- Hay una comida por hueco `(hogar, fecha, tipo)`. Cada comida tiene modalidad, asistentes
  (comensales o invitados con sus restricciones), recetas, notas, bloqueo y el registro de lo
  que se comió realmente (`outcome`).
- **Snapshot**: al asignar una receta se copian nombre, ingredientes, pasos y versión
  (`MealRecipe`, `MealRecipeIngredient`). Editar la receta incrementa `Recipe.version`; las
  comidas muestran «hay una versión más reciente» y solo se actualizan con una acción explícita.
- Las correcciones de cantidad y las sustituciones se hacen sobre la copia de la comida.
- **Protección**: cualquier edición manual deja la comida protegida (candado). Regenerar un
  intervalo no toca las comidas protegidas.
- **Valores por defecto de un hueco**: patrón de asistencia por día y comida → regla recurrente
  → excepción de fecha. La excepción siempre prevalece.
- `Meal.version` se incrementa en cada cambio y sirve como control de concurrencia optimista
  para las propuestas de la IA.
- **Sobras** (`Meal.leftovers_from`): una comida «aprovechar sobras» puede apuntar a una comida
  cocinada, con recetas, de los 4 días anteriores. `planned_servings()` suma a esa comida las
  raciones de sus sobras, y así se escalan sus cantidades y la compra. La comida de sobras no
  genera compra y se valida contra los ingredientes de la comida de origen. Revalidar la comida de
  origen revalida también sus sobras. Si deja de cocinarse en casa, las sobras pasan a «requiere
  revisión».

## Unidades y compra

- Tres dimensiones: masa (g, kg), volumen (ml, l, cucharada = 15 ml, cucharadita = 5 ml) y
  unidades contables (unidad, diente, loncha, lata…). Dentro de una dimensión la conversión es
  exacta. Las cantidades son decimales.
- **Equivalencias** (`foods.UnitConversion`, `foods/conversions.py`): gramos de 1 pieza o de 1 ml
  de un ingrediente. Las filas sin hogar son del catálogo y una fila del hogar para la misma
  unidad la sustituye. La compra agrupa cada ingrediente en su unidad habitual (`default_unit`).
  Una línea de otra dimensión se convierte a gramos y de ahí a esa unidad, pero solo si existen
  las dos equivalencias. Si no, se queda como artículo aparte y nunca se inventa la conversión.
  Los artículos convertidos llevan `is_approximate` y se muestran con «≈».
- Escalado: `cantidad × raciones previstas / raciones base`, donde las raciones previstas son
  la suma de los factores de ración de los asistentes (o unas raciones fijadas a mano).
- La compra suma solo las comidas en modalidad «cocinar en casa». La clave de agregación es
  `ingrediente + unidad base`, con una restricción única parcial en la base de datos: recalcular
  es idempotente.
- Recalcular actualiza la cantidad necesaria y conserva la cantidad comprada y los artículos
  manuales. Si algo comprado deja de hacer falta, se queda como **excedente**; no se borra ni se
  da por consumido.
- Los ingredientes «al gusto» (sin cantidad) no se añaden a la compra.
- Para piezas, la lista sugiere comprar el entero superior de lo pendiente sin alterar la cantidad
  necesaria calculada.

## Asistente (OpenAI)

```
vista ──► request_proposal ──► build_context (seudonimizado)
                  │                   │
                  │            provider.generate  ← fuera de transacciones
                  │                   │
                  └──► validate_output (reglas de negocio) ──► Proposal(pending)
usuario revisa ──► apply_proposal: bloqueo de fila, estado, versión de comidas, revalidación
```

- **Proveedores**: `OpenAIProvider` usa `client.responses.parse(text_format=AssistantOutput,
  store=False)` con timeout y reintentos limitados del SDK. `DemoProvider` es determinista y
  local; sus respuestas llevan la etiqueta «Modo demostración».
- **Contexto mínimo**: los comensales viajan como C1, C2… con grupo de edad, factor de ración,
  restricciones y gustos. No se envían nombres, fechas de nacimiento, pesos ni notas libres.
  Los nombres de comensales escritos en el chat (petición y últimos 6 mensajes) se sustituyen por
  su código antes de enviarlos, y los códigos de la respuesta se muestran como nombres.
- **Esquema estricto** (`assistant/schemas.py`). La salida es la entrada de una validación
  posterior: fechas dentro del intervalo, tipos de comida activos, huecos no protegidos, recetas
  del propio hogar, códigos de comensal existentes y reglas alimentarias. Lo inválido se marca
  como «rechazado»; lo incompatible no se aplica nunca; lo desconocido requiere confirmación
  explícita de cada cambio.
- **Operaciones permitidas**: cambiar la modalidad, los asistentes y las recetas de una comida,
  y crear recetas nuevas (como «generadas por IA», pendientes de revisión, con los ingredientes
  desconocidos creados como «sin revisar»). El modelo no ejecuta nada.
- **Concurrencia**: la propuesta guarda las versiones de las comidas del intervalo. Si cambian
  antes de aplicarla, queda «desactualizada» y no se aplica. Aplicar dos veces no duplica nada.
- **Errores**: sin credenciales, timeout, conexión, límites, rechazo del modelo, respuesta
  incompleta y esquema inválido producen un mensaje claro y ningún cambio. `AIRequestLog`
  registra el proveedor, el modelo, la operación, el estado, la latencia y los tokens, sin el
  contenido.

## Correo

- `core/emails.send_email(plantilla, destinatario, asunto, contexto)` envía texto y HTML
  (`templates/emails/`) con la etiqueta de la plantilla. **Nunca lanza excepciones**: si el
  proveedor falla, lo registra en el log (solo con el dominio del destinatario) y devuelve `False`,
  y quien lo llama avisa a la persona. Por ejemplo, la invitación sigue mostrando el enlace para
  copiarlo.
- Proveedor por entorno: consola en local, memoria (`mail.outbox`) en los tests y SMTP de
  Mailgun en producción (`EMAIL_PROVIDER=smtp`). `production.py` exige `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD` y `DEFAULT_FROM_EMAIL`. La API HTTP de Mailgun (Anymail) sigue disponible
  con `EMAIL_PROVIDER=mailgun`, que exige `MAILGUN_API_KEY` y `MAILGUN_SENDER_DOMAIN`.
  `EMAIL_PROVIDER=console` desactiva el envío a propósito.
- Correos que se envían:
  - recuperación de contraseña, con enlace de 24 h y un solo uso, y sin revelar si la dirección
    existe;
  - aviso de contraseña cambiada, tanto al restablecerla como al cambiarla;
  - invitación al hogar, opcional y con el mismo enlace de un solo uso;
  - errores del servidor a `ADMINS`.
- Sin webhook de Mailgun: se retiró porque rechazaba todas las llamadas y llenaba el log. Los
  rebotes y las quejas se consultan en el panel de Mailgun. `EmailEvent` y su admin conservan los
  eventos que ya se hubieran guardado.

## Planes y pagos (Stripe)

- La suscripción es **por hogar**: `billing.Subscription`, uno por hogar. La paga una persona
  administradora con Stripe Checkout alojado y se gestiona en el Customer Portal de Stripe.
- `billing/entitlements.py` decide qué puede usar cada hogar. Premium se activa con los estados
  `active`, `trialing` y `past_due` (este último da margen mientras Stripe reintenta el cobro).
  Límites que se comprueban en el backend, no solo ocultando botones:
  - asistente con IA solo en Premium y con cupo mensual. Cuentan las llamadas que llegan al
    proveedor de pago; la demo y los errores de red no;
  - personas con cuenta por hogar, al añadir, invitar y aceptar una invitación. Si se baja de
    plan, nadie pierde el acceso; solo no se pueden añadir más;
  - sin facturación (`BILLING_ENABLED=false`, lo normal en local) todo está desbloqueado.
    Producción la exige por defecto.
- Sincronización: Stripe manda. Los webhooks firmados se procesan una sola vez (`StripeEvent`)
  dentro de una transacción; si algo falla se deshace y se devuelve 500 para que Stripe
  reintente. Al volver de Checkout se consulta la sesión, comprobando que pertenece al hogar,
  para mostrar Premium sin esperar al webhook.
- Con la versión de API que fija el SDK, el fin del periodo se lee de
  `items.data[0].current_period_end`.
- `invoice.payment_failed` avisa por correo a las personas administradoras del hogar.

## Configuración por entorno

`config/settings/base.py` define lo común; `local.py`, `production.py` y `test.py` lo
especializan. Producción exige `DJANGO_SECRET_KEY` y activa cookies seguras, HSTS y estáticos
comprimidos. `ATOMIC_REQUESTS=False` para que las llamadas de red no queden dentro de
transacciones largas.

Despliegue: `compose.prod.yaml` está pensado para Dokploy. Las variables llegan por interpolación
`${VAR}` desde el `.env` que genera Dokploy, y las obligatorias hacen fallar el despliegue si
faltan. Traefik enruta al puerto 8000 con las etiquetas que añade Dokploy. `HealthCheckMiddleware`
va el primero y atiende `/healthz` antes de la validación de host y de la redirección HTTPS.
