"""Search engine support for the public pages: meta data, structured data, robots.txt and sitemap.

Private pages (everything behind sign-in) are `noindex` by default in the base template; public
pages opt in with the `robots` block and include `partials/seo_public.html`.
"""

import json
import re
from xml.sax.saxutils import escape

from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import redirect
from django.templatetags.static import static
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .legal import LEGAL_UPDATED

OG_IMAGE = "img/og-menuamano.png"
LANDING_TITLE = "menuamano · menú semanal, alergias y lista de la compra"
LANDING_DESCRIPTION = (
    "Planifica las comidas de casa teniendo en cuenta las alergias de cada persona, con recetas, "
    "sobras y la lista de la compra con cantidades justas. Gratis para empezar."
)
# Areas that need an account: never worth crawling.
PRIVATE_PREFIXES = (
    "/admin/", "/calendario/", "/compra/", "/asistente/", "/hogar/", "/comensales/",
    "/recetas/", "/ingredientes/", "/plan/", "/cuenta/",
)


def site_url(request):
    """Public base URL: SITE_URL when configured, the request's own host otherwise."""
    return (settings.SITE_URL or request.build_absolute_uri("/")).rstrip("/")


def seo_context(request):
    base = site_url(request)
    return {"site_url": base, "canonical_url": base + request.path, "og_image_url": base + static(OG_IMAGE)}


def ld_json(data):
    """A JSON-LD script tag, escaped like Django's json_script so no text can close it."""
    text = json.dumps(data, ensure_ascii=False)
    text = text.replace("<", "\\u003C").replace(">", "\\u003E").replace("&", "\\u0026")
    return mark_safe(f'<script type="application/ld+json">{text}</script>')


def _price(label):
    """«4,99 €» → «4.99», the format schema.org expects."""
    return re.sub(r"[^\d,.]", "", label).replace(",", ".") or "0"


def landing_faqs(free, premium):
    if free.has_ai:
        ai_answer = (
            f"Sí, con {free.ai_total_limit} peticiones de prueba para conocerlo. Para seguir usándolo, "
            f"Premium incluye {premium.ai_monthly_limit} peticiones al mes."
        )
    else:
        ai_answer = "No. El asistente con IA forma parte del plan Premium."
    return [
        {
            "question": "¿Tienen que tener cuenta todas las personas de casa?",
            "answer": "No. Los comensales son perfiles sin cuenta. Solo necesitan cuenta quienes vayan a consultar o editar el menú.",
        },
        {
            "question": "¿Cómo tiene en cuenta las alergias?",
            "answer": (
                "Cada comensal tiene sus alergias, intolerancias y dietas. menuamano comprueba cada receta con quien la come "
                "y avisa cuando falta información de algún ingrediente: nunca da por segura una receta sin datos."
            ),
        },
        {"question": "¿La cuenta gratuita incluye el asistente con IA?", "answer": ai_answer},
        {
            "question": "¿Qué datos ve la inteligencia artificial?",
            "answer": (
                "Solo lo necesario para proponer el menú: códigos en lugar de nombres, grupos de edad, restricciones y "
                "recetas. Nunca nombres, fechas de nacimiento ni pesos."
            ),
        },
        {
            "question": "¿Y el registro de peso?",
            "answer": "Es opcional y privado. Solo lo ve la propia persona y quien ella autorice. menuamano no calcula dietas ni objetivos.",
        },
        {
            "question": "¿Puedo cancelar Premium?",
            "answer": "Sí, desde la página del plan de tu hogar, en cualquier momento. Mantienes Premium hasta el final del periodo pagado.",
        },
    ]


def landing_seo(request, free, premium, prices):
    base = site_url(request)
    faqs = landing_faqs(free, premium)
    data = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebApplication",
                "name": "menuamano",
                "url": f"{base}/",
                "description": LANDING_DESCRIPTION,
                "applicationCategory": "LifestyleApplication",
                "operatingSystem": "Web",
                "inLanguage": "es",
                "image": base + static(OG_IMAGE),
                "offers": [
                    {"@type": "Offer", "name": free.name, "price": "0", "priceCurrency": "EUR"},
                    {"@type": "Offer", "name": f"{premium.name} mensual", "price": _price(prices["monthly"]),
                     "priceCurrency": "EUR", "description": "Suscripción mensual por hogar"},
                    {"@type": "Offer", "name": f"{premium.name} anual", "price": _price(prices["yearly"]),
                     "priceCurrency": "EUR", "description": "Suscripción anual por hogar"},
                ],
            },
            {
                "@type": "FAQPage",
                "mainEntity": [
                    {"@type": "Question", "name": f["question"], "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
                    for f in faqs
                ],
            },
        ],
    }
    return {"seo_title": LANDING_TITLE, "seo_description": LANDING_DESCRIPTION, "faqs": faqs, "json_ld": ld_json(data)}


@require_GET
@cache_control(max_age=86400, public=True)
def favicon(request):
    """Browsers and crawlers ask for /favicon.ico whatever the page links."""
    return redirect(static("img/favicon.ico"))


@require_GET
@cache_control(max_age=86400, public=True)
def robots_txt(request):
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {prefix}" for prefix in PRIVATE_PREFIXES]
    lines += [f"Allow: {reverse('accounts:signup')}", "", f"Sitemap: {site_url(request)}{reverse('core:sitemap')}"]
    return HttpResponse("\n".join(lines) + "\n", content_type="text/plain; charset=utf-8")


@require_GET
@cache_control(max_age=86400, public=True)
def sitemap_xml(request):
    from .views import LEGAL_PAGES

    base = site_url(request)
    updated = LEGAL_UPDATED.isoformat()
    entries = [
        (reverse("core:home"), None, "1.0"),
        (reverse("accounts:signup"), None, "0.6"),
        (reverse("core:install"), None, "0.4"),
        (reverse("core:legal"), updated, "0.3"),
    ]
    entries += [(reverse("core:legal_page", args=[slug]), updated, "0.3") for slug in LEGAL_PAGES]
    urls = "".join(
        f"  <url><loc>{escape(base + path)}</loc>{f'<lastmod>{lastmod}</lastmod>' if lastmod else ''}"
        f"<priority>{priority}</priority></url>\n"
        for path, lastmod, priority in entries
    )
    body = f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n'
    return HttpResponse(body, content_type="application/xml; charset=utf-8")
