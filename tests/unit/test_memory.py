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


class TestRatedRecipes:
    def test_top_rated_orders_by_rating_and_excludes_unrated(self):
        _init()
        memory.rate_recipe(memory.save_recipe(["a"], "Good"), 4)
        memory.rate_recipe(memory.save_recipe(["b"], "Best"), 5)
        memory.save_recipe(["c"], "Unrated")
        memory.rate_recipe(memory.save_recipe(["d"], "Meh"), 2)
        assert memory.get_top_rated_recipes(5) == ["Best", "Good"]

    def test_top_rated_respects_limit(self):
        _init()
        memory.rate_recipe(memory.save_recipe(["a"], "Five"), 5)
        memory.rate_recipe(memory.save_recipe(["b"], "Four"), 4)
        assert memory.get_top_rated_recipes(1) == ["Five"]

    def test_disliked_excludes_unrated_and_highly_rated(self):
        _init()
        memory.rate_recipe(memory.save_recipe(["a"], "Bad"), 1)
        memory.rate_recipe(memory.save_recipe(["b"], "Okay"), 2)
        memory.save_recipe(["c"], "Unrated")
        memory.rate_recipe(memory.save_recipe(["d"], "Loved"), 5)
        assert memory.get_disliked_recipes(5) == ["Bad", "Okay"]

    def test_empty_when_no_ratings(self):
        _init()
        memory.save_recipe(["a"], "Unrated")
        assert memory.get_top_rated_recipes(5) == []
        assert memory.get_disliked_recipes(5) == []


class TestPantry:
    def test_add_and_list_sorted(self):
        _init()
        assert memory.add_pantry_item("rice") is True
        assert memory.add_pantry_item("olive oil") is True
        assert memory.list_pantry_items() == ["olive oil", "rice"]

    def test_add_normalizes_and_dedupes(self):
        _init()
        assert memory.add_pantry_item("  Rice ") is True
        assert memory.add_pantry_item("RICE") is False
        assert memory.list_pantry_items() == ["rice"]

    def test_add_blank_rejected(self):
        _init()
        assert memory.add_pantry_item("   ") is False
        assert memory.list_pantry_items() == []

    def test_remove(self):
        _init()
        memory.add_pantry_item("rice")
        assert memory.remove_pantry_item("RICE") is True
        assert memory.remove_pantry_item("rice") is False
        assert memory.list_pantry_items() == []


class TestSettings:
    def test_get_unset_returns_none(self):
        _init()
        assert memory.get_setting("diet") is None

    def test_set_and_get(self):
        _init()
        memory.set_setting("diet", "vegetarian")
        assert memory.get_setting("diet") == "vegetarian"

    def test_set_overwrites(self):
        _init()
        memory.set_setting("diet", "vegetarian")
        memory.set_setting("diet", "vegan")
        assert memory.get_setting("diet") == "vegan"

    def test_delete(self):
        _init()
        memory.set_setting("diet", "vegan")
        memory.delete_setting("diet")
        assert memory.get_setting("diet") is None


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
