import pytest

from remy.debug_cli import _parse_ingredient_args


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        # `/ingredients "milk, eggs"` -> line.split() keeps the quotes on the ends.
        (['"milk,', 'eggs"'], ["milk", "eggs"]),
        (["'milk,", "eggs'"], ["milk", "eggs"]),
        (["milk,", "eggs,", "cheese"], ["milk", "eggs", "cheese"]),
        (['"chicken thighs,', "rice,", 'bell peppers"'], ["chicken thighs", "rice", "bell peppers"]),
        (["milk"], ["milk"]),
        (["  ,  milk ,, "], ["milk"]),  # blank pieces dropped
    ],
)
def test_parse_ingredient_args(args, expected):
    assert _parse_ingredient_args(args) == expected
