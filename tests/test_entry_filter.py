"""Tests for src.utils.entry_filter.filter_entry_indices."""

import logging

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
    return ["", "", "", "", "", "", "", ""]


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
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "New", False, False, "★")
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
    col_filters = ["", "", "", "", "", "", "", "new"]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [1]


def test_column_filter_by_order():
    # The order getter (col index 5) reads the two-digit sort prefix off a
    # ship's custom_value; non-ship rows and unordered ships return "".
    entries = [
        _e("k1", custom_value="*05-Avenger"),
        _e("k2", custom_value="*12-Cutlass"),
        _e("k3", category="Gear", custom_value="*05-Helmet"),
    ]
    col_filters = ["", "", "", "", "", "05", "", ""]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "*")
    assert result == [0]


def test_column_filter_by_default_values():
    entries = [_e("k1"), _e("k2")]
    default_vals = {"k1": "searchterm"}
    col_filters = ["", "", "searchterm", "", "", "", ""]
    result = filter_entry_indices(entries, default_vals, col_filters, "All", "All", False, False, "★")
    assert result == [0]


def test_column_filter_by_custom_value():
    entries = [
        _e("k1", custom_value="my custom", status="Modified"),
        _e("k2", status="Unmodified"),
    ]
    col_filters = ["", "", "", "", "", "", "custom", ""]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [0]


def test_out_of_bounds_column_filter_skipped_with_warning(caplog):
    """A filter index >= NUM_COLUMNS would IndexError inside the per-entry
    loop; the validator at the top of filter_entry_indices drops it and
    logs once instead. This test seeds an 11-element column_filters list
    where only index 10 is non-empty (the rest are empty so the validator
    sees a single OOB index, not ten of them) — proves the OOB index is
    dropped without raising and without affecting the visible row set.
    """
    entries = [_e("k1"), _e("k2")]
    col_filters = ["", "", "", "", "", "", "", "", "", "", "sometext"]  # 11 items
    with caplog.at_level(logging.WARNING, logger="src.utils.entry_filter"):
        result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [0, 1]  # OOB filter dropped → all entries visible
    assert any("out of range" in rec.message.lower() for rec in caplog.records)


def test_getter_count_matches_num_columns():
    """If a future column is added to string_table_model.NUM_COLUMNS, the
    getter tuple inside filter_entry_indices must grow to match — otherwise
    a filter on the new column would silently use the wrong getter (or
    IndexError, depending on order). This test catches that drift by
    introspecting the function's bytecode for tuple length, which is
    cheaper than running a filter on every column.
    """
    from src.gui.string_table_model import NUM_COLUMNS
    from src.utils.entry_filter import filter_entry_indices as fef

    # Seed one filter per column with a string that will not match anything,
    # then confirm none raise IndexError — implicit tuple-length check via
    # exercise rather than introspection.
    entries = [_e("k1")]
    for col in range(NUM_COLUMNS):
        col_filters = [""] * NUM_COLUMNS
        col_filters[col] = "no_such_value_anywhere_xyz"
        result = fef(entries, {}, col_filters, "All", "All", False, False, "★")
        assert result == [], f"col {col}: filter should match nothing"


def test_favorites_marker_searchable_in_star_column():
    """The fav-star column getter returns '★' when custom_value starts with the prefix."""
    entries = [
        _e("k1", custom_value="★ fave"),
        _e("k2", custom_value="plain"),
    ]
    col_filters = ["", "", "", "", "★", "", ""]
    result = filter_entry_indices(entries, {}, col_filters, "All", "All", False, False, "★")
    assert result == [0]


# ── #156: blueprint-mission filters ──────────────────────────────────────────

def _bp_entries():
    return [
        _e("title_bp", original_value="Retrieve Cargo Haul <EM4>[BP]</EM4>"),
        _e("title_bpq", original_value="Recoup Stolen Haul <EM4>[BP?]</EM4>"),
        _e("desc_bp", original_value="POSTING...\n<EM4>POTENTIAL BLUEPRINTS</EM4>\n- Antium Core"),
        _e("plain_title", original_value="Some Mission"),
        _e("plain_desc", original_value="A description with no rewards section"),
    ]


def test_bp_titles_only_keeps_tagged_titles():
    e = _bp_entries()
    result = filter_entry_indices(e, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_titles_only=True)
    assert result == [0, 1]  # [BP] and [BP?] titles only


def test_bp_descs_only_keeps_potential_blueprints_bodies():
    e = _bp_entries()
    result = filter_entry_indices(e, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_descs_only=True)
    assert result == [2]  # the POTENTIAL BLUEPRINTS body only


def test_both_bp_flags_show_titles_or_descs():
    e = _bp_entries()
    result = filter_entry_indices(e, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_titles_only=True, bp_descs_only=True)
    assert result == [0, 1, 2]  # titles OR descriptions


def test_bp_filter_reads_custom_override_when_present():
    # A user override on a title row is what's shown, so the tag must be read
    # from custom_value when set.
    e = [_e("t", original_value="bare title", custom_value="Custom <EM4>[BP]</EM4>")]
    result = filter_entry_indices(e, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_titles_only=True)
    assert result == [0]
