"""Nutrition maths: daily targets from the user's profile, portion scaling, totals."""

from backend.models import ItemInput, Nutrients, Profile, Targets

NUTRIENT_KEYS = ("calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg")

ACTIVITY_FACTORS = {"sedentary": 1.2, "light": 1.375, "moderate": 1.55, "active": 1.725, "very_active": 1.9}
GOAL_CALORIE_ADJUST = {"lose": -500, "maintain": 0, "gain": 300}
PROTEIN_G_PER_KG = {"lose": 1.6, "maintain": 1.2, "gain": 1.7}


def compute_targets(p: Profile) -> Targets:
    """Mifflin-St Jeor BMR x activity factor = TDEE, then adjusted for the goal."""
    bmr = 10 * p.weight_kg + 6.25 * p.height_cm - 5 * p.age + (5 if p.sex == "male" else -161)
    tdee = bmr * ACTIVITY_FACTORS[p.activity_level]
    floor = 1500 if p.sex == "male" else 1200                 # never suggest a crash diet
    calories = max(tdee + GOAL_CALORIE_ADJUST[p.goal], floor)

    protein_g = PROTEIN_G_PER_KG[p.goal] * p.weight_kg
    fat_g = calories * 0.27 / 9                               # 27% of calories from fat
    carbs_g = max(calories - protein_g * 4 - fat_g * 9, 0) / 4  # the rest from carbs
    return Targets(
        calories=round(calories), protein_g=round(protein_g), carbs_g=round(carbs_g),
        fat_g=round(fat_g), fiber_g=round(calories / 1000 * 14),  # 14 g per 1000 kcal
        sugar_g=round(calories * 0.10 / 4),                       # <=10% of calories
        sodium_mg=2300, bmr=round(bmr), tdee=round(tdee),
    )


def scale_item(item: ItemInput) -> dict:
    """Scale an item's nutrients from base_grams to the grams the user confirmed."""
    factor = item.grams / item.base_grams
    scaled = {k: round(getattr(item, k) * factor, 1) for k in NUTRIENT_KEYS}
    return {"name": item.name.strip(), "grams": round(item.grams, 1), **scaled}


def sum_nutrients(items: list[dict]) -> Nutrients:
    return Nutrients(**{k: round(sum(i.get(k, 0) for i in items), 1) for k in NUTRIENT_KEYS})


def percent_of(value: float, target: float) -> int:
    return round(value / target * 100) if target else 0
