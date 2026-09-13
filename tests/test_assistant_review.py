"""Changes that need review: nothing is lost when «He revisado los avisos» is not ticked."""

from datetime import timedelta

from django.urls import reverse

from assistant import services
from assistant.models import Proposal
from assistant.schemas import AssistantOutput, NewIngredientLine, NewRecipe
from planning.models import Meal
from recipes.models import Recipe

from .factories import PASSWORD
from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)

SOUP = "Sopa de caldo"


def soup():
    """A new recipe with a processed ingredient nobody reviewed: it needs review for Nora (egg)."""
    return NewRecipe(
        ref="N1", name=SOUP, description="", base_servings=4, prep_minutes=5, cook_minutes=15, difficulty="easy",
        tags=["cena"], equipment="", steps=["Calentar el caldo."],
        ingredients=[NewIngredientLine(name="Caldo de verduras", quantity=500, unit="ml", optional=False)],
    )


def propose(monkeypatch, home, *changes):
    output = AssistantOutput(summary="", warnings=[], new_recipes=[soup()], changes=list(changes))
    use_provider(monkeypatch, FakeProvider(output))
    return services.request_proposal(home.household, home.user, "plan_range", home.monday, home.monday + timedelta(days=6))


def test_nothing_is_done_while_the_only_change_waits_for_confirmation(monkeypatch, home):
    proposal = propose(monkeypatch, home, change(home.monday + timedelta(days=1), refs=["N1"]))
    assert proposal.items[0]["status"] == "review"
    result = services.apply_proposal(proposal, home.user)
    assert result.needs_confirmation and result.applied == 0
    assert Proposal.objects.get(pk=proposal.pk).status == Proposal.Status.PENDING  # it can still be ticked
    assert not Recipe.objects.filter(name=SOUP).exists()

    result = services.apply_proposal(proposal, home.user, accepted_review=[proposal.items[0]["slot"]])
    assert result.applied == 1 and Recipe.objects.get(name=SOUP).review_status == Recipe.ReviewStatus.NEEDS_REVIEW


def test_the_page_asks_to_tick_the_change_instead_of_losing_it(client, monkeypatch, home):
    proposal = propose(monkeypatch, home, change(home.monday + timedelta(days=1), refs=["N1"]))
    assert client.login(email=home.user.email, password=PASSWORD)
    url = reverse("assistant:proposal", args=[proposal.pk])
    html = client.get(url).content.decode()
    assert "He revisado los avisos: aplicar este cambio" in html and 'class="check review-confirm"' in html
    response = client.post(reverse("assistant:proposal_apply", args=[proposal.pk]), follow=True)
    assert response.redirect_chain[-1][0] == url
    assert "marca «He revisado los avisos»" in response.content.decode()


def test_the_recipe_of_a_change_left_for_review_is_kept(monkeypatch, home):
    tuesday = home.monday + timedelta(days=1)
    proposal = propose(monkeypatch, home, change(home.monday, [home.arroz.pk]), change(tuesday, refs=["N1"]))
    assert [i["status"] for i in proposal.items] == ["ok", "review"]
    result = services.apply_proposal(proposal, home.user)
    assert result.applied == 1
    assert Recipe.objects.get(name=SOUP).review_status == Recipe.ReviewStatus.NEEDS_REVIEW
    assert not Meal.objects.filter(household=home.household, date=tuesday, recipes__name=SOUP).exists()
    assert result.skipped == [
        f"el martes 8 (cena): requiere revisión y no se marcó «He revisado los avisos». «{SOUP}» queda en el "
        "recetario, pendiente de revisión."
    ]
