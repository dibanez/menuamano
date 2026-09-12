"""Structured output contract shared by every provider.

Kept compatible with OpenAI Structured Outputs (strict mode): every field is required,
optional values are expressed as `X | None`, and there are no default values. A response
that satisfies this schema can still be wrong; `assistant.services` validates it again
against the household's data and rules.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict

MealTypeLiteral = Literal["breakfast", "lunch", "snack", "dinner"]
ModeLiteral = Literal["cook", "eat_out", "order", "leftovers", "free", "pending"]
UnitLiteral = Literal["g", "kg", "ml", "l", "tbsp", "tsp", "unit", "clove", "slice", "can", "bunch", "pack", "pinch"]
DifficultyLiteral = Literal["easy", "medium", "hard"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NewIngredientLine(StrictModel):
    name: str
    quantity: float | None
    unit: UnitLiteral
    optional: bool


class NewRecipe(StrictModel):
    ref: str
    name: str
    description: str
    base_servings: int
    prep_minutes: int
    cook_minutes: int
    difficulty: DifficultyLiteral
    tags: list[str]
    equipment: str
    ingredients: list[NewIngredientLine]
    steps: list[str]


class MealChange(StrictModel):
    date: str
    meal_type: MealTypeLiteral
    mode: ModeLiteral
    recipe_ids: list[int]
    new_recipe_refs: list[str]
    attendee_codes: list[str] | None
    notes: str
    reason: str


class AssistantOutput(StrictModel):
    summary: str
    changes: list[MealChange]
    new_recipes: list[NewRecipe]
    warnings: list[str]
