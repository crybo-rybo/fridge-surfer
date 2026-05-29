from remy.vision import _parse, _prompt_for


class TestParse:
    def test_clean_json_array(self):
        assert _parse('["milk", "eggs"]') == ["milk", "eggs"]

    def test_json_with_markdown_fences(self):
        raw = '```json\n["chicken", "tomato"]\n```'
        assert _parse(raw) == ["chicken", "tomato"]

    def test_comma_separated_single_line(self):
        assert _parse("milk, eggs, broccoli") == ["milk", "eggs", "broccoli"]

    def test_bullet_list(self):
        raw = "- milk\n- eggs\n- cheese"
        assert _parse(raw) == ["milk", "eggs", "cheese"]

    def test_numbered_list(self):
        raw = "1. milk\n2. eggs"
        assert _parse(raw) == ["milk", "eggs"]

    def test_multiline_fallback_when_no_json(self):
        assert _parse("milk\neggs") == ["milk", "eggs"]

    def test_empty_string(self):
        assert _parse("") == []

    def test_whitespace_only(self):
        assert _parse("   \n  ") == []

    def test_filters_overly_long_comma_items(self):
        long_item = "x" * 61
        assert _parse(f"milk, eggs, {long_item}") == ["milk", "eggs"]

    def test_json_embedded_in_prose(self):
        raw = 'Here are the items: ["apple", "banana"] hope that helps.'
        assert _parse(raw) == ["apple", "banana"]

    def test_strips_empty_json_entries(self):
        assert _parse('["milk", "", "  ", "eggs"]') == ["milk", "eggs"]


class TestPromptFor:
    def test_registered_model_prefix(self):
        prompt = _prompt_for("qwen3-vl:2b")
        assert "JSON array" in prompt

    def test_unknown_model_uses_fallback(self):
        prompt = _prompt_for("unknown-model")
        assert prompt == "List all food items visible as a JSON array of strings."
