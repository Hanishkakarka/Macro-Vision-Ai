"""SQLite database: connection helper and schema."""

import sqlite3
from contextlib import contextmanager

from backend import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id        INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    sex            TEXT NOT NULL DEFAULT 'female',
    age            INTEGER NOT NULL DEFAULT 21,
    height_cm      REAL NOT NULL DEFAULT 160,
    weight_kg      REAL NOT NULL DEFAULT 55,
    activity_level TEXT NOT NULL DEFAULT 'moderate',
    goal           TEXT NOT NULL DEFAULT 'maintain',
    diet_type      TEXT NOT NULL DEFAULT 'any'
);

CREATE TABLE IF NOT EXISTS meals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    meal_type  TEXT NOT NULL,
    eaten_at   TEXT NOT NULL,          -- ISO date-time (local)
    image_path TEXT,
    note       TEXT,
    calories   REAL NOT NULL, protein_g REAL NOT NULL, carbs_g REAL NOT NULL,
    fat_g      REAL NOT NULL, fiber_g REAL NOT NULL, sugar_g REAL NOT NULL, sodium_mg REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meal_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id    INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    grams      REAL NOT NULL,
    calories   REAL NOT NULL, protein_g REAL NOT NULL, carbs_g REAL NOT NULL,
    fat_g      REAL NOT NULL, fiber_g REAL NOT NULL, sugar_g REAL NOT NULL, sodium_mg REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_meals_user_time ON meals(user_id, eaten_at);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    """Open a connection, commit on success, roll back on error, always close."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    with get_db() as conn:
        conn.executescript(SCHEMA)
