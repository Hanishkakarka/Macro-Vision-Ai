"""Data access: users, profiles and meals (all SQL lives here or in report_service)."""

import sqlite3
from datetime import datetime

from backend import config
from backend.database import get_db
from backend.models import Profile


# ---------- Users ----------
def create_user(name: str, email: str, password_hash: str) -> int:
    with get_db() as db:
        try:
            cur = db.execute("INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
                             (name.strip(), email.lower(), password_hash))
        except sqlite3.IntegrityError:
            raise ValueError("An account with this email already exists")
        db.execute("INSERT INTO profiles (user_id) VALUES (?)", (cur.lastrowid,))
        return cur.lastrowid


def find_user_by_email(email: str):
    with get_db() as db:
        return db.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()


# ---------- Profiles ----------
def get_profile(user_id: int) -> Profile:
    with get_db() as db:
        row = db.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    return Profile(**{k: row[k] for k in Profile.model_fields}) if row else Profile()


def save_profile(user_id: int, p: Profile) -> None:
    fields = list(Profile.model_fields)
    with get_db() as db:
        db.execute(
            f"INSERT OR REPLACE INTO profiles (user_id, {', '.join(fields)}) VALUES (?, {', '.join('?' * len(fields))})",
            (user_id, *[getattr(p, f) for f in fields]))


# ---------- Meals ----------
def save_meal(user_id: int, meal_type: str, eaten_at: str | None, note: str | None,
              image_token: str | None, items: list[dict], totals: dict) -> int:
    eaten = eaten_at or datetime.now().isoformat(timespec="minutes")
    image_path = None
    if image_token and (config.UPLOAD_DIR / f"{image_token}.jpg").exists():
        image_path = f"{image_token}.jpg"
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO meals (user_id, meal_type, eaten_at, image_path, note,
               calories, protein_g, carbs_g, fat_g, fiber_g, sugar_g, sodium_mg)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, meal_type, eaten, image_path, note, totals["calories"], totals["protein_g"],
             totals["carbs_g"], totals["fat_g"], totals["fiber_g"], totals["sugar_g"], totals["sodium_mg"]))
        meal_id = cur.lastrowid
        db.executemany(
            """INSERT INTO meal_items (meal_id, name, grams, calories, protein_g, carbs_g, fat_g,
               fiber_g, sugar_g, sodium_mg) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(meal_id, i["name"], i["grams"], i["calories"], i["protein_g"], i["carbs_g"], i["fat_g"],
              i["fiber_g"], i["sugar_g"], i["sodium_mg"]) for i in items])
        return meal_id


def delete_meal(user_id: int, meal_id: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT image_path FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id)).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM meals WHERE id = ? AND user_id = ?", (meal_id, user_id))
    if row["image_path"]:
        (config.UPLOAD_DIR / row["image_path"]).unlink(missing_ok=True)
    return True


def can_view_image(user_id: int, filename: str) -> bool:
    """A saved meal photo is visible only to its owner. A fresh upload that isn't saved yet
    is reachable only through its random 128-bit token (shown to the uploader during review)."""
    with get_db() as db:
        owner = db.execute("SELECT user_id FROM meals WHERE image_path = ?", (filename,)).fetchone()
    return owner is None or owner["user_id"] == user_id
