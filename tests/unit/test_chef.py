from remy.chef import build_user_content


class TestBuildUserContent:
    def test_ingredients_only(self):
        content = build_user_content(["milk", "eggs"], [])
        assert content == "Available ingredients: milk, eggs"

    def test_includes_recent_recipe_titles(self):
        content = build_user_content(
            ["milk"], ["Omelette\nstep 1\nstep 2", "Pancakes\nstep 1"]
        )
        assert "something different" in content
        assert "Omelette; Pancakes" in content
        # Only the title line, not the full body, leaks into the prompt.
        assert "step 1" not in content

    def test_includes_favorites_and_dislikes(self):
        content = build_user_content(
            ["chicken"],
            recent_recipes=[],
            favorites=["Garlic Roast Chicken\n..."],
            dislikes=["Bland Boiled Chicken\n..."],
        )
        assert "lean toward this style: Garlic Roast Chicken" in content
        assert "avoid anything similar: Bland Boiled Chicken" in content

    def test_includes_constraints(self):
        content = build_user_content(
            ["tofu"], [], constraints="vegetarian, no nuts"
        )
        assert "Dietary constraints / preferences: vegetarian, no nuts" in content

    def test_omits_empty_sections(self):
        content = build_user_content(["rice"], [], favorites=[], dislikes=[])
        assert content == "Available ingredients: rice"
