import json
import logging
import sqlite3
from pathlib import Path

from remy import config

logger = logging.getLogger(__name__)


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recipes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                ingredients TEXT NOT NULL,
                recipe_text TEXT NOT NULL,
                rating      INTEGER,
                constraints TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pantry (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                item     TEXT NOT NULL UNIQUE,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)


# ── Settings (key/value) ──────────────────────────────────────────────────────

def set_setting(key: str, value: str) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_setting(key: str) -> str | None:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


def delete_setting(key: str) -> None:
    with _get_conn() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# ── Pantry staples ────────────────────────────────────────────────────────────
# Items the kitchen always has but the fridge camera can't see (rice, oil,
# canned goods). Merged with detected ingredients before the chef runs.

def add_pantry_item(item: str) -> bool:
    """Add a staple. Returns False if blank or already present (case-insensitive)."""
    normalized = item.strip().lower()
    if not normalized:
        return False
    with _get_conn() as conn:
        try:
            conn.execute("INSERT INTO pantry (item) VALUES (?)", (normalized,))
        except sqlite3.IntegrityError:
            return False
    logger.info("Added pantry item %r", normalized)
    return True


def remove_pantry_item(item: str) -> bool:
    """Remove a staple. Returns True if a row was deleted."""
    normalized = item.strip().lower()
    with _get_conn() as conn:
        cur = conn.execute("DELETE FROM pantry WHERE item = ?", (normalized,))
        return cur.rowcount > 0


def list_pantry_items() -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT item FROM pantry ORDER BY item").fetchall()
    return [r["item"] for r in rows]


def save_recipe(
    ingredients: list[str],
    recipe_text: str,
    constraints: str | None = None,
) -> int:
    with _get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO recipes (ingredients, recipe_text, constraints) VALUES (?, ?, ?)",
            (json.dumps(ingredients), recipe_text, constraints),
        )
        row_id = cur.lastrowid
    logger.info("Saved recipe id=%d", row_id)
    return row_id


def get_recent_recipes(n: int) -> list[str]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_text FROM recipes ORDER BY timestamp DESC LIMIT ?",
            (n,),
        ).fetchall()
    return [r["recipe_text"] for r in rows]


def get_top_rated_recipes(n: int, min_rating: int = 4) -> list[str]:
    """Highest-rated recipe texts (rating >= min_rating), best first.

    Unrated recipes (rating IS NULL) are excluded by the comparison.
    """
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_text FROM recipes WHERE rating >= ? "
            "ORDER BY rating DESC, timestamp DESC LIMIT ?",
            (min_rating, n),
        ).fetchall()
    return [r["recipe_text"] for r in rows]


def get_disliked_recipes(n: int, max_rating: int = 2) -> list[str]:
    """Lowest-rated recipe texts (rating <= max_rating), worst first."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT recipe_text FROM recipes WHERE rating IS NOT NULL AND rating <= ? "
            "ORDER BY rating ASC, timestamp DESC LIMIT ?",
            (max_rating, n),
        ).fetchall()
    return [r["recipe_text"] for r in rows]


def get_last_recipe() -> tuple[int, str] | None:
    """Returns (id, recipe_text) of the most recent recipe, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, recipe_text FROM recipes ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    return row["id"], row["recipe_text"]


def rate_recipe(recipe_id: int, rating: int) -> None:
    with _get_conn() as conn:
        conn.execute(
            "UPDATE recipes SET rating = ? WHERE id = ?",
            (rating, recipe_id),
        )
    logger.info("Rated recipe id=%d rating=%d", recipe_id, rating)


def query_ingredients_frequency() -> dict[str, int]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT ingredients FROM recipes").fetchall()
    freq: dict[str, int] = {}
    for row in rows:
        try:
            items = json.loads(row["ingredients"])
        except json.JSONDecodeError:
            continue
        for item in items:
            freq[item] = freq.get(item, 0) + 1
    return freq
