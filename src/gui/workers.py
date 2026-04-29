"""Worker threads and dialog for Open Strings GUI operations."""

import importlib.util
import logging
import os
import sys
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtGui import QColor, QMouseEvent
from PyQt6.QtWidgets import QLabel, QProgressBar, QProgressDialog, QStyledItemDelegate, QWidget

from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


def get_resource_path(relative_path: str) -> str:
    """Get absolute path to resource, works for dev and for PyInstaller."""
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path is None:
        # If not running as PyInstaller bundle, use the project root
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    return os.path.join(base_path, relative_path)


def _resolve_patches_dir() -> Path:
    """Return the path to the bundled DataForge patches directory."""
    return Path(get_resource_path("patches"))


class AnimatedProgressDialog(QProgressDialog):
    """Reusable progress dialog that toggles between indeterminate and determinate.

    Starts indeterminate (range 0-0, auto-animating). Call `set_progress(completed,
    total, message)` to switch to determinate; pass total=0 to drop back to
    indeterminate for phases with an unknown extent. The phase message shows
    in the label above the bar. In determinate mode the bar displays the
    percent-complete (default Qt ``%p%`` format); indeterminate mode hides
    the bar text since there's no meaningful percentage to show.
    """

    def __init__(self, message: str, parent=None, title: str = "Processing"):
        super().__init__(message, None, 0, 0, parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(400)
        self._bar = self.findChild(QProgressBar)
        if self._bar is not None:
            # Start indeterminate — bar text hidden until set_progress flips
            # to determinate and a real percentage exists to display.
            self._bar.setTextVisible(False)
        self.show()

    def set_progress(self, completed: int, total: int, message: str = "") -> None:
        """Drive the bar from a ProgressSink. total=0 ⇒ indeterminate.

        Determinate mode applies a two-tone gradient QSS and shows ``%p%``
        inside the bar. Indeterminate mode clears the QSS so Fusion's
        animated busy indicator still works, and hides the bar text.
        Phase messages go to the label above the bar in both modes.
        """
        if total <= 0:
            if self.maximum() != 0 or self.minimum() != 0:
                self.setRange(0, 0)
            if self._bar is not None:
                self._bar.setTextVisible(False)
                self._bar.setStyleSheet("")
        else:
            if self.maximum() != total:
                self.setRange(0, total)
            self.setValue(min(completed, total))
            if self._bar is not None:
                # Reset format to the Qt default so %p% resolves even if
                # something upstream had set a custom format string.
                self._bar.setFormat("%p%")
                self._bar.setTextVisible(True)
                from src.gui.theme import get_progress_chunk_color, get_progress_groove_color

                chunk = QColor(get_progress_chunk_color())
                light = chunk.lighter(135).name()
                dark = chunk.darker(125).name()
                mid = chunk.name()
                self._bar.setStyleSheet(
                    "QProgressBar {"
                    f" background-color: {get_progress_groove_color()};"
                    " border: 1px solid rgba(0,0,0,0.25);"
                    " border-radius: 3px;"
                    " text-align: center;"
                    "}"
                    "QProgressBar::chunk {"
                    " background: qlineargradient("
                    "  x1:0, y1:0, x2:0, y2:1,"
                    f"  stop:0 {light},"
                    f"  stop:0.5 {mid},"
                    f"  stop:1 {dark}"
                    " );"
                    " border-radius: 2px;"
                    "}"
                )
        if message:
            self.setLabelText(message)


class ClickableLabel(QLabel):
    """QLabel variant that exposes a clicked signal."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class ClickableWidget(QWidget):
    """QWidget variant that exposes a clicked signal."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event: QMouseEvent | None) -> None:
        self.clicked.emit()
        super().mousePressEvent(event)


class FileLoaderWorker(QThread):
    """Worker thread for loading INI files without blocking UI.

    Loads configured sources from settings and emits the merged entries plus
    pre-computed sort keys so the main thread doesn't need to re-parse base.ini.
    """

    # (entries, default_values dict, pre-computed group sort keys)
    finished = pyqtSignal(list, dict, list)
    error = pyqtSignal(str)
    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)

    # 3 phase boundaries: sources read → entries built → sort keys computed.
    _PHASE_TOTAL = 3

    def run(self):
        from src.gui.string_table_model import _group_sort_key
        from src.parser.ini_parser import load_source_files, load_sources_from_settings

        try:
            logger.info("FileLoaderWorker starting...")
            self.progress_pct.emit(0, self._PHASE_TOTAL, "Reading source files...")
            self.progress.emit("Reading source files...")

            sources_dict, hierarchy, enhancements_key_categories = load_sources_from_settings()
            logger.info(f"Loaded from settings: sources={list(sources_dict.keys())}, hierarchy={hierarchy}")

            if not (sources_dict and hierarchy):
                raise ValueError("No sources configured")

            self.progress_pct.emit(1, self._PHASE_TOTAL, "Creating StringEntry objects...")
            self.progress.emit("Creating StringEntry objects...")
            entries = load_source_files(
                sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories
            )
            logger.info(f"load_source_files returned {len(entries)} entries")

            default_values = dict(sources_dict.get("global", {}))

            self.progress_pct.emit(2, self._PHASE_TOTAL, "Computing sort keys...")
            self.progress.emit("Computing sort keys...")
            sort_keys = [_group_sort_key(e.key) for e in entries]

            self.progress_pct.emit(3, self._PHASE_TOTAL, "Ready")
            logger.info("FileLoaderWorker finished successfully")
            self.finished.emit(entries, default_values, sort_keys)
        except Exception as e:
            logger.exception(f"Error loading files: {e}")
            self.error.emit(str(e))


class StartupSyncWorker(QThread):
    """Worker thread that syncs all enabled remote sources on startup.

    Uses conditional GET (If-Modified-Since) so only changed files are downloaded.
    Emits source_starting before each download, source_synced after, source_error on
    failure. Always emits finished so loading proceeds even when sources fail.
    """

    source_starting = pyqtSignal(str)  # source_name (about to sync)
    source_synced = pyqtSignal(str, bool)  # (source_name, was_updated)
    source_error = pyqtSignal(str, str)  # (source_name, error_message)
    finished = pyqtSignal()

    def run(self):
        from src.utils.updater import download_file_if_changed

        cache_dir = AppSettings.get_cache_dir()
        cache_mapping = {
            AppSettings.SOURCE_GLOBAL: "base.ini",
        }

        for source_name in [
            AppSettings.SOURCE_GLOBAL,
        ]:
            if not AppSettings.is_source_enabled(source_name):
                continue
            if not AppSettings.get_source_auto_update(source_name):
                continue

            source_url = AppSettings.get_source_path(source_name)
            if not source_url or not source_url.startswith("https://"):
                continue

            self.source_starting.emit(source_name)
            cache_file = cache_dir / cache_mapping.get(source_name, f"{source_name}.ini")
            try:
                updated = download_file_if_changed(source_url, cache_file)
                self.source_synced.emit(source_name, updated)
            except Exception as e:
                logger.warning(f"Startup sync failed for {source_name}: {e}")
                self.source_error.emit(source_name, str(e))

        self.finished.emit()


class EnhancementsGeneratorWorker(QThread):
    """Worker thread for generating enhancements INI files via generate_enhancements_ini.py."""

    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, categories: set[str] | None = None):
        super().__init__()
        self.categories = categories

    def run(self):
        from src.utils.dataforge_patcher import apply_patches

        try:
            if getattr(sys, "frozen", False):
                script_path = Path(getattr(sys, "_MEIPASS", "")) / "scripts" / "generate_enhancements_ini.py"
            else:
                script_path = Path(__file__).parent.parent.parent / "scripts" / "generate_enhancements_ini.py"

            if not script_path.exists():
                raise FileNotFoundError(f"Enhancements generator script not found: {script_path}")

            base_ini = AppSettings.get_cache_dir() / "base.ini"
            forge_dir = AppSettings.get_dataforge_cache_dir()

            # Re-apply DataForge patches before generation. apply_patches is
            # idempotent: already-patched files are a cheap no-op, so running
            # this every regen picks up newly-added patches without forcing
            # the user through a full re-extract. Bar stays indeterminate
            # here — ``mod.main()`` below takes over with determinate ticks
            # once its ProgressSink is wired up.
            self.progress_pct.emit(0, 0, "Applying DataForge patches…")
            self.progress.emit("Applying DataForge patches…")
            patch_report = apply_patches(
                _resolve_patches_dir(),
                forge_dir,
                progress_callback=self.progress.emit,
            )
            logger.info(f"DataForge patches: {patch_report.summary_line()}")
            if patch_report.errors:
                for err in patch_report.errors:
                    logger.warning(f"  patch error: {err}")

            self.progress.emit("Loading enhancements generator...")

            module_name = "generate_enhancements_ini_worker"
            if module_name in sys.modules:
                del sys.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if spec is None or spec.loader is None:
                raise FileNotFoundError(f"Cannot load module spec for {script_path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            spec.loader.exec_module(mod)

            self.progress.emit("Generating enhancements (may take a few minutes on first run)...")
            logger.info("Enhancements generation worker: calling mod.main()")

            cat_desc = ", ".join(sorted(self.categories)) if self.categories else "all"
            logger.info(f"Enhancements generation: base_ini={base_ini}, forge_dir={forge_dir}, categories={cat_desc}")

            # Bridge the script's ProgressSink callback into a Qt-safe signal.
            # PyQt signal emits are thread-safe across QThread boundaries, so
            # this is safe to call from lookup-pool workers.
            def _on_progress(completed: int, total: int, message: str) -> None:
                self.progress_pct.emit(completed, total, message)

            mod.main(
                base_ini,
                forge_dir,
                categories=self.categories,
                progress_callback=_on_progress,
                patches_dir=_resolve_patches_dir(),
            )
            logger.info("Enhancements generation worker: mod.main() completed successfully")

            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"Enhancements generation failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class P4kExtractWorker(QThread):
    """Worker thread for extracting global.ini from Data.p4k via unp4k.exe."""

    progress = pyqtSignal(str)  # status message
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)  # True = success
    error = pyqtSignal(str)  # error message (emitted before finished(False))

    def __init__(self, p4k_path, output_path, unp4k_exe):
        super().__init__()
        self._p4k = p4k_path
        self._out = output_path
        self._exe = unp4k_exe

    def run(self):
        from src.utils.pak_extractor import extract_global_ini

        try:
            extract_global_ini(
                self._p4k,
                self._out,
                self._exe,
                progress_callback=self.progress.emit,
                progress_pct_callback=lambda c, t, m: self.progress_pct.emit(c, t, m),
            )
            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"P4K extraction failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class DataForgeExtractWorker(QThread):
    """Worker thread for extracting DataForge entity XMLs from Data.p4k."""

    progress = pyqtSignal(str)
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self, p4k_path, unp4k_exe, unforge_exe, cache_dir):
        super().__init__()
        self._p4k = p4k_path
        self._unp4k_exe = unp4k_exe
        self._unforge_exe = unforge_exe
        self._cache_dir = cache_dir

    def run(self):
        from src.utils.dataforge_patcher import apply_patches
        from src.utils.pak_extractor import extract_dataforge

        try:
            extract_dataforge(
                self._p4k,
                self._unp4k_exe,
                self._unforge_exe,
                self._cache_dir,
                progress_callback=self.progress.emit,
                progress_pct_callback=lambda c, t, m: self.progress_pct.emit(c, t, m),
            )
            # Apply declarative patches over known CIG data bugs so downstream
            # consumers (enhancement generator, future tooling) see corrected
            # data. Patch failures are recorded in the report but don't block
            # the pipeline.
            #
            # Flip the progress bar back to indeterminate (range 0-0, auto-
            # animating) so the user can see we're still working — after
            # extract_dataforge completes, the bar sits at its final 3/3
            # "Done" determinate state, which would look like the dialog is
            # about to close. The patches phase has no useful per-file
            # progress, so indeterminate is the honest signal.
            self.progress_pct.emit(0, 0, "Applying DataForge patches…")
            self.progress.emit("Applying DataForge patches…")
            patch_root = _resolve_patches_dir()
            report = apply_patches(patch_root, self._cache_dir, progress_callback=self.progress.emit)
            logger.info(f"DataForge patches: {report.summary_line()}")
            if report.errors:
                for err in report.errors:
                    logger.warning(f"  patch error: {err}")
            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"DataForge extraction failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class AppUpdateCheckerWorker(QThread):
    """Check for a newer app release against the GitHub Releases API.

    Emits ``finished(update_available, new_version, release_url)`` on
    success.  Emits ``error(message)`` if the network request fails or
    the response cannot be parsed — callers that initiated the check
    manually should surface this; auto-checks can silently swallow it.

    Version comparison is done numerically on dot-separated integer
    tuples so "1.10.0" > "1.9.0" works correctly.
    """

    finished = pyqtSignal(bool, str, str)  # (update_available, new_version, release_url)
    error = pyqtSignal(str)

    _API_URL = "https://api.github.com/repos/jonigirl/open-strings/releases/latest"
    _RELEASES_URL = "https://github.com/jonigirl/open-strings/releases"

    def run(self):
        import json
        import urllib.request

        from src.utils.version import get_version

        try:
            req = urllib.request.Request(
                self._API_URL,
                headers={"User-Agent": "open-strings-update-check", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310  # HTTPS enforced by URL constant
                data = json.loads(resp.read())

            tag = data.get("tag_name", "").lstrip("v").strip()
            release_url = data.get("html_url", self._RELEASES_URL)

            if not tag:
                self.error.emit("GitHub API returned an empty tag_name")
                return

            current = get_version()
            update_available = self._is_newer(tag, current)
            AppSettings.set_last_update_check_epoch(int(__import__("time").time()))
            self.finished.emit(update_available, tag, release_url)
        except Exception as e:
            logger.warning(f"Update check failed: {e}")
            self.error.emit(str(e))

    @staticmethod
    def _is_newer(remote: str, current: str) -> bool:
        """Return True if *remote* version is strictly newer than *current*.

        Comparison is done on integer tuples so "1.10.0" > "1.9.0".
        Falls back to False on any parse error.
        """
        try:

            def _parts(v: str) -> tuple[int, ...]:
                return tuple(int(x) for x in v.split("."))

            return _parts(remote) > _parts(current)
        except (ValueError, AttributeError):
            return False


class SelectAllDelegate(QStyledItemDelegate):
    """Custom delegate that selects all text on edit."""

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if editor is not None and hasattr(editor, "selectAll"):
            editor.selectAll()  # type: ignore  # hasattr guard is correct; type checkers can't narrow through hasattr
        return editor
