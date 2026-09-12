from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import Q
from django.utils.text import slugify


class Trait(models.TextChoices):
    """Closed vocabulary used to express mandatory dietary restrictions.

    The first fourteen are the allergens with mandatory labelling in the EU
    (Regulation 1169/2011, Annex II).
    """

    GLUTEN = "gluten", "Gluten"
    CRUSTACEANS = "crustaceans", "Crustáceos"
    EGG = "egg", "Huevo"
    FISH = "fish", "Pescado"
    PEANUT = "peanut", "Cacahuete"
    SOY = "soy", "Soja"
    MILK = "milk", "Leche y derivados"
    TREE_NUTS = "tree_nuts", "Frutos de cáscara"
    CELERY = "celery", "Apio"
    MUSTARD = "mustard", "Mostaza"
    SESAME = "sesame", "Sésamo"
    SULPHITES = "sulphites", "Sulfitos"
    LUPIN = "lupin", "Altramuces"
    MOLLUSCS = "molluscs", "Moluscos"
    LACTOSE = "lactose", "Lactosa"
    MEAT = "meat", "Carne"
    PORK = "pork", "Cerdo"
    ALCOHOL = "alcohol", "Alcohol"
    ANIMAL_ORIGIN = "animal_origin", "Origen animal"


ALLERGEN_TRAITS = frozenset(
    [
        Trait.GLUTEN, Trait.CRUSTACEANS, Trait.EGG, Trait.FISH, Trait.PEANUT, Trait.SOY, Trait.MILK,
        Trait.TREE_NUTS, Trait.CELERY, Trait.MUSTARD, Trait.SESAME, Trait.SULPHITES, Trait.LUPIN,
        Trait.MOLLUSCS,
    ]
)

# Traits that imply other traits. Applied on save so the catalogue stays consistent.
IMPLIED_TRAITS = {
    Trait.PORK: {Trait.MEAT},
    Trait.LACTOSE: {Trait.MILK},
    Trait.MEAT: {Trait.ANIMAL_ORIGIN},
    Trait.FISH: {Trait.ANIMAL_ORIGIN},
    Trait.CRUSTACEANS: {Trait.ANIMAL_ORIGIN},
    Trait.MOLLUSCS: {Trait.ANIMAL_ORIGIN},
    Trait.EGG: {Trait.ANIMAL_ORIGIN},
    Trait.MILK: {Trait.ANIMAL_ORIGIN},
}

DIET_PRESETS = {
    "vegetarian": ("Dieta vegetariana", [Trait.MEAT, Trait.FISH, Trait.CRUSTACEANS, Trait.MOLLUSCS]),
    "vegan": ("Dieta vegana", [Trait.ANIMAL_ORIGIN]),
    "no_pork": ("Sin cerdo", [Trait.PORK]),
    "no_alcohol": ("Sin alcohol", [Trait.ALCOHOL]),
}


def expand_traits(traits):
    result = set(traits)
    pending = list(result)
    while pending:
        for implied in IMPLIED_TRAITS.get(pending.pop(), ()):
            if implied not in result:
                result.add(implied)
                pending.append(implied)
    return result


class Category(models.TextChoices):
    PRODUCE = "produce", "Frutas y verduras"
    MEAT = "meat", "Carne"
    FISH = "fish", "Pescado y marisco"
    DAIRY_EGGS = "dairy_eggs", "Lácteos y huevos"
    BAKERY = "bakery", "Pan y cereales"
    PASTA_RICE_LEGUMES = "pasta_rice_legumes", "Pasta, arroz y legumbres"
    PANTRY = "pantry", "Despensa"
    SPICES = "spices", "Especias y condimentos"
    FROZEN = "frozen", "Congelados"
    DRINKS = "drinks", "Bebidas"
    OTHER = "other", "Otros"


CATEGORY_ORDER = [c.value for c in Category]


class Dimension(models.TextChoices):
    MASS = "mass", "Masa"
    VOLUME = "volume", "Volumen"
    COUNT = "count", "Unidades"


class Unit(models.TextChoices):
    G = "g", "g"
    KG = "kg", "kg"
    ML = "ml", "ml"
    L = "l", "l"
    TBSP = "tbsp", "cucharada"
    TSP = "tsp", "cucharadita"
    UNIT = "unit", "unidad"
    CLOVE = "clove", "diente"
    SLICE = "slice", "loncha"
    CAN = "can", "lata"
    BUNCH = "bunch", "manojo"
    PACK = "pack", "paquete"
    PINCH = "pinch", "pizca"


# unit -> (dimension, factor to the dimension's base unit). Count units have no factor:
# they only aggregate with themselves.
UNIT_INFO = {
    Unit.G: (Dimension.MASS, Decimal("1")),
    Unit.KG: (Dimension.MASS, Decimal("1000")),
    Unit.ML: (Dimension.VOLUME, Decimal("1")),
    Unit.L: (Dimension.VOLUME, Decimal("1000")),
    Unit.TBSP: (Dimension.VOLUME, Decimal("15")),
    Unit.TSP: (Dimension.VOLUME, Decimal("5")),
    Unit.UNIT: (Dimension.COUNT, None),
    Unit.CLOVE: (Dimension.COUNT, None),
    Unit.SLICE: (Dimension.COUNT, None),
    Unit.CAN: (Dimension.COUNT, None),
    Unit.BUNCH: (Dimension.COUNT, None),
    Unit.PACK: (Dimension.COUNT, None),
    Unit.PINCH: (Dimension.COUNT, None),
}


def normalize_name(value):
    return slugify(value or "").replace("-", " ").strip()


class IngredientQuerySet(models.QuerySet):
    def for_household(self, household):
        """Shared catalogue plus the household's own ingredients."""
        return self.filter(Q(household__isnull=True) | Q(household=household))


class Ingredient(models.Model):
    class Source(models.TextChoices):
        CATALOG = "catalog", "Catálogo"
        MANUAL = "manual", "Añadido por el hogar"
        AI = "ai", "Propuesto por IA"

    household = models.ForeignKey(
        "households.Household", null=True, blank=True, on_delete=models.CASCADE, related_name="ingredients",
        help_text="Vacío = catálogo compartido.",
    )
    name = models.CharField("nombre", max_length=100)
    normalized_name = models.CharField(max_length=100, editable=False)
    aliases = ArrayField(models.CharField(max_length=100), default=list, blank=True, verbose_name="alias")
    category = models.CharField("categoría", max_length=24, choices=Category.choices, default=Category.OTHER)
    default_unit = models.CharField("unidad habitual", max_length=8, choices=Unit.choices, default=Unit.G)
    traits = ArrayField(
        models.CharField(max_length=16, choices=Trait.choices), default=list, blank=True,
        verbose_name="contiene",
    )
    trait_info_complete = models.BooleanField(
        "información de alérgenos revisada", default=False,
        help_text="Solo si se ha comprobado qué contiene. Si no, la compatibilidad será «desconocida».",
    )
    is_processed = models.BooleanField(
        "producto procesado", default=False,
        help_text="La composición depende de la marca: hay que revisar la etiqueta.",
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = IngredientQuerySet.as_manager()

    class Meta:
        verbose_name = "ingrediente"
        verbose_name_plural = "ingredientes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["household", "normalized_name"], name="unique_ingredient_name", nulls_distinct=False
            )
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.normalized_name = normalize_name(self.name)
        self.traits = sorted(str(t) for t in expand_traits(self.traits))
        super().save(*args, **kwargs)

    def trait_labels(self):
        labels = dict(Trait.choices)
        return [labels.get(t, t) for t in self.traits]
