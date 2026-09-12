"""A new recipe generated for the meal being planned is linked to that meal when accepted."""

from django.urls import reverse

from assistant import services
from assistant.models import Proposal
from assistant.schemas import AssistantOutput, NewIngredientLine, NewRecipe
from planning import services as planning
from planning.models import Meal
from recipes.models import Recipe

from .factories import PASSWORD
from .test_assistant import FakeProvider, change, home, use_provider  # noqa: F401 (home is a fixture)


def new_recipe(ref="N1", name="Arroz con verduras"):
    return NewRecipe(
        ref=ref, name=name, description="", base_servings=4, prep_minutes=10, cook_minutes=20, difficulty="easy",
        tags=["cena"], equipment="", steps=["Cocer el arroz."],
        ingredients=[NewIngredientLine(name="Arroz", quantity=300, unit="g", optional=False)],
    )


def ask(monkeypatch, home, *changes, recipes=(), operation="replace_meal"):
    output = AssistantOutput(summary="", warnings=[], new_recipes=list(recipes), changes=list(changes))
    use_provider(monkeypatch, FakeProvider(output))
    focus = (home.monday, "dinner") if operation == "replace_meal" else None
    return services.request_proposal(home.household, home.user, operation, home.monday, home.monday, focus=focus)


def test_unlinked_new_recipe_is_linked_to_the_meal_being_planned(monkeypatch, home):
    meal, _ = planning.get_or_create_meal(home.household, home.monday, "dinner")  # «Planificar esta comida»
    proposal = ask(monkeypatch, home, recipes=[new_recipe()])
    assert [(i["status"], i["new_recipe_refs"]) for i in proposal.items] == [("ok", ["N1"])]

    result = services.apply_proposal(proposal, home.user)
    assert result.applied == 1
    assert [mr.name for mr in Meal.objects.get(pk=meal.pk).recipes.all()] == ["Arroz con verduras"]
    assert Recipe.objects.get(name="Arroz con verduras").origin == Recipe.Origin.AI


def test_an_empty_cook_change_for_the_meal_gets_the_new_recipe(monkeypatch, home):
    proposal = ask(monkeypatch, home, change(home.monday), recipes=[new_recipe()])
    assert proposal.items[0]["new_recipe_refs"] == ["N1"]


def test_an_existing_recipe_chosen_by_the_model_is_kept(monkeypatch, home):
    proposal = ask(monkeypatch, home, change(home.monday, [home.arroz.pk]), recipes=[new_recipe()])
    assert proposal.items[0]["recipe_ids"] == [home.arroz.pk]
    assert proposal.items[0]["new_recipe_refs"] == []


def test_range_proposals_keep_new_recipes_in_the_recipe_book_only(monkeypatch, home):
    proposal = ask(monkeypatch, home, recipes=[new_recipe()], operation="plan_range")
    assert proposal.items == []
    services.apply_proposal(proposal, home.user)
    assert Recipe.objects.filter(name="Arroz con verduras").exists()
    assert not Meal.objects.filter(household=home.household, recipes__name="Arroz con verduras").exists()


def test_accepting_goes_back_to_the_meal(client, monkeypatch, home):
    planning.get_or_create_meal(home.household, home.monday, "dinner")
    proposal = ask(monkeypatch, home, recipes=[new_recipe()])
    assert client.login(email=home.user.email, password=PASSWORD)
    response = client.post(reverse("assistant:proposal_apply", args=[proposal.pk]))
    assert response.url == reverse("planning:slot", args=[home.monday.isoformat(), "dinner"])
    assert Proposal.objects.get().status == Proposal.Status.APPLIED
