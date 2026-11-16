"""MacroVision AI: FastAPI application (REST API + serves the web app).

Run:  uvicorn backend.main:app --reload
"""

import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend import auth, config, repository
from backend.database import init_db
from backend.models import LoginRequest, PreviewRequest, Profile, SaveMealRequest, SignupRequest
from backend.services import nutrition_service, report_service, suggestion_service, vision_service

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="MacroVision AI", version="1.0.0",
              description="AI-powered food recognition and macro estimation", lifespan=lifespan)

CurrentUser = Depends(auth.current_user)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(config.COOKIE_NAME, token, httponly=True, samesite="lax",
                        max_age=config.SESSION_DAYS * 86400)


# ---------- Auth ----------
@app.post("/api/auth/signup", status_code=201)
def signup(body: SignupRequest, response: Response):
    try:
        user_id = repository.create_user(body.name, body.email, auth.hash_password(body.password))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    _set_cookie(response, auth.create_session(user_id))
    return {"id": user_id, "name": body.name.strip(), "email": body.email.lower()}


@app.post("/api/auth/login")
def login(body: LoginRequest, response: Response):
    user = repository.find_user_by_email(body.email)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    _set_cookie(response, auth.create_session(user["id"]))
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(config.COOKIE_NAME)
    if token:
        auth.delete_session(token)
    response.delete_cookie(config.COOKIE_NAME)
    return {"ok": True}


@app.get("/api/me")
def me(user=CurrentUser):
    profile = repository.get_profile(user["id"])
    return {"user": user, "profile": profile, "targets": nutrition_service.compute_targets(profile),
            "ai_ready": config.DEMO_MODE or config.has_claude_credentials(), "demo_mode": config.DEMO_MODE}


# ---------- Profile & goals ----------
@app.put("/api/profile")
def update_profile(body: Profile, user=CurrentUser):
    repository.save_profile(user["id"], body)
    return {"profile": body, "targets": nutrition_service.compute_targets(body)}


# ---------- Food recognition ----------
@app.post("/api/analyze")
async def analyze(photo: UploadFile = File(...), user=CurrentUser):
    if photo.content_type not in config.ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Please upload a JPG, PNG or WEBP image")
    raw = await photo.read()
    if len(raw) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"Image is larger than {config.MAX_UPLOAD_MB} MB")
    try:
        return vision_service.analyze_photo(raw)
    except vision_service.VisionError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@app.post("/api/meals/preview")
def preview_meal(body: PreviewRequest, user=CurrentUser):
    """Re-calculate nutrients when the user edits portion sizes (scaling done on the server)."""
    items = [nutrition_service.scale_item(i) for i in body.items]
    return {"items": items, "totals": nutrition_service.sum_nutrients(items)}


# ---------- Meals ----------
@app.post("/api/meals", status_code=201)
def save_meal(body: SaveMealRequest, user=CurrentUser):
    if body.eaten_at and not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", body.eaten_at):
        raise HTTPException(status_code=400, detail="eaten_at must look like 2026-11-16T13:30")
    items = [nutrition_service.scale_item(i) for i in body.items]
    totals = nutrition_service.sum_nutrients(items).model_dump()
    meal_id = repository.save_meal(user["id"], body.meal_type, body.eaten_at, body.note,
                                   body.image_token, items, totals)
    return {"id": meal_id, "totals": totals}


@app.get("/api/meals")
def list_meals(days: int = Query(30, ge=1, le=366), user=CurrentUser):
    today = date.today()
    return {"meals": report_service.meals_between(user["id"], today - timedelta(days=days - 1), today)}


@app.delete("/api/meals/{meal_id}")
def delete_meal(meal_id: int, user=CurrentUser):
    if not repository.delete_meal(user["id"], meal_id):
        raise HTTPException(status_code=404, detail="Meal not found")
    return {"ok": True}


@app.get("/api/images/{filename}")
def meal_image(filename: str, user=CurrentUser):
    if not re.fullmatch(r"[a-f0-9]{32}\.jpg", filename):
        raise HTTPException(status_code=404, detail="Image not found")
    path = config.UPLOAD_DIR / filename
    if not path.exists() or not repository.can_view_image(user["id"], filename):
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(path, media_type="image/jpeg")


# ---------- Dashboard, reports, suggestions ----------
@app.get("/api/dashboard")
def get_dashboard(user=CurrentUser):
    profile = repository.get_profile(user["id"])
    targets = nutrition_service.compute_targets(profile)
    data = report_service.dashboard(user["id"], targets)
    week = report_service.report(user["id"], targets, "week", 0)
    data["suggestions"] = suggestion_service.rule_based(week, profile)[:3]
    data["targets"] = targets
    return data


@app.get("/api/reports/{period}")
def get_report(period: str, offset: int = Query(0, ge=-24, le=0), user=CurrentUser):
    if period not in ("week", "month"):
        raise HTTPException(status_code=404, detail="Report period must be 'week' or 'month'")
    profile = repository.get_profile(user["id"])
    data = report_service.report(user["id"], nutrition_service.compute_targets(profile), period, offset)
    data["suggestions"] = suggestion_service.rule_based(data, profile)
    return data


@app.post("/api/reports/{period}/ai-coach")
def get_ai_coach(period: str, offset: int = Query(0, ge=-24, le=0), user=CurrentUser):
    if period not in ("week", "month"):
        raise HTTPException(status_code=404, detail="Report period must be 'week' or 'month'")
    profile = repository.get_profile(user["id"])
    data = report_service.report(user["id"], nutrition_service.compute_targets(profile), period, offset)
    if data["days_logged"] == 0:
        raise HTTPException(status_code=400, detail="Log a few meals first so the coach has data to work with")
    try:
        return suggestion_service.ai_coach(data, profile)
    except Exception as e:   # surface a friendly message instead of a 500
        raise HTTPException(status_code=503, detail=str(e) if isinstance(e, RuntimeError)
                            else "The AI coach is unavailable right now. Please try again.")


# ---------- Frontend ----------
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(FRONTEND_DIR / "index.html")
