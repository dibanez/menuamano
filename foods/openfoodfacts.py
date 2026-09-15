"""Product data from Open Food Facts (https://world.openfoodfacts.org), an open database.

Used to fill in a household's label review: the allergens and traces a product declares, its
ingredients and where it is sold. The data is collaborative and can be wrong or old, so it only
pre-fills the review; a person still confirms it against the label. Licence: ODbL (credited).
"""

import hashlib
import json
import logging
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.core.cache import cache

from .models import Trait

logger = logging.getLogger(__name__)

BASE_URL = "https://world.openfoodfacts.org"
USER_AGENT = "menuamano/1.0 (+https://www.menuamano.com)"
TIMEOUT_SECONDS = 8
CACHE_SECONDS = 24 * 60 * 60
RETRY_STATUSES = {502, 503, 504}
RETRY_PAUSE_SECONDS = 1
FIELDS = (
    "code,product_name,product_name_es,brands,quantity,stores,allergens_tags,traces_tags,ingredients_tags,"
    "ingredients_text_es,ingredients_text"
)
BARCODE = re.compile(r"^\d{8,14}$")

# Open Food Facts allergen tags → menuamano traits (the 14 EU allergens).
ALLERGENS = {
    "en:gluten": Trait.GLUTEN, "en:crustaceans": Trait.CRUSTACEANS, "en:eggs": Trait.EGG, "en:fish": Trait.FISH,
    "en:peanuts": Trait.PEANUT, "en:soybeans": Trait.SOY, "en:milk": Trait.MILK, "en:nuts": Trait.TREE_NUTS,
    "en:celery": Trait.CELERY, "en:mustard": Trait.MUSTARD, "en:sesame-seeds": Trait.SESAME,
    "en:sulphur-dioxide-and-sulphites": Trait.SULPHITES, "en:lupin": Trait.LUPIN, "en:molluscs": Trait.MOLLUSCS,
}

# Ingredient tags that mean added sugars, for people with diabetes. Open Food Facts also tags the
# parent of each ingredient (cane sugar is tagged en:sugar too), so the common ones are enough.
ADDED_SUGAR_TAGS = frozenset({
    "en:sugar", "en:added-sugar", "en:glucose", "en:glucose-syrup", "en:glucose-fructose-syrup",
    "en:fructose-glucose-syrup", "en:fructose", "en:dextrose", "en:invert-sugar", "en:syrup", "en:honey",
    "en:molasses", "en:caramel",
})


class OpenFoodFactsError(Exception):
    """`message` is shown to the person (Spanish)."""

    def __init__(self, message):
        self.message = message
        super().__init__(message)


def _get(path, params, retries=1):
    """GET a JSON document from Open Food Facts. The only network call of this module.

    Its search sometimes turns requests away at once (502–504) when busy: one retry after a pause.
    """
    request = Request(f"{BASE_URL}{path}?{urlencode(params)}", headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read(2_000_000))
    except HTTPError as exc:
        if exc.code in RETRY_STATUSES and retries > 0:
            time.sleep(RETRY_PAUSE_SECONDS)
            return _get(path, params, retries - 1)
        logger.warning("open food facts unavailable: path=%s status=%s", path.split("/")[1], exc.code)
        if exc.code == 429:  # searches are limited to a few per minute for everyone
            raise OpenFoodFactsError(
                "Open Food Facts está recibiendo muchas búsquedas. Espera un minuto o busca por el código de barras."
            ) from exc
        raise OpenFoodFactsError("Open Food Facts no responde ahora mismo. Prueba en un rato.") from exc
    except (URLError, OSError, ValueError) as exc:  # includes timeouts, and HTML error pages
        logger.warning("open food facts unavailable: %s", type(exc).__name__)
        raise OpenFoodFactsError("Open Food Facts no responde ahora mismo. Prueba en un rato.") from exc


def _traits(tags):
    return sorted({str(ALLERGENS[tag]) for tag in tags or [] if tag in ALLERGENS})


def _product(data):
    allergens, traces = data.get("allergens_tags") or [], data.get("traces_tags") or []
    return {
        "code": str(data.get("code") or ""),
        "name": (data.get("product_name_es") or data.get("product_name") or "").strip()[:120] or "Producto sin nombre",
        "brand": (data.get("brands") or "").split(",")[0].strip()[:60],
        "quantity": (data.get("quantity") or "").strip()[:30],  # e.g. «400 g»: tells sizes of one product apart
        "stores": ", ".join(s.strip() for s in (data.get("stores") or "").split(",") if s.strip())[:120],
        "ingredients": (data.get("ingredients_text_es") or data.get("ingredients_text") or "").strip()[:600],
        # Added sugars are not an allergen, but the review needs them for people with diabetes.
        "allergens": sorted(set(_traits(allergens)) | (
            {str(Trait.ADDED_SUGAR)} if ADDED_SUGAR_TAGS & set(data.get("ingredients_tags") or []) else set()
        )),
        "traces": _traits(traces),
        # Declared allergens outside the EU list (they are shown, never guessed into a trait).
        "other_allergens": [t.split(":", 1)[-1] for t in allergens + traces if t not in ALLERGENS][:6],
        "url": f"{BASE_URL}/product/{data.get('code')}",
    }


def search(query, limit=6):
    """Products whose name or brand match `query`, Spanish products first."""
    query = " ".join((query or "").split())[:80]
    if len(query) < 2:
        return []
    # Hashed: cache keys must not carry spaces or accents.
    key = f"off:search:{hashlib.sha256(query.lower().encode()).hexdigest()[:32]}:{limit}"
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = _get("/cgi/search.pl", {
        "search_terms": query, "search_simple": 1, "action": "process", "json": 1, "page_size": limit,
        "fields": FIELDS, "sort_by": "unique_scans_n",
        "tagtype_0": "countries", "tag_contains_0": "contains", "tag_0": "spain",
    })
    products = [_product(p) for p in data.get("products") or [] if p.get("code")]
    cache.set(key, products, CACHE_SECONDS)
    return products


def product(code):
    """One product by barcode, or None when Open Food Facts does not know it."""
    code = (code or "").strip()
    if not BARCODE.match(code):
        raise OpenFoodFactsError("El código de barras son entre 8 y 14 cifras, sin espacios.")
    key = f"off:product:{code}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    data = _get(f"/api/v2/product/{code}", {"fields": FIELDS})
    found = _product({**data["product"], "code": code}) if data.get("status") == 1 and data.get("product") else {}
    cache.set(key, found, CACHE_SECONDS)
    return found or None
