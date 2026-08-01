"""Imported Tag Builder configs must survive a later widget-driven save.

Regression for the Export/Import Settings feature: `_tag_builder_pages` is
built once at tab construction, so an import that rewrites the
`tag_builder/*` keys underneath a live tab leaves the pages holding the
PRE-import config. The next `_persist_tag_builder_state()` — reachable from
Save Tag Changes, Generate Enhancements, and Export Settings — then wrote
that stale state back over everything the import restored, which is how
imported tag configs were being lost.

`EnhancementsTab.reload_tag_builder_from_settings()` (called by
`MainWindow._handle_import_settings`) resyncs the pages so none of those
paths can resurrect the old config.

Needs a real QApplication for the widgets, so it uses the offscreen Qt
platform like tests/test_ui_mode.py rather than pytest-qt (not a dev dep).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import CATEGORIES, default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

CUSTOM_SEPARATOR = "underscore"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


def _import_custom_configs():
    """Mimic Import Settings writing a customised backup into settings."""
    for cat in CATEGORIES:
        cfg = default_config(cat)
        cfg.separator = CUSTOM_SEPARATOR
        AppSettings.set_tag_config(cat, cfg)
    AppSettings.set_tag_annotate_mission_descs(False)


def _separators() -> dict:
    return {c: AppSettings.get_tag_config(c).separator for c in CATEGORIES}


class TestImportRefresh:
    def test_stale_pages_clobber_import_without_refresh(self, qapp, json_backend):
        """Locks the failure mode itself, so a future refactor can't undo the fix."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()                 # built against an empty profile
        _import_custom_configs()                # import lands underneath it
        tab._persist_tag_builder_state()        # Save / Generate / Export
        assert all(v != CUSTOM_SEPARATOR for v in _separators().values()), (
            "expected the un-refreshed page state to overwrite the import — "
            "if this now passes, the clobber path changed and this test needs review"
        )

    def test_refresh_makes_import_survive_a_later_save(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()  # the fix
        tab._persist_tag_builder_state()
        assert _separators() == {c: CUSTOM_SEPARATOR for c in CATEGORIES}

    def test_refresh_updates_the_visible_pages(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()
        assert {c: p.config.separator for c, p in tab._tag_builder_pages.items()} == {
            c: CUSTOM_SEPARATOR for c in CATEGORIES
        }

    def test_refresh_syncs_annotate_toggle(self, qapp, json_backend):
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()                # imported it as False
        tab.reload_tag_builder_from_settings()
        assert tab._annotate_mission_descs_cb.isChecked() is False

    def test_refresh_leaves_save_button_clean(self, qapp, json_backend):
        """Nothing is unsaved after a refresh, so the button must not light up."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()
        assert tab._tag_dirty is False

    def test_refresh_does_not_write_title_tags(self, qapp, json_backend):
        """The import path mirrors General Tags; it must not persist over them."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        AppSettings.set_mission_title_tag("rep_track", True)  # non-default
        _import_custom_configs()
        tab.reload_tag_builder_from_settings()
        assert AppSettings.get_mission_title_tags()["rep_track"] is True

    def test_reset_to_defaults_still_persists_title_tags(self, qapp, json_backend):
        """The refactor must not change Reset-to-defaults' write behaviour."""
        from src.gui.enhancements_tab import EnhancementsTab

        tab = EnhancementsTab()
        AppSettings.set_mission_title_tag("rep_track", True)
        tab._tag_builder_pages["mission_titles"]._reset_to_defaults()
        assert AppSettings.get_mission_title_tags()["rep_track"] == (
            AppSettings.get_mission_title_tag_default("rep_track")
        )
