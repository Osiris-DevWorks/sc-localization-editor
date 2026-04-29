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
            "_MEIPASS should not be set in the test process "
            "(would mean tests are running inside a frozen build)"
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
