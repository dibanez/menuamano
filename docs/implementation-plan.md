# menuamano — plan de implementación

Documento vivo. Se actualiza al cerrar cada fase con lo completado y lo pendiente.

## Punto de partida

Repositorio vacío (sin git, sin código). Se crea el proyecto desde cero con el stack
propuesto.

## Decisiones técnicas

| Tema | Decisión | Motivo |
|---|---|---|
| Lenguaje / framework | Python 3.12 + Django 5.2 LTS | LTS con soporte hasta abril de 2028; 6.x es más reciente pero 5.2 minimiza riesgo. |
| Base de datos | PostgreSQL 17 | Se usan `ArrayField` y restricciones parciales. Los tests también corren sobre PostgreSQL. |
| Interfaz | Templates de Django + HTMX 2 (servido localmente, sin CDN) | Sin build de frontend. |
| CSS | Una hoja propia con variables (`static/css/app.css`) | Sistema visual pequeño y consistente, mobile first. |
| IA | SDK oficial `openai` 3.x, Responses API con `responses.parse(text_format=Pydantic)` | Salida estructurada con esquema estricto. Modelo leído de `OPENAI_MODEL`. |
| Arquitectura | Monolito modular: `accounts`, `households`, `foods`, `diners`, `recipes`, `planning`, `shopping`, `assistant`, `core` | Cada app con `models`, `services` y `views`; las reglas viven en servicios puros testeables. |
| Hogar activo | Guardado en sesión y **revalidado en cada petición** contra `Membership` | Nunca se confía en un id del navegador como prueba de autorización. |
| Configuración | `config/settings/{base,local,production,test}.py` + variables de entorno | Local y producción separadas; los secretos solo llegan por entorno. |
| Tests | pytest + pytest-django | Sin llamadas reales a OpenAI: proveedor de demostración y dobles de prueba. |

## Supuestos razonables

1. **Una comida por hueco**: cada `(hogar, fecha, tipo de comida)` tiene como máximo una comida,
   que puede contener varias recetas.
2. **Raciones**: cada comensal tiene un factor de ración (1 = adulto estándar, 0,5 = medio plato…).
   Las raciones de una comida son la suma de los factores de los asistentes, incluidos los invitados.
3. **Rasgos alimentarios**: las restricciones se expresan sobre un vocabulario cerrado de rasgos
   (los 14 alérgenos de declaración obligatoria en la UE más lactosa, carne, cerdo, alcohol y
   origen animal) o sobre un ingrediente concreto. Las dietas (vegetariana, vegana) se aplican como
   conjuntos de rasgos. Solo lo estructurado se puede comprobar; el texto libre del perfil se muestra
   como nota «no verificable automáticamente».
4. **Información incompleta = desconocido**: un ingrediente cuyo perfil de rasgos no está revisado
   (`trait_info_complete=False`), como los productos procesados, los ingredientes creados por la IA
   o los ingredientes nuevos del hogar, da una compatibilidad **desconocida**, nunca «segura».
5. **Unidades**: tres dimensiones (masa, volumen, unidades contables). Dentro de una dimensión la
   conversión es exacta (g↔kg, ml↔l, cucharada = 15 ml, cucharadita = 5 ml). Entre dimensiones solo
   se convierte con una equivalencia conocida del ingrediente (p. ej. 1 huevo ≈ 60 g), y el
   resultado se marca como aproximado. Sin equivalencia, las piezas (`unidad`, `diente`, `lata`…)
   solo se suman con la misma pieza.
6. **Snapshot de receta**: al asignar una receta a una comida se copia (nombre, ingredientes, pasos,
   versión). Editar la receta incrementa su versión; las comidas conservan su copia y muestran un
   aviso de «hay versión más reciente» con una acción explícita para actualizar.
7. **Datos de peso**: los ve y registra el propio usuario vinculado al comensal y quienes tengan una
   concesión explícita. Si el comensal tiene cuenta, la concede él; si no la tiene (por ejemplo, un
   menor), la concede un administrador. Ser administrador no da acceso automático. No se calculan
   objetivos calóricos ni recomendaciones.
8. **Despensa**: fuera de la primera versión. La compra muestra necesidad, comprado y pendiente,
   sin descontar existencias; se indica en la interfaz.
9. **Nutrición**: fuera de alcance; no hay fuente de composición de alimentos.
10. **Llamadas a la IA síncronas** dentro de la petición HTMX (con indicador de carga y timeout
    configurable). Sin colas ni workers: no hay necesidad concreta todavía.

## Fases

### Fase 1 — base funcional
- [x] Proyecto Django + Docker Compose (web + PostgreSQL), settings separados, `.env.example`.
- [x] Usuarios (registro, acceso), hogares, membresías con roles (admin, editor, lector), selección de hogar.
- [x] Catálogo de ingredientes con rasgos y categorías (migración de datos `foods/0002`).
- [x] Comensales: restricciones obligatorias vs preferencias, ración, patrón de asistencia, altura.
- [x] Motor de compatibilidad alimentaria independiente (compatible / desconocido / conflicto).
- [x] Recetas manuales con ingredientes normalizados, pasos, escalado y versionado.
- [x] Calendario día / semana / mes; detalle de comida con asistentes, invitados, modalidad,
      recetas (snapshot), notas, bloqueo, planificado vs consumido; mover y copiar.
- [x] Lista de compra por intervalo, idempotente, con manuales, compras y excedentes.
- [x] Comando `load_demo`.
- [x] Tests de reglas críticas y de aislamiento entre hogares.

### Fase 2 — IA
- [x] Servicio aislado `assistant` con interfaz de proveedor: OpenAI y demostración determinista.
- [x] Esquemas Pydantic estrictos; validación de negocio posterior.
- [x] Propuestas persistidas (revisión → aplicar), detección de conflictos por versión de comida,
      aplicación idempotente.
- [x] Chat contextual con operaciones acotadas; contexto seudonimizado.
- [x] Registro de uso y latencia sin contenido sensible; manejo de errores del proveedor.

### Fase 3 — reglas y cuidado
- [x] Reglas recurrentes de modalidad y excepciones por fecha (la excepción prevalece).
- [x] Regeneración de intervalos que respeta comidas bloqueadas y excepciones.
- [x] Favoritos por usuario e historial de recetas usadas.
- [x] Registro opcional de peso con permisos explícitos.
- [x] README y documentación de arquitectura (`docs/architecture.md`).

## Estado (12/09/2026)

Las tres fases están implementadas y la aplicación arranca con Docker. 96 pruebas automáticas
pasan sin llamadas reales a OpenAI. La interfaz se ha revisado en el navegador a 400 px de ancho.

### Iteración 2 (rama `iteration-2`)

- [x] `.dockerignore`: la imagen ya no copia `.venv` ni `.git`.
- [x] Invitaciones con enlace de un solo uso, con rol y caducidad a 7 días. Solo se guarda el hash
      del token y el enlace se muestra una vez. Quien no tiene cuenta puede registrarse desde el enlace.
- [x] Chat: los nombres que se escriben se sustituyen por códigos antes de salir del servidor y
      los códigos de la respuesta se muestran como nombres. Se envían los 6 últimos mensajes.
- [x] Compra: para piezas se sugiere comprar el entero superior (p. ej. «falta 1,9 unidades. Compra 2»).
- [x] Sobras enlazadas: una comida «aprovechar sobras» apunta a una comida cocinada de los 4 días
      anteriores. Esa comida cocina las raciones de más (cantidades y compra incluidas) y las sobras
      se validan con sus ingredientes. Se revalidan si la comida de origen cambia.
- [x] Buscador en el selector de ingredientes del formulario de recetas.
- [x] Auditoría automática de accesibilidad (axe-core 4.11.1, WCAG 2.1 AA y buenas prácticas) sobre
      las pantallas principales: corregidos los roles ARIA del mes, el contraste, la barra de progreso,
      el orden de encabezados y una etiqueta que faltaba. Ninguna incidencia pendiente.

### Iteración 3 (rama `piece-weights`)

- [x] Equivalencias de peso por ingrediente (`UnitConversion`): cuánto pesa una pieza o un ml. El
      catálogo trae valores aproximados para piezas medianas y densidades comunes, y cada hogar puede
      sustituirlos por los suyos. La compra junta piezas, volumen y gramos del mismo ingrediente en su
      unidad habitual solo si hay equivalencia, y marca la cantidad con «≈». Cada origen muestra la
      cantidad tal como aparece en la receta.

### Iteración 4 — correo con Mailgun

- [x] Envío con Mailgun (Anymail, API HTTP, región configurable) en producción; consola en local.
- [x] Recuperación y cambio de contraseña, con aviso por correo cuando cambia.
- [x] Invitaciones por correo (opcional), manteniendo el enlace para copiar si falla el envío.
- [x] Errores del servidor a `DJANGO_ADMINS`.
- [x] Webhook de Mailgun con firma verificada: rebotes, quejas y fallos en `EmailEvent`.
- [x] Comando `send_test_email` para comprobar la configuración desde Dokploy.
- [x] Healthcheck `/healthz` y `compose.prod.yaml` para Dokploy.

### Pendiente o conocido

- **Integración real con OpenAI sin probar contra la API**: el cliente se ha verificado con el
  SDK 3.13 instalado (firmas, excepciones y tipos) y con dobles de prueba, pero no con una clave
  real. Primer paso para continuar: fijar `AI_PROVIDER=openai`, `OPENAI_API_KEY` y `OPENAI_MODEL`
  en `.env`, pedir una propuesta semanal y revisar `AIRequestLog`.
- **Invitaciones**: el correo de destino es informativo; el enlace sirve a quien lo abra primero.
- **Correo**: sin verificación de la dirección al registrarse y sin bajas automáticas cuando una
  dirección rebota (los rebotes solo se registran). No se ha probado contra Mailgun real.
- **Equivalencias**: solo se usan en la lista de compra. Las cantidades de cada comida se muestran en
  la unidad de la receta. El catálogo cubre las piezas y los líquidos más comunes; el resto hay que
  añadirlo por hogar.
- **Sobras**: el enlace es de una comida a otra; no hay lotes, congelación ni control de raciones
  restantes (fuera de alcance).
- **Revalidación**: se revalidan las comidas futuras al cambiar restricciones o ingredientes. Las
  pasadas se conservan como estaban.
- **Memoria del chat limitada**: se envían los 6 últimos mensajes; cada mensaje genera una propuesta
  independiente. El proveedor de demostración no interpreta el historial.
- **Rendimiento**: sin medir con volúmenes de datos reales.
- **Accesibilidad**: la auditoría automática no encuentra incidencias; falta una prueba con lector de
  pantalla real.

### Fuera de alcance (no se muestran como operativos)

Despensa y congelador, caducidades, lotes de sobras, presupuesto y precios, nutrición, códigos
de barras e integraciones con supermercados o dispositivos.
