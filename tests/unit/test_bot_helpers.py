import pytest

from remy.bot import _parse_rating_callback, _photo_mode_from_caption, _rating_keyboard


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


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("rate:7:5", (7, 5)),
        ("rate:42:1", (42, 1)),
        ("rate:7:0", None),       # rating out of range
        ("rate:7:6", None),       # rating out of range
        ("rate:abc:3", None),     # non-numeric id
        ("rate:7", None),         # too few parts
        ("rate:7:3:9", None),     # too many parts
        ("scan:7:3", None),       # wrong prefix
        ("", None),
    ],
)
def test_parse_rating_callback(data, expected):
    assert _parse_rating_callback(data) == expected


def test_rating_keyboard_has_five_star_buttons():
    markup = _rating_keyboard(7)
    (row,) = markup.inline_keyboard
    assert len(row) == 5
    assert [b.text for b in row] == ["1⭐", "2⭐", "3⭐", "4⭐", "5⭐"]
    assert [b.callback_data for b in row] == [f"rate:7:{n}" for n in range(1, 6)]
