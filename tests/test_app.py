"""API + logic tests (run in demo mode with a throwaway database).   Run:  python -m pytest -q"""

import io
import os
import tempfile
from datetime import date, timedelta

os.environ["MACROVISION_DEMO"] = "1"
os.environ["MACROVISION_DATA_DIR"] = tempfile.mkdtemp(prefix="mv-test-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from backend import auth  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import ItemInput, Profile  # noqa: E402
from backend.services import nutrition_service, report_service, suggestion_service, vision_service  # noqa: E402


def jpeg_bytes(size=(640, 480)):
    buf = io.BytesIO()
    Image.new("RGB", size, (210, 140, 60)).save(buf, "JPEG")
    return buf.getvalue()


def new_client(email):
    c = TestClient(app)
    c.__enter__()
    r = c.post("/api/auth/signup", json={"name": "Tester", "email": email, "password": "secret12"})
    assert r.status_code == 201
    return c


def analysed_items(client):
    a = client.post("/api/analyze", files={"photo": ("plate.jpg", jpeg_bytes(), "image/jpeg")}).json()
    items = [{**{k: i[k] for k in ("name", "grams", "calories", "protein_g", "carbs_g", "fat_g",
                                    "fiber_g", "sugar_g", "sodium_mg")}, "base_grams": i["grams"]} for i in a["items"]]
    return a, items


# ---------- Auth ----------
def test_password_hashing_roundtrip():
    h = auth.hash_password("hunter22")
    assert h != "hunter22" and auth.verify_password("hunter22", h) and not auth.verify_password("wrong", h)


def test_signup_login_logout_flow():
    c = new_client("flow@example.com")
    assert c.get("/api/me").status_code == 200
    assert c.post("/api/auth/signup", json={"name": "X", "email": "flow@example.com", "password": "secret12"}).status_code == 409
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401
    assert c.post("/api/auth/login", json={"email": "flow@example.com", "password": "nope123"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "FLOW@example.com", "password": "secret12"}).status_code == 200


def test_protected_routes_need_login():
    with TestClient(app) as c:
        for path in ("/api/dashboard", "/api/reports/week", "/api/meals"):
            assert c.get(path).status_code == 401


# ---------- Nutrition maths ----------
def test_targets_mifflin_st_jeor():
    t = nutrition_service.compute_targets(Profile(sex="male", age=25, height_cm=175, weight_kg=70,
                                                   activity_level="moderate", goal="maintain"))
    bmr = 10 * 70 + 6.25 * 175 - 5 * 25 + 5                            # 1673.75
    assert t.bmr == round(bmr) and t.tdee == round(bmr * 1.55)          # TDEE uses the unrounded BMR
    assert t.protein_g == 84                                           # 1.2 g/kg


def test_lose_goal_never_below_safe_floor():
    t = nutrition_service.compute_targets(Profile(sex="female", age=60, height_cm=150, weight_kg=40,
                                                   activity_level="sedentary", goal="lose"))
    assert t.calories == 1200


def test_scale_item_proportionally():
    item = ItemInput(name="Rice", grams=300, base_grams=150, calories=195, protein_g=4, carbs_g=43,
                     fat_g=0.4, fiber_g=0.6, sugar_g=0.2, sodium_mg=2)
    scaled = nutrition_service.scale_item(item)
    assert scaled["calories"] == 390 and scaled["carbs_g"] == 86


# ---------- Analysis & meals ----------
def test_analyze_rejects_non_images():
    c = new_client("files@example.com")
    assert c.post("/api/analyze", files={"photo": ("a.txt", b"hello", "text/plain")}).status_code == 400
    assert c.post("/api/analyze", files={"photo": ("a.jpg", b"not really a jpeg", "image/jpeg")}).status_code == 400


def test_analyze_resizes_large_images():
    jpeg, token = vision_service.prepare_image(jpeg_bytes((4000, 3000)))
    assert max(Image.open(io.BytesIO(jpeg)).size) <= vision_service.MAX_SIDE_PX
    assert vision_service.image_path_for(token).exists()


def test_preview_and_save_meal_use_server_scaling():
    c = new_client("meal@example.com")
    a, items = analysed_items(c)
    assert a["is_food"] and a["source"] == "demo" and a["totals"]["calories"] == 590
    items[0]["grams"] *= 2                                              # double the dosa
    preview = c.post("/api/meals/preview", json={"items": items}).json()
    assert preview["totals"]["calories"] == 960
    saved = c.post("/api/meals", json={"meal_type": "breakfast", "items": items, "image_token": a["image_token"]})
    assert saved.status_code == 201 and saved.json()["totals"]["calories"] == 960
    meals = c.get("/api/meals?days=1").json()["meals"]
    assert len(meals) == 1 and len(meals[0]["items"]) == 3


def test_save_meal_validation():
    c = new_client("valid@example.com")
    _, items = analysed_items(c)
    assert c.post("/api/meals", json={"meal_type": "brunch", "items": items}).status_code == 422
    assert c.post("/api/meals", json={"meal_type": "lunch", "items": []}).status_code == 422
    bad = [{**items[0], "grams": -5}]
    assert c.post("/api/meals", json={"meal_type": "lunch", "items": bad}).status_code == 422
    assert c.post("/api/meals", json={"meal_type": "lunch", "items": items, "eaten_at": "yesterday"}).status_code == 400


def test_users_cannot_see_or_delete_each_others_meals():
    alice, bob = new_client("alice@example.com"), new_client("bob@example.com")
    a, items = analysed_items(alice)
    meal_id = alice.post("/api/meals", json={"meal_type": "lunch", "items": items,
                                             "image_token": a["image_token"]}).json()["id"]
    image = alice.get("/api/meals").json()["meals"][0]["image_path"]
    assert alice.get(f"/api/images/{image}").status_code == 200
    assert bob.get(f"/api/images/{image}").status_code == 404
    assert bob.delete(f"/api/meals/{meal_id}").status_code == 404
    assert bob.get("/api/meals").json()["meals"] == []
    assert alice.delete(f"/api/meals/{meal_id}").status_code == 200


# ---------- Reports & suggestions ----------
def test_period_ranges():
    monday = date(2026, 11, 16)
    assert report_service.period_range("week", 0, monday + timedelta(days=3)) == (monday, monday + timedelta(days=6))
    assert report_service.period_range("month", -1, monday) == (date(2026, 10, 1), date(2026, 10, 31))
    assert report_service.period_range("month", -11, monday) == (date(2025, 12, 1), date(2025, 12, 31))


def test_dashboard_and_reports_reflect_logged_meals():
    c = new_client("report@example.com")
    _, items = analysed_items(c)
    c.post("/api/meals", json={"meal_type": "breakfast", "items": items})
    d = c.get("/api/dashboard").json()
    assert d["progress"]["calories"]["value"] == 590 and d["streak"] == 1 and len(d["last7"]) == 7
    for period in ("week", "month"):
        r = c.get(f"/api/reports/{period}").json()
        assert r["days_logged"] == 1 and r["averages"]["calories"] == 590
        assert r["top_foods"][0]["times"] == 1 and r["suggestions"]
    assert c.get("/api/reports/year").status_code == 404


def test_rule_based_suggestions():
    profile = Profile(diet_type="vegetarian")
    base = {"days_logged": 5, "days_elapsed": 7, "logging_rate": 71, "adherence": 20, "on_target_days": 1,
            "targets": {"calories": 2000, "protein_g": 80, "fiber_g": 28},
            "averages": {"calories": 2500, "protein_g": 40, "fiber_g": 10},
            "avg_percent_of_target": {"calories": 125, "protein_g": 50, "fiber_g": 36, "sugar_g": 150, "sodium_mg": 90},
            "macro_split": {"protein": 10, "carbs": 50, "fat": 40}, "meal_types": {"breakfast": 1}}
    titles = [t["title"] for t in suggestion_service.rule_based(base, profile)]
    assert "Calories above target" in titles and "Boost your protein" in titles and "Watch the sugar" in titles
    protein_tip = next(t for t in suggestion_service.rule_based(base, profile) if t["title"] == "Boost your protein")
    assert "paneer" in protein_tip["text"]                              # diet-aware food ideas
    assert suggestion_service.rule_based({"days_logged": 0}, profile)[0]["title"] == "Start logging"


def test_ai_coach_unavailable_in_demo_mode():
    c = new_client("coach@example.com")
    _, items = analysed_items(c)
    c.post("/api/meals", json={"meal_type": "lunch", "items": items})
    r = c.post("/api/reports/week/ai-coach")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_vision_errors_are_friendly(monkeypatch):
    """A refusal or missing parse from Claude becomes a clear VisionError, never a crash."""
    class FakeResponse:
        stop_reason, parsed_output = "refusal", None

    class FakeClient:
        class beta:
            class messages:
                @staticmethod
                def parse(**kwargs):
                    assert kwargs["model"] and kwargs["output_format"].__name__ == "AIFoodAnalysis"
                    return FakeResponse()

    monkeypatch.setattr(vision_service, "_get_client", lambda: FakeClient())
    with pytest.raises(vision_service.VisionError) as e:
        vision_service._ask_claude(jpeg_bytes())
    assert e.value.status_code == 422
