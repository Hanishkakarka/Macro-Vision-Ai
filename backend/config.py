"""App settings, read from environment variables (and an optional .env file)."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Claude model used for food recognition and the AI coach.
CLAUDE_MODEL = os.getenv("MACROVISION_MODEL", "claude-opus-5-5")

# Demo mode returns a sample analysis instead of calling Claude (for tests / offline demos).
DEMO_MODE = os.getenv("MACROVISION_DEMO", "0") == "1"

DATA_DIR = Path(os.getenv("MACROVISION_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "macrovision.db"
UPLOAD_DIR = DATA_DIR / "uploads"

MAX_UPLOAD_MB = 10
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
SESSION_DAYS = 14
COOKIE_NAME = "mv_session"


def has_claude_credentials() -> bool:
    """True if the Anthropic SDK can find credentials (API key or auth token)."""
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))
