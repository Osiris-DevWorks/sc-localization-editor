"""Tests for ship sort-order prefix helpers (issue #142).

The order number rides in custom_value, zero-padded to two digits, inserted
after any favorite prefix. So a ship can be "*", "01", or "*01" and the two
tokens always compose as ``{favorite}{order}{name}`` — never ``01*name``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from src.utils.ship_sort_prefix import get_order, set_order  # noqa: E402

pytestmark = pytest.mark.unit

FAV = "*"


# ── get_order ────────────────────────────────────────────────────────────────

class TestGetOrder:
    def test_no_prefix(self):
        assert get_order("Avenger", FAV) == ""

    def test_order_only(self):
        assert get_order("01Avenger", FAV) == "01"

    def test_favorite_only(self):
        assert get_order("*Avenger", FAV) == ""

    def test_favorite_and_order(self):
        assert get_order("*01Avenger", FAV) == "01"

    def test_single_digit_is_not_an_order(self):
        assert get_order("1Avenger", FAV) == ""

    def test_empty(self):
        assert get_order("", FAV) == ""

    def test_high_number(self):
        assert get_order("*99Reclaimer", FAV) == "99"


# ── set_order: add / replace / clear ─────────────────────────────────────────

class TestSetOrder:
    def test_add_to_plain(self):
        # No custom value yet → order prepends to the stock name.
        assert set_order("", "Avenger", FAV, "05") == "05Avenger"

    def test_add_to_existing_custom(self):
        assert set_order("Avenger Titan", "Avenger", FAV, "02") == "02Avenger Titan"

    def test_replace_order(self):
        assert set_order("03Avenger", "Avenger", FAV, "07") == "07Avenger"

    def test_clear_order_collapses_to_empty(self):
        # Removing the only thing distinguishing it from stock → "".
        assert set_order("03Avenger", "Avenger", FAV, "") == ""

    def test_clear_order_keeps_custom_name(self):
        assert set_order("03Avenger Titan", "Avenger", FAV, "") == "Avenger Titan"


# ── set_order: composition with the favorite prefix ──────────────────────────

class TestSetOrderWithFavorite:
    def test_order_lands_behind_favorite(self):
        # Favorite stays first; we must never produce "01*Avenger".
        assert set_order("*Avenger", "Avenger", FAV, "01") == "*01Avenger"

    def test_replace_order_preserves_favorite(self):
        assert set_order("*01Avenger", "Avenger", FAV, "08") == "*08Avenger"

    def test_clear_order_preserves_favorite(self):
        assert set_order("*01Avenger", "Avenger", FAV, "") == "*Avenger"

    def test_favorite_only_then_clear_order_is_noop(self):
        assert set_order("*Avenger", "Avenger", FAV, "") == "*Avenger"


# ── set_order: zero-padding normalization ────────────────────────────────────

class TestSetOrderPadding:
    def test_single_digit_input_is_padded(self):
        assert set_order("Avenger", "Avenger", FAV, "5") == "05Avenger"

    def test_two_digit_input_unchanged(self):
        assert set_order("Avenger", "Avenger", FAV, "10") == "10Avenger"
