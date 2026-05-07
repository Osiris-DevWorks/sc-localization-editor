"""Open Strings - Main entry point."""

import ctypes
import logging
import os
import sys
from pathlib import Path

# Allow `python src\main.py` from the repo root by ensuring the project root
# is importable before resolving `from src...` imports below.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Force Qt to look for platform plugins in OUR bundled Qt6/plugins directory
# ── BEFORE we import anything from PyQt6. The most common source of the
# ── "No Qt platform plugin could be initialized" crash on user machines is a
# ── pre-existing environment variable (QT_PLUGIN_PATH, QT_QPA_PLATFORM_PLUGIN_PATH)
# ── from some other Qt app (IDE, another PyQt install, Anaconda, etc.) that
# ── points at an incompatible Qt version. PyInstaller's runtime hook sets
# ── these env vars but only if they're not already set — we override
# ── unconditionally so the frozen build always uses its own plugins.
if getattr(sys, "frozen", False):
    _meipass = getattr(sys, "_MEIPASS", None)
    if _meipass is not None:
        _bundled_plugins = os.path.join(_meipass, "PyQt6", "Qt6", "plugins")
        if os.path.isdir(_bundled_plugins):
            os.environ["QT_PLUGIN_PATH"] = _bundled_plugins
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(_bundled_plugins, "platforms")

from PyQt6.QtWidgets import QApplication, QMessageBox

from src.gui.main_window import MainWindow
from src.gui.theme import apply_body_font, apply_theme, load_application_fonts
from src.utils.settings import AppSettings
from src.utils.version import get_version

logger = logging.getLogger(__name__)


def main():
    """Application entry point."""
    # Setup logging — use --debug flag or LOG_LEVEL env var for perf timing output
    _log_level = (
        logging.DEBUG if ("--debug" in sys.argv or os.environ.get("LOG_LEVEL", "").upper() == "DEBUG") else logging.INFO
    )
    logging.basicConfig(
        level=_log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger.info(f"Starting Open Strings v{get_version()}")

    try:
        # Seed default settings on first launch if registry is empty.
        AppSettings.ensure_default_settings()

        # Always keep user source path in sync with canonical user.ini location
        AppSettings.set_source_path(AppSettings.SOURCE_USER, str(AppSettings.get_user_ini_path()))

        # Keep the global source path pointing at the active channel's cached
        # base.ini — the channel migrator moved the file into
        # {user_data}\{channel}\cache\ but the stored path in the registry
        # kept pointing at the pre-migration flat location, so the loader
        # would read a file that no longer exists. Do this every startup (not
        # just once post-migration) so channel switches also refresh the
        # path. Skip the rewrite if the current value is a URL — we don't
        # want to clobber a user who's configured a custom remote global
        # source.
        _global_stored = AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)
        if not (_global_stored.startswith("http://") or _global_stored.startswith("https://")):
            _canonical_global = str(AppSettings.get_cache_dir() / "base.ini")
            if _global_stored != _canonical_global:
                AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, _canonical_global)
                logger.info(
                    f"Re-synced SOURCE_GLOBAL path to active channel cache: "
                    f"{_global_stored or '(unset)'} → {_canonical_global}"
                )

        # Ensure user.ini exists (create empty if first run)
        AppSettings.ensure_user_ini_file()
    except Exception as exc:
        _err_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.critical(None, "Startup Error", f"A startup error occurred:\n\n{exc}")
        raise

    # Required on Windows so the taskbar groups the app under its own icon
    # instead of the Python interpreter icon.
    if sys.platform == "win32":
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("JoniHayes.OpenStrings")

    app = QApplication(sys.argv)
    load_application_fonts()
    apply_theme(app, AppSettings.get_theme())
    apply_body_font(AppSettings.get_font_preference())
    window = MainWindow()
    window.show()

    logger.info("Application window shown")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
