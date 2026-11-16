"""Create a demo account with ~4 weeks of realistic meals (for presentations).

Run from the project folder:   python -m scripts.seed_demo
Login: demo@macrovision.ai / demo1234
"""

import random
from datetime import date, datetime, timedelta

from backend import auth, repository
from backend.database import get_db, init_db
from backend.models import Profile
from backend.services.nutrition_service import sum_nutrients

random.seed(7)
EMAIL, PASSWORD = "demo@macrovision.ai", "demo1234"

# name: (grams, kcal, protein, carbs, fat, fibre, sugar, sodium) per portion
FOODS = {
    "breakfast": [
        [("Masala dosa", 180, 370, 7.5, 52, 14, 4.2, 2.5, 520), ("Sambar", 150, 125, 6, 18, 3.5, 5, 4, 480)],
        [("Poha with peanuts", 200, 330, 7, 50, 11, 3, 4, 420), ("Masala chai", 150, 90, 3, 12, 3.5, 0, 10, 40)],
        [("Idli", 150, 210, 6, 44, 1, 2, 0.5, 380), ("Coconut chutney", 40, 95, 1.2, 3.5, 8.5, 2, 1.2, 130)],
        [("Boiled eggs", 100, 155, 13, 1.1, 10.6, 0, 1.1, 124), ("Whole-wheat toast", 60, 160, 7, 28, 2, 4, 3, 300)],
        [("Oats with milk & banana", 250, 310, 11, 52, 6, 6, 18, 110)],
    ],
    "lunch": [
        [("Steamed rice", 200, 260, 5, 57, 0.6, 0.8, 0.2, 2), ("Dal tadka", 180, 210, 11, 26, 7, 6, 2, 560),
         ("Mixed veg sabzi", 120, 110, 3, 12, 6, 4, 4, 320)],
        [("Chicken biryani", 300, 520, 26, 60, 18, 2.5, 3, 890), ("Raita", 100, 60, 3, 5, 3, 0.5, 4, 180)],
        [("Roti", 80, 240, 8, 46, 3, 6, 1, 360), ("Paneer butter masala", 180, 380, 14, 14, 30, 2, 6, 640)],
        [("Rajma", 180, 230, 12, 32, 5, 9, 2, 520), ("Steamed rice", 180, 235, 4.5, 51, 0.5, 0.7, 0.2, 2)],
    ],
    "snack": [
        [("Apple", 150, 78, 0.4, 21, 0.3, 3.6, 15, 1)],
        [("Samosa", 100, 310, 5, 32, 18, 2.5, 2, 420), ("Masala chai", 150, 90, 3, 12, 3.5, 0, 10, 40)],
        [("Roasted chana", 40, 150, 8, 24, 2.6, 7, 1, 10)],
        [("Greek yogurt", 150, 130, 15, 8, 4, 0, 6, 70)],
    ],
    "dinner": [
        [("Roti", 80, 240, 8, 46, 3, 6, 1, 360), ("Palak paneer", 180, 290, 13, 10, 22, 4, 3, 560)],
        [("Grilled chicken", 150, 250, 38, 0, 10, 0, 0, 380), ("Salad", 120, 40, 2, 8, 0.3, 3, 4, 30)],
        [("Vegetable khichdi", 300, 360, 12, 60, 8, 7, 3, 620)],
        [("Fish curry", 180, 280, 26, 8, 16, 1.5, 2, 720), ("Steamed rice", 150, 195, 4, 43, 0.4, 0.6, 0.2, 2)],
    ],
}
TIMES = {"breakfast": "08:30", "lunch": "13:15", "snack": "17:00", "dinner": "20:30"}
KEYS = ("name", "grams", "calories", "protein_g", "carbs_g", "fat_g", "fiber_g", "sugar_g", "sodium_mg")


def main():
    init_db()
    with get_db() as db:
        db.execute("DELETE FROM users WHERE email = ?", (EMAIL,))   # cascades to meals
    user_id = repository.create_user("Demo User", EMAIL, auth.hash_password(PASSWORD))
    repository.save_profile(user_id, Profile(sex="female", age=21, height_cm=162, weight_kg=58,
                                             activity_level="moderate", goal="maintain", diet_type="any"))
    today, count = date.today(), 0
    for back in range(27, -1, -1):
        day = today - timedelta(days=back)
        if random.random() < 0.12 and back:        # skip some days, like a real user
            continue
        for meal_type in ("breakfast", "lunch", "snack", "dinner"):
            if meal_type == "snack" and random.random() < 0.4:
                continue
            if back == 0 and meal_type in ("snack", "dinner") and datetime.now().hour < 17:
                continue
            factor = random.uniform(0.85, 1.2)
            items = [dict(zip(KEYS, (f[0], round(f[1] * factor), *[round(v * factor, 1) for v in f[2:]])))
                     for f in random.choice(FOODS[meal_type])]
            totals = sum_nutrients(items).model_dump()
            repository.save_meal(user_id, meal_type, f"{day.isoformat()}T{TIMES[meal_type]}", None, None, items, totals)
            count += 1
    print(f"Demo account ready: {EMAIL} / {PASSWORD}  ({count} meals)")


if __name__ == "__main__":
    main()
