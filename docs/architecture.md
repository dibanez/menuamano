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
| **Desconocido** | La persona tiene restricciones y el ingrediente no tiene la información revisada (`trait_info_complete=False`): productos procesados, ingredientes nuevos del hogar e ingredientes creados por la IA. |
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

## Unidades y compra

- Tres dimensiones: masa (g, kg), volumen (ml, l, cucharada = 15 ml, cucharadita = 5 ml) y
  unidades contables (unidad, diente, loncha, lata…). Solo se convierte dentro de una
  dimensión; las piezas solo se suman con la misma pieza. Las cantidades son decimales.
- Escalado: `cantidad × raciones previstas / raciones base`, donde las raciones previstas son
  la suma de los factores de ración de los asistentes (o unas raciones fijadas a mano).
- La compra suma solo las comidas en modalidad «cocinar en casa». La clave de agregación es
  `ingrediente + unidad base`, con una restricción única parcial en la base de datos: recalcular
  es idempotente.
- Recalcular actualiza la cantidad necesaria y conserva la cantidad comprada y los artículos
  manuales. Si algo comprado deja de hacer falta, se queda como **excedente**; no se borra ni se
  da por consumido.
- Los ingredientes «al gusto» (sin cantidad) no se añaden a la compra.

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

## Configuración por entorno

`config/settings/base.py` define lo común; `local.py`, `production.py` y `test.py` lo
especializan. Producción exige `DJANGO_SECRET_KEY` y activa cookies seguras, HSTS y estáticos
comprimidos. `ATOMIC_REQUESTS=False` para que las llamadas de red no queden dentro de
transacciones largas.
