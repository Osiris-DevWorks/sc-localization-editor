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
    entries = [
        _e("vehicle_NameAVNR_Carrack", custom_value="★ favorite"),
        _e("vehicle_NameANVL_Hornet", custom_value="plain"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, True, "★")
    assert result == [0]


def test_favorites_only_excludes_a_favorited_description_row():
    """#329: a ship description row must never count as a favorite, even if
    its custom_value happens to carry the prefix (e.g. leftover state from
    before the star column was restricted to name rows)."""
    entries = [
        _e("vehicle_DescAVNR_Carrack", custom_value="★ favorite"),
        _e("vehicle_NameANVL_Hornet", custom_value="★ favorite"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, True, "★")
    assert result == [1]


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
    # ship NAME row's custom_value; non-ship rows, ship description rows,
    # and unordered ships all return "".
    entries = [
        _e("vehicle_NameANVL_Avenger", custom_value="*05-Avenger"),
        _e("vehicle_NameANVL_Cutlass", custom_value="*12-Cutlass"),
        _e("k3", category="Gear", custom_value="*05-Helmet"),
        _e("vehicle_DescANVL_Avenger", custom_value="*05-Avenger"),
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
    """The fav-star column getter returns '★' when custom_value starts with
    the prefix on a ship NAME row -- description rows always get ''."""
    entries = [
        _e("vehicle_NameANVL_Hornet", custom_value="★ fave"),
        _e("vehicle_NameANVL_Gladius", custom_value="plain"),
        _e("vehicle_DescANVL_Hornet", custom_value="★ fave"),
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


@pytest.mark.regression
def test_bp_descs_only_recognises_multiple_blueprint_pools_header():
    """CIG uses a second, entirely different header ("MULTIPLE BLUEPRINT
    POOLS") for missions offering more than one blueprint pool (#266
    follow-up) -- pre-fix, the "BP Descriptions" checkbox only recognised
    "POTENTIAL BLUEPRINTS" and silently excluded these mission bodies."""
    entries = [
        _e("desc_pools", original_value=(
            "POSTING...\n<EM4>MULTIPLE BLUEPRINT POOLS</EM4>"
            "\n<EM4>Pool 1</EM4>\n- Helix I Mining Laser (Mining Laser)"
        )),
        _e("plain_desc", original_value="A description with no rewards section"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_descs_only=True)
    assert result == [0]


def test_bp_filter_reads_custom_override_when_present():
    # A user override on a title row is what's shown, so the tag must be read
    # from custom_value when set.
    e = [_e("t", original_value="bare title", custom_value="Custom <EM4>[BP]</EM4>")]
    result = filter_entry_indices(e, {}, _no_filters(), "All", "All", False, False, "★",
                                  bp_titles_only=True)
    assert result == [0]


# ── ship_vehicle_names_only (#329) ───────────────────────────────────────────

def test_ship_vehicle_names_only_hides_ship_description_rows():
    entries = [
        _e("vehicle_NameANVL_Carrack"),
        _e("vehicle_DescANVL_Carrack"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★",
                                  ship_vehicle_names_only=True)
    assert result == [0]


def test_ship_vehicle_names_only_hides_every_other_category():
    """It's "names only", not "Ships category only" -- anything that isn't a
    ship/vehicle name row is hidden, so the list is exactly what favorites
    and ASOP sort order apply to."""
    entries = [
        _e("vehicle_NameANVL_Carrack"),
        _e("item_Name_rifle_behr", category="Gear"),
        _e("item_NameSHLD_Aspirum", category="Ship Items"),
        _e("mission_title_001", category="Missions"),
        _e("items_commodities_agricium", category="Commodities"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★",
                                  ship_vehicle_names_only=True)
    assert result == [0]


def test_ship_vehicle_names_only_keeps_wikelo_vehiclename_rows():
    """Wikelo/Collector ship mods key their name as *_VehicleName rather
    than vehicle_Name*, and are still real ship names."""
    entries = [
        _e("TheCollector_ShipMod_01_VehicleName"),
        _e("TheCollector_ShipMod_01_VehicleDesc"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★",
                                  ship_vehicle_names_only=True)
    assert result == [0]


def test_ship_vehicle_names_only_off_shows_everything():
    entries = [
        _e("vehicle_NameANVL_Carrack"),
        _e("vehicle_DescANVL_Carrack"),
        _e("item_Name_rifle_behr", category="Gear"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, False, "★",
                                  ship_vehicle_names_only=False)
    assert result == [0, 1, 2]


def test_ship_vehicle_names_only_combined_with_favorites_only():
    """The issue's actual motivating case: browsing favorited ship names
    without descriptions or unrelated categories cluttering the list."""
    entries = [
        _e("vehicle_NameANVL_Carrack", custom_value="★ Carrack"),
        _e("vehicle_DescANVL_Carrack", custom_value="★ leftover"),
        _e("vehicle_NameANVL_Hornet", custom_value="plain"),
        _e("item_Name_rifle_behr", category="Gear", custom_value="★ rifle"),
    ]
    result = filter_entry_indices(entries, {}, _no_filters(), "All", "All", False, True, "★",
                                  ship_vehicle_names_only=True)
    assert result == [0]
