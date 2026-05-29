import sqlite3

from remy import config, memory


def _init():
    memory.init_db()


def _set_timestamp(recipe_id: int, timestamp: str) -> None:
    with sqlite3.connect(config.DB_PATH) as conn:
        conn.execute(
            "UPDATE recipes SET timestamp = ? WHERE id = ?",
            (timestamp, recipe_id),
        )


class TestSaveAndRetrieve:
    def test_save_recipe_returns_incrementing_ids(self):
        _init()
        id1 = memory.save_recipe(["milk"], "Recipe one")
        id2 = memory.save_recipe(["eggs"], "Recipe two")
        assert id1 == 1
        assert id2 == 2

    def test_get_last_recipe_returns_most_recent(self):
        _init()
        memory.save_recipe(["a"], "First")
        id2 = memory.save_recipe(["b"], "Second")
        _set_timestamp(1, "2020-01-01 00:00:00")
        _set_timestamp(id2, "2020-01-02 00:00:00")
        result = memory.get_last_recipe()
        assert result == (2, "Second")

    def test_get_last_recipe_empty_db(self):
        _init()
        assert memory.get_last_recipe() is None

    def test_get_recent_recipes_respects_limit_and_order(self):
        _init()
        memory.save_recipe(["a"], "One")
        id2 = memory.save_recipe(["b"], "Two")
        id3 = memory.save_recipe(["c"], "Three")
        _set_timestamp(1, "2020-01-01 00:00:00")
        _set_timestamp(id2, "2020-01-02 00:00:00")
        _set_timestamp(id3, "2020-01-03 00:00:00")
        recent = memory.get_recent_recipes(2)
        assert recent == ["Three", "Two"]


class TestRateRecipe:
    def test_rate_recipe_persists(self):
        _init()
        recipe_id = memory.save_recipe(["milk"], "Recipe")
        memory.rate_recipe(recipe_id, 4)
        with sqlite3.connect(config.DB_PATH) as conn:
            row = conn.execute(
                "SELECT rating FROM recipes WHERE id = ?",
                (recipe_id,),
            ).fetchone()
        assert row[0] == 4


class TestQueryIngredientsFrequency:
    def test_aggregates_ingredients(self):
        _init()
        memory.save_recipe(["milk", "eggs"], "A")
        memory.save_recipe(["milk", "cheese"], "B")
        freq = memory.query_ingredients_frequency()
        assert freq == {"milk": 2, "eggs": 1, "cheese": 1}

    def test_skips_corrupt_json(self):
        _init()
        memory.save_recipe(["ok"], "Good")
        with sqlite3.connect(config.DB_PATH) as conn:
            conn.execute(
                "INSERT INTO recipes (ingredients, recipe_text) VALUES (?, ?)",
                ("not-json", "Bad row"),
            )
        freq = memory.query_ingredients_frequency()
        assert freq == {"ok": 1}
