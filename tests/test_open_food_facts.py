"""Filling a label review from Open Food Facts. No test reaches the network."""

import pytest
from django.core.cache import cache
from django.urls import reverse

from foods import openfoodfacts
from foods.models import IngredientReview

from .factories import PASSWORD, ingredient

SAUCE = "Tomate triturado"
CODE = "8480000160447"
SAMPLE = {
    "code": CODE, "product_name": "Tomate triturado", "brands": "Hacendado,Mercadona", "quantity": "800 g",
    "stores": "Mercadona",
    "allergens_tags": ["en:celery"], "traces_tags": ["en:gluten", "en:kiwi"],
    "ingredients_text_es": "Tomate, sal, apio.",
}


@pytest.fixture
def off(monkeypatch):
    """Open Food Facts answers from memory; returns the calls made."""
    calls = []

    def fake_get(path, params):
        calls.append(path)
        if path.startswith("/api/v2/product/"):
            return {"status": 1, "product": SAMPLE} if path.endswith(CODE) else {"status": 0}
        return {"products": [SAMPLE]}

    cache.clear()
    monkeypatch.setattr(openfoodfacts, "_get", fake_get)
    return calls


def test_allergens_and_traces_become_traits(off):
    product = openfoodfacts.product(CODE)
    assert product["name"] == "Tomate triturado" and product["brand"] == "Hacendado" and product["stores"] == "Mercadona"
    assert product["allergens"] == ["celery"] and product["traces"] == ["gluten"]
    assert product["other_allergens"] == ["kiwi"]  # outside the EU list: shown, never guessed


def test_lookups_are_cached_and_bad_codes_never_leave(off):
    openfoodfacts.search("tomate hacendado")
    openfoodfacts.search("tomate  hacendado")
    assert off == ["/cgi/search.pl"]
    with pytest.raises(openfoodfacts.OpenFoodFactsError):
        openfoodfacts.product("12 34")
    assert off == ["/cgi/search.pl"]


def test_the_review_page_finds_the_product_and_fills_the_review(client, household, admin_user, off):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("foods:review", args=[ingredient(SAUCE).pk])
    html = client.get(url, {"buscar": "tomate hacendado"}).content.decode()
    assert "Tomate triturado</strong> · Hacendado · 800 g" in html and f"?codigo={CODE}" in html
    assert f"Código {CODE}." in html  # sizes and variants of one product tell apart
    assert "Open Food Facts</a>, con licencia ODbL" in html

    response = client.get(url, {"codigo": CODE})
    form = response.context["form"]
    assert form.initial["traits"] == ["celery", "gluten"]
    assert form.initial["note"] == f"Hacendado · Tomate triturado ({CODE})"
    assert "Ingredientes: Tomate, sal, apio." in response.content.decode()

    # Nothing is saved until someone confirms having read the label.
    client.post(url, {"traits": ["celery", "gluten"], "note": form.initial["note"]})
    assert not IngredientReview.objects.exists()
    client.post(url, {"traits": ["celery", "gluten"], "note": form.initial["note"], "confirm": "on"})
    assert set(IngredientReview.objects.get().traits) >= {"celery", "gluten"}


def test_unknown_codes_and_outages_are_explained(client, household, admin_user, off, monkeypatch):
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = reverse("foods:review", args=[ingredient(SAUCE).pk])
    assert "no conoce ese código" in client.get(url, {"codigo": "00000000"}).content.decode()

    def down(path, params):
        raise openfoodfacts.OpenFoodFactsError("Open Food Facts no responde ahora mismo. Prueba en un rato.")

    monkeypatch.setattr(openfoodfacts, "_get", down)
    response = client.get(url, {"buscar": "otra cosa"})
    assert response.status_code == 200 and "no responde ahora mismo" in response.content.decode()


def test_being_rate_limited_suggests_the_barcode(monkeypatch):
    from urllib.error import HTTPError

    def limited(request, timeout):
        raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)

    cache.clear()
    monkeypatch.setattr(openfoodfacts, "urlopen", limited)
    with pytest.raises(openfoodfacts.OpenFoodFactsError) as error:
        openfoodfacts.search("tomate hacendado")
    assert "busca por el código de barras" in error.value.message


def test_a_busy_search_is_tried_once_more(monkeypatch):
    import io
    import json as json_module
    from urllib.error import HTTPError

    answers = [HTTPError("url", 503, "Service Unavailable", {}, None)]

    def busy_then_fine(request, timeout):
        if answers:
            raise answers.pop()
        return io.BytesIO(json_module.dumps({"products": [SAMPLE]}).encode())

    cache.clear()
    monkeypatch.setattr(openfoodfacts, "urlopen", busy_then_fine)
    monkeypatch.setattr(openfoodfacts, "RETRY_PAUSE_SECONDS", 0)
    assert [p["code"] for p in openfoodfacts.search("tomate hacendado")] == [CODE]


def test_the_review_page_alone_asks_nothing_from_open_food_facts(client, household, admin_user, off):
    assert client.login(email=admin_user.email, password=PASSWORD)
    html = client.get(reverse("foods:review", args=[ingredient(SAUCE).pk])).content.decode()
    assert off == [] and 'value="Tomate triturado"' in html  # the search box starts with the ingredient
