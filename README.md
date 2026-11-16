# 🥗 MacroVision AI
**AI-powered food recognition and macro estimation system**

Take or upload a photo of your meal. MacroVision AI recognises each food, estimates the portion size and calculates **calories, protein, carbs, fat, fibre, sugar and sodium**. Every meal is saved to your personal log, which powers a **daily dashboard**, **weekly & monthly reports** and **personalised suggestions**, including an optional AI nutrition coach.

---

## ✨ Features
| Area | What it does |
|---|---|
| 📸 **Food recognition** | Upload or snap a photo → Claude vision identifies every item on the plate (Indian dishes included), with a confidence level |
| ⚖️ **Macro estimation** | Estimates grams per item and its calories, protein, carbs, fat, fibre, sugar and sodium; the user can correct portions and the server re-scales the nutrients |
| 👤 **Accounts** | Sign up / log in, each user sees only their own meals and photos |
| 🎯 **Goals** | Profile (age, sex, height, weight, activity, goal, diet) → daily targets via the Mifflin-St Jeor equation |
| 🏠 **Dashboard** | Calorie ring, macro progress bars, logging streak, 7-day calorie chart, today's macro split, today's meals, top suggestions |
| 📊 **Reports** | Weekly and monthly: averages vs targets, days logged, on-target days, change vs previous period, daily calorie and macro charts, top foods, meal-type breakdown, print / save as PDF |
| 💡 **Suggestions** | Rule-based tips (instant, free, diet-aware) + **AI coach** that reviews the whole period with Claude |
| 🍽️ **Meal log** | History grouped by day with photos, delete meals |
| 📱 **Mobile-friendly** | Responsive layout with bottom navigation and camera capture on phones; light and dark themes |

## 🏗️ Architecture
```
 Browser (frontend/)                         FastAPI server (backend/)
 index.html · styles.css · app.js            main.py ─────── REST API, auth, validation
  ├─ photo upload  ── POST /api/analyze ──►    services/vision_service.py ──► Claude vision (structured JSON)
  ├─ edit grams    ── POST /api/meals/preview  services/nutrition_service.py (targets, scaling, totals)
  ├─ save meal     ── POST /api/meals          repository.py ──► SQLite (data/macrovision.db)
  ├─ dashboard     ── GET  /api/dashboard      services/report_service.py (daily / weekly / monthly aggregates)
  └─ reports       ── GET  /api/reports/{week|month}, POST …/ai-coach   services/suggestion_service.py
```
**All business logic runs on the server.** The browser only displays results and sends user actions.

### How food recognition works
1. The photo is validated, auto-rotated, resized to ≤1568 px and converted to JPEG (Pillow), which keeps cost and latency low.
2. It's sent to **Claude (`claude-opus-5-5`)** with a dietitian-style prompt and a **structured output schema** (`AIFoodAnalysis` in `backend/models.py`), so the reply is always valid JSON: items, grams, nutrients, confidence and health notes.
3. Refusals, rate limits, bad keys and network errors are turned into friendly messages. Server-side fallback (`fallbacks: "default"`) retries on another model if a safety filter declines.
4. The user reviews and edits portions, and the server scales nutrients (`value × new_grams / original_grams`) before saving.

### Daily targets
`BMR = 10·weight + 6.25·height − 5·age + (5 male / −161 female)` → `TDEE = BMR × activity factor` → goal adjustment (−500 lose, +300 gain, never below 1200/1500 kcal). Protein 1.2–1.7 g/kg, fat 27% of calories, carbs = the rest, fibre 14 g per 1000 kcal, sugar ≤10% of calories, sodium ≤2300 mg.

## 🚀 Setup & run
```bash
python -m venv .venv
.\.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env              # macOS/Linux: cp .env.example .env
```
Edit `.env`: paste your key from https://console.anthropic.com into `ANTHROPIC_API_KEY=` and set `MACROVISION_DEMO=0`.
> No key yet? Keep `MACROVISION_DEMO=1`: photo analysis returns a sample meal so you can try the whole app.

```bash
uvicorn backend.main:app --reload
```
Open **http://127.0.0.1:8000** · API docs: http://127.0.0.1:8000/docs

**Demo data for presentations** (4 weeks of meals):
```bash
python -m scripts.seed_demo        # login: demo@macrovision.ai / demo1234
```

## 🧪 Tests
```bash
python -m pytest -q
```
16 tests cover auth, password hashing, target maths, portion scaling, image validation and resizing, meal saving and validation, privacy between users, report periods, dashboard and report numbers, suggestions, and AI error handling.

## 📁 Project structure
```
backend/
  main.py                    # FastAPI routes
  config.py                  # settings (.env)
  database.py                # SQLite schema & connection
  auth.py                    # PBKDF2 password hashing + cookie sessions
  models.py                  # Pydantic models (API + AI output schema)
  repository.py              # users, profiles, meals (SQL)
  services/
    vision_service.py        # ⭐ Claude food recognition
    nutrition_service.py     # targets, scaling, totals
    report_service.py        # dashboard, weekly / monthly reports
    suggestion_service.py    # rule-based tips + AI coach
frontend/  index.html · styles.css · app.js
scripts/seed_demo.py         # demo account with sample data
tests/test_app.py
```

## ⚠️ Limitations
- Portion sizes from a single 2D photo are **estimates** (typically ±15–25%); users can correct them before saving.
- Hidden ingredients (oil, sugar, ghee inside the dish) can't always be seen.
- Nutrition guidance is general and **not medical advice**.

## 🔭 Future work
Barcode scanning, water and exercise tracking, reminders and notifications, multi-photo meals, a native mobile app, and export to CSV.
