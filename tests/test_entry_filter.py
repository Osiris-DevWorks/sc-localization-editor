"""Tests for src.utils.entry_filter.filter_entry_indices."""

import pytest
from src.models.string_model import StringEntry
from src.utils.entry_filter import filter_entry_indices

pytestmark = pytest.mark.unit


def _e(key="k", category="Ships", original_value="val", custom_value="", status="Unmodified"):
    return StringEntry(
        key=key,
        source_file="global",
        category=category,
        original_value=original_value,
        custom_value=custom_value,
        status=status,
    )


def _no_filters():
    return ["", "", "", "", "", "", ""]


def test_no_filters_returns_all_indices():
    entries = [_e("k1"), _e("k2"), _e("k3")]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★")
    assert result == [0, 1, 2]


def test_empty_entries_returns_empty():
    result = filter_entry_indices([], {}, _no_filters(), "All", "All", False, False, "★")
    assert result == []


def test_hide_unmodified_removes_unmodified_entries():
    entries = [_e("k1", status="Unmodified"), _e("k2", status="Modified")]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", True, False, "★")
    assert result == [1]


def test_category_filter_excludes_non_matching():
    entries = [_e("k1", category="Ships"), _e("k2", category="Gear")]
    result = filter_entry_indices(entries, {}, _no_filters(), "Ships", "All", False, False, "★")
    assert result == [0]


def test_status_filter_excludes_non_matching():
    entries = [_e("k1", status="Unmodified"), _e("k2", status="New")]
    col_filters = _no_filters()
    result = filter_entry_indices(entries, {}, col_filters, "All", "New", False, False, "★")
    assert result == [1]


def test_favorites_only_keeps_entries_starting_with_prefix():
    entries = [_e("k1", custom_value="★ favorite"), _e("k2", custom_value="plain")]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, True, "★")
    assert result == [0]


def test_column_filter_by_key():
    entries = [_e("alpha"), _e("beta"), _e("gamma")]
    col_filters = ["", "bet", "", "", "", "", ""]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [1]


def test_column_filter_by_status_text():
    entries = [_e("k1", status="Unmodified"), _e("k2", status="New")]
    col_filters = ["", "", "", "", "", "", "new"]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [1]


def test_column_filter_by_default_values():
    entries = [_e("k1"), _e("k2")]
    default_vals = {"k1": "searchterm"}
    col_filters = ["", "", "searchterm", "", "", "", ""]
    result = filter_entry_indices(entries, default_vals, col_filters, "All", "All", False, False, "★")
    assert result == [0]
