"""Tests for src/gui/string_table_model.py.

Covers:
- Pure helper functions: _group_sort_key, _make_sort_key, status_color
- StringTableModel Qt compliance via qtmodeltester
- rowCount / columnCount / headerData
- data() for all roles (DisplayRole, UserRole, ForegroundRole,
  BackgroundRole, TextAlignmentRole, ToolTipRole)
- flags() for each column type
- setData() inline editing + dataChanged signal
- sort() by every column, ascending and descending
- set_filtered_indices() + reverse index
- Grouped sort
- refresh_favorite_prefix()
- entry_for_row / entry_index_for_row / source_row_for_entry_index
- notify_entry_changed() signal
"""

from unittest.mock import patch

import pytest
from PyQt6.QtCore import QModelIndex, Qt
from src.gui.string_table_model import (
    COL_CATEGORY,
    COL_CURRENT,
    COL_CUSTOM,
    COL_DEFAULT,
    COL_KEY,
    COL_STAR,
    COL_STATUS,
    NUM_COLUMNS,
    StringTableModel,
    _group_sort_key,
    status_color,
)
from src.models.string_model import StringEntry

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    key="vehicle_NameHunter",
    source_file="global",
    category="Ships",
    original_value="Drake Cutlass",
    custom_value="",
    status="Unmodified",
) -> StringEntry:
    e = StringEntry.__new__(StringEntry)
    e.key = key
    e.source_file = source_file
    e.category = category
    e.original_value = original_value
    e.custom_value = custom_value
    e.status = status
    return e


def _ship(key="vehicle_NameHunter", custom_value="", status="Unmodified") -> StringEntry:
    return _entry(key=key, category="Ships", custom_value=custom_value, status=status)


def _item(key="item_NameSHLD_test", custom_value="", status="Unmodified") -> StringEntry:
    return _entry(key=key, category="Ship Items", custom_value=custom_value, status=status)


def _model_with(*entries, defaults=None, prefix="*") -> StringTableModel:
    m = StringTableModel()
    m.set_data_source(list(entries), defaults or {}, prefix)
    return m


# ---------------------------------------------------------------------------
# _group_sort_key
# ---------------------------------------------------------------------------


class TestGroupSortKey:
    def test_item_name_prefix(self):
        group, sub = _group_sort_key("item_NameSHLD_Aspirum")
        assert group == "item_shld_aspirum"
        assert sub == 0  # name → 0

    def test_item_desc_prefix(self):
        group, sub = _group_sort_key("item_DescSHLD_Aspirum")
        assert group == "item_shld_aspirum"
        assert sub == 1  # desc → 1

    def test_vehicle_name_prefix(self):
        group, sub = _group_sort_key("vehicle_NameHunter")
        assert group == "vehicle_hunter"
        assert sub == 0

    def test_vehicle_desc_prefix(self):
        group, sub = _group_sort_key("vehicle_DescHunter")
        assert group == "vehicle_hunter"
        assert sub == 1

    def test_commodity_name(self):
        group, sub = _group_sort_key("items_commodities_AluminumOre")
        assert group == "items_commodities_aluminumore"
        assert sub == 0

    def test_commodity_desc(self):
        group, sub = _group_sort_key("items_commodities_AluminumOre_desc")
        assert group == "items_commodities_aluminumore"
        assert sub == 1

    def test_mission_title(self):
        group, sub = _group_sort_key("contract_001_title")
        assert sub == 0

    def test_mission_desc(self):
        group, sub = _group_sort_key("contract_001_desc")
        assert sub == 1

    def test_fallback_plain_key(self):
        group, sub = _group_sort_key("ui_some_label")
        assert group == "ui_some_label"
        assert sub == 0


# ---------------------------------------------------------------------------
# status_color
# ---------------------------------------------------------------------------


class TestStatusColor:
    def test_modified_is_green(self):
        c = status_color("Modified")
        assert c.name() == "#4caf50"

    def test_unmodified_is_grey(self):
        c = status_color("Unmodified")
        assert c.name() == "#999999"

    def test_new_is_orange(self):
        c = status_color("New")
        assert c.name() == "#ff9800"

    def test_unknown_is_black(self):
        c = status_color("Whatever")
        assert c.name() == "#000000"


# ---------------------------------------------------------------------------
# Basic shape
# ---------------------------------------------------------------------------


class TestStringTableModelShape:
    def test_empty_model_row_count_is_zero(self):
        m = StringTableModel()
        assert m.rowCount() == 0

    def test_column_count(self):
        m = StringTableModel()
        assert m.columnCount() == NUM_COLUMNS

    def test_row_count_matches_entries(self):
        m = _model_with(_ship(), _item())
        assert m.rowCount() == 2

    def test_header_labels(self):
        m = StringTableModel()
        for col in range(NUM_COLUMNS):
            label = m.headerData(col, Qt.Orientation.Horizontal, Qt.ItemDataRole.DisplayRole)
            assert isinstance(label, str) and label

    def test_vertical_header_returns_none(self):
        m = StringTableModel()
        val = m.headerData(0, Qt.Orientation.Vertical, Qt.ItemDataRole.DisplayRole)
        assert val is None

    def test_header_non_display_role_returns_none(self):
        m = StringTableModel()
        val = m.headerData(0, Qt.Orientation.Horizontal, Qt.ItemDataRole.ToolTipRole)
        assert val is None


# ---------------------------------------------------------------------------
# Qt model compliance
# ---------------------------------------------------------------------------


class TestStringTableModelCompliance:
    def test_model_tester_empty(self, qtmodeltester):
        m = StringTableModel()
        qtmodeltester.check(m)

    def test_model_tester_with_data(self, qtmodeltester):
        entries = [
            _ship("vehicle_NameHunter", "Drake Cutlass"),
            _item("item_NameSHLD_x", "Shield Gen"),
            _entry(key="ui_label", category="UI", original_value="Label"),
        ]
        m = _model_with(*entries, defaults={"vehicle_NameHunter": "Drake Cutlass Black"})
        qtmodeltester.check(m)


# ---------------------------------------------------------------------------
# data() — DisplayRole
# ---------------------------------------------------------------------------


class TestStringTableModelDisplayRole:
    def _make(self):
        e = _ship("vehicle_NameHunter", custom_value="*Drake Cutlass", status="Modified")
        e.original_value = "Drake Cutlass"
        m = _model_with(e, defaults={"vehicle_NameHunter": "Drake Cutlass Black"})
        return m, e

    def test_category_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_CATEGORY)) == "Ships"

    def test_key_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_KEY)) == "vehicle_NameHunter"

    def test_default_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_DEFAULT)) == "Drake Cutlass Black"

    def test_current_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_CURRENT)) == "Drake Cutlass"

    def test_custom_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_CUSTOM)) == "*Drake Cutlass"

    def test_status_column(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_STATUS)) == "Modified"

    def test_star_column_favorite_ship(self):
        m, e = self._make()
        assert m.data(m.index(0, COL_STAR)) == "\u2605"

    def test_star_column_unfavorite_ship(self):
        e = _ship("vehicle_NameHunter", custom_value="Drake Cutlass")
        m = _model_with(e)
        assert m.data(m.index(0, COL_STAR)) == "\u2606"

    def test_star_column_non_ship_is_empty(self):
        e = _item()
        m = _model_with(e)
        assert m.data(m.index(0, COL_STAR)) == ""

    def test_invalid_index_returns_none(self):
        m = StringTableModel()
        assert m.data(QModelIndex()) is None

    def test_unknown_column_returns_none(self):
        e = _ship()
        m = _model_with(e)
        # Temporarily probe a column index beyond NUM_COLUMNS by abusing the index
        idx = m.createIndex(0, 99)
        assert m.data(idx) is None


# ---------------------------------------------------------------------------
# data() — UserRole
# ---------------------------------------------------------------------------


class TestStringTableModelUserRole:
    def test_user_role_returns_entry_index(self):
        e1, e2 = _ship("a"), _ship("b")
        m = _model_with(e1, e2)
        assert m.data(m.index(0, COL_KEY), Qt.ItemDataRole.UserRole) == 0
        assert m.data(m.index(1, COL_KEY), Qt.ItemDataRole.UserRole) == 1

    def test_user_role_after_filter(self):
        e0, e1, e2 = _ship("a"), _ship("b"), _ship("c")
        m = _model_with(e0, e1, e2)
        # set_filtered_indices re-applies current sort (key ascending)
        # so [2, 0] → sorted to [0, 2] ("a" < "c")
        m.set_filtered_indices([2, 0])
        assert m.data(m.index(0, COL_KEY), Qt.ItemDataRole.UserRole) == 0
        assert m.data(m.index(1, COL_KEY), Qt.ItemDataRole.UserRole) == 2


# ---------------------------------------------------------------------------
# data() — ForegroundRole
# ---------------------------------------------------------------------------


class TestStringTableModelForegroundRole:
    def test_star_favorite_is_gold(self):
        e = _ship(custom_value="*Drake")
        m = _model_with(e)
        color = m.data(m.index(0, COL_STAR), Qt.ItemDataRole.ForegroundRole)
        assert color is not None
        assert color.name() == "#ffd700"

    def test_star_non_favorite_is_grey(self):
        e = _ship(custom_value="Drake")
        m = _model_with(e)
        color = m.data(m.index(0, COL_STAR), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == "#666666"

    def test_status_modified_is_green(self):
        e = _entry(status="Modified")
        m = _model_with(e)
        color = m.data(m.index(0, COL_STATUS), Qt.ItemDataRole.ForegroundRole)
        assert color.name() == "#4caf50"

    def test_other_column_foreground_is_none(self):
        e = _ship()
        m = _model_with(e)
        assert m.data(m.index(0, COL_KEY), Qt.ItemDataRole.ForegroundRole) is None


# ---------------------------------------------------------------------------
# data() — BackgroundRole
# ---------------------------------------------------------------------------


class TestStringTableModelBackgroundRole:
    def test_favorite_ship_has_background_dark_theme(self):
        e = _ship(custom_value="*Drake")
        m = _model_with(e)
        with patch("src.utils.settings.AppSettings.get_theme", return_value="dark"):
            color = m.data(m.index(0, COL_CATEGORY), Qt.ItemDataRole.BackgroundRole)
        assert color is not None
        assert color.name() == "#3a3000"

    def test_favorite_ship_has_background_light_theme(self):
        e = _ship(custom_value="*Drake")
        m = _model_with(e)
        with patch("src.utils.settings.AppSettings.get_theme", return_value="light"):
            color = m.data(m.index(0, COL_CATEGORY), Qt.ItemDataRole.BackgroundRole)
        assert color is not None
        assert color.name() == "#fff4c4"

    def test_non_favorite_background_is_none(self):
        e = _ship(custom_value="Drake")
        m = _model_with(e)
        assert m.data(m.index(0, COL_CATEGORY), Qt.ItemDataRole.BackgroundRole) is None


# ---------------------------------------------------------------------------
# data() — TextAlignmentRole
# ---------------------------------------------------------------------------


class TestStringTableModelAlignmentRole:
    def test_star_column_is_centered(self):
        e = _ship()
        m = _model_with(e)
        val = m.data(m.index(0, COL_STAR), Qt.ItemDataRole.TextAlignmentRole)
        assert val == int(Qt.AlignmentFlag.AlignCenter)

    def test_other_column_alignment_is_none(self):
        e = _ship()
        m = _model_with(e)
        assert m.data(m.index(0, COL_KEY), Qt.ItemDataRole.TextAlignmentRole) is None


# ---------------------------------------------------------------------------
# data() — ToolTipRole
# ---------------------------------------------------------------------------


class TestStringTableModelToolTipRole:
    def test_star_tooltip_favorite(self):
        e = _ship(custom_value="*Drake")
        m = _model_with(e)
        tip = m.data(m.index(0, COL_STAR), Qt.ItemDataRole.ToolTipRole)
        assert "remove" in tip.lower()

    def test_star_tooltip_not_favorite(self):
        e = _ship(custom_value="Drake")
        m = _model_with(e)
        tip = m.data(m.index(0, COL_STAR), Qt.ItemDataRole.ToolTipRole)
        assert "favorite" in tip.lower()

    def test_star_tooltip_non_ship_is_none(self):
        e = _item()
        m = _model_with(e)
        assert m.data(m.index(0, COL_STAR), Qt.ItemDataRole.ToolTipRole) is None

    def test_other_column_tooltip_is_display_text(self):
        e = _ship("vehicle_NameHunter")
        e.original_value = "Drake Cutlass"
        m = _model_with(e)
        tip = m.data(m.index(0, COL_CURRENT), Qt.ItemDataRole.ToolTipRole)
        assert tip == "Drake Cutlass"


# ---------------------------------------------------------------------------
# data() — EditRole
# ---------------------------------------------------------------------------


class TestStringTableModelEditRole:
    def test_edit_role_custom_column_returns_value(self):
        e = _ship(custom_value="My Edit")
        m = _model_with(e)
        val = m.data(m.index(0, COL_CUSTOM), Qt.ItemDataRole.EditRole)
        assert val == "My Edit"

    def test_edit_role_custom_column_empty_value_returns_empty_string(self):
        e = _ship(custom_value="")
        m = _model_with(e)
        val = m.data(m.index(0, COL_CUSTOM), Qt.ItemDataRole.EditRole)
        assert val == ""

    def test_edit_role_non_custom_column_returns_none(self):
        e = _ship(custom_value="My Edit")
        m = _model_with(e)
        for col in (COL_CATEGORY, COL_KEY, COL_DEFAULT, COL_CURRENT, COL_STATUS):
            assert m.data(m.index(0, col), Qt.ItemDataRole.EditRole) is None


# ---------------------------------------------------------------------------
# flags()
# ---------------------------------------------------------------------------


class TestStringTableModelFlags:
    def test_custom_column_is_editable(self):
        e = _ship()
        m = _model_with(e)
        flags = m.flags(m.index(0, COL_CUSTOM))
        assert flags & Qt.ItemFlag.ItemIsEditable

    def test_non_custom_column_is_not_editable(self):
        e = _ship()
        m = _model_with(e)
        for col in (COL_CATEGORY, COL_KEY, COL_DEFAULT, COL_CURRENT, COL_STATUS):
            flags = m.flags(m.index(0, col))
            assert not (flags & Qt.ItemFlag.ItemIsEditable)

    def test_star_on_ship_is_selectable(self):
        e = _ship()
        m = _model_with(e)
        flags = m.flags(m.index(0, COL_STAR))
        assert flags & Qt.ItemFlag.ItemIsSelectable

    def test_star_on_non_ship_is_not_selectable(self):
        e = _item()
        m = _model_with(e)
        flags = m.flags(m.index(0, COL_STAR))
        assert not (flags & Qt.ItemFlag.ItemIsSelectable)


# ---------------------------------------------------------------------------
# setData()
# ---------------------------------------------------------------------------


class TestStringTableModelSetData:
    def test_set_custom_value_updates_entry(self):
        e = _ship("vehicle_NameHunter", custom_value="")
        e.original_value = "Drake Cutlass"
        m = _model_with(e)
        m.setData(m.index(0, COL_CUSTOM), "My Custom", Qt.ItemDataRole.EditRole)
        assert e.custom_value == "My Custom"

    def test_set_custom_value_marks_modified(self):
        e = _ship("vehicle_NameHunter", custom_value="")
        e.original_value = "Drake Cutlass"
        m = _model_with(e)
        m.setData(m.index(0, COL_CUSTOM), "My Custom", Qt.ItemDataRole.EditRole)
        assert e.status == "Modified"

    def test_set_custom_value_to_original_marks_unmodified(self):
        e = _ship("vehicle_NameHunter", custom_value="My Custom", status="Modified")
        e.original_value = "Drake Cutlass"
        m = _model_with(e)
        m.setData(m.index(0, COL_CUSTOM), "Drake Cutlass", Qt.ItemDataRole.EditRole)
        assert e.status == "Unmodified"

    def test_set_custom_value_emits_data_changed(self, qtbot):
        e = _ship("vehicle_NameHunter", custom_value="")
        e.original_value = "Drake Cutlass"
        m = _model_with(e)
        with qtbot.waitSignal(m.dataChanged, timeout=1000):
            m.setData(m.index(0, COL_CUSTOM), "New Value", Qt.ItemDataRole.EditRole)

    def test_set_same_value_returns_false(self):
        e = _ship(custom_value="Same")
        m = _model_with(e)
        result = m.setData(m.index(0, COL_CUSTOM), "Same", Qt.ItemDataRole.EditRole)
        assert result is False

    def test_set_data_wrong_column_returns_false(self):
        e = _ship()
        m = _model_with(e)
        result = m.setData(m.index(0, COL_KEY), "anything", Qt.ItemDataRole.EditRole)
        assert result is False

    def test_set_data_invalid_index_returns_false(self):
        m = StringTableModel()
        result = m.setData(QModelIndex(), "x", Qt.ItemDataRole.EditRole)
        assert result is False

    def test_set_data_wrong_role_returns_false(self):
        e = _ship()
        m = _model_with(e)
        result = m.setData(m.index(0, COL_CUSTOM), "x", Qt.ItemDataRole.DisplayRole)
        assert result is False


# ---------------------------------------------------------------------------
# sort()
# ---------------------------------------------------------------------------


class TestStringTableModelSort:
    def _sorted_keys(self, m):
        return [m.entry_for_row(r).key for r in range(m.rowCount())]

    def test_sort_by_key_ascending(self):
        a, b, c = _ship("c_key"), _ship("a_key"), _ship("b_key")
        m = _model_with(a, b, c)
        m.sort(COL_KEY, Qt.SortOrder.AscendingOrder)
        assert self._sorted_keys(m) == ["a_key", "b_key", "c_key"]

    def test_sort_by_key_descending(self):
        a, b, c = _ship("c_key"), _ship("a_key"), _ship("b_key")
        m = _model_with(a, b, c)
        m.sort(COL_KEY, Qt.SortOrder.DescendingOrder)
        assert self._sorted_keys(m) == ["c_key", "b_key", "a_key"]

    def test_sort_by_category(self):
        ship = _ship("s_key")
        item = _item("i_key")
        gear = _entry("g_key", category="Gear")
        m = _model_with(gear, ship, item)
        m.sort(COL_CATEGORY, Qt.SortOrder.AscendingOrder)
        cats = [m.entry_for_row(r).category for r in range(m.rowCount())]
        assert cats == sorted(cats, key=str.lower)

    def test_sort_by_custom(self):
        a = _ship("k1", custom_value="Zebra")
        b = _ship("k2", custom_value="Alpha")
        m = _model_with(a, b)
        m.sort(COL_CUSTOM, Qt.SortOrder.AscendingOrder)
        assert self._sorted_keys(m) == ["k2", "k1"]

    def test_sort_by_status(self):
        mod = _ship("k1", status="Modified")
        unmod = _ship("k2", status="Unmodified")
        m = _model_with(mod, unmod)
        m.sort(COL_STATUS, Qt.SortOrder.AscendingOrder)
        statuses = [m.entry_for_row(r).status for r in range(m.rowCount())]
        assert statuses == sorted(statuses, key=str.lower)

    def test_sort_by_star_favorites_first(self):
        fav = _ship("fav_key", custom_value="*Drake")
        non = _ship("non_key", custom_value="Drake")
        m = _model_with(non, fav)
        m.sort(COL_STAR, Qt.SortOrder.AscendingOrder)
        assert self._sorted_keys(m)[0] == "fav_key"

    def test_sort_by_default(self):
        a = _ship("key_a")
        b = _ship("key_b")
        m = _model_with(a, b, defaults={"key_a": "Zeta", "key_b": "Alpha"})
        m.sort(COL_DEFAULT, Qt.SortOrder.AscendingOrder)
        assert self._sorted_keys(m) == ["key_b", "key_a"]

    def test_sort_by_current(self):
        a = _ship("key_a")
        a.original_value = "Zeta"
        b = _ship("key_b")
        b.original_value = "Alpha"
        m = _model_with(a, b)
        m.sort(COL_CURRENT, Qt.SortOrder.AscendingOrder)
        assert self._sorted_keys(m) == ["key_b", "key_a"]

    def test_sort_emits_layout_signals(self, qtbot):
        a, b = _ship("b_key"), _ship("a_key")
        m = _model_with(a, b)
        with qtbot.waitSignals([m.layoutAboutToBeChanged, m.layoutChanged], timeout=1000):
            m.sort(COL_KEY, Qt.SortOrder.AscendingOrder)

    def test_grouped_sort_resets_flag_after_sort(self):
        a, b = _ship("item_NameSHLD_x"), _ship("item_DescSHLD_x")
        m = _model_with(a, b)
        m.set_grouped_sort(True)
        m.sort(COL_KEY, Qt.SortOrder.AscendingOrder)
        assert not m._grouped_sort


# ---------------------------------------------------------------------------
# set_filtered_indices()
# ---------------------------------------------------------------------------


class TestStringTableModelFilter:
    def test_filter_reduces_row_count(self):
        a, b, c = _ship("a"), _ship("b"), _ship("c")
        m = _model_with(a, b, c)
        m.set_filtered_indices([0, 2])
        assert m.rowCount() == 2

    def test_filter_correct_entries_visible(self):
        a, b, c = _ship("a"), _ship("b"), _ship("c")
        m = _model_with(a, b, c)
        # set_filtered_indices re-applies current sort (key ascending)
        # so [2, 0] → sorted to [0, 2] ("a" < "c")
        m.set_filtered_indices([2, 0])
        assert m.entry_for_row(0).key == "a"
        assert m.entry_for_row(1).key == "c"

    def test_filter_empty_indices(self):
        a, b = _ship("a"), _ship("b")
        m = _model_with(a, b)
        m.set_filtered_indices([])
        assert m.rowCount() == 0

    def test_filter_emits_layout_signals(self, qtbot):
        a, b = _ship("a"), _ship("b")
        m = _model_with(a, b)
        with qtbot.waitSignals([m.layoutAboutToBeChanged, m.layoutChanged], timeout=1000):
            m.set_filtered_indices([0])

    def test_reverse_index_after_filter(self):
        a, b, c = _ship("a"), _ship("b"), _ship("c")
        m = _model_with(a, b, c)
        # set_filtered_indices re-applies sort, so [2,0] → [0, 2]
        m.set_filtered_indices([2, 0])
        assert m.source_row_for_entry_index(0) == 0  # entry "a" at row 0
        assert m.source_row_for_entry_index(2) == 1  # entry "c" at row 1
        assert m.source_row_for_entry_index(1) is None  # entry "b" filtered out


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


class TestStringTableModelLookups:
    def test_entry_index_for_row(self):
        a, b = _ship("a"), _ship("b")
        m = _model_with(a, b)
        assert m.entry_index_for_row(0) == 0
        assert m.entry_index_for_row(1) == 1

    def test_entry_for_row(self):
        a, b = _ship("a"), _ship("b")
        m = _model_with(a, b)
        assert m.entry_for_row(0) is a
        assert m.entry_for_row(1) is b

    def test_source_row_for_entry_index_missing_returns_none(self):
        a = _ship("a")
        m = _model_with(a)
        m.set_filtered_indices([])
        assert m.source_row_for_entry_index(0) is None


# ---------------------------------------------------------------------------
# refresh_favorite_prefix()
# ---------------------------------------------------------------------------


class TestRefreshFavoritePrefix:
    def test_changed_prefix_updates_star_display(self):
        e = _ship(custom_value="$Drake")
        m = _model_with(e, prefix="*")
        assert m.data(m.index(0, COL_STAR)) == "\u2606"  # not favorite yet
        m.refresh_favorite_prefix("$")
        assert m.data(m.index(0, COL_STAR)) == "\u2605"  # now favorite

    def test_refresh_emits_model_reset(self, qtbot):
        e = _ship()
        m = _model_with(e)
        with qtbot.waitSignals([m.modelAboutToBeReset, m.modelReset], timeout=1000):
            m.refresh_favorite_prefix("$")


# ---------------------------------------------------------------------------
# notify_entry_changed()
# ---------------------------------------------------------------------------


class TestNotifyEntryChanged:
    def test_visible_entry_emits_data_changed(self, qtbot):
        e = _ship("a")
        m = _model_with(e)
        with qtbot.waitSignal(m.dataChanged, timeout=1000):
            m.notify_entry_changed(0)

    def test_hidden_entry_does_not_emit(self, qtbot):
        a, b = _ship("a"), _ship("b")
        m = _model_with(a, b)
        m.set_filtered_indices([0])  # entry 1 is hidden
        with qtbot.assertNotEmitted(m.dataChanged):
            m.notify_entry_changed(1)


# ---------------------------------------------------------------------------
# set_data_source() emits model reset
# ---------------------------------------------------------------------------


class TestSetDataSource:
    def test_emits_model_reset_signals(self, qtbot):
        m = StringTableModel()
        with qtbot.waitSignals([m.modelAboutToBeReset, m.modelReset], timeout=1000):
            m.set_data_source([_ship()], {}, "*")

    def test_replaces_existing_data(self):
        m = _model_with(_ship("old"))
        m.set_data_source([_ship("new1"), _ship("new2")], {}, "*")
        assert m.rowCount() == 2
        assert m.entry_for_row(0).key == "new1"

    def test_sort_keys_computed_if_not_provided(self):
        e = _ship("item_NameSHLD_x")
        m = StringTableModel()
        m.set_data_source([e], {}, "*", sort_keys=None)
        assert len(m._sort_keys) == 1

    def test_sort_keys_used_if_provided(self):
        e = _ship("item_NameSHLD_x")
        precomputed = [("custom_group", 0)]
        m = StringTableModel()
        m.set_data_source([e], {}, "*", sort_keys=precomputed)
        assert m._sort_keys == precomputed
