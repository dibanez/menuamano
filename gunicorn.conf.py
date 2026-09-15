"""Gunicorn settings, read automatically from the working directory (/app in the container).

Behind Dokploy's Traefik every connection comes from the proxy (10.0.x.x), so the access log
shows the visitor's address instead: Traefik sends it in X-Real-Ip, replacing any value the
client sent. Requests that do not pass through Traefik (the container health check) log "-".
The rest of the line keeps gunicorn's default format, which the log dashboards parse.
"""

logger_class = "core.gunicorn_logging.RedactingLogger"  # hides the tokens of calendar and invitation links
access_log_format = '%({x-real-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
