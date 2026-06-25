"""Owned-blueprint tagging core (#157)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.owned_items import (  # noqa: E402
    apply_owned_to_value,
    extract_bp_item_names,
    normalize_item_name,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# A realistic BP-bearing mission description value (literal \n separators).
_DESC = (
    "POSTING: salvage run.\\n\\n<EM3>POTENTIAL BLUEPRINTS</EM3>"
    "\\n- Antium Core\\n- [Mil-S1-A] Norfield\\n- Abrade Scraper Module"
    "\\n\\n<EM3>MISSION DETAILS</EM3>\\n<EM4>Difficulty:</EM4> 3"
)


class TestNormalize:
    def test_strips_leading_component_tag(self):
        assert normalize_item_name("[Mil-S1-A] Norfield") == "Norfield"

    def test_strips_owned_tag(self):
        assert normalize_item_name("Antium Core <EM4>[Owned]</EM4>") == "Antium Core"

    def test_bare_name_unchanged(self):
        assert normalize_item_name("Antium Core") == "Antium Core"

    def test_tagged_bullet_matches_bare_row(self):
        # The whole point: a tagged bullet and the bare item row normalize equal.
        assert normalize_item_name("[Mil-S1-A] Norfield") == normalize_item_name("Norfield")


class TestExtract:
    def test_finds_normalized_bullet_names(self):
        names = extract_bp_item_names(_DESC)
        assert names == {"Antium Core", "Norfield", "Abrade Scraper Module"}

    def test_no_section_returns_empty(self):
        assert extract_bp_item_names("Just a plain description, no rewards.") == set()

    def test_empty_value(self):
        assert extract_bp_item_names("") == set()


class TestApply:
    def test_tags_only_owned_bullets(self):
        out = apply_owned_to_value(_DESC, {"Antium Core"})
        assert "- Antium Core <EM4>[Owned]</EM4>" in out
        assert "- [Mil-S1-A] Norfield\\n" in out  # not owned -> untagged

    def test_tags_owned_via_normalized_match_through_component_tag(self):
        out = apply_owned_to_value(_DESC, {"Norfield"})
        assert "- [Mil-S1-A] Norfield <EM4>[Owned]</EM4>" in out

    def test_idempotent(self):
        once = apply_owned_to_value(_DESC, {"Antium Core"})
        twice = apply_owned_to_value(once, {"Antium Core"})
        assert once == twice
        assert once.count("[Owned]") == 1

    def test_unowning_removes_tag(self):
        tagged = apply_owned_to_value(_DESC, {"Antium Core"})
        cleared = apply_owned_to_value(tagged, set())
        assert "[Owned]" not in cleared
        assert cleared == _DESC

    def test_no_bp_section_only_strips_stale_owned(self):
        v = "A plain line\\n- not a blueprint bullet <EM4>[Owned]</EM4>"
        out = apply_owned_to_value(v, {"whatever"})
        assert "[Owned]" not in out

    def test_empty_owned_set_strips_and_returns(self):
        tagged = apply_owned_to_value(_DESC, {"Antium Core"})
        assert "[Owned]" not in apply_owned_to_value(tagged, set())


# ── AppSettings owned-set persistence + model rendering ──────────────────────

import os as _os  # noqa: E402
_os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtCore import QSettings, Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class TestOwnedSettings:
    def test_default_empty(self, isolated_settings):
        assert AppSettings.get_owned_items() == set()

    def test_roundtrip_single_item(self, isolated_settings):
        # The JSON-string backing must survive a single-item set (a raw list in
        # QSettings would come back mangled).
        AppSettings.set_owned_items({"Antium Core"})
        assert AppSettings.get_owned_items() == {"Antium Core"}

    def test_toggle(self, isolated_settings):
        assert AppSettings.toggle_owned_item("Norfield") is True
        assert "Norfield" in AppSettings.get_owned_items()
        assert AppSettings.toggle_owned_item("Norfield") is False
        assert "Norfield" not in AppSettings.get_owned_items()


class TestModelOwnedColumn:
    def _model(self, qapp):
        from src.gui.string_table_model import StringTableModel
        from src.models.string_model import StringEntry
        m = StringTableModel()
        item = StringEntry(key="item_NameNorfield", source_file="global",
                           category="Components", original_value="Norfield",
                           custom_value="", status="Unmodified")
        other = StringEntry(key="misc", source_file="global", category="Misc",
                            original_value="not an item", custom_value="", status="Unmodified")
        m.set_data_source([item, other], {}, "*")
        return m, item, other

    def test_star_only_on_bp_item_rows(self, qapp):
        from src.gui.string_table_model import COL_OWNED
        m, item, other = self._model(qapp)
        m.set_owned_state({"Norfield"}, set())
        item_row = m.source_row_for_entry_index(0)
        other_row = m.source_row_for_entry_index(1)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "☆"   # empty star
        assert m.data(m.index(other_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == ""        # non-item: blank

    def test_filled_star_when_owned(self, qapp):
        from src.gui.string_table_model import COL_OWNED
        m, item, other = self._model(qapp)
        m.set_owned_state({"Norfield"}, {"Norfield"})
        item_row = m.source_row_for_entry_index(0)
        assert m.data(m.index(item_row, COL_OWNED), Qt.ItemDataRole.DisplayRole) == "★"   # filled star

    def test_sort_by_owned_floats_owned_to_top(self, qapp):
        # #189: clicking the Owned header must group owned items, like Favorites,
        # not sort stably by key. "Zeta" is owned but sorts after "Alpha"
        # alphabetically, so owned-first ordering is the only thing that puts
        # its row on top.
        from src.gui.string_table_model import COL_OWNED, StringTableModel
        from src.models.string_model import StringEntry

        owned = StringEntry(key="item_NameZeta", source_file="global",
                            category="Components", original_value="Zeta",
                            custom_value="", status="Unmodified")
        not_owned = StringEntry(key="item_NameAlpha", source_file="global",
                                category="Components", original_value="Alpha",
                                custom_value="", status="Unmodified")
        m = StringTableModel()
        m.set_data_source([owned, not_owned], {}, "*")
        m.set_owned_state({"Zeta", "Alpha"}, {"Zeta"})

        m.sort(COL_OWNED, Qt.SortOrder.AscendingOrder)
        assert m.entry_index_for_row(0) == 0   # owned "Zeta" on top despite key

        # The header arrow flips it: descending puts owned at the bottom.
        m.sort(COL_OWNED, Qt.SortOrder.DescendingOrder)
        assert m.entry_index_for_row(1) == 0
