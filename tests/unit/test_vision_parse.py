from unittest.mock import patch

from remy import vision
from remy.vision import _parse, _prompt_for, _union


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


class TestUnion:
    def test_dedupes_case_insensitively_preserving_order(self):
        assert _union([["milk", "Eggs"], ["eggs", "cheese"]]) == ["milk", "Eggs", "cheese"]

    def test_drops_blanks(self):
        assert _union([["milk", "  "], ["", "eggs"]]) == ["milk", "eggs"]

    def test_empty(self):
        assert _union([[], []]) == []


class TestMultiPass:
    @patch("remy.vision._extract_once")
    def test_runs_n_passes_and_unions(self, mock_once):
        mock_once.side_effect = [["milk", "eggs"], ["Eggs", "cheese"]]
        result = vision.extract_ingredients(b"img", passes=2)
        assert result == ["milk", "eggs", "cheese"]
        assert mock_once.call_count == 2

    @patch("remy.vision._extract_once", return_value=["milk"])
    def test_streaming_forces_single_pass(self, mock_once):
        vision.extract_ingredients(b"img", stream_callback=lambda kind, text: None, passes=5)
        assert mock_once.call_count == 1

    @patch("remy.vision._extract_once", return_value=["milk"])
    def test_defaults_to_config_passes(self, mock_once):
        with patch.object(vision.config, "VISION_PASSES", 3):
            vision.extract_ingredients(b"img")
        assert mock_once.call_count == 3
