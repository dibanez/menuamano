"""Load a reproducible demo household.

Only touches demo users (@menuamano.demo) and the demo household. Use --reset to rebuild it.
"""

from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from core.choices import MealType
from core.legal import record_consent
from diners.models import AttendancePattern, Diner, DinerPreference, DinerRestriction, WeightMeasurement
from foods.models import Ingredient, Trait
from households.models import Household, Membership, Role
from planning.models import DateException, MealMode, RecurringRule
from planning.services import regenerate_range
from recipes.models import Recipe, RecipeIngredient, RecipeStep
from shopping.services import create_list

HOUSEHOLD_NAME = "Casa demo"
PASSWORD = "menuamano-demo"
USERS = [
    ("ana@menuamano.demo", "Ana", Role.ADMIN),
    ("luis@menuamano.demo", "Luis", Role.EDITOR),
    ("lector@menuamano.demo", "Abuela Carmen", Role.READER),
]

# name, base servings, prep, cook, difficulty, tags, equipment, ingredients, steps
RECIPES = [
    ("Lentejas estofadas", 4, 15, 45, "easy", ["comida", "cuchara"], "Olla",
     [("Lentejas", 300, "g"), ("Patata", 400, "g"), ("Zanahoria", 2, "unit"), ("Cebolla", 1, "unit"),
      ("Ajo", 2, "clove"), ("Pimentón", 1, "tsp"), ("Laurel", 1, "unit"), ("Aceite de oliva", 30, "ml"), ("Sal", None, "g")],
     ["Pica la cebolla, el ajo y la zanahoria y rehógalos en el aceite.", "Añade el pimentón, las lentejas lavadas, la patata troceada y el laurel.",
      "Cubre con agua y cuece a fuego suave unos 40 minutos. Ajusta de sal."]),
    ("Tortilla de patata", 4, 15, 25, "medium", ["cena"], "Sartén",
     [("Huevo", 6, "unit"), ("Patata", 700, "g"), ("Cebolla", 1, "unit"), ("Aceite de oliva", 150, "ml"), ("Sal", None, "g")],
     ["Pela y lamina las patatas y la cebolla.", "Fríelas a fuego medio hasta que estén tiernas y escúrrelas.",
      "Bate los huevos, mezcla con la patata y cuaja la tortilla por ambos lados."]),
    ("Espaguetis con tomate y albahaca", 4, 5, 15, "easy", ["comida", "cena"], "Olla, sartén",
     [("Espaguetis", 400, "g"), ("Tomate triturado", 400, "g"), ("Ajo", 2, "clove"), ("Aceite de oliva", 30, "ml"),
      ("Albahaca fresca", 1, "bunch")],
     ["Cuece la pasta en agua con sal.", "Dora el ajo, añade el tomate y deja reducir 10 minutos.", "Mezcla con la pasta y la albahaca picada."]),
    ("Merluza al horno con patatas", 4, 15, 35, "easy", ["comida", "cena", "pescado"], "Horno",
     [("Merluza", 600, "g"), ("Patata", 600, "g"), ("Cebolla", 1, "unit"), ("Limón", 1, "unit"),
      ("Aceite de oliva", 40, "ml"), ("Perejil fresco", 1, "bunch")],
     ["Hornea la patata y la cebolla en láminas 20 minutos a 200 °C.", "Coloca la merluza encima, riega con aceite y limón y hornea 12 minutos más.", "Espolvorea perejil."]),
    ("Pollo al curry con arroz", 4, 10, 30, "easy", ["comida", "cena"], "Sartén honda",
     [("Pechuga de pollo", 600, "g"), ("Arroz", 300, "g"), ("Cebolla", 1, "unit"), ("Curry en polvo", 2, "tsp"),
      ("Tomate triturado", 200, "g"), ("Aceite de oliva", 30, "ml")],
     ["Cuece el arroz.", "Sofríe la cebolla, añade el pollo en dados y el curry.", "Incorpora el tomate y cocina 15 minutos. Sirve con el arroz."]),
    ("Crema de calabacín", 4, 10, 25, "easy", ["cena", "cuchara"], "Olla, batidora",
     [("Calabacín", 3, "unit"), ("Puerro", 1, "unit"), ("Patata", 200, "g"), ("Aceite de oliva", 30, "ml"), ("Sal", None, "g")],
     ["Rehoga el puerro en el aceite.", "Añade calabacín y patata troceados, cubre con agua y cuece 20 minutos.", "Tritura y ajusta de sal."]),
    ("Arroz con verduras", 4, 15, 25, "easy", ["comida", "cena"], "Paellera o sartén",
     [("Arroz", 320, "g"), ("Calabacín", 1, "unit"), ("Pimiento rojo", 1, "unit"), ("Zanahoria", 1, "unit"),
      ("Guisantes congelados", 150, "g"), ("Pimentón", 1, "tsp"), ("Aceite de oliva", 40, "ml")],
     ["Sofríe las verduras troceadas.", "Añade el arroz y el pimentón y rehoga un minuto.", "Cubre con el doble de agua y cuece 18 minutos."]),
    ("Ensalada de alubias", 4, 15, 60, "easy", ["comida"], "Olla",
     [("Alubias blancas", 250, "g"), ("Tomate", 2, "unit"), ("Pepino", 1, "unit"), ("Cebolla", 1, "unit"), ("Aceite de oliva", 30, "ml")],
     ["Cuece las alubias remojadas hasta que estén tiernas y enfríalas.", "Pica las verduras y mezcla todo con el aceite."]),
    ("Filetes de ternera con pimientos", 4, 10, 15, "easy", ["comida", "cena"], "Sartén",
     [("Filetes de ternera", 600, "g"), ("Pimiento verde", 2, "unit"), ("Pimiento rojo", 1, "unit"), ("Ajo", 2, "clove"),
      ("Aceite de oliva", 30, "ml")],
     ["Saltea los pimientos en tiras con el ajo.", "Marca los filetes a la plancha y sirve con los pimientos."]),
    ("Salmón a la plancha con brócoli", 4, 5, 15, "easy", ["cena", "pescado"], "Sartén, vaporera",
     [("Salmón", 600, "g"), ("Brócoli", 500, "g"), ("Limón", 1, "unit"), ("Aceite de oliva", 30, "ml")],
     ["Cuece el brócoli al vapor 6 minutos.", "Haz el salmón a la plancha 3 minutos por lado y sirve con limón."]),
    ("Macarrones con carne", 4, 10, 25, "easy", ["comida"], "Olla, sartén",
     [("Macarrones", 400, "g"), ("Carne picada de ternera", 400, "g"), ("Tomate triturado", 400, "g"), ("Cebolla", 1, "unit")],
     ["Cuece la pasta.", "Sofríe la cebolla y la carne, añade el tomate y cocina 10 minutos.", "Mezcla con la pasta."]),
    ("Gachas de avena con plátano", 2, 2, 8, "easy", ["desayuno"], "Cazo",
     [("Copos de avena", 100, "g"), ("Leche entera", 400, "ml"), ("Plátano", 1, "unit"), ("Canela", 1, "tsp")],
     ["Cuece la avena con la leche 6 minutos removiendo.", "Sirve con plátano en rodajas y canela."]),
    ("Fruta de temporada", 1, 5, 0, "easy", ["desayuno", "merienda"], "",
     [("Naranja", 1, "unit"), ("Kiwi", 1, "unit")],
     ["Lava, pela y trocea la fruta."]),
    ("Yogur con fresas", 1, 5, 0, "easy", ["merienda", "desayuno"], "",
     [("Yogur natural", 1, "unit"), ("Fresas", 100, "g")],
     ["Lava y trocea las fresas y mézclalas con el yogur."]),
    ("Manzana y nueces", 1, 3, 0, "easy", ["merienda"], "",
     [("Manzana", 1, "unit"), ("Nueces", 20, "g")],
     ["Trocea la manzana y acompaña con las nueces."]),
    ("Tostada con tomate", 2, 5, 3, "easy", ["desayuno"], "Tostadora",
     [("Pan de barra", 1, "unit"), ("Tomate", 2, "unit"), ("Aceite de oliva", 20, "ml"), ("Sal", None, "g")],
     ["Tuesta el pan.", "Ralla el tomate por encima y aliña con aceite y sal."]),
]


def ing(name):
    return Ingredient.objects.get(household__isnull=True, name=name)


class Command(BaseCommand):
    help = "Create (or rebuild with --reset) the demo household with diners, recipes, plan and shopping list."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Delete and recreate the demo household.")

    def handle(self, *args, reset=False, **options):
        users = {}
        for email, name, _ in USERS:
            user, created = User.objects.get_or_create(email=email, defaults={"display_name": name})
            if created:
                user.set_password(PASSWORD)
                user.save()
            record_consent(user)  # demo accounts start with the legal texts accepted
            users[email] = user
        admin = users[USERS[0][0]]

        existing = Household.objects.filter(name=HOUSEHOLD_NAME, memberships__user=admin).first()
        if existing and not reset:
            self.stdout.write(self.style.WARNING("The demo household already exists. Use --reset to rebuild it."))
            self._print_access()
            return
        if existing:
            existing.delete()

        with transaction.atomic():
            household = Household.objects.create(name=HOUSEHOLD_NAME)
            for email, _, role in USERS:
                Membership.objects.create(user=users[email], household=household, role=role)
            diners = self._diners(household, users)
            self._recipes(household, admin)
            self._rules(household, diners)

        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        end = monday + timedelta(days=13)
        report = regenerate_range(household, monday, end, admin)
        shopping_list = create_list(household, admin, monday, monday + timedelta(days=6), "Compra de esta semana")

        self.stdout.write(self.style.SUCCESS(
            f"Demo household ready: {report.created} meals planned, shopping list with "
            f"{shopping_list.items.count()} items."
        ))
        self._print_access()

    def _print_access(self):
        self.stdout.write("Demo accounts (password: %s):" % PASSWORD)
        for email, _, role in USERS:
            self.stdout.write(f"  {email}  ({role})")

    def _diners(self, household, users):
        weekdays = range(0, 5)
        ana = Diner.objects.create(household=household, alias="Ana", linked_user=users["ana@menuamano.demo"], height_cm=Decimal("165"))
        luis = Diner.objects.create(household=household, alias="Luis", linked_user=users["luis@menuamano.demo"])
        nora = Diner.objects.create(
            household=household, alias="Nora", birth_date=timezone.localdate().replace(year=timezone.localdate().year - 8, day=1),
            portion_factor=Decimal("0.6"),
        )
        leo = Diner.objects.create(
            household=household, alias="Leo", birth_date=timezone.localdate().replace(year=timezone.localdate().year - 14, day=1),
            portion_factor=Decimal("1.2"), notes="Prefiere la comida poco especiada.",
        )
        DinerRestriction.objects.create(diner=nora, kind=DinerRestriction.Kind.ALLERGY, trait=Trait.EGG)
        DinerRestriction.objects.create(diner=leo, kind=DinerRestriction.Kind.INTOLERANCE, trait=Trait.LACTOSE)
        DinerPreference.objects.create(diner=leo, kind=DinerPreference.Kind.DISLIKE, ingredient=ing("Champiñones"))
        DinerPreference.objects.create(diner=nora, kind=DinerPreference.Kind.LIKE, text="pasta")
        # Luis eats at work on weekdays; the kids have lunch at school.
        for diner in (luis, nora, leo):
            for weekday in weekdays:
                AttendancePattern.objects.create(diner=diner, weekday=weekday, meal_type=MealType.LUNCH, attends=False)
        today = timezone.localdate()
        WeightMeasurement.objects.create(diner=ana, measured_on=today - timedelta(days=30), weight_kg=Decimal("62.4"), recorded_by=ana.linked_user)
        WeightMeasurement.objects.create(diner=ana, measured_on=today - timedelta(days=2), weight_kg=Decimal("62.1"), recorded_by=ana.linked_user)
        return {"ana": ana, "luis": luis, "nora": nora, "leo": leo}

    def _recipes(self, household, admin):
        for name, servings, prep, cook, difficulty, tags, equipment, lines, steps in RECIPES:
            recipe = Recipe.objects.create(
                household=household, name=name, base_servings=servings, prep_minutes=prep, cook_minutes=cook,
                difficulty=difficulty, tags=tags, equipment=equipment, origin=Recipe.Origin.DEMO, created_by=admin,
            )
            for order, (ingredient_name, quantity, unit) in enumerate(lines):
                RecipeIngredient.objects.create(
                    recipe=recipe, ingredient=ing(ingredient_name), unit=unit, order=order,
                    quantity=None if quantity is None else Decimal(str(quantity)),
                )
            for order, text in enumerate(steps):
                RecipeStep.objects.create(recipe=recipe, order=order, text=text)

    def _rules(self, household, diners):
        RecurringRule.objects.create(
            household=household, weekday=4, meal_type=MealType.DINNER, mode=MealMode.EAT_OUT, notes="Cena fuera los viernes"
        )
        today = timezone.localdate()
        next_wednesday = today + timedelta(days=(2 - today.weekday()) % 7 or 7)
        exception = DateException.objects.create(
            household=household, date=next_wednesday, meal_type=MealType.DINNER, override_attendance=True,
            notes="Ese día solo cenan dos",
        )
        exception.attendees.set([diners["ana"], diners["luis"]])
