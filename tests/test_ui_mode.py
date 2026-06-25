"""Simple/Advanced UI mode (#180).

Three layers:

* The AppSettings contract: default is 'simple', round-trips, and any
  unrecognized stored value coerces back to 'simple'.
* The SimpleModeWidget: its two buttons emit the right intent signals and
  ``set_busy`` disables the action.
* ``MainWindow._apply_ui_mode``: swaps the stacked page and hides/shows the
  advanced toolbar. Driven on a lightweight stand-in ``self`` (the real
  unbound method) so we don't construct the whole window, which pulls in the
  full startup pipeline (no pytest-qt in dev deps — see tests/CLAUDE.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QSettings  # noqa: E402
from PyQt6.QtWidgets import QApplication, QStackedWidget, QWidget  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Import via the same path src/gui/main_window.py uses (`src.utils.settings`)
# so monkeypatching AppSettings.settings affects the exact class the window
# sees — `utils.settings` and `src.utils.settings` are distinct module objects
# under this repo's dual pythonpath.
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


# ── Settings contract ───────────────────────────────────────────────────────

def test_default_is_simple(isolated_settings):
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_roundtrip(isolated_settings):
    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_ADVANCED
    AppSettings.set_ui_mode(AppSettings.UI_MODE_SIMPLE)
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_unknown_stored_value_coerces_to_simple(isolated_settings):
    AppSettings.settings().setValue(AppSettings.UI_MODE, "banana")
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


def test_set_unknown_value_coerces_to_simple(isolated_settings):
    AppSettings.set_ui_mode("nonsense")
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE


# ── SimpleModeWidget ────────────────────────────────────────────────────────

def test_simple_widget_signals(qapp):
    from src.gui.simple_mode_widget import SimpleModeWidget

    w = SimpleModeWidget()
    hits = []
    w.generate_and_apply_requested.connect(lambda: hits.append("generate"))
    w.switch_to_advanced_requested.connect(lambda: hits.append("advanced"))
    w.generate_apply_btn.click()
    w.advanced_btn.click()
    assert hits == ["generate", "advanced"]


def test_simple_widget_set_busy(qapp):
    from src.gui.simple_mode_widget import SimpleModeWidget

    w = SimpleModeWidget()
    assert w.generate_apply_btn.isEnabled()
    w.set_busy(True)
    assert not w.generate_apply_btn.isEnabled()
    w.set_busy(False)
    assert w.generate_apply_btn.isEnabled()


# ── _apply_ui_mode swap ─────────────────────────────────────────────────────

class _StubWindow:
    """Minimal stand-in carrying just the widgets _apply_ui_mode touches."""

    def __init__(self):
        self.tabs = QWidget()
        self.simple_page = QWidget()
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.tabs)
        self.view_stack.addWidget(self.simple_page)
        self.toolbar_container = QWidget()
        # _apply_ui_mode only resizes the window when it's already shown; this
        # never-shown stub reports not-visible so the swap is exercised in
        # isolation, without the sizing helper.
        self.isVisible = lambda: False


def test_apply_ui_mode_swaps_page(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    stub = _StubWindow()

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_SIMPLE)
    assert stub.view_stack.currentWidget() is stub.simple_page
    assert stub.toolbar_container.isHidden()
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE

    MainWindow._apply_ui_mode(stub, AppSettings.UI_MODE_ADVANCED)
    assert stub.view_stack.currentWidget() is stub.tabs
    assert not stub.toolbar_container.isHidden()
    assert AppSettings.get_ui_mode() == AppSettings.UI_MODE_ADVANCED


def test_apply_ui_mode_unknown_falls_back_to_simple(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    stub = _StubWindow()
    MainWindow._apply_ui_mode(stub, "garbage")
    assert stub.view_stack.currentWidget() is stub.simple_page


# ── _size_window_for_mode (mode-driven startup size, #180 follow-up) ─────────

class _SizeStub:
    """Records the window-sizing calls _size_window_for_mode makes, so the
    Advanced=maximized / Simple=shrink-to-fit contract is tested without a
    real top-level window (offscreen QPA doesn't report maximize reliably)."""

    def __init__(self, maximized=False):
        self.calls = []
        self._maximized = maximized

    def showMaximized(self):
        self.calls.append("max")
        self._maximized = True

    def showNormal(self):
        self.calls.append("normal")
        self._maximized = False

    def resize(self, size):
        self.calls.append(("resize", size))

    def minimumSizeHint(self):
        return "MIN"  # sentinel — Simple resizes to the minimum fit

    def isMaximized(self):
        return self._maximized

    def isFullScreen(self):
        return False


def test_advanced_mode_opens_maximized(qapp):
    from src.gui.main_window import MainWindow

    s = _SizeStub()
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_ADVANCED)
    assert s.calls == ["max"]


def test_simple_mode_shrinks_to_minimum_when_normal(qapp):
    from src.gui.main_window import MainWindow

    s = _SizeStub()
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_SIMPLE)
    assert s.calls == [("resize", "MIN")]


def test_switch_from_maximized_unmaximizes_then_defers_shrink(qapp):
    # From a maximized (Advanced) window the shrink is deferred past the async
    # geometry restore, so only the un-maximize is synchronous here.
    from src.gui.main_window import MainWindow

    s = _SizeStub(maximized=True)
    MainWindow._size_window_for_mode(s, AppSettings.UI_MODE_SIMPLE)
    assert s.calls == ["normal"]


def test_deferred_shrink_resizes_when_still_simple(qapp, isolated_settings):
    from src.gui.main_window import MainWindow

    AppSettings.set_ui_mode(AppSettings.UI_MODE_SIMPLE)
    s = _SizeStub()
    MainWindow._shrink_to_fit_if_simple(s)
    assert s.calls == [("resize", "MIN")]


def test_deferred_shrink_skipped_if_switched_to_advanced(qapp, isolated_settings):
    # Guards the race: if the user flips back to Advanced before the deferred
    # shrink fires, it must not shrink the maximized window.
    from src.gui.main_window import MainWindow

    AppSettings.set_ui_mode(AppSettings.UI_MODE_ADVANCED)
    s = _SizeStub()
    MainWindow._shrink_to_fit_if_simple(s)
    assert s.calls == []
