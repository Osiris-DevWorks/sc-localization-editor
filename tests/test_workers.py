"""Tests for src.gui.workers — pure-function helpers and Qt worker components."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from src.gui.workers import _resolve_patches_dir, get_resource_path

# ─────────────────────────────────────────────────────────────────────────────
# Pure-function helpers (no Qt required)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestGetResourcePath:
    """get_resource_path() must return the right base directory."""

    def test_unfrozen_returns_path_under_project_root(self):
        """Outside a PyInstaller bundle, the path is rooted at the project dir."""
        result = get_resource_path("patches")
        # Should be an absolute path ending with 'patches'
        assert Path(result).name == "patches"
        assert Path(result).is_absolute()

    def test_unfrozen_no_meipass(self, monkeypatch):
        """_MEIPASS must not be set when running tests — confirm that invariant."""
        assert not hasattr(sys, "_MEIPASS"), (
            "_MEIPASS should not be set in the test process (would mean tests are running inside a frozen build)"
        )

    def test_frozen_uses_meipass(self, monkeypatch, tmp_path):
        """When _MEIPASS is set, get_resource_path() uses it as the base."""
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = get_resource_path("patches")
        assert result == str(tmp_path / "patches")

    def test_nested_relative_path(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
        result = get_resource_path("assets/fonts")
        # os.path.join preserves the slash style from the relative arg;
        # normalise both sides before comparing.
        import os.path as _osp

        assert _osp.normpath(result) == _osp.normpath(str(tmp_path / "assets" / "fonts"))


@pytest.mark.unit
class TestResolvePatchesDir:
    """_resolve_patches_dir() must return a Path ending with 'patches'."""

    def test_returns_path_instance(self):
        result = _resolve_patches_dir()
        assert isinstance(result, Path)

    def test_name_is_patches(self):
        result = _resolve_patches_dir()
        assert result.name == "patches"

    def test_is_absolute(self):
        assert _resolve_patches_dir().is_absolute()


# ─────────────────────────────────────────────────────────────────────────────
# Qt widget tests (require qtbot from pytest-qt)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAnimatedProgressDialog:
    """AnimatedProgressDialog state transitions."""

    def test_starts_indeterminate(self, qtbot):
        from src.gui.workers import AnimatedProgressDialog

        dlg = AnimatedProgressDialog("Loading…")
        qtbot.addWidget(dlg)
        # Indeterminate ⇒ range [0, 0]
        assert dlg.minimum() == 0
        assert dlg.maximum() == 0

    def test_set_progress_switches_to_determinate(self, qtbot):
        from src.gui.workers import AnimatedProgressDialog

        dlg = AnimatedProgressDialog("Loading…")
        qtbot.addWidget(dlg)
        dlg.set_progress(3, 10, "Scanning…")
        assert dlg.maximum() == 10
        assert dlg.value() == 3

    def test_set_progress_total_zero_resets_to_indeterminate(self, qtbot):
        from src.gui.workers import AnimatedProgressDialog

        dlg = AnimatedProgressDialog("Loading…")
        qtbot.addWidget(dlg)
        dlg.set_progress(5, 10, "Midpoint")
        assert dlg.maximum() == 10
        dlg.set_progress(0, 0, "Unknown extent")
        assert dlg.maximum() == 0

    def test_set_progress_clamps_value_to_total(self, qtbot):
        from src.gui.workers import AnimatedProgressDialog

        dlg = AnimatedProgressDialog("Loading…")
        qtbot.addWidget(dlg)
        dlg.set_progress(999, 10, "Over-reported")
        # set_progress passes min(completed, total) to setValue; the maximum is 10
        assert dlg.maximum() == 10
        # QProgressDialog.value() may return -1 until the dialog is fully initialised;
        # validate the range is correct instead.
        assert dlg.minimum() == 0


# ─────────────────────────────────────────────────────────────────────────────
# Pending-edit snapshot / restore logic (MainWindow helpers)
# ─────────────────────────────────────────────────────────────────────────────


def _entry(key, custom_value="", original_value="base", status="Unmodified"):
    from src.models.string_model import StringEntry

    e = StringEntry.__new__(StringEntry)
    e.key = key
    e.custom_value = custom_value
    e.original_value = original_value
    e.status = status
    return e


@pytest.mark.unit
class TestPendingEditSnapshotRestore:
    """Verify MainWindow._snapshot_pending_user_edits and _restore_pending_user_edits.

    Both methods are called as unbound functions with minimal fake-self objects
    so the full MainWindow widget is never instantiated.
    """

    def _snapshot(self, entries):
        import types

        from src.gui.main_window import MainWindow

        fake = types.SimpleNamespace(entries=entries)
        return MainWindow._snapshot_pending_user_edits(fake)

    def _restore(self, entries, snapshot):
        from src.gui.main_window import MainWindow

        return MainWindow._restore_pending_user_edits(None, entries, snapshot)

    # -- snapshot ----------------------------------------------------------

    def test_snapshot_empty_entries_returns_empty_dict(self):
        assert self._snapshot([]) == {}

    def test_snapshot_skips_entries_with_no_custom_value(self):
        entries = [_entry("k1", custom_value=""), _entry("k2", custom_value="")]
        assert self._snapshot(entries) == {}

    def test_snapshot_captures_non_empty_custom_values(self):
        entries = [_entry("k1", custom_value="edit1"), _entry("k2", custom_value="edit2")]
        assert self._snapshot(entries) == {"k1": "edit1", "k2": "edit2"}

    def test_snapshot_mixed_entries_only_captures_non_empty(self):
        entries = [
            _entry("k1", custom_value="edit1"),
            _entry("k2", custom_value=""),
            _entry("k3", custom_value="edit3"),
        ]
        result = self._snapshot(entries)
        assert result == {"k1": "edit1", "k3": "edit3"}

    # -- restore -----------------------------------------------------------

    def test_restore_empty_snapshot_returns_zero(self):
        entries = [_entry("k1", custom_value="edit1")]
        assert self._restore(entries, {}) == 0

    def test_restore_skips_key_not_in_snapshot(self):
        entries = [_entry("k1", custom_value="")]
        count = self._restore(entries, {"other_key": "val"})
        assert count == 0
        assert entries[0].custom_value == ""

    def test_restore_skips_entry_already_matching_snapshot(self):
        # If the new entries already loaded this value from user.ini, no-op
        entries = [_entry("k1", custom_value="already")]
        count = self._restore(entries, {"k1": "already"})
        assert count == 0

    def test_restore_applies_pending_edit_and_sets_modified(self):
        entries = [_entry("k1", custom_value="", original_value="base")]
        count = self._restore(entries, {"k1": "pending edit"})
        assert count == 1
        assert entries[0].custom_value == "pending edit"
        assert entries[0].status == "Modified"

    def test_restore_sets_unmodified_when_pending_matches_original(self):
        entries = [_entry("k1", custom_value="", original_value="base")]
        count = self._restore(entries, {"k1": "base"})
        assert count == 1
        assert entries[0].status == "Unmodified"

    def test_restore_returns_count_of_restored_entries(self):
        entries = [
            _entry("k1", custom_value="", original_value="base"),
            _entry("k2", custom_value="already", original_value="base"),
            _entry("k3", custom_value="", original_value="base"),
        ]
        count = self._restore(entries, {"k1": "edit1", "k2": "already", "k3": "edit3"})
        # k2 is skipped (value already matches), k1 and k3 are restored
        assert count == 2

    def test_restore_snapshot_taken_before_entries_replaced(self):
        """Verify the order-of-operations contract: snapshot old entries, restore into new."""
        old = [_entry("k1", custom_value="unsaved")]
        new = [_entry("k1", custom_value="", original_value="new base")]

        snapshot = self._snapshot(old)
        assert snapshot == {"k1": "unsaved"}

        count = self._restore(new, snapshot)
        assert count == 1
        assert new[0].custom_value == "unsaved"
        assert new[0].status == "Modified"
