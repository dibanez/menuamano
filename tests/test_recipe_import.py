"""Importing a recipe from a web page: safe fetching, reading the page, reviewing before saving.

No test touches the network: pages are given to the importer directly.
"""

import json

import pytest
from django.urls import reverse

from assistant.models import Proposal
from recipes import importer
from recipes.models import Recipe

from .factories import PASSWORD, make_diner

RECIPE_PAGE = """<!doctype html><html><head><title>Espaguetis con tomate | Recetas</title>
<script type="application/ld+json">{data}</script></head>
<body><nav>Menú</nav><h1>Espaguetis con tomate</h1></body></html>"""

RECIPE_DATA = {
    "@context": "https://schema.org",
    "@graph": [
        {"@type": "WebPage", "name": "Recetas"},
        {
            "@type": ["Recipe"], "name": "Espaguetis con tomate", "description": "Un clásico &amp; rápido.",
            "recipeYield": ["4", "4 raciones"], "prepTime": "PT10M", "cookTime": "PT1H5M",
            "recipeIngredient": ["400 g de espaguetis", "400 g de tomate triturado", "2 dientes de ajo", "Sal al gusto"],
            "recipeInstructions": [
                {"@type": "HowToSection", "name": "Salsa", "itemListElement": [
                    {"@type": "HowToStep", "text": "Sofríe el ajo."},
                    {"@type": "HowToStep", "text": "Añade el tomate."},
                ]},
                {"@type": "HowToStep", "text": "Cuece la pasta y mezcla."},
            ],
        },
    ],
}


def page(data=RECIPE_DATA):
    return RECIPE_PAGE.format(data=json.dumps(data))


@pytest.mark.parametrize("url", [
    "ftp://example.com/receta", "example.com/receta", "http://user:secret@example.com/",
    "https://example.com:8443/receta",
])
def test_only_plain_web_links_are_accepted(url):
    with pytest.raises(importer.RecipeImportError):
        importer.check_url(url)


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "192.168.1.20", "169.254.169.254", "::1", "localhost"])
def test_the_server_never_fetches_its_own_network(host):
    with pytest.raises(importer.RecipeImportError):
        importer.public_address(host, 443)


def test_schema_org_recipes_are_read_directly():
    source = importer.extract(page())
    assert source["format"] == "schema.org" and source["name"] == "Espaguetis con tomate"
    assert source["description"] == "Un clásico & rápido."
    assert source["servings"] == 4 and source["prep_minutes"] == 10 and source["cook_minutes"] == 65
    assert source["ingredients"][2] == "2 dientes de ajo"
    assert source["instructions"] == ["Sofríe el ajo.", "Añade el tomate.", "Cuece la pasta y mezcla."]


def test_pages_without_recipe_data_keep_their_visible_text():
    text = "Pon las lentejas en remojo la víspera y cuécelas con verduras. " * 5
    source = importer.extract(f"<html><head><title>Lentejas</title><style>p{{}}</style></head><body><p>{text}</p></body></html>")
    assert source["format"] == "text" and source["title"] == "Lentejas" and "remojo" in source["text"]
    assert "p{}" not in source["text"]
    with pytest.raises(importer.RecipeImportError):
        importer.extract("<html><body><p>Hola</p></body></html>")


def test_an_imported_recipe_is_reviewed_before_it_is_saved(client, household, admin_user, monkeypatch):
    make_diner(household, "Ana")
    fetched = []
    monkeypatch.setattr(importer, "fetch_html", lambda url: fetched.append(url) or page())
    assert client.login(email=admin_user.email, password=PASSWORD)
    url = "https://recetas.example/espaguetis"
    response = client.post(reverse("assistant:import_recipe"), {"url": url})
    proposal = Proposal.objects.get(household=household)
    assert response.url == reverse("assistant:proposal", args=[proposal.pk]) and fetched == [url]
    assert proposal.operation == Proposal.Operation.IMPORT_RECIPE and not Recipe.objects.exists()
    recipe = proposal.new_recipes[0]
    lines = {line["name"]: line for line in recipe["ingredients"]}
    assert lines["Espaguetis"]["ingredient_id"] and lines["Espaguetis"]["quantity"] == "400.000"
    assert lines["Ajo"]["unit"] == "clove" and lines["Sal"]["quantity"] is None
    assert "Guardar en el recetario" in client.get(response.url).content.decode()

    client.post(reverse("assistant:proposal_apply", args=[proposal.pk]))
    saved = Recipe.objects.get(household=household)
    assert saved.origin == Recipe.Origin.IMPORTED and saved.source_url == url
    assert saved.review_status == Recipe.ReviewStatus.NEEDS_REVIEW
    assert saved.ingredients.count() == 4 and saved.steps.count() == 3 and saved.cook_minutes == 65
    assert "Ver la receta original" in client.get(reverse("recipes:detail", args=[saved.pk])).content.decode()


def test_import_errors_are_explained(client, household, admin_user, monkeypatch):
    def refuse(url):
        raise importer.RecipeImportError("Ese enlace no lleva a una página pública de internet.")

    monkeypatch.setattr(importer, "fetch_html", refuse)
    assert client.login(email=admin_user.email, password=PASSWORD)
    response = client.post(reverse("assistant:import_recipe"), {"url": "http://10.0.0.1/"}, follow=True)
    assert "no lleva a una página pública" in response.content.decode()
    assert not Proposal.objects.exists()
