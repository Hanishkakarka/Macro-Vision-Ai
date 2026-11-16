"""Food recognition + macro estimation with Claude vision.

Flow: uploaded photo -> resize/normalise (Pillow) -> base64 -> Claude (structured output
validated against AIFoodAnalysis) -> items + totals.
"""

import base64
import io
import secrets
from pathlib import Path

import anthropic
from PIL import Image, ImageOps, UnidentifiedImageError

from backend import config
from backend.models import AIFoodAnalysis
from backend.services.nutrition_service import sum_nutrients

MAX_SIDE_PX = 1568          # Claude's recommended max image edge; larger only adds cost

SYSTEM_PROMPT = """You are MacroVision AI, a registered-dietitian-level food recognition system.
Look at the meal photo and identify every distinct food or drink item, including Indian dishes,
sides, sauces, chutneys and beverages. For each item estimate the edible portion in grams using
visual cues (plate size ~26 cm, bowls, cutlery, hands, packaging) and give nutrition for THAT
portion, based on standard food composition data (USDA / Indian Food Composition Tables).
Account for visible cooking oil, ghee and gravies. Be realistic, not optimistic.
If the image is not food, set is_food to false and return an empty items list.
Health notes must be short, specific to this meal, and non-judgemental."""

USER_PROMPT = "Identify the foods in this photo and estimate portion sizes and nutrition for each item."


class VisionError(Exception):
    """Raised with a user-friendly message when the photo can't be analysed."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


# ---------- Image handling ----------
def prepare_image(raw: bytes) -> tuple[bytes, str]:
    """Validate, auto-rotate, shrink and convert the upload to JPEG. Returns (jpeg_bytes, token)."""
    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img).convert("RGB")   # fix phone rotation, drop alpha
    except (UnidentifiedImageError, OSError):
        raise VisionError("That file isn't a readable image. Please upload a JPG, PNG or WEBP photo.", 400)
    img.thumbnail((MAX_SIDE_PX, MAX_SIDE_PX))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    token = secrets.token_hex(16)
    (config.UPLOAD_DIR / f"{token}.jpg").write_bytes(buf.getvalue())
    return buf.getvalue(), token


def image_path_for(token: str) -> Path:
    return config.UPLOAD_DIR / f"{token}.jpg"


# ---------- Claude call ----------
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()   # reads ANTHROPIC_API_KEY from the environment / .env
    return _client


def _ask_claude(jpeg: bytes) -> AIFoodAnalysis:
    image_b64 = base64.standard_b64encode(jpeg).decode("utf-8")
    try:
        response = _get_client().beta.messages.parse(
            model=config.CLAUDE_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",                       # retry on another model if a safety filter declines
            output_config={"effort": "medium"},
            output_format=AIFoodAnalysis,              # structured output, validated by Pydantic
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}},
                    {"type": "text", "text": USER_PROMPT},
                ],
            }],
        )
    except anthropic.AuthenticationError:
        raise VisionError("The AI service rejected the API key. Check ANTHROPIC_API_KEY in your .env file.", 503)
    except anthropic.RateLimitError:
        raise VisionError("The AI service is busy right now. Please try again in a minute.", 503)
    except anthropic.BadRequestError as e:
        raise VisionError(f"The AI service couldn't process this image ({e.message}).", 502)
    except anthropic.APIStatusError as e:
        raise VisionError(f"The AI service returned an error ({e.status_code}). Please try again.", 502)
    except anthropic.APIConnectionError:
        raise VisionError("Couldn't reach the AI service. Check your internet connection.", 503)

    if response.stop_reason == "refusal":
        raise VisionError("The AI couldn't analyse this image. Please try a different photo.", 422)
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise VisionError("The AI response was incomplete. Please try again.", 502)
    return response.parsed_output


def _demo_analysis() -> AIFoodAnalysis:
    """Sample result used in demo mode (no API key needed) and in tests."""
    return AIFoodAnalysis(
        is_food=True,
        meal_name="Masala dosa with sambar and coconut chutney",
        items=[
            {"name": "Masala dosa", "portion_description": "1 large dosa", "grams": 180, "calories": 370,
             "protein_g": 7.5, "carbs_g": 52, "fat_g": 14, "fiber_g": 4.2, "sugar_g": 2.5, "sodium_mg": 520,
             "confidence": "high"},
            {"name": "Sambar", "portion_description": "1 small bowl", "grams": 150, "calories": 125,
             "protein_g": 6, "carbs_g": 18, "fat_g": 3.5, "fiber_g": 5, "sugar_g": 4, "sodium_mg": 480,
             "confidence": "high"},
            {"name": "Coconut chutney", "portion_description": "2 tbsp", "grams": 40, "calories": 95,
             "protein_g": 1.2, "carbs_g": 3.5, "fat_g": 8.5, "fiber_g": 2, "sugar_g": 1.2, "sodium_mg": 130,
             "confidence": "medium"},
        ],
        health_notes=["Good fibre from the sambar lentils and vegetables.",
                      "Protein is modest; add curd or an egg to make it more filling."],
    )


def analyze_photo(raw: bytes) -> dict:
    """Public entry point used by the API route."""
    jpeg, token = prepare_image(raw)
    if config.DEMO_MODE:
        analysis, source = _demo_analysis(), "demo"
    else:
        if not config.has_claude_credentials():
            raise VisionError("AI is not configured: add your ANTHROPIC_API_KEY to the .env file "
                              "(or set MACROVISION_DEMO=1 to try the app with sample data).", 503)
        analysis, source = _ask_claude(jpeg), "claude"

    items = [i.model_dump() for i in analysis.items] if analysis.is_food else []
    return {
        "is_food": analysis.is_food and bool(items),
        "meal_name": analysis.meal_name,
        "items": items,
        "totals": sum_nutrients(items).model_dump(),
        "health_notes": analysis.health_notes,
        "image_token": token,
        "source": source,
    }
