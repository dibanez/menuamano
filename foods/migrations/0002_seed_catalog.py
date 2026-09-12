"""Seed the shared ingredient catalogue.

Processed products are marked `trait_info_complete=False`: their composition depends on the
brand, so compatibility with restrictions stays "unknown" until someone reviews the label.
"""

from django.db import migrations
from django.utils.text import slugify

A = "animal_origin"

# name, category, default unit, traits (fully expanded), info complete, processed, aliases
CATALOG = [
    # Frutas y verduras
    ("Tomate", "produce", "unit", [], True, False, ["tomates"]),
    ("Cebolla", "produce", "unit", [], True, False, ["cebollas"]),
    ("Ajo", "produce", "clove", [], True, False, ["ajos", "diente de ajo"]),
    ("Patata", "produce", "g", [], True, False, ["patatas"]),
    ("Zanahoria", "produce", "unit", [], True, False, ["zanahorias"]),
    ("Calabacín", "produce", "unit", [], True, False, ["calabacines"]),
    ("Pimiento rojo", "produce", "unit", [], True, False, []),
    ("Pimiento verde", "produce", "unit", [], True, False, []),
    ("Berenjena", "produce", "unit", [], True, False, []),
    ("Lechuga", "produce", "unit", [], True, False, []),
    ("Espinacas frescas", "produce", "g", [], True, False, ["espinacas"]),
    ("Brócoli", "produce", "g", [], True, False, ["brocoli"]),
    ("Champiñones", "produce", "g", [], True, False, ["champiñon"]),
    ("Puerro", "produce", "unit", [], True, False, ["puerros"]),
    ("Apio", "produce", "g", ["celery"], True, False, []),
    ("Pepino", "produce", "unit", [], True, False, []),
    ("Calabaza", "produce", "g", [], True, False, []),
    ("Aguacate", "produce", "unit", [], True, False, []),
    ("Limón", "produce", "unit", [], True, False, ["limon", "limones"]),
    ("Naranja", "produce", "unit", [], True, False, ["naranjas"]),
    ("Plátano", "produce", "unit", [], True, False, ["platano", "plátanos"]),
    ("Manzana", "produce", "unit", [], True, False, ["manzanas"]),
    ("Fresas", "produce", "g", [], True, False, ["fresa"]),
    ("Kiwi", "produce", "unit", [], True, False, []),
    ("Perejil fresco", "produce", "bunch", [], True, False, ["perejil"]),
    ("Albahaca fresca", "produce", "bunch", [], True, False, ["albahaca"]),
    # Carne
    ("Pechuga de pollo", "meat", "g", ["meat", A], True, False, ["pollo"]),
    ("Muslos de pollo", "meat", "g", ["meat", A], True, False, []),
    ("Carne picada de ternera", "meat", "g", ["meat", A], True, False, ["carne picada"]),
    ("Filetes de ternera", "meat", "g", ["meat", A], True, False, ["ternera"]),
    ("Lomo de cerdo", "meat", "g", ["pork", "meat", A], True, False, ["cerdo"]),
    ("Jamón serrano", "meat", "g", ["pork", "meat", A], False, True, ["jamon serrano"]),
    ("Chorizo", "meat", "g", ["pork", "meat", A], False, True, []),
    ("Pavo en lonchas", "meat", "slice", ["meat", A], False, True, ["fiambre de pavo"]),
    # Pescado y marisco
    ("Merluza", "fish", "g", ["fish", A], True, False, []),
    ("Salmón", "fish", "g", ["fish", A], True, False, ["salmon"]),
    ("Bacalao", "fish", "g", ["fish", A], True, False, []),
    ("Atún en lata", "fish", "can", ["fish", A], False, True, ["atun", "atún"]),
    ("Gambas", "fish", "g", ["crustaceans", A], True, False, ["langostinos"]),
    ("Mejillones", "fish", "g", ["molluscs", A], True, False, []),
    # Lácteos y huevos
    ("Huevo", "dairy_eggs", "unit", ["egg", A], True, False, ["huevos"]),
    ("Leche entera", "dairy_eggs", "ml", ["milk", "lactose", A], True, False, ["leche"]),
    ("Leche sin lactosa", "dairy_eggs", "ml", ["milk", A], False, True, []),
    ("Yogur natural", "dairy_eggs", "unit", ["milk", "lactose", A], True, False, ["yogur"]),
    ("Queso fresco", "dairy_eggs", "g", ["milk", "lactose", A], False, True, []),
    ("Queso rallado", "dairy_eggs", "g", ["milk", "lactose", A], False, True, []),
    ("Mozzarella", "dairy_eggs", "g", ["milk", "lactose", A], False, True, []),
    ("Mantequilla", "dairy_eggs", "g", ["milk", "lactose", A], True, False, []),
    ("Nata para cocinar", "dairy_eggs", "ml", ["milk", "lactose", A], False, True, ["nata"]),
    # Pan y cereales
    ("Pan de barra", "bakery", "unit", ["gluten"], False, True, ["pan", "barra de pan"]),
    ("Pan de molde", "bakery", "slice", ["gluten"], False, True, []),
    ("Pan rallado", "bakery", "g", ["gluten"], False, True, []),
    ("Tortillas de trigo", "bakery", "unit", ["gluten"], False, True, ["tortillas mexicanas"]),
    ("Harina de trigo", "bakery", "g", ["gluten"], True, False, ["harina"]),
    ("Copos de avena", "bakery", "g", ["gluten"], False, True, ["avena"]),
    # Pasta, arroz y legumbres
    ("Arroz", "pasta_rice_legumes", "g", [], True, False, ["arroz redondo", "arroz largo"]),
    ("Espaguetis", "pasta_rice_legumes", "g", ["gluten"], True, False, ["spaghetti"]),
    ("Macarrones", "pasta_rice_legumes", "g", ["gluten"], True, False, []),
    ("Pasta sin gluten", "pasta_rice_legumes", "g", [], False, True, []),
    ("Cuscús", "pasta_rice_legumes", "g", ["gluten"], True, False, ["cuscus"]),
    ("Quinoa", "pasta_rice_legumes", "g", [], True, False, []),
    ("Lentejas", "pasta_rice_legumes", "g", [], True, False, []),
    ("Garbanzos cocidos", "pasta_rice_legumes", "g", [], False, True, ["garbanzos"]),
    ("Alubias blancas", "pasta_rice_legumes", "g", [], True, False, ["judías blancas"]),
    # Despensa
    ("Aceite de oliva", "pantry", "ml", [], True, False, ["aceite", "aceite de oliva virgen extra"]),
    ("Sal", "pantry", "g", [], True, False, []),
    ("Azúcar", "pantry", "g", [], True, False, ["azucar"]),
    ("Miel", "pantry", "g", [A], True, False, []),
    ("Tomate triturado", "pantry", "g", [], False, True, []),
    ("Tomate frito", "pantry", "g", [], False, True, []),
    ("Caldo de verduras", "pantry", "ml", [], False, True, []),
    ("Caldo de pollo", "pantry", "ml", ["meat", A], False, True, []),
    ("Salsa de soja", "pantry", "ml", ["soy", "gluten"], False, True, []),
    ("Mostaza", "pantry", "g", ["mustard"], False, True, []),
    ("Vinagre de vino", "pantry", "ml", ["sulphites"], False, True, ["vinagre"]),
    ("Vino blanco", "drinks", "ml", ["alcohol", "sulphites"], False, True, []),
    ("Tofu", "pantry", "g", ["soy"], False, True, []),
    ("Tahini", "pantry", "g", ["sesame"], False, True, []),
    ("Cacahuetes", "pantry", "g", ["peanut"], True, False, []),
    ("Nueces", "pantry", "g", ["tree_nuts"], True, False, []),
    ("Almendras", "pantry", "g", ["tree_nuts"], True, False, []),
    ("Cacao en polvo", "pantry", "g", [], False, True, ["cacao"]),
    ("Chocolate negro", "pantry", "g", [], False, True, []),
    ("Mermelada", "pantry", "g", [], False, True, []),
    ("Levadura química", "pantry", "g", [], False, True, ["levadura"]),
    # Especias y condimentos
    ("Pimienta negra", "spices", "pinch", [], True, False, ["pimienta"]),
    ("Pimentón", "spices", "tsp", [], True, False, ["pimentón dulce"]),
    ("Comino", "spices", "tsp", [], True, False, []),
    ("Orégano", "spices", "tsp", [], True, False, ["oregano"]),
    ("Canela", "spices", "tsp", [], True, False, []),
    ("Laurel", "spices", "unit", [], True, False, ["hoja de laurel"]),
    ("Curry en polvo", "spices", "tsp", [], False, True, ["curry"]),
    # Congelados
    ("Guisantes congelados", "frozen", "g", [], True, False, ["guisantes"]),
]


def seed(apps, schema_editor):
    Ingredient = apps.get_model("foods", "Ingredient")
    for name, category, unit, traits, complete, processed, aliases in CATALOG:
        Ingredient.objects.update_or_create(
            household=None,
            normalized_name=slugify(name).replace("-", " ").strip(),
            defaults={
                "name": name,
                "category": category,
                "default_unit": unit,
                "traits": sorted(set(traits)),
                "trait_info_complete": complete,
                "is_processed": processed,
                "aliases": aliases,
                "source": "catalog",
            },
        )


def unseed(apps, schema_editor):
    apps.get_model("foods", "Ingredient").objects.filter(household=None, source="catalog").delete()


class Migration(migrations.Migration):
    dependencies = [("foods", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
