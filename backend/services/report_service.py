"""Dashboard and weekly / monthly reports (all aggregation happens here, on the server)."""

import calendar
from datetime import date, datetime, timedelta

from backend.database import get_db
from backend.models import Targets
from backend.services.nutrition_service import NUTRIENT_KEYS, percent_of

MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")


# ---------- Periods ----------
def period_range(period: str, offset: int = 0, today: date | None = None) -> tuple[date, date]:
    """Week = Monday..Sunday, month = calendar month. offset -1 = previous period."""
    today = today or date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        return start, start + timedelta(days=6)
    year, month = today.year, today.month + offset
    while month < 1:
        year, month = year - 1, month + 12
    while month > 12:
        year, month = year + 1, month - 12
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


# ---------- Queries ----------
def daily_totals(user_id: int, start: date, end: date) -> dict[str, dict]:
    """{'2026-11-16': {calories:..., ..., meals: n}} for days that have meals."""
    sums = ", ".join(f"SUM({k}) AS {k}" for k in NUTRIENT_KEYS)
    with get_db() as db:
        rows = db.execute(
            f"""SELECT substr(eaten_at, 1, 10) AS day, COUNT(*) AS meals, {sums}
                FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) BETWEEN ? AND ?
                GROUP BY day ORDER BY day""",
            (user_id, start.isoformat(), end.isoformat())).fetchall()
    return {r["day"]: {**{k: round(r[k] or 0, 1) for k in NUTRIENT_KEYS}, "meals": r["meals"]} for r in rows}


def meals_between(user_id: int, start: date, end: date, limit: int | None = None) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            f"""SELECT * FROM meals WHERE user_id = ? AND substr(eaten_at, 1, 10) BETWEEN ? AND ?
                ORDER BY eaten_at DESC {'LIMIT ' + str(int(limit)) if limit else ''}""",
            (user_id, start.isoformat(), end.isoformat())).fetchall()
        meals = [dict(r) for r in rows]
        for m in meals:
            m["items"] = [dict(i) for i in db.execute(
                "SELECT name, grams, calories, protein_g, carbs_g, fat_g FROM meal_items WHERE meal_id = ?",
                (m["id"],)).fetchall()]
    return meals


def logging_streak(user_id: int, today: date | None = None) -> int:
    """Consecutive days (ending today, or yesterday if nothing logged yet today) with a meal."""
    today = today or date.today()
    days = set(daily_totals(user_id, today - timedelta(days=365), today))
    day = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while day.isoformat() in days:
        streak += 1
        day -= timedelta(days=1)
    return streak


# ---------- Dashboard ----------
def dashboard(user_id: int, targets: Targets, today: date | None = None) -> dict:
    today = today or date.today()
    today_totals = daily_totals(user_id, today, today).get(today.isoformat(), {k: 0 for k in NUTRIENT_KEYS})
    target_dict = targets.model_dump()
    progress = {k: {"value": today_totals.get(k, 0), "target": target_dict[k],
                    "percent": percent_of(today_totals.get(k, 0), target_dict[k]),
                    "remaining": round(max(target_dict[k] - today_totals.get(k, 0), 0), 1)}
                for k in NUTRIENT_KEYS}

    week_start = today - timedelta(days=6)
    totals = daily_totals(user_id, week_start, today)
    last7 = [{"date": (week_start + timedelta(days=i)).isoformat(),
              "label": (week_start + timedelta(days=i)).strftime("%a"),
              "calories": totals.get((week_start + timedelta(days=i)).isoformat(), {}).get("calories", 0)}
             for i in range(7)]

    cal = today_totals.get("calories", 0) or 0
    macro_split = _macro_split(today_totals.get("protein_g", 0), today_totals.get("carbs_g", 0),
                               today_totals.get("fat_g", 0))
    return {
        "date": today.isoformat(),
        "progress": progress,
        "calories_left": round(target_dict["calories"] - cal),
        "macro_split": macro_split,
        "last7": last7,
        "streak": logging_streak(user_id, today),
        "today_meals": meals_between(user_id, today, today),
    }


def _macro_split(protein_g: float, carbs_g: float, fat_g: float) -> dict:
    """Share of calories from protein / carbs / fat, in percent."""
    kcal = {"protein": protein_g * 4, "carbs": carbs_g * 4, "fat": fat_g * 9}
    total = sum(kcal.values())
    return {k: round(v / total * 100) if total else 0 for k, v in kcal.items()}


# ---------- Weekly / monthly report ----------
def report(user_id: int, targets: Targets, period: str = "week", offset: int = 0,
           today: date | None = None) -> dict:
    today = today or date.today()
    start, end = period_range(period, offset, today)
    last_day = min(end, today)                     # don't count future days
    elapsed_days = max((last_day - start).days + 1, 0)
    totals = daily_totals(user_id, start, end)
    logged = len(totals)
    t = targets.model_dump()

    sum_all = {k: round(sum(d[k] for d in totals.values()), 1) for k in NUTRIENT_KEYS}
    avg = {k: round(sum_all[k] / logged, 1) if logged else 0 for k in NUTRIENT_KEYS}

    def within(day, key, low, high):
        return low <= day[key] / t[key] <= high if t[key] else False

    on_target = sum(1 for d in totals.values() if within(d, "calories", 0.9, 1.1))
    protein_hit = sum(1 for d in totals.values() if d["protein_g"] >= 0.9 * t["protein_g"])

    days = []
    for i in range((end - start).days + 1):
        d = start + timedelta(days=i)
        row = totals.get(d.isoformat())
        days.append({"date": d.isoformat(), "label": d.strftime("%a %d") if period == "week" else d.strftime("%d"),
                     "future": d > today, **({k: row[k] for k in NUTRIENT_KEYS} if row else {k: 0 for k in NUTRIENT_KEYS})})

    with get_db() as db:
        top_foods = [dict(r) for r in db.execute(
            """SELECT mi.name, COUNT(*) AS times, ROUND(SUM(mi.calories)) AS calories
               FROM meal_items mi JOIN meals m ON m.id = mi.meal_id
               WHERE m.user_id = ? AND substr(m.eaten_at, 1, 10) BETWEEN ? AND ?
               GROUP BY lower(mi.name) ORDER BY times DESC, calories DESC LIMIT 5""",
            (user_id, start.isoformat(), end.isoformat())).fetchall()]
        meal_types = {r["meal_type"]: r["n"] for r in db.execute(
            """SELECT meal_type, COUNT(*) AS n FROM meals WHERE user_id = ?
               AND substr(eaten_at, 1, 10) BETWEEN ? AND ? GROUP BY meal_type""",
            (user_id, start.isoformat(), end.isoformat())).fetchall()}

    prev_start, prev_end = period_range(period, offset - 1, today)
    prev = daily_totals(user_id, prev_start, prev_end)
    prev_avg_cal = round(sum(d["calories"] for d in prev.values()) / len(prev)) if prev else None

    logged_days = [d for d in days if not d["future"] and d["calories"] > 0]
    best_protein = max(logged_days, key=lambda d: d["protein_g"], default=None)
    highest_cal = max(logged_days, key=lambda d: d["calories"], default=None)

    return {
        "period": period, "offset": offset,
        "start": start.isoformat(), "end": end.isoformat(),
        "title": (f"Week of {start.strftime('%d %b')} – {end.strftime('%d %b %Y')}" if period == "week"
                  else start.strftime("%B %Y")),
        "days_elapsed": elapsed_days, "days_logged": logged,
        "logging_rate": percent_of(logged, elapsed_days),
        "totals": sum_all, "averages": avg, "targets": t,
        "avg_percent_of_target": {k: percent_of(avg[k], t[k]) for k in NUTRIENT_KEYS},
        "on_target_days": on_target, "protein_goal_days": protein_hit,
        "adherence": percent_of(on_target, logged),
        "macro_split": _macro_split(avg["protein_g"], avg["carbs_g"], avg["fat_g"]),
        "meal_types": {m: meal_types.get(m, 0) for m in MEAL_TYPES},
        "top_foods": top_foods,
        "days": days,
        "previous_avg_calories": prev_avg_cal,
        "calorie_change": (round(avg["calories"] - prev_avg_cal) if prev_avg_cal and logged else None),
        "highlights": {
            "best_protein_day": best_protein and {"date": best_protein["date"], "protein_g": best_protein["protein_g"]},
            "highest_calorie_day": highest_cal and {"date": highest_cal["date"], "calories": highest_cal["calories"]},
        },
    }
