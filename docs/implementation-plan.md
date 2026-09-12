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
5. **Unidades**: tres dimensiones (masa, volumen, unidades contables). Solo se convierte dentro de
   una dimensión (g↔kg, ml↔l, cucharada = 15 ml, cucharadita = 5 ml). Las piezas (`unidad`,
   `diente`, `lata`…) solo se suman con la misma pieza.
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

Las tres fases están implementadas y la aplicación arranca con Docker. 64 pruebas automáticas
pasan sin llamadas reales a OpenAI. La interfaz se ha revisado en el navegador a 400 px de ancho.

### Pendiente o conocido

- **Integración real con OpenAI sin probar contra la API**: el cliente se ha verificado con el
  SDK 3.13 instalado (firmas, excepciones y tipos) y con dobles de prueba, pero no con una clave
  real. Primer paso para continuar: fijar `AI_PROVIDER=openai`, `OPENAI_API_KEY` y `OPENAI_MODEL`
  en `.env`, pedir una propuesta semanal y revisar `AIRequestLog`.
- **Invitaciones**: solo se puede añadir a personas ya registradas, por correo. Falta un flujo de
  invitación con enlace.
- **Ingredientes**: la selección en el formulario de recetas es un `<select>` simple; con catálogos
  grandes convendrá un buscador. No hay equivalencias pieza↔gramos (p. ej. «1 huevo ≈ 60 g»):
  las piezas nunca se convierten.
- **Sobras**: «aprovechar sobras» no genera compra ni enlaza con la comida de origen; para cocinar
  de más hay que fijar raciones a mano en la comida original.
- **Revalidación**: se revalidan las comidas futuras al cambiar restricciones o ingredientes. Las
  pasadas se conservan como estaban.
- **El chat es de un solo turno**: cada mensaje genera una propuesta independiente; no se envía el
  historial de la conversación al modelo.
- Accesibilidad y rendimiento: revisados a mano, sin auditoría automatizada.

### Fuera de alcance (no se muestran como operativos)

Despensa y congelador, caducidades, lotes de sobras, presupuesto y precios, nutrición, códigos
de barras e integraciones con supermercados o dispositivos.
