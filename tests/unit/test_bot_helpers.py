import pytest

from remy.bot import _photo_mode_from_caption


@pytest.mark.parametrize(
    ("caption", "expected"),
    [
        ("/recipe", "recipe"),
        ("recipe", "recipe"),
        (" /RECIPE ", "recipe"),
        ("/scan", "scan"),
        ("scan", "scan"),
        (" /SCAN ", "scan"),
        ("hello", None),
        ("", None),
        ("/help", None),
    ],
)
def test_photo_mode_from_caption(caption, expected):
    assert _photo_mode_from_caption(caption) == expected
