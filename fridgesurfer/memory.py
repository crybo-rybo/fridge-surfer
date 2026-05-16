import json
import logging
import sqlite3
from pathlib import Path

from fridgesurfer import config

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
