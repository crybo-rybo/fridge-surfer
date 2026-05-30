from unittest.mock import patch

import pytest

from remy import orchestrator
from remy.camera import CameraUnavailableError


class TestFormatHelpers:
    def test_format_ingredients_empty(self):
        assert orchestrator.format_ingredients([]) == "No ingredients detected."

    def test_format_ingredients_nonempty(self):
        text = orchestrator.format_ingredients(["milk", "eggs"])
        assert text == "Ingredients found:\n• milk\n• eggs"

    def test_format_feedback_saved(self):
        assert orchestrator.format_feedback_saved(1, 5) == "Saved rating 5 for recipe #1."

    @patch("remy.orchestrator.memory.get_last_recipe", return_value=None)
    def test_get_last_recipe_text_empty(self, _mock_last):
        assert orchestrator.get_last_recipe_text() == "No recipes in history yet."

    @patch("remy.orchestrator.memory.get_last_recipe", return_value=(3, "Pasta night"))
    def test_get_last_recipe_text_found(self, _mock_last):
        text = orchestrator.get_last_recipe_text()
        assert text == "[Recipe #3]\n\nPasta night"


class TestRun:
    @patch("remy.orchestrator.memory.get_disliked_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_top_rated_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_recent_recipes", return_value=[])
    @patch("remy.orchestrator.memory.save_recipe", return_value=7)
    @patch("remy.orchestrator.chef.generate_recipe", return_value="Pasta")
    @patch("remy.orchestrator.vision.extract_ingredients", return_value=["tomato"])
    def test_happy_path(
        self, mock_vision, mock_chef, mock_save, _mock_recent, _mock_top, _mock_disliked
    ):
        seen_ingredients: list[list[str]] = []
        seen_ids: list[int] = []

        result = orchestrator.run(
            image_bytes=b"jpg",
            on_ingredients=seen_ingredients.append,
            on_saved=seen_ids.append,
        )

        assert result == "Pasta"
        mock_vision.assert_called_once()
        mock_chef.assert_called_once()
        assert mock_chef.call_args.args[0] == ["tomato"]
        mock_save.assert_called_once_with(["tomato"], "Pasta")
        assert seen_ingredients == [["tomato"]]
        assert seen_ids == [7]

    @patch("remy.camera.capture", side_effect=CameraUnavailableError("no cam"))
    def test_camera_unavailable(self, _mock_capture):
        result = orchestrator.run()
        assert "couldn't access the camera" in result

    @patch("remy.orchestrator.vision.extract_ingredients", side_effect=RuntimeError("boom"))
    def test_vision_failure(self, _mock_vision):
        result = orchestrator.run(image_bytes=b"jpg")
        assert "AI models appear to be unavailable" in result

    @patch("remy.orchestrator.vision.extract_ingredients", return_value=[])
    def test_empty_fridge(self, _mock_vision):
        result = orchestrator.run(image_bytes=b"jpg")
        assert "fridge looks empty" in result

    @patch("remy.orchestrator.memory.get_disliked_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_top_rated_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_recent_recipes", return_value=[])
    @patch("remy.orchestrator.memory.save_recipe")
    @patch("remy.orchestrator.chef.generate_recipe", side_effect=RuntimeError("chef down"))
    @patch("remy.orchestrator.vision.extract_ingredients", return_value=["milk"])
    def test_chef_failure(
        self, _mock_vision, _mock_chef, mock_save, _mock_recent, _mock_top, _mock_disliked
    ):
        result = orchestrator.run(image_bytes=b"jpg")
        assert "AI models appear to be unavailable" in result
        mock_save.assert_not_called()


class TestScan:
    @patch("remy.camera.capture", side_effect=CameraUnavailableError("no cam"))
    def test_camera_unavailable(self, _mock_capture):
        assert orchestrator.scan() == []

    @patch("remy.orchestrator.vision.extract_ingredients", return_value=["milk", "eggs"])
    def test_returns_ingredients(self, mock_vision):
        result = orchestrator.scan(image_bytes=b"jpg")
        assert result == ["milk", "eggs"]
        mock_vision.assert_called_once()

    @patch("remy.orchestrator.vision.extract_ingredients", side_effect=RuntimeError("vlm down"))
    def test_vision_failure(self, _mock_vision):
        assert orchestrator.scan(image_bytes=b"jpg") == []


class TestRunChefOnly:
    def test_empty_ingredients(self):
        result = orchestrator.run_chef_only([])
        assert "fridge looks empty" in result

    @patch("remy.orchestrator.memory.get_disliked_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_top_rated_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_recent_recipes", return_value=[])
    @patch("remy.orchestrator.memory.save_recipe", return_value=2)
    @patch("remy.orchestrator.chef.generate_recipe", return_value="Omelette")
    def test_happy_path(
        self, mock_chef, mock_save, _mock_recent, _mock_top, _mock_disliked
    ):
        saved: list[int] = []
        result = orchestrator.run_chef_only(["eggs"], on_saved=saved.append)
        assert result == "Omelette"
        mock_chef.assert_called_once()
        mock_save.assert_called_once_with(["eggs"], "Omelette")
        assert saved == [2]

    @patch("remy.orchestrator.memory.get_disliked_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_top_rated_recipes", return_value=[])
    @patch("remy.orchestrator.memory.get_recent_recipes", return_value=[])
    @patch("remy.orchestrator.memory.save_recipe")
    @patch("remy.orchestrator.chef.generate_recipe", side_effect=RuntimeError("chef down"))
    def test_chef_failure(
        self, _mock_chef, mock_save, _mock_recent, _mock_top, _mock_disliked
    ):
        result = orchestrator.run_chef_only(["eggs"])
        assert "AI models appear to be unavailable" in result
        mock_save.assert_not_called()
