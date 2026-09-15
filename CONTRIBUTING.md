# Contribuir a menuamano

Gracias por querer mejorar menuamano. Puedes probar la aplicación en
[www.menuamano.com](https://www.menuamano.com/) y montar tu entorno en unos minutos con Docker.

## Antes de empezar

- Para errores y propuestas, abre un issue. Para cambios grandes, coméntalos en un issue antes de
  escribir código: así no se pierde trabajo.
- Un pull request por cambio, con sus pruebas y con la documentación al día si cambia algo que se
  explique en el README.
- Las vulnerabilidades no van en issues públicos: sigue [`SECURITY.md`](SECURITY.md).

## Entorno

```bash
cp .env.example .env
docker compose up --build -d                        # http://localhost:8010
docker compose exec web python manage.py load_demo  # hogar y cuentas de demostración
docker compose exec web pytest                      # todas las pruebas
```

Las cuentas de demostración están en el [README](README.md#arranque-rápido-con-docker).

## Convenciones

- **Idiomas**: la interfaz y la documentación, en español de España. El código, los comentarios,
  los mensajes de log, los nombres de las pruebas y los mensajes de commit, en inglés.
- **Commits** en imperativo («Add…», «Fix…», «Show…»), con un cuerpo que explique el porqué.
- **Reglas en los servicios**: la lógica vive en módulos como `foods/compatibility.py` o
  `*/services.py`; las vistas solo orquestan. Todo permiso se comprueba en el servidor, no solo
  ocultando botones.
- **Alergias**: nada se da por seguro sin datos. Si falta información, el resultado es «requiere
  revisión», nunca «compatible».
- **Sin paso de build**: el CSS está en `static/css/app.css`, con variables, y el JavaScript en
  `static/js/app.js`. Los flujos funcionan sin JavaScript, salvo el asistente con clave propia.
- **Móvil primero**: revisa la interfaz a unos 400 px de ancho.
- **Pruebas sin coste**: nunca llaman a APIs de pago (OpenAI, Stripe…). Usa el proveedor de
  demostración o dobles de prueba.
- **Secretos**: nunca subas claves ni contraseñas. La configuración va por variables de entorno
  (ver `.env.example`).

## Licencia de las contribuciones

Al enviar una contribución aceptas que se publique con la licencia del proyecto,
[AGPL-3.0](LICENSE).
