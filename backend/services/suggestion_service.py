"""Personalised suggestions: rule-based (instant, free) + optional AI coach (Claude)."""

import json

import anthropic
from pydantic import BaseModel, Field

from backend import config
from backend.models import Profile

PROTEIN_FOODS = {
    "vegan": "tofu, soya chunks, chana, rajma, moong dal, peanuts",
    "vegetarian": "paneer, curd / Greek yogurt, dal, chana, rajma, milk, soya chunks",
    "eggetarian": "eggs, paneer, curd, dal, chana",
    "non_vegetarian": "eggs, chicken breast, fish, curd, dal",
    "any": "eggs, paneer, curd, dal, chicken or fish",
}
FIBRE_FOODS = "fruit with skin, salads, sprouts, oats, whole-wheat roti, brown rice, dal and vegetables"


def _tip(kind: str, icon: str, title: str, text: str) -> dict:
    return {"kind": kind, "icon": icon, "title": title, "text": text}


def rule_based(report: dict, profile: Profile) -> list[dict]:
    """Turn a report into a short list of practical suggestions (good / warn / tip)."""
    tips: list[dict] = []
    if report["days_logged"] == 0:
        return [_tip("tip", "📸", "Start logging", "Snap a photo of your next meal to start getting personalised insights.")]

    pct = report["avg_percent_of_target"]
    avg, tgt = report["averages"], report["targets"]

    # Calories vs goal
    if pct["calories"] > 110:
        over = round(avg["calories"] - tgt["calories"])
        tips.append(_tip("warn", "🔥", "Calories above target",
                         f"You averaged {over} kcal/day over your {round(tgt['calories'])} kcal target. "
                         "Try smaller rice/roti portions, less oil or ghee, and swap fried snacks for fruit or roasted chana."))
    elif pct["calories"] < 85:
        under = round(tgt["calories"] - avg["calories"])
        msg = ("Eating too little can slow your metabolism and cost muscle. " if profile.goal != "gain"
               else "To gain weight you need a consistent surplus. ")
        tips.append(_tip("warn", "⚡", "Calories below target",
                         f"You averaged {under} kcal/day below target. {msg}Add a balanced snack such as nuts, curd or a banana."))
    else:
        tips.append(_tip("good", "🎯", "Calories on track",
                         f"Your average intake is within {abs(pct['calories'] - 100)}% of your target. Keep it up!"))

    # Protein
    if pct["protein_g"] < 80:
        tips.append(_tip("warn", "💪", "Boost your protein",
                         f"Protein averaged {round(avg['protein_g'])} g vs {round(tgt['protein_g'])} g. "
                         f"Add a protein source to each meal: {PROTEIN_FOODS[profile.diet_type]}."))
    elif pct["protein_g"] >= 95:
        tips.append(_tip("good", "💪", "Great protein intake", "You're meeting your protein goal, which helps muscle and keeps you full."))

    # Fibre, sugar, sodium, fat
    if pct["fiber_g"] < 70:
        tips.append(_tip("tip", "🥗", "Add more fibre",
                         f"Fibre averaged {round(avg['fiber_g'])} g (target {round(tgt['fiber_g'])} g). Try {FIBRE_FOODS}."))
    if pct["sugar_g"] > 110:
        tips.append(_tip("warn", "🍬", "Watch the sugar",
                         "Sugar is above the recommended limit. Cut back on sweets, sweetened chai/coffee and packaged juices."))
    if pct["sodium_mg"] > 110:
        tips.append(_tip("warn", "🧂", "High sodium",
                         "Sodium is high. Pickles, papad, namkeen and instant noodles are common sources; go easy on them."))
    if report["macro_split"]["fat"] > 38:
        tips.append(_tip("tip", "🫒", "Fat-heavy meals",
                         f"{report['macro_split']['fat']}% of your calories come from fat. Use less oil and prefer grilled or steamed dishes."))

    # Habits
    if report["days_elapsed"] >= 3 and report["logging_rate"] < 60:
        tips.append(_tip("tip", "📅", "Log more consistently",
                         f"You logged {report['days_logged']} of {report['days_elapsed']} days. Consistent tracking gives more accurate insights."))
    if report["meal_types"].get("breakfast", 0) < report["days_logged"] / 2:
        tips.append(_tip("tip", "🌅", "Don't skip breakfast",
                         "Breakfast was missing on most days. A protein-rich breakfast (eggs, poha with peanuts, besan chilla) helps control cravings."))
    if report["adherence"] >= 70:
        tips.append(_tip("good", "🏆", "Consistent days",
                         f"{report['on_target_days']} of your logged days were on target. Excellent consistency!"))
    return tips[:7]


# ---------- AI coach ----------
class CoachTip(BaseModel):
    title: str = Field(description="3-6 word headline")
    advice: str = Field(description="1-2 sentences of specific, practical advice")


class CoachResponse(BaseModel):
    summary: str = Field(description="2-3 sentence friendly overview of the period")
    tips: list[CoachTip] = Field(description="3-5 prioritised, personalised suggestions")


COACH_SYSTEM = """You are a supportive nutrition coach inside the MacroVision AI app.
You get a JSON summary of a user's food log for one period, their targets and profile.
Give practical, culturally relevant (Indian context welcome) advice tied to their actual numbers.
Never give medical diagnoses; suggest seeing a doctor or dietitian for medical conditions."""


def ai_coach(report: dict, profile: Profile) -> dict:
    if not config.has_claude_credentials() or config.DEMO_MODE:
        raise RuntimeError("AI coach needs an ANTHROPIC_API_KEY (demo mode only has rule-based tips).")
    summary = {k: report[k] for k in ("title", "days_elapsed", "days_logged", "averages", "targets",
                                     "avg_percent_of_target", "macro_split", "meal_types", "top_foods",
                                     "adherence", "calorie_change")}
    response = anthropic.Anthropic().beta.messages.parse(
        model=config.CLAUDE_MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        output_config={"effort": "low"},
        output_format=CoachResponse,
        system=COACH_SYSTEM,
        messages=[{"role": "user", "content":
                   "Profile: " + profile.model_dump_json() + "\nReport: " + json.dumps(summary)}],
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError("The AI coach couldn't generate advice this time. Please try again.")
    return response.parsed_output.model_dump()
