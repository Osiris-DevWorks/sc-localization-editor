"""Main window for Smart Citizen."""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread, pyqtSignal, QModelIndex, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QTabWidget,
    QHeaderView, QStatusBar, QStyledItemDelegate,
    QAbstractItemView, QMenu, QProgressDialog, QProgressBar, QTextBrowser,
    QTableView, QStackedLayout, QGraphicsOpacityEffect,
    QDockWidget,
)
from PyQt6.QtGui import QColor, QFont, QCursor, QPixmap, QIcon, QMouseEvent
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from src.gui.filter_header import FilterHeaderView
from src.gui.string_table_model import (
    StringTableModel, COL_STAR, COL_CUSTOM,
)
from src.models.string_model import StringEntry
from src.parser.ini_parser import load_source_files, load_sources_from_settings
from src.utils.settings import AppSettings
from src.merger.ini_merger import merge_sources_by_hierarchy
from src.utils.version import get_version
from src.utils.perf import timed
from src.utils.app_updater import AppUpdateCheckWorker
from src.gui.config_tab import ConfigTab
from src.gui.theme import get_button_color, get_button_text_color, get_title_color, get_tagline_color, BRAND_FONT_FAMILY
from src.gui.enhancements_tab import EnhancementsTab
from src.gui.log_tab import LogTab
from src.gui.coach_mark import CoachMarkStep, TutorialTour


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
                from src.gui.theme import get_progress_groove_color, get_progress_chunk_color
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


logger = logging.getLogger(__name__)


def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller."""
    base_path = getattr(sys, "_MEIPASS", None)
    if base_path is None:
        # If not running as PyInstaller bundle, use the project root
        base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    return os.path.join(base_path, relative_path)


def _resolve_patches_dir() -> Path:
    """Return the path to the bundled DataForge patches directory."""
    return Path(get_resource_path("patches"))


# Preview-pane token translation — turns the raw loc-string format the game
# reads into styled HTML that mirrors the in-game feel. Patterns:
#   \n              → line break
#   <EM3>X</EM3>    → block-level heading (section dividers)
#   <EM4>X</EM4>    → inline emphasis (stats / tag values)
#   ~mission(Foo)   → greyed placeholder [Foo] (game substitutes at runtime)
# Escape first, then substitute against the escaped tags so raw text
# containing < or & can't break rendering.
import html as _html_mod
import re as _re_mod

_EM3_RE = _re_mod.compile(r"&lt;EM3&gt;(.*?)&lt;/EM3&gt;", _re_mod.DOTALL)
_EM4_RE = _re_mod.compile(r"&lt;EM4&gt;(.*?)&lt;/EM4&gt;", _re_mod.DOTALL)
_MISSION_TOKEN_RE = _re_mod.compile(r"~mission\(([^|)]+)(?:\|[^)]*)?\)")


def _render_preview_html(key: str, raw: str) -> str:
    """Render *raw* loc-string value as styled HTML for the preview pane."""
    if not raw:
        body = "<em style='color:#888;'>(empty)</em>"
    else:
        escaped = _html_mod.escape(raw)
        # Literal backslash-n in the INI → actual line break. Handle the
        # escape sequence as two characters, not a Python newline — the
        # parser reads lines verbatim.
        escaped = escaped.replace("\\n", "<br>")
        escaped = _EM3_RE.sub(
            r'<span style="text-decoration:underline;">\1</span>',
            escaped,
        )
        escaped = _EM4_RE.sub(
            r'<span style="font-weight:bold;color:#4a9eff;">\1</span>',
            escaped,
        )
        escaped = _MISSION_TOKEN_RE.sub(
            r'<span style="color:#888;font-style:italic;">[\1]</span>',
            escaped,
        )
        body = escaped

    return (
        '<div style="font-family:Segoe UI,sans-serif;font-size:10pt;line-height:1.45;">'
        f'<div style="color:#888;font-size:8pt;margin-bottom:8px;'
        f'font-family:Consolas,monospace;">{_html_mod.escape(key)}</div>'
        "<br>"
        f"{body}"
        "</div>"
    )


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
            entries = load_source_files(sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories)
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

    source_starting = pyqtSignal(str)        # source_name (about to sync)
    source_synced = pyqtSignal(str, bool)    # (source_name, was_updated)
    source_error = pyqtSignal(str, str)      # (source_name, error_message)
    finished = pyqtSignal()

    def run(self):
        from src.utils.updater import download_file_if_changed
        from src.utils.settings import AppSettings

        cache_dir = AppSettings.get_cache_dir()
        cache_mapping = {
            AppSettings.SOURCE_GLOBAL:      "base.ini",
        }

        for source_name in [
            AppSettings.SOURCE_GLOBAL,
        ]:
            if not AppSettings.is_source_enabled(source_name):
                continue
            if not AppSettings.get_source_auto_update(source_name):
                continue

            source_url = AppSettings.get_source_path(source_name)
            if not source_url or not source_url.startswith("http"):
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
        import importlib.util
        import sys as sys_module
        from src.utils.dataforge_patcher import apply_patches
        try:
            if getattr(sys, 'frozen', False):
                script_path = Path(sys._MEIPASS) / 'scripts' / 'generate_enhancements_ini.py'
            else:
                script_path = Path(__file__).parent.parent.parent / 'scripts' / 'generate_enhancements_ini.py'

            if not script_path.exists():
                raise FileNotFoundError(f"Enhancements generator script not found: {script_path}")

            base_ini  = AppSettings.get_cache_dir() / 'base.ini'
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
                _resolve_patches_dir(), forge_dir,
                progress_callback=self.progress.emit,
            )
            logger.info(f"DataForge patches: {patch_report.summary_line()}")
            if patch_report.errors:
                for err in patch_report.errors:
                    logger.warning(f"  patch error: {err}")

            self.progress.emit("Loading enhancements generator...")

            module_name = "generate_enhancements_ini_worker"
            if module_name in sys_module.modules:
                del sys_module.modules[module_name]

            spec = importlib.util.spec_from_file_location(module_name, script_path)
            mod = importlib.util.module_from_spec(spec)
            sys_module.modules[module_name] = mod
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

            mod.main(base_ini, forge_dir, categories=self.categories,
                     progress_callback=_on_progress,
                     patches_dir=_resolve_patches_dir())
            logger.info("Enhancements generation worker: mod.main() completed successfully")

            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"Enhancements generation failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class P4kExtractWorker(QThread):
    """Worker thread for extracting global.ini from Data.p4k via unp4k.exe."""

    progress = pyqtSignal(str)   # status message
    progress_pct = pyqtSignal(int, int, str)  # (completed, total, message)
    finished = pyqtSignal(bool)  # True = success
    error = pyqtSignal(str)      # error message (emitted before finished(False))

    def __init__(self, p4k_path, output_path, unp4k_exe):
        super().__init__()
        self._p4k = p4k_path
        self._out = output_path
        self._exe = unp4k_exe

    def run(self):
        from src.utils.pak_extractor import extract_global_ini
        try:
            extract_global_ini(
                self._p4k, self._out, self._exe,
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
        self._p4k       = p4k_path
        self._unp4k_exe = unp4k_exe
        self._unforge_exe = unforge_exe
        self._cache_dir = cache_dir

    def run(self):
        from src.utils.pak_extractor import extract_dataforge
        from src.utils.dataforge_patcher import apply_patches
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
            report = apply_patches(patch_root, self._cache_dir,
                                   progress_callback=self.progress.emit)
            logger.info(f"DataForge patches: {report.summary_line()}")
            if report.errors:
                for err in report.errors:
                    logger.warning(f"  patch error: {err}")
            self.finished.emit(True)
        except Exception as e:
            logger.exception(f"DataForge extraction failed: {e}")
            self.error.emit(str(e))
            self.finished.emit(False)


class SelectAllDelegate(QStyledItemDelegate):
    """Custom delegate that selects all text on edit."""

    def createEditor(self, parent, option, index):
        editor = super().createEditor(parent, option, index)
        if hasattr(editor, 'selectAll'):
            editor.selectAll()
        return editor


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Smart Citizen v{get_version()}")
        self.setGeometry(100, 100, 1400, 800)

        # Set window icon (taskbar + window title bar + favicon)
        icon_path = get_resource_path(os.path.join("assets", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Data
        self.entries: list[StringEntry] = []
        self.filtered_row_indices: list[int] = []
        self.default_values: dict[str, str] = {}  # Store default values from cached base source

        # File loader worker
        self._loader_worker: Optional[FileLoaderWorker] = None

        # Startup sync worker
        self._startup_sync_worker: Optional[StartupSyncWorker] = None

        # P4K extraction worker and progress dialog
        self._p4k_worker: Optional[P4kExtractWorker] = None
        self._p4k_progress: Optional[QProgressDialog] = None

        # Enhancements generation worker
        self._enhancements_worker: Optional[EnhancementsGeneratorWorker] = None
        self._enhancements_progress_dialog: Optional[AnimatedProgressDialog] = None

        # DataForge extraction worker
        self._forge_worker: Optional[DataForgeExtractWorker] = None
        self._forge_progress_dialog: Optional[AnimatedProgressDialog] = None

        # Track whether we've prompted for enhancements on startup (prevents duplicate dialogs)
        self._enhancements_prompted_on_startup = False
        # Flag to defer enhancements checking until after file loading completes (avoid I/O contention)
        self._check_enhancements_after_loading = False

        # Status bar state (composed message) - tracks sync status per source
        self._source_status: dict[str, str] = {}  # source_name -> status_string

        # Progress dialogs
        self._startup_progress: Optional[AnimatedProgressDialog] = None
        self._loading_progress: Optional[QProgressDialog] = None
        self._eye_label: Optional[QLabel] = None
        self._eye_pulse: Optional[QPropertyAnimation] = None
        self._eye_glow: Optional[QGraphicsOpacityEffect] = None
        self._eye_fadeout: Optional[QPropertyAnimation] = None
        self._eye_pulse_monitor: Optional[QTimer] = None
        self.osiris_button: QWidget
        self.feedback_label: ClickableLabel
        self.paypal_button: ClickableLabel
        self.venmo_button: ClickableLabel

        # App self-update check
        self._update_check_worker: Optional[AppUpdateCheckWorker] = None
        self._latest_release_url: Optional[str] = None
        self.help_dock: Optional[QDockWidget] = None
        self._tutorial_tour: Optional[TutorialTour] = None
        self._channel_indicator: Optional[QLabel] = None
        self._app_version_indicator: Optional[ClickableLabel] = None

        # Build UI
        self.setup_ui()
        self.restore_window_state()

        # Ensure cache directory exists
        AppSettings.get_cache_dir()

        # Startup tasks (source sync + app-update check) are NOT kicked off
        # here on purpose. They get scheduled by _maybe_start_first_run_tutorial
        # so that, on a first-run launch where the guided tour is about to
        # appear, their modal prompts (P4K extraction, "new version available",
        # enhancements pipeline) don't pop over the coach-mark overlay and
        # break the tour. See _start_post_tutorial_tasks.

        # Ensure user.cfg has language setting
        from src.utils.user_cfg import ensure_user_cfg_language
        ensure_user_cfg_language()

        logger.info("MainWindow initialized")

    def _status_bar(self) -> QStatusBar:
        """Return the window status bar, creating it if needed."""
        status_bar = self.statusBar()
        if status_bar is None:
            status_bar = QStatusBar(self)
            self.setStatusBar(status_bar)
        return status_bar

    def setup_ui(self):
        """Build user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Title bar — branded font (Hyperspace Race Expanded Bold)
        self.title_label = QLabel("SMART CITIZEN")
        title_font = QFont(BRAND_FONT_FAMILY)
        title_font.setPointSize(22)
        self.title_label.setFont(title_font)
        main_layout.addWidget(self.title_label)

        self.tagline_label = QLabel("SMARTER STRINGS FOR STAR CITIZEN")
        main_layout.addWidget(self.tagline_label)
        self._apply_branding_styles()

        # Toolbar on the left; rendered-preview pane on the right. The
        # preview renders the currently-selected row's effective value
        # (custom override if present, else the merged baseline) with the
        # game's EM3/EM4/~mission(...) tokens translated into styled HTML
        # so mission and journal blocks read like in-game text instead of
        # wall-of-tag. Stays wired across all tabs — it just reflects the
        # last row you selected in the String Editor.
        toolbar_layout = self.create_toolbar()

        self.preview_pane = QTextBrowser()
        self.preview_pane.setReadOnly(True)
        self.preview_pane.setOpenExternalLinks(False)
        self.preview_pane.setPlaceholderText(
            "Select a row to preview its rendered text."
        )
        self.preview_pane.setMinimumWidth(420)
        self.preview_pane.setMaximumHeight(200)

        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(12)
        toolbar_row.setContentsMargins(0, 0, 12, 0)
        toolbar_row.addLayout(toolbar_layout, stretch=2)
        toolbar_row.addWidget(self.preview_pane, stretch=1)
        main_layout.addLayout(toolbar_row)

        # Tabs
        self.tabs = QTabWidget()
        self._strings_tab_index = self.tabs.addTab(self.create_strings_tab(), "String Editor")

        # Config tab
        self.config_tab = ConfigTab()
        self.config_tab.merge_requested.connect(self.perform_merge_and_reload)
        self.config_tab.p4k_extract_requested.connect(self._run_p4k_extraction)
        self.config_tab.import_ini_requested.connect(self._handle_import_ini)
        self.config_tab.channel_changed.connect(self._on_channel_changed)
        self.config_tab.check_updates_requested.connect(self._on_check_updates_clicked)
        self._config_tab_index = self.tabs.addTab(self.config_tab, "Config")

        # Enhancements tab
        self.enhancements_tab = EnhancementsTab()
        self.enhancements_tab.merge_requested.connect(self.perform_merge_and_reload)
        self.enhancements_tab.enhancements_pipeline_requested.connect(self._run_enhancements_pipeline)
        self._enhancements_tab_index = self.tabs.addTab(self.enhancements_tab, "Enhancements")

        self.log_tab = LogTab()
        self.tabs.addTab(self.log_tab, "Log")

        self.tabs.addTab(self.create_about_tab(), "About")

        # Revert unapplied enhancement checkbox changes when leaving the tab
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._previous_tab_index = self.tabs.currentIndex()

        main_layout.addWidget(self.tabs)

        # Footer
        footer_layout = self.create_footer()
        main_layout.addLayout(footer_layout)

        # Help side-panel. Created eagerly (before restore_window_state runs)
        # so Qt's native saveState/restoreState can persist its open/closed
        # width across sessions — a dock only gets remembered if it exists
        # with a stable objectName at restoreState() time. Start hidden so
        # first-launch users aren't surprised by a panel they didn't ask for;
        # restoreState will reopen it if the user had it open last session.
        self._ensure_help_dock()
        self.help_dock.hide()

        # App-version indicator sits immediately next to the SC-version
        # text in the status bar message area. Added BEFORE the channel
        # indicator so it lands leftmost in the permanent-widget zone
        # (QStatusBar lays these out left-to-right in addition order, with
        # the first-added sitting closest to the message text).
        self._ensure_app_version_indicator()

        # Channel indicator on the right side of the status bar. Installed
        # now so it's visible before any source loading kicks off — users
        # who launch into an empty cache still see which channel they're on.
        self._ensure_channel_indicator()

    def _on_tab_changed(self, new_index: int):
        """Revert unapplied enhancement checkbox changes when leaving the Enhancements tab."""
        if self._previous_tab_index == self._enhancements_tab_index and new_index != self._enhancements_tab_index:
            self.enhancements_tab.revert_category_checkboxes()
        self._previous_tab_index = new_index

    def create_toolbar(self) -> QVBoxLayout:
        """Create toolbar with buttons."""
        layout = QVBoxLayout()

        # Button row
        button_layout = QHBoxLayout()

        # Blue group — read / navigate
        self.open_loc_dir_btn = QPushButton("Open Localization Dir")
        self.open_loc_dir_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.open_loc_dir_btn.setToolTip("Open the game's localization directory in Windows Explorer")
        self.open_loc_dir_btn.clicked.connect(self.open_localization_dir)
        button_layout.addWidget(self.open_loc_dir_btn)

        # Green — commit
        self.apply_btn = QPushButton("Apply to Game")
        self.apply_btn.setStyleSheet(f"background-color: {get_button_color('apply')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.apply_btn.setToolTip("Write the merged table contents to the game's global.ini. A timestamped backup of the current global.ini is created first.")
        self.apply_btn.clicked.connect(self.apply_to_game)
        button_layout.addWidget(self.apply_btn)

        # Red-orange — rollback
        self.restore_backup_btn = QPushButton("Restore Backup")
        self.restore_backup_btn.setStyleSheet(f"background-color: {get_button_color('restore')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.restore_backup_btn.setToolTip("Restore a previous global.ini from Documents\\Smart Citizen\\backups\\. Up to 5 timestamped backups are kept; the oldest is pruned when a new one is created.")
        self.restore_backup_btn.clicked.connect(self.restore_backup)
        button_layout.addWidget(self.restore_backup_btn)

        # Gray group — cleanup
        self.clear_loc_btn = QPushButton("Clear Localization")
        self.clear_loc_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.clear_loc_btn.setToolTip("Delete the applied global.ini from the game's localization directory, reverting to vanilla game text")
        self.clear_loc_btn.clicked.connect(self.clear_localization)
        button_layout.addWidget(self.clear_loc_btn)

        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.clear_cache_btn.setToolTip("Delete all cached source files (base.ini, contracts.ini, etc.) from the local cache directory")
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        button_layout.addWidget(self.clear_cache_btn)

        # Help — sits with the other toolbar buttons rather than floating
        # right; uses the 'open' role so it shares the blue/cyan/gold
        # information-action palette with Open Localization Dir.
        self.help_btn = QPushButton("Help")
        self.help_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.help_btn.setCheckable(True)
        self.help_btn.setToolTip("Toggle the Help side-panel")
        self.help_btn.clicked.connect(self.show_help)
        button_layout.addWidget(self.help_btn)

        # Tutorial — shares the 'open' blue/cyan/gold info-action role with
        # Help so the two read as a pair. Always restartable on demand.
        self.tutorial_btn = QPushButton("Tutorial")
        self.tutorial_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.tutorial_btn.setToolTip("Start the guided tour of Smart Citizen's workflow — runs automatically on first launch; click here anytime to replay.")
        self.tutorial_btn.clicked.connect(self._start_tutorial)
        button_layout.addWidget(self.tutorial_btn)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        # Filter row
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(200)
        self.category_combo.setToolTip("Filter rows by domain (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other). Categories are derived from the loc-key prefix.")
        self.category_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.category_combo)

        filter_layout.addWidget(QLabel("Status:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "Modified", "Unmodified", "New"])
        self.status_combo.setMaximumWidth(120)
        self.status_combo.setToolTip("Filter by modification status. Modified = you've set a Custom Value; New = key exists only in enhancements/user.ini, not in the base file; Unmodified = default text only.")
        self.status_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_combo)

        self.hide_unmodified_check = QCheckBox("Hide Unmodified")
        self.hide_unmodified_check.setToolTip("Show only rows where you've set a Custom Value. Same as the Status filter's Modified option but togglable on its own.")
        self.hide_unmodified_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.hide_unmodified_check)

        self.favorites_only_check = QCheckBox("★ Favorites Only")
        self.favorites_only_check.setToolTip("Show only rows you've starred as favorites. Favorites get a configurable prefix prepended to their name so they sort to the top of the in-game list.")
        self.favorites_only_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.favorites_only_check)

        self.grouped_sort_btn = QPushButton("Group Sort")
        self.grouped_sort_btn.setToolTip("Sort titles and descriptions together for the same entity")
        self.grouped_sort_btn.setMaximumWidth(100)
        self.grouped_sort_btn.clicked.connect(self._on_grouped_sort)
        filter_layout.addWidget(self.grouped_sort_btn)

        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.setMaximumWidth(100)
        self.clear_filters_btn.setToolTip("Reset every filter (category, status, search, per-column boxes, checkboxes) so the full table is shown.")
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_layout.addWidget(self.clear_filters_btn)

        self.copy_filtered_btn = QPushButton("Copy Filtered")
        self.copy_filtered_btn.setMaximumWidth(100)
        self.copy_filtered_btn.setToolTip("Copy all visible filtered rows to clipboard (tab-separated)")
        self.copy_filtered_btn.clicked.connect(self.copy_filtered_to_clipboard)
        filter_layout.addWidget(self.copy_filtered_btn)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        return layout

    def create_footer(self) -> QHBoxLayout:
        """Create footer with Osiris DevWorks branding and donation buttons."""
        footer_layout = QHBoxLayout()
        footer_layout.setContentsMargins(8, 8, 8, 0)

        # Osiris DevWorks logo (left side). Built as a stacked pair so the
        # Eye of Horus glyph can pulse-glow while a background worker is
        # running. Base pixmap is the full logo; `osiris-eye-glow.png` is a
        # same-size pre-rendered overlay with the eye + a baked-in gold halo
        # stacked on top. We animate the overlay's QGraphicsOpacityEffect
        # between 0 and 1 — opacity interpolation on a static sprite is
        # exact float math and never re-renders, so no sub-pixel jitter
        # (the earlier QGraphicsDropShadowEffect-on-the-fly approach had
        # the shadow kernel rebuilt every frame and read as visibly shaky).
        osiris_image_path = get_resource_path(os.path.join("assets", "osiris-devworks.png"))
        osiris_glow_path = get_resource_path(os.path.join("assets", "osiris-eye-glow.png"))

        if os.path.exists(osiris_image_path) and os.path.exists(osiris_glow_path):
            self.osiris_button = ClickableWidget()
            stack = QStackedLayout(self.osiris_button)
            stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
            stack.setContentsMargins(0, 0, 0, 0)

            base_label = QLabel()
            base_pixmap = QPixmap(osiris_image_path)
            if base_pixmap.height() > 40:
                base_pixmap = base_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            base_label.setPixmap(base_pixmap)

            self._eye_label = QLabel()
            glow_pixmap = QPixmap(osiris_glow_path)
            if glow_pixmap.height() > 40:
                glow_pixmap = glow_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self._eye_label.setPixmap(glow_pixmap)

            self._eye_glow = QGraphicsOpacityEffect(self._eye_label)
            self._eye_glow.setOpacity(0.0)
            self._eye_label.setGraphicsEffect(self._eye_glow)

            self._eye_pulse = QPropertyAnimation(self._eye_glow, b"opacity", self)
            self._eye_pulse.setDuration(1800)
            self._eye_pulse.setKeyValueAt(0.0, 0.0)
            self._eye_pulse.setKeyValueAt(0.5, 1.0)
            self._eye_pulse.setKeyValueAt(1.0, 0.0)
            self._eye_pulse.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._eye_pulse.setLoopCount(-1)

            # Separate one-shot animation used when work ends mid-pulse —
            # eases the current opacity down to 0 instead of snapping off.
            self._eye_fadeout = QPropertyAnimation(self._eye_glow, b"opacity", self)
            self._eye_fadeout.setEasingCurve(QEasingCurve.Type.InOutSine)
            self._eye_fadeout.setEndValue(0.0)

            stack.addWidget(base_label)
            stack.addWidget(self._eye_label)

            # Pin to the scaled logo's natural size — opacity animation
            # doesn't expand the paint rect the way drop-shadow did, so no
            # extra padding is needed.
            self.osiris_button.setFixedSize(base_pixmap.size())

            self.osiris_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.osiris_button.setToolTip("Open the Osiris DevWorks GitHub organization")
            self.osiris_button.clicked.connect(self.open_osiris_github)
            footer_layout.addWidget(self.osiris_button)

            # Poll every 300ms and toggle the pulse to match worker state.
            # Cheaper than wiring into every worker start/finish slot and
            # robust to every extraction/generation/load entrypoint.
            self._eye_pulse_monitor = QTimer(self)
            self._eye_pulse_monitor.setInterval(300)
            self._eye_pulse_monitor.timeout.connect(self._update_eye_pulse)
            self._eye_pulse_monitor.start()
        else:
            # Fallback to styled text button
            self.osiris_button = ClickableLabel("Osiris DevWorks")
            self.osiris_button.setStyleSheet("""
                QLabel {
                    background-color: #1a1f2e;
                    color: #c9a961;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QLabel:hover {
                    background-color: #242938;
                }
            """)
            self._eye_pulse = None
            self._eye_glow = None
            self._eye_fadeout = None
            self.osiris_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            self.osiris_button.setToolTip("Open the Osiris DevWorks GitHub organization")
            self.osiris_button.clicked.connect(self.open_osiris_github)
            footer_layout.addWidget(self.osiris_button)

        # Feedback button — sits immediately to the right of the Osiris logo.
        # Image link to the dedicated Smart Citizen channel in the Osiris
        # DevWorks Discord; falls back to a styled text label if the asset
        # is missing.
        footer_layout.addSpacing(10)
        self.feedback_label = ClickableLabel()
        discord_image_path = get_resource_path(os.path.join("assets", "discord.png"))
        if os.path.exists(discord_image_path):
            discord_pixmap = QPixmap(discord_image_path)
            if discord_pixmap.height() > 40:
                discord_pixmap = discord_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.feedback_label.setPixmap(discord_pixmap)
        else:
            self.feedback_label.setText("Feedback, Bugs, & Feature Voting")
            self.feedback_label.setStyleSheet("font-size: 12px;")
        self.feedback_label.setToolTip(
            "Open the Smart Citizen Discord channel for feedback, bug reports, and voting on "
            "upcoming features (requires joining the Osiris DevWorks Discord)."
        )
        self.feedback_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.feedback_label.clicked.connect(self.open_feedback_link)
        footer_layout.addWidget(self.feedback_label)

        # Stretch to push the donation cluster to the right.
        footer_layout.addStretch()

        # PayPal button (right side)
        self.paypal_button = ClickableLabel()
        paypal_image_path = get_resource_path(os.path.join("assets", "paypal.png"))

        # Try to load PayPal image, fall back to text if not found
        if os.path.exists(paypal_image_path):
            paypal_pixmap = QPixmap(paypal_image_path)
            # Scale to match Osiris button (max height 40px)
            if paypal_pixmap.height() > 40:
                paypal_pixmap = paypal_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.paypal_button.setPixmap(paypal_pixmap)
        else:
            # Fallback to styled text button
            self.paypal_button.setText("Donate via PayPal")
            self.paypal_button.setStyleSheet("""
                QLabel {
                    background-color: #0070ba;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QLabel:hover {
                    background-color: #005ea6;
                }
            """)

        self.paypal_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.paypal_button.clicked.connect(self.open_paypal_donation)
        footer_layout.addWidget(self.paypal_button)

        # Spacer between PayPal and Venmo
        footer_layout.addSpacing(10)

        # Venmo button (right side)
        self.venmo_button = ClickableLabel()
        venmo_image_path = get_resource_path(os.path.join("assets", "venmo.png"))

        # Try to load Venmo image, fall back to text button
        if os.path.exists(venmo_image_path):
            venmo_pixmap = QPixmap(venmo_image_path)
            # Scale to match Osiris button (max height 40px)
            if venmo_pixmap.height() > 40:
                venmo_pixmap = venmo_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.venmo_button.setPixmap(venmo_pixmap)
        else:
            # Fallback to styled text button
            self.venmo_button.setText("Venmo")
            self.venmo_button.setStyleSheet("""
                QLabel {
                    background-color: #008CFF;
                    color: white;
                    padding: 8px 16px;
                    border-radius: 4px;
                    font-size: 12px;
                    font-weight: bold;
                }
                QLabel:hover {
                    background-color: #0074D9;
                }
            """)

        self.venmo_button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.venmo_button.clicked.connect(self.open_venmo_donation)
        footer_layout.addWidget(self.venmo_button)

        return footer_layout

    def open_osiris_github(self, _event: object | None = None) -> None:
        """Open the Osiris DevWorks GitHub organization in browser."""
        QDesktopServices.openUrl(QUrl("https://github.com/Osiris-DevWorks"))

    def open_feedback_link(self, _event: object | None = None) -> None:
        """Open the dedicated Smart Citizen feedback channel in browser."""
        feedback_url = "https://discord.com/channels/1438175448420057323/1472394204347895890"
        QDesktopServices.openUrl(QUrl(feedback_url))

    def open_paypal_donation(self, _event: object | None = None) -> None:
        """Open PayPal donation link in browser."""
        paypal_url = "https://paypal.me/RighteousKill"
        QDesktopServices.openUrl(QUrl(paypal_url))

    def open_venmo_donation(self, _event: object | None = None) -> None:
        """Open Venmo donation link in browser."""
        venmo_url = "https://venmo.com/u/Amr-Abouelleil"
        QDesktopServices.openUrl(QUrl(venmo_url))

    # ── App self-update ─────────────────────────────────────────────────────

    # Auto-check runs on startup but only every 6h to stay under GitHub's
    # 60-req/hr unauthenticated rate limit.
    _UPDATE_CHECK_MIN_INTERVAL_SECONDS = 6 * 60 * 60

    def _maybe_auto_check_app_updates(self) -> None:
        """Kick off an app-update check iff the throttle window has elapsed."""
        import time
        last = AppSettings.get_last_update_check_epoch()
        now = int(time.time())
        if last and now - last < self._UPDATE_CHECK_MIN_INTERVAL_SECONDS:
            logger.debug(
                f"Skipping auto update check (last ran {now - last}s ago, "
                f"throttle {self._UPDATE_CHECK_MIN_INTERVAL_SECONDS}s)"
            )
            return
        self._run_app_update_check(force_dialog=False)

    def _on_check_updates_clicked(self) -> None:
        """Handle the Config tab's 'Check for Updates' button."""
        self._run_app_update_check(force_dialog=True)

    def _run_app_update_check(self, force_dialog: bool) -> None:
        """Spawn a single ``AppUpdateCheckWorker`` — no-op if one is running."""
        if self._update_check_worker is not None:
            logger.debug("Update check already in flight; ignoring new request")
            return

        worker = AppUpdateCheckWorker(self)
        self._update_check_worker = worker
        self._force_update_dialog = force_dialog

        worker.update_available.connect(self._on_update_available)
        worker.up_to_date.connect(self._on_update_up_to_date)
        worker.check_error.connect(self._on_update_check_error)
        worker.finished.connect(self._on_update_check_finished)

        self.config_tab.set_check_updates_enabled(False)
        self.config_tab.set_update_status("Checking…")
        worker.start()

    @pyqtSlot(str, str, str)
    def _on_update_available(self, latest: str, url: str, body: str) -> None:
        current = get_version()
        self._latest_release_url = url
        indicator = self._app_version_indicator
        if indicator is None:
            self._ensure_app_version_indicator()
            indicator = self._app_version_indicator
        if indicator is None:
            return
        indicator.setText(f"v{current} · update available")
        indicator.setStyleSheet(
            "font-size: 11px; padding: 0 8px; color: #c9a961; font-weight: bold;"
        )
        indicator.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        indicator.setToolTip(f"Open release page for v{latest}")
        self.config_tab.set_update_status(f"v{latest} available")

        # Truncate long release bodies for the dialog so the modal doesn't
        # stretch off-screen. Users get the full notes on the release page.
        excerpt = body.strip()
        if len(excerpt) > 600:
            excerpt = excerpt[:600].rstrip() + "…"

        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Information)
        msg.setWindowTitle("Smart Citizen — Update Available")
        text = f"A new version is available: v{latest}\nYou are on v{current}."
        if excerpt:
            text += f"\n\n—\n{excerpt}"
        msg.setText(text)
        open_btn = msg.addButton("Open Release Page", QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(open_btn)
        msg.exec()
        if msg.clickedButton() is open_btn:
            QDesktopServices.openUrl(QUrl(url))

    @pyqtSlot(str)
    def _on_update_up_to_date(self, current: str) -> None:
        self._latest_release_url = None
        indicator = self._app_version_indicator
        if indicator is None:
            self._ensure_app_version_indicator()
            indicator = self._app_version_indicator
        if indicator is None:
            return
        indicator.setText(f"v{current} · up to date")
        indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        indicator.setToolTip("")
        self.config_tab.set_update_status(f"Up to date (v{current})")
        if getattr(self, "_force_update_dialog", False):
            QMessageBox.information(
                self,
                "Smart Citizen — Up to Date",
                f"You are on the latest version (v{current}).",
            )

    @pyqtSlot(str)
    def _on_update_check_error(self, message: str) -> None:
        self._latest_release_url = None
        current = get_version()
        indicator = self._app_version_indicator
        if indicator is None:
            self._ensure_app_version_indicator()
            indicator = self._app_version_indicator
        if indicator is None:
            return
        indicator.setText(f"v{current} · check failed")
        indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        indicator.setToolTip(message)
        self.config_tab.set_update_status("Check failed")
        logger.warning(f"App update check error: {message}")
        if getattr(self, "_force_update_dialog", False):
            QMessageBox.warning(
                self,
                "Smart Citizen — Update Check Failed",
                f"Could not check for updates:\n\n{message}",
            )

    @pyqtSlot()
    def _on_update_check_finished(self) -> None:
        import time
        AppSettings.set_last_update_check_epoch(int(time.time()))
        worker = self._update_check_worker
        if worker is not None:
            worker.quit()
            worker.wait()
            worker.deleteLater()
            self._update_check_worker = None
        self._force_update_dialog = False
        self.config_tab.set_check_updates_enabled(True)

    def _on_version_label_clicked(self, _event: object | None = None) -> None:
        """Footer version label click — opens the release page when available."""
        if self._latest_release_url:
            QDesktopServices.openUrl(QUrl(self._latest_release_url))

    def create_strings_tab(self) -> QWidget:
        """Create strings table tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Model
        self._model = StringTableModel(self)

        # Table view
        self.table = QTableView()
        self.table.setModel(self._model)

        # Per-column filter header
        column_names = ["Category", "Key", "Default Value", "Current Value", "★", "Custom Value", "Status"]
        self.filter_header = FilterHeaderView(column_names, self.table, skip_columns={0, 4, 6})
        self.table.setHorizontalHeader(self.filter_header)
        self.filter_header.filter_changed.connect(self.apply_filters)

        # Table settings
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Hide row numbers
        vertical_header = self.table.verticalHeader()
        if vertical_header is not None:
            vertical_header.setVisible(False)

        # Set column widths
        header = self.filter_header
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # Category
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)           # Key
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)           # Default Value
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)           # Current Value
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # ★
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)           # Custom Value
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # Status

        # Set custom delegate for editing Custom Value column (col 5)
        self.table.setItemDelegateForColumn(COL_CUSTOM, SelectAllDelegate())
        # Star column click handling
        self.table.clicked.connect(self._on_cell_clicked)

        layout.addWidget(self.table)

        # Hook selection after the model is attached so selectionModel() exists.
        # Drives the top-right preview pane created in setup_ui().
        selection_model = self.table.selectionModel()
        if selection_model is not None:
            selection_model.currentRowChanged.connect(self._on_preview_row_changed)

        # Status label
        self.table_status_label = QLabel("No data loaded")
        layout.addWidget(self.table_status_label)

        return widget

    def create_about_tab(self) -> QWidget:
        """Create about tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.about_browser = QTextBrowser()
        self.about_browser.setOpenExternalLinks(True)
        self._render_about_html()
        layout.addWidget(self.about_browser)
        return widget

    def _render_about_html(self):
        """(Re)render the About tab HTML using the current palette. Also
        force the browser's palette to match so its chrome (viewport bg,
        scrollbars) tracks the theme — widget-local palette can otherwise
        lag behind QApplication.setPalette."""
        from PyQt6.QtWidgets import QApplication
        self.about_browser.setPalette(QApplication.palette())
        try:
            about_path = get_resource_path("ABOUT.md")
            with open(about_path, 'r', encoding='utf-8') as f:
                about_content = f.read()
            about_content = about_content.replace(
                "# Smart Citizen",
                f"# Smart Citizen v{get_version()}"
            )
            self.about_browser.setHtml(self.markdown_to_html(about_content))
        except Exception as e:
            logger.error(f"Error loading ABOUT.md: {e}", exc_info=True)
            self.about_browser.setHtml(
                f"<h1>About</h1><p>Unable to load about information.</p>"
                f"<p style='color: gray;'>{str(e)}</p>"
            )

    @pyqtSlot()
    def _set_toolbar_enabled(self, enabled: bool):
        """Toggle toolbar button enabled states."""
        self.apply_btn.setEnabled(enabled)
        self.restore_backup_btn.setEnabled(enabled)
        self.clear_loc_btn.setEnabled(enabled)

    @timed
    def load_default_values(self):
        """Load default values from cached base source in AppData."""
        from src.parser.ini_parser import parse_ini_file

        cache_file = AppSettings.get_cache_dir() / "base.ini"

        if cache_file.exists():
            try:
                # Parse cached base.ini and convert to dict for lookup
                parsed = parse_ini_file(cache_file)
                self.default_values = {key: value for key, value in parsed.items()}
                logger.info(f"Loaded {len(self.default_values)} default values from cache")
            except Exception as e:
                logger.warning(f"Failed to load default values from {cache_file}: {e}")
        else:
            logger.debug(f"Cache file not found: {cache_file}. Default values will be empty until sources are downloaded.")

    @pyqtSlot()
    @timed
    def apply_to_game(self):
        """Apply merged sources + user edits to game installation and backup existing file."""
        if not self.entries:
            QMessageBox.warning(self, "Warning", "Please load a file first")
            return

        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, "Warning", "Please configure game install path in Config tab")
            return

        target_path = AppSettings.get_global_ini_path()

        try:
            import shutil
            from datetime import datetime

            target_path.parent.mkdir(parents=True, exist_ok=True)

            backup_path = None  # Tracks the backup created this apply (used for restore on validation failure)

            # Backup existing file if it exists
            if target_path.exists():
                backup_dir = AppSettings.get_backups_dir()

                # Find all existing backups
                backup_files = sorted(
                    backup_dir.glob("global.ini.bak_*"),
                    key=lambda f: f.stat().st_mtime
                )

                # Delete oldest backup if we already have 5
                if len(backup_files) >= 5:
                    oldest_backup = backup_files[0]
                    oldest_backup.unlink()
                    logger.info(f"Deleted oldest backup: {oldest_backup.name}")

                # Create new backup
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = backup_dir / f"global.ini.bak_{timestamp}"
                shutil.copy2(target_path, backup_path)
                logger.info(f"Backed up existing file to {backup_path}")

            # Build final merged dict by re-merging all sources with user edits
            # This ensures Apply uses latest source versions and user edits
            sources_dict, hierarchy, _mrk = load_sources_from_settings()

            # Warn if any active sources are missing (only check sources actually in AVAILABLE_SOURCES)
            active_source_names = set(AppSettings.AVAILABLE_SOURCES)
            active_source_names.add("enhancements")
            missing_sources = [
                name for name in hierarchy
                if name in active_source_names
                and name != AppSettings.SOURCE_USER and name != "enhancements"
                and name not in sources_dict
                and AppSettings.is_source_enabled(name)
            ]
            if missing_sources:
                names = ", ".join(missing_sources)
                reply = QMessageBox.warning(
                    self, "Missing Sources",
                    f"The following enabled sources could not be loaded:\n\n  {names}\n\n"
                    "Their customizations will NOT be included in the applied file.\n\n"
                    "Apply anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Build user overrides dict from entries with custom_value
            user_overrides_dict = {
                entry.key: entry.custom_value
                for entry in self.entries
                if entry.custom_value
            }

            # Merge all sources in hierarchy order, with user edits on top
            merged_dict = merge_sources_by_hierarchy(sources_dict, hierarchy, user_overrides_dict)

            # Get a base file to use for structure preservation
            # Use the first source file from hierarchy
            base_file = None
            for source_name in hierarchy:
                source_path = AppSettings.get_source_path(source_name)
                # Check if it's a URL (remote source) - use cache
                if source_path and (source_path.startswith('http://') or source_path.startswith('https://')):
                    # Map source name to cache file
                    cache_mapping = {
                        AppSettings.SOURCE_GLOBAL:      "base.ini",
                    }
                    if source_name in cache_mapping:
                        cache_file = AppSettings.get_cache_dir() / cache_mapping[source_name]
                        if cache_file.exists():
                            base_file = cache_file
                            break
                # Otherwise check if it's a local file that exists
                elif source_path and Path(source_path).exists():
                    base_file = source_path
                    break

            if not base_file:
                raise FileNotFoundError("No base file found. Configure sources and download them first.")

            # Use merger to preserve original file structure
            from src.merger.ini_merger import merge_ini_files
            merge_ini_files(str(base_file), merged_dict, str(target_path))

            # Validate written file against stock base. Pass the already-parsed
            # base.ini key set so validation skips a redundant 87k-line parse.
            # sources_dict["global"] holds the parsed base.ini from
            # load_sources_from_settings() above; fall back to on-disk read if
            # the global source wasn't loaded (e.g. missing cache).
            stock_keys_hint = (
                set(sources_dict["global"].keys())
                if AppSettings.SOURCE_GLOBAL in sources_dict
                else None
            )
            validation_msg = self._validate_applied_file(target_path, stock_keys=stock_keys_hint)

            if validation_msg:
                # Delete the bad file and restore the backup we just made
                try:
                    target_path.unlink()
                    logger.warning(f"Deleted invalid output file: {target_path}")
                except Exception as del_err:
                    logger.error(f"Could not delete invalid file: {del_err}")

                if backup_path and backup_path.exists():
                    try:
                        shutil.copy2(backup_path, target_path)
                        logger.info(f"Restored backup: {backup_path.name}")
                        restore_note = f"\n\nThe previous file has been restored from backup:\n{backup_path.name}"
                    except Exception as restore_err:
                        logger.error(f"Could not restore backup: {restore_err}")
                        restore_note = "\n\nCould not restore backup — game will use vanilla text."
                else:
                    restore_note = "\n\nNo backup was available to restore."

                self.statusBar().showMessage("Apply failed — validation error")
                QMessageBox.critical(
                    self, "Validation Failed",
                    f"The written file failed validation and has been deleted.\n\n"
                    f"{validation_msg}"
                    f"{restore_note}"
                )
                return

            # Save user overrides to AppData
            from src.utils.user_ini_manager import save_user_ini
            user_count = save_user_ini(self.entries, AppSettings.get_user_ini_path())

            # Count enhancement entries
            enhancement_count = sum(
                1 for entry in self.entries
                if entry.source_file == "enhancements"
            )

            # Ensure user.cfg has language setting
            from src.utils.user_cfg import ensure_user_cfg_language
            ensure_user_cfg_language()

            logger.info(f"Applied to game: {target_path}")
            self.statusBar().showMessage(
                f"Applied to game | {user_count} user edits | {enhancement_count} enhancements"
            )
            QMessageBox.information(
                self, "Success",
                f"Applied to {target_path}\n\n"
                f"  User edits: {user_count}\n"
                f"  SCLE enhancements: {enhancement_count}"
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply to game: {e}")
            logger.error(f"Error applying to game: {e}")

    def _validate_applied_file(
        self,
        written_path: Path,
        stock_keys: set[str] | None = None,
    ) -> str:
        """Validate the written global.ini against the stock base.ini.

        Checks that every key in base.ini is present in the written file.
        Values are allowed to differ. Extra keys (from components/contracts/
        commodities sources) are expected and not treated as errors.

        Args:
            written_path: Path to the global.ini just written to the game directory.
            stock_keys: Optional pre-parsed set of base.ini keys. If provided,
                skips a redundant ~87k-line parse — apply_to_game already has
                base.ini in memory via load_sources_from_settings(). The
                written-file parse remains (independent verification against
                a merger bug).

        Returns:
            Empty string if validation passed, or a human-readable warning message
            describing any missing keys.
        """
        from src.parser.ini_parser import parse_ini_file

        if stock_keys is None:
            stock_path = AppSettings.get_cache_dir() / "base.ini"
            if not stock_path.exists():
                logger.warning("Validation skipped: base.ini not found in cache")
                return ""
            try:
                stock_keys = set(parse_ini_file(stock_path).keys())
            except Exception as e:
                logger.warning(f"Validation error reading stock base.ini: {e}")
                return ""

        try:
            written_keys = set(parse_ini_file(written_path).keys())
        except Exception as e:
            logger.warning(f"Validation error reading written file: {e}")
            return ""

        missing = stock_keys - written_keys
        extra = written_keys - stock_keys

        logger.info(
            f"Validation: stock={len(stock_keys)} keys, "
            f"written={len(written_keys)} keys, "
            f"missing={len(missing)}, extra={len(extra)}"
        )

        if not missing and not extra:
            return ""

        lines = []

        if missing:
            sample = sorted(missing)[:20]
            lines += [f"{len(missing)} key(s) from base.ini are missing from the written file:"]
            lines += [f"  {k}" for k in sample]
            if len(missing) > 20:
                lines.append(f"  ... and {len(missing) - 20} more")

        if extra:
            if lines:
                lines.append("")
            sample = sorted(extra)[:20]
            lines += [f"{len(extra)} unexpected key(s) in written file (not in base.ini):"]
            lines += [f"  {k}" for k in sample]
            if len(extra) > 20:
                lines.append(f"  ... and {len(extra) - 20} more")

        lines += ["", "The previous file has been restored. Check your source configuration."]
        return "\n".join(lines)

    @pyqtSlot()
    def clear_localization(self):
        """Delete global.ini from the active channel's localization directory, reverting to vanilla text."""
        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, "Warning", "Please configure game install path in Config tab")
            return

        global_ini = AppSettings.get_global_ini_path()
        loc_dir = global_ini.parent

        if not global_ini.exists():
            QMessageBox.information(self, "Nothing to Clear",
                "No custom global.ini found in the game's localization directory.\n"
                "The game is already using vanilla text.")
            return

        reply = QMessageBox.question(
            self, "Clear Localization",
            f"This will delete the custom global.ini from:\n{loc_dir}\n\n"
            "The game will revert to its default (vanilla) localization text.\n\n"
            "Your overrides are preserved in the app and can be re-applied at any time.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            global_ini.unlink()
            logger.info(f"Deleted {global_ini}")
            self.statusBar().showMessage("Localization cleared — game reverted to vanilla text")
            QMessageBox.information(self, "Done",
                "Custom localization removed.\n"
                "The game will now use its default text.\n\n"
                "To re-apply your overrides and stat descriptions, click Apply to Game.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete global.ini: {e}")
            logger.error(f"Error clearing localization: {e}")

    @pyqtSlot()
    def clear_cache(self):
        """Delete cached source files from the cache directory. Optionally clear DataForge cache."""
        import shutil
        from PyQt6.QtWidgets import QApplication
        cache_dir = AppSettings.get_cache_dir()
        cached_files = list(cache_dir.glob("*.ini")) + list(cache_dir.glob("*.txt"))

        # Also check for dataforge directory
        dataforge_dir = cache_dir / "dataforge"
        has_dataforge = dataforge_dir.exists()

        if not cached_files and not has_dataforge:
            QMessageBox.information(self, "Cache Empty", "The cache directory is already empty.")
            return

        # First dialog: clear regular cache files
        file_list = "\n".join(f"  {f.name}" for f in sorted(cached_files))
        msg = f"This will delete the following cached files:\n\n{file_list}\n\n"
        msg += "base.ini will need to be re-extracted from Data.p4k before strings can be loaded."

        reply = QMessageBox.question(
            self, "Clear Cache", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted, failed = [], []

        # Show progress dialog while deleting files
        progress = AnimatedProgressDialog("Clearing cache files...", parent=self, title="Clearing Cache")

        # Delete cache files
        for f in cached_files:
            try:
                progress.setLabelText(f"Deleting {f.name}...")
                QApplication.processEvents()  # Keep dialog responsive
                f.unlink()
                deleted.append(f.name)
            except Exception as e:
                failed.append(f"{f.name}: {e}")
                logger.error(f"Failed to delete cache file {f}: {e}")

        # Second dialog: ask about DataForge cache (only if it exists)
        clear_dataforge = False
        if has_dataforge:
            progress.close()  # Close progress dialog while asking user
            reply = QMessageBox.question(
                self, "Clear DataForge Cache?",
                "Also clear the DataForge entity cache?\n\n"
                "⚠️  Warning: Recreating the DataForge cache takes 5–10 minutes on first run.\n\n"
                "The DataForge cache contains extracted entity data used for generating\n"
                "ship and weapon stats. You can keep this cache and only clear the INI files\n"
                "if you just want to refresh the localization strings.\n\n"
                "Clear DataForge cache?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply == QMessageBox.StandardButton.Yes:
                clear_dataforge = True
                # Show progress dialog again for DataForge deletion
                progress = AnimatedProgressDialog("Clearing DataForge cache...", parent=self, title="Clearing Cache")

        # Delete dataforge directory if user agreed
        if clear_dataforge:
            try:
                progress.setLabelText("Deleting DataForge directory...")
                QApplication.processEvents()

                # Shared helper — retries with backoff, clears read-only bits,
                # and outlasts OneDrive/Defender/indexer locks that commonly
                # reject the first attempt with WinError 5.
                from src.utils.pak_extractor import _robust_rmtree
                _robust_rmtree(dataforge_dir)
                deleted.append("dataforge/")
                logger.info("Deleted DataForge cache directory")
            except Exception as e:
                failed.append(f"dataforge/: {e}")
                logger.error(f"Failed to delete DataForge cache: {e}")
                logger.error(f"Failed to delete DataForge cache: {e}")

        progress.close()

        self.config_tab._refresh_p4k_status()
        self.entries = []
        self._model.set_data_source([], {}, AppSettings.get_favorite_prefix())

        msg = f"Deleted {len(deleted)} item(s) from cache."
        if failed:
            msg += "\n\nFailed to delete:\n" + "\n".join(failed)
        QMessageBox.information(self, "Cache Cleared", msg)

        # Re-sync all remote sources so they're available for the next Apply.
        # The sync completion will also prompt for p4k extraction if base.ini is missing.
        if self._startup_sync_worker is None:
            self._start_startup_sync()

    @pyqtSlot()
    def open_localization_dir(self):
        """Open the active channel's localization directory in Windows Explorer."""
        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, "Warning", "Please configure game install path in Config tab")
            return

        loc_dir = AppSettings.get_global_ini_path().parent

        if not loc_dir.exists():
            QMessageBox.warning(
                self, "Directory Not Found",
                f"Localization directory not found:\n{loc_dir}\n\n"
                "Check your game install path in the Config tab."
            )
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(loc_dir)))

    @pyqtSlot()
    @timed
    def perform_merge_and_reload(self):
        """Perform merge of configured sources and reload table.

        Called when user saves configuration in Config tab. Loads all configured
        sources, merges them in hierarchy order, and updates the table display.
        """
        try:
            # Load all configured sources
            sources_dict, hierarchy, enhancements_key_categories = load_sources_from_settings()

            if not sources_dict or not hierarchy:
                QMessageBox.warning(self, "Warning", "No sources configured. Please configure data sources in Config tab.")
                return

            self.statusBar().showMessage("Merging sources...")

            try:
                # Load synchronously in main thread
                logger.info("Merging configured sources...")
                entries = load_source_files(sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories)
                logger.info(f"Merge complete: {len(entries)} entries")
                self.entries = entries
                self.default_values = dict(sources_dict.get("global", {}))
                self.update_category_combo()
                self._model.set_data_source(
                    self.entries,
                    self.default_values,
                    AppSettings.get_favorite_prefix(),
                )
                self.apply_filters()

                # Update status bar with entry counts and per-source status
                self._update_status_bar()
            except Exception as e:
                logger.exception(f"Error during merge: {e}")
                QMessageBox.critical(self, "Error", f"Failed to merge sources: {e}")
                self.statusBar().showMessage("Merge failed")

        except Exception as e:
            logger.exception(f"Error in perform_merge_and_reload: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load sources: {e}")

    # ── INI Import ────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _apply_branding_styles(self):
        """Apply per-theme colors to the title + tagline header labels."""
        self.title_label.setStyleSheet(f"color: {get_title_color()};")
        self.tagline_label.setStyleSheet(
            f"font-size: 11px; letter-spacing: 2px; color: {get_tagline_color()};"
        )

    def refresh_action_buttons(self):
        """Re-apply theme-dependent stylesheets on the toolbar action buttons
        and re-render the About tab HTML (whose palette-derived colors are
        baked in at render time). Called after a live theme swap.
        """
        self._apply_branding_styles()
        base = "font-weight: bold; padding: 6px;"
        text = get_button_text_color()
        self.open_loc_dir_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {text}; {base}")
        self.apply_btn.setStyleSheet(f"background-color: {get_button_color('apply')}; color: {text}; {base}")
        self.restore_backup_btn.setStyleSheet(f"background-color: {get_button_color('restore')}; color: {text}; {base}")
        self.clear_loc_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {text}; {base}")
        self.clear_cache_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {text}; {base}")
        self.help_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {text}; {base}")
        if hasattr(self, "about_browser"):
            self._render_about_html()
        if hasattr(self, "help_browser"):
            self._render_help_html()

    def _handle_import_ini(self):
        """Handle Import INI button: get source, validate, resolve conflicts, merge."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
            QPushButton, QLabel, QDialogButtonBox, QFileDialog
        )
        from src.parser.ini_parser import parse_ini_file
        from src.utils.user_ini_manager import save_user_ini_dict
        import tempfile
        import urllib.request

        # Step 1: Get source path/URL from user
        source = self._get_import_source()
        if not source:
            return

        temp_file = None
        try:
            # Step 2: Resolve to local file
            if source.startswith('http://') or source.startswith('https://'):
                # Auto-convert GitHub web URLs to raw URLs
                if source.startswith('https://github.com/'):
                    source = source.replace('https://github.com/', 'https://raw.githubusercontent.com/')
                    source = source.replace('/blob/', '/')

                self.statusBar().showMessage("Downloading INI file...")
                try:
                    temp_file = tempfile.NamedTemporaryFile(suffix='.ini', delete=False)
                    temp_file.close()
                    urllib.request.urlretrieve(source, temp_file.name)
                    resolved_path = temp_file.name
                except Exception as e:
                    QMessageBox.critical(self, "Download Error", f"Failed to download:\n{source}\n\n{e}")
                    return
            else:
                resolved_path = source
                if not Path(resolved_path).exists():
                    QMessageBox.warning(self, "File Not Found", f"File does not exist:\n{resolved_path}")
                    return

            # Step 3: Parse imported file
            imported = parse_ini_file(resolved_path)
            if not imported:
                QMessageBox.warning(self, "Empty File", "The imported file contains no valid key=value entries.")
                return

            # Step 4: Validate against base.ini keys
            if not self.default_values:
                QMessageBox.warning(self, "No Base Data",
                    "Base INI not loaded yet. Extract from Data.p4k first.")
                return

            valid_keys = {k: v for k, v in imported.items() if k in self.default_values}
            excluded_count = len(imported) - len(valid_keys)

            if not valid_keys:
                QMessageBox.warning(self, "No Valid Keys",
                    f"None of the {len(imported)} imported keys exist in base.ini.\n"
                    f"All keys were excluded.")
                return

            # Step 5: Load current user.ini
            user_ini_path = AppSettings.get_user_ini_path()
            current_user = parse_ini_file(user_ini_path) if user_ini_path.exists() else {}

            # Step 6: Categorize keys
            auto_add = {}
            conflicts = {}
            for key, imported_value in valid_keys.items():
                current_value = current_user.get(key)
                if current_value is None:
                    auto_add[key] = imported_value
                elif current_value != imported_value:
                    conflicts[key] = (current_value, imported_value)
                # else: identical, skip

            # Step 7: Handle cases
            if not auto_add and not conflicts:
                QMessageBox.information(self, "Nothing to Import",
                    "All imported keys already exist in user.ini with the same values.")
                return

            if not conflicts:
                reply = QMessageBox.question(self, "Import INI",
                    f"{len(auto_add)} new keys will be added to user.ini.\n"
                    f"{excluded_count} keys excluded (not in base.ini).\n\n"
                    "Proceed?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
                if reply != QMessageBox.StandardButton.Yes:
                    return
                resolutions = {}
            else:
                from src.gui.import_dialog import ImportConflictDialog
                dialog = ImportConflictDialog(conflicts, len(auto_add), excluded_count, self)
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return
                resolutions = dialog.get_resolutions()

            # Step 8: Merge
            final = dict(current_user)
            final.update(auto_add)
            final.update(resolutions)

            # Step 9: Save
            save_user_ini_dict(final, user_ini_path)

            # Step 10: Reload
            self._show_loading_progress("Reloading with imported data...")

            # Step 11: Summary
            QMessageBox.information(self, "Import Complete",
                f"Import successful.\n\n"
                f"  Added: {len(auto_add)} keys\n"
                f"  Conflicts resolved: {len(resolutions)} keys\n"
                f"  Excluded: {excluded_count} keys")

        except Exception as e:
            logger.exception(f"Import failed: {e}")
            QMessageBox.critical(self, "Import Error", f"Failed to import INI file:\n{e}")
        finally:
            if temp_file:
                try:
                    Path(temp_file.name).unlink(missing_ok=True)
                except Exception:
                    pass

    def _get_import_source(self) -> str | None:
        """Show dialog to get a file path or URL for import."""
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLineEdit,
            QPushButton, QLabel, QDialogButtonBox, QFileDialog
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("Import INI File")
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel("Enter a local file path or URL:"))

        input_row = QHBoxLayout()
        line_edit = QLineEdit()
        line_edit.setPlaceholderText(r"C:\path\to\file.ini or https://example.com/file.ini")
        input_row.addWidget(line_edit)

        browse_btn = QPushButton("Browse...")
        def browse():
            path, _ = QFileDialog.getOpenFileName(
                dialog, "Select INI File", "", "INI Files (*.ini);;All Files (*)")
            if path:
                line_edit.setText(path)
        browse_btn.clicked.connect(browse)
        input_row.addWidget(browse_btn)
        layout.addLayout(input_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted and line_edit.text().strip():
            return line_edit.text().strip()
        return None

    @pyqtSlot()
    def restore_backup(self):
        """Restore a backup file as the current global.ini."""
        game_path = AppSettings.get_game_install_path()
        if not game_path:
            QMessageBox.warning(self, "Warning", "Please configure game install path in Config tab")
            return

        backup_dir = AppSettings.get_backups_dir()

        # Open file dialog to select backup
        backup_file, _ = QFileDialog.getOpenFileName(
            self,
            "Select Backup File to Restore",
            str(backup_dir),
            "Backup Files (*.bak_*);;INI Files (*.ini);;All Files (*)"
        )

        if not backup_file:
            return

        try:
            import shutil

            target_path = AppSettings.get_global_ini_path()
            backup_file_path = Path(backup_file)

            # Restore the backup
            shutil.copy2(str(backup_file_path), str(target_path))

            # Reload the file with overrides
            overrides_path = AppSettings.get_user_ini_path()
            overrides_arg = str(overrides_path) if overrides_path.exists() else None
            self.entries = load_source_files(str(target_path), overrides_arg)
            self.load_default_values()
            self.update_category_combo()
            self._model.set_data_source(
                self.entries, self.default_values, AppSettings.get_favorite_prefix(),
            )
            self.apply_filters()

            # Update status bar with entry counts and per-source status
            self._update_status_bar()

            logger.info(f"Restored backup from {backup_file} to {target_path}")
            QMessageBox.information(self, "Success", f"Backup restored from:\n{backup_file_path.name}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to restore backup: {e}")
            logger.error(f"Error restoring backup: {e}")

    @pyqtSlot()
    def _ensure_help_dock(self) -> QDockWidget:
        """Create the side-docked Help panel on first use and return it.

        The panel is a QDockWidget docked to the right edge so users can keep
        the guide open as a reference while editing. Users can drag it to the
        left, undock it into a floating window, or close it via the title-bar
        X. Qt restores its last state (position, width, visibility) on the
        next launch because saveState/restoreState are already wired into
        restore_window_state. An objectName is required for that mapping.
        """
        if self.help_dock is not None:
            return self.help_dock

        dock = QDockWidget("Help", self)
        dock.setObjectName("helpDock")  # needed by restoreState
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        self.help_browser = QTextBrowser(dock)
        self.help_browser.setOpenExternalLinks(True)
        dock.setWidget(self.help_browser)

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.help_dock = dock

        # Keep the Help button's checked state in sync if the user closes the
        # dock via its title-bar X instead of the toolbar button.
        dock.visibilityChanged.connect(self._on_help_dock_visibility_changed)

        self._render_help_html()
        return dock

    def _render_help_html(self):
        """(Re)render the Help panel's HTML using the current palette.

        Mirrors _render_about_html — forces the browser's palette to the app
        palette so its viewport/scrollbar chrome tracks theme swaps, then
        reloads HELP.md (bundled via SmartCitizen.spec). Falls back to a
        short stub if the file is missing so a misconfigured build still
        shows something usable instead of a blank panel.
        """
        if not hasattr(self, "help_browser"):
            return
        from PyQt6.QtWidgets import QApplication
        self.help_browser.setPalette(QApplication.palette())
        try:
            help_path = get_resource_path("HELP.md")
            with open(help_path, "r", encoding="utf-8") as f:
                help_markdown = f.read()
            self.help_browser.setHtml(self.markdown_to_html(help_markdown))
        except Exception as e:
            logger.error(f"Error loading HELP.md: {e}", exc_info=True)
            self.help_browser.setHtml(
                "<h1>Help</h1><p>Help content could not be loaded. "
                "See the About tab or the project README for usage details.</p>"
            )

    def _on_help_dock_visibility_changed(self, visible: bool):
        """Keep the toolbar Help button's checked state in sync with the dock."""
        if hasattr(self, "help_btn"):
            # blockSignals so toggling the button here doesn't loop back into
            # show_help and flip the dock visibility again.
            was_blocked = self.help_btn.blockSignals(True)
            try:
                self.help_btn.setChecked(visible)
            finally:
                self.help_btn.blockSignals(was_blocked)

    def show_help(self):
        """Toggle the Help side-panel.

        Help content lives in HELP.md at the project root (bundled into the
        PyInstaller onedir via SmartCitizen.spec). The first call creates the
        dock lazily; subsequent calls flip visibility so users can keep the
        guide open as a reference while editing without juggling a modal
        dialog.
        """
        dock = self._ensure_help_dock()
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            dock.raise_()

    # ── Guided tour (coach-marks) ─────────────────────────────────────────────

    def _tutorial_step_wiring(self) -> dict[str, dict]:
        """Map each tutorial step id to its widget-targeting logic.

        Kept in code — not in JSON — because target and pre_action are
        closures over `self`/QWidget references that can't be serialized.
        The user-editable copy (title / description / order / inclusion)
        lives in ``assets/tutorial.json`` and is keyed by these ids.

        Each value is a dict with:
            target:     Callable[[], QWidget | None]
            pre_action: Optional[Callable[[], None]]
        """
        def _switch_to(tab_index: int):
            def _action():
                if hasattr(self, "tabs"):
                    self.tabs.setCurrentIndex(tab_index)
            return _action

        strings_tab = getattr(self, "_strings_tab_index", 0)
        config_tab = getattr(self, "_config_tab_index", 1)
        enh_tab = getattr(self, "_enhancements_tab_index", 2)

        return {
            "welcome":      {"target": lambda: None,                                            "pre_action": None},
            "extract":      {"target": lambda: self.config_tab._extract_btn,                    "pre_action": _switch_to(config_tab)},
            "edit":         {"target": lambda: self.table,                                      "pre_action": _switch_to(strings_tab)},
            "preview":      {"target": lambda: self.preview_pane,                               "pre_action": _switch_to(strings_tab)},
            "apply":        {"target": lambda: self.apply_btn,                                  "pre_action": None},
            "enhancements": {"target": lambda: self.enhancements_tab._generate_enhancements_btn, "pre_action": _switch_to(enh_tab)},
            "help":         {"target": lambda: self.help_btn,                                   "pre_action": _switch_to(strings_tab)},
        }

    def _build_tutorial_steps(self) -> list[CoachMarkStep]:
        """Assemble the tour by combining ``assets/tutorial.json`` (content)
        with ``_tutorial_step_wiring()`` (targets).

        Order and inclusion are driven by the JSON — reorder or remove entries
        there to change the tour without touching code. Entries whose ``id``
        has no matching wiring are skipped with a warning (so a typo in the
        JSON surfaces in the Log Tab rather than crashing the tour).
        """
        import json

        wiring = self._tutorial_step_wiring()

        try:
            tutorial_path = Path(get_resource_path("assets/tutorial.json"))
            with tutorial_path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.error(f"Could not load assets/tutorial.json: {e} — tour disabled")
            return []

        raw_steps = payload.get("steps", [])
        steps: list[CoachMarkStep] = []
        for raw in raw_steps:
            step_id = raw.get("id")
            if not step_id:
                logger.warning(f"Tutorial step missing 'id'; skipped: {raw!r}")
                continue
            w = wiring.get(step_id)
            if w is None:
                logger.warning(
                    f"Tutorial step id {step_id!r} has no wiring entry in "
                    f"_tutorial_step_wiring(); skipped"
                )
                continue
            title = raw.get("title", "")
            description = raw.get("description", "")
            if not title or not description:
                logger.warning(f"Tutorial step {step_id!r} missing title/description; skipped")
                continue
            steps.append(CoachMarkStep(
                target=w["target"],
                title=title,
                description=description,
                pre_action=w.get("pre_action"),
                preferred_side=raw.get("preferred_side", "auto"),
            ))

        return steps

    def _start_tutorial(self) -> None:
        """Launch the guided tour. Safe to call repeatedly; a running tour is ignored."""
        if self._tutorial_tour is not None and self._tutorial_tour.is_running():
            return
        try:
            self._tutorial_tour = TutorialTour(self, self._build_tutorial_steps())
            self._tutorial_tour.finished.connect(self._on_tutorial_finished)
            self._tutorial_tour.start()
        except Exception:
            # Don't let a broken tour strand the deferred startup tasks —
            # users without sources synced / update checks would never see
            # P4K prompts or the new-version notice.
            logger.exception("Tutorial failed to launch; running deferred startup tasks anyway")
            self._tutorial_tour = None
            self._start_post_tutorial_tasks()

    def _on_tutorial_finished(self, completed: bool) -> None:
        """Record completion on Finish; skip doesn't burn the flag so the user
        still sees the tour on their next launch if they hit Skip by accident."""
        if completed:
            AppSettings.set_tutorial_completed_version(get_version())
        self._tutorial_tour = None
        # Now that the user is past (or has skipped) the tour, fire the
        # deferred startup tasks. Their modal prompts would otherwise pop
        # over the coach-mark overlay and break first-run.
        self._start_post_tutorial_tasks()

    def _start_post_tutorial_tasks(self) -> None:
        """Fire the deferred startup tasks (source sync + app-update check) once.

        Held back until the guided tour finishes so its modal prompts (P4K
        extraction, app-update dialog, enhancements pipeline) don't pop over
        the coach-mark overlay during first-run. Idempotent — safe to call
        from multiple paths (no-tutorial branch, tour-finished, tour-skipped).
        """
        if getattr(self, "_post_tutorial_tasks_started", False):
            return
        self._post_tutorial_tasks_started = True
        self._start_startup_sync()
        self._maybe_auto_check_app_updates()

    def _maybe_start_first_run_tutorial(self) -> None:
        """Auto-start the tour on first launch of a version whose tour wasn't seen.

        Matching on version (not a boolean) means we can re-trigger the tour
        in a future release if we add meaningful steps worth showing again.
        Hooked from showEvent so widgets have geometry; a short QTimer delay
        lets the restore-window-state pass finish before we compute spotlight
        rectangles.

        Also responsible for kicking off the deferred startup tasks (source
        sync + app-update check). On a first-run launch the tour starts and
        those tasks are held back until ``_on_tutorial_finished``; otherwise
        they fire here on the next event-loop tick.
        """
        if getattr(self, "_tutorial_first_run_checked", False):
            return
        self._tutorial_first_run_checked = True
        last_seen = AppSettings.get_tutorial_completed_version()
        current = get_version()
        if last_seen == current:
            QTimer.singleShot(0, self._start_post_tutorial_tasks)
            return
        QTimer.singleShot(400, self._start_tutorial)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._maybe_start_first_run_tutorial()

    def keyPressEvent(self, event):
        """Handle keyboard shortcuts."""
        if event.key() == Qt.Key.Key_C and event.modifiers() == Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier:
            # Ctrl+Shift+C: Copy filtered rows
            self.copy_filtered_to_clipboard()
        else:
            super().keyPressEvent(event)

    def _update_eye_pulse(self) -> None:
        """Toggle the Osiris eye glow animation to mirror worker activity.

        Polled by `_eye_pulse_monitor` instead of wiring into every worker
        lifecycle slot — polling is cheaper than touching every entrypoint
        and guarantees we can't forget to stop the pulse on an error path.
        When work ends mid-pulse we ease the current opacity down to 0
        instead of snapping it off.
        """
        if self._eye_pulse is None or self._eye_glow is None or self._eye_fadeout is None:
            return
        running = self._has_long_running_worker()
        pulse_on   = self._eye_pulse.state()   == QPropertyAnimation.State.Running
        fadeout_on = self._eye_fadeout.state() == QPropertyAnimation.State.Running

        if running:
            # Starting up or resuming — cancel any in-flight fade-out and
            # rejoin the pulse loop.
            if fadeout_on:
                self._eye_fadeout.stop()
            if not pulse_on:
                self._eye_pulse.start()
        elif pulse_on:
            # Work just ended — stop the loop, then ease from wherever we
            # are right now down to 0. Duration scales with remaining
            # opacity so a near-dark eye fades quickly and a bright one
            # takes the full ~600ms.
            current = self._eye_glow.opacity()
            self._eye_pulse.stop()
            self._eye_fadeout.stop()
            self._eye_fadeout.setStartValue(current)
            self._eye_fadeout.setDuration(int(100 + 500 * current))
            self._eye_fadeout.start()

    def _has_long_running_worker(self) -> bool:
        """True while an extract/generate/load worker is running. Status-bar
        refreshes that would otherwise fall back to 'Ready' are suppressed
        during that window so in-progress messages aren't clobbered mid-run.
        """
        workers = (
            self._enhancements_worker,
            self._forge_worker,
            self._p4k_worker,
            self._loader_worker,
            self._startup_sync_worker,
        )
        return any(w is not None and w.isRunning() for w in workers)

    def _ensure_channel_indicator(self) -> None:
        """Install a permanent right-side status-bar widget showing the active channel.

        Lazily created on first call so it survives statusBar().showMessage()
        churn (transient messages on the left don't displace permanent
        widgets). The label's text is refreshed by :meth:`_refresh_channel_indicator`
        whenever the channel changes.
        """
        if self._channel_indicator is not None:
            return
        self._channel_indicator = QLabel()
        self._channel_indicator.setStyleSheet("font-size: 11px; font-weight: bold; padding: 0 8px;")
        self._status_bar().addPermanentWidget(self._channel_indicator)
        self._refresh_channel_indicator()

    def _ensure_app_version_indicator(self) -> None:
        """Install a permanent status-bar widget for the app version + update state.

        Sits immediately next to the SC version text (added before the
        channel indicator so it lands leftmost in the permanent zone). Text
        starts as plain ``v{version}`` and is suffixed with the check result
        ("up to date" / "update available" / "check failed") once the
        app-update worker reports back. Becomes clickable when an update is
        available — the click opens the release page.
        """
        if self._app_version_indicator is not None:
            return
        self._app_version_indicator = ClickableLabel(f"v{get_version()}")
        self._app_version_indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        self._app_version_indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._app_version_indicator.clicked.connect(self._on_version_label_clicked)
        self._status_bar().addPermanentWidget(self._app_version_indicator)

    def _refresh_channel_indicator(self) -> None:
        """Update the status-bar channel label to reflect AppSettings.get_active_channel()."""
        if self._channel_indicator is None:
            return
        self._channel_indicator.setText(f"Channel: {AppSettings.get_active_channel()}")

    @pyqtSlot(str)
    def _on_channel_changed(self, channel: str) -> None:
        """Handle a channel switch from the Config tab.

        Re-runs the merge + reload against the new channel's data: the
        path helpers are already channel-aware, so calling
        :meth:`perform_merge_and_reload` picks up the new cache, user.ini,
        and enhancement INIs automatically. Also refreshes the status-bar
        indicator, the Config tab's P4K status dot, and the Enhancements
        tab's DataForge freshness label so the user sees an immediate
        consistent view across the whole UI.
        """
        logger.info(f"MainWindow reacting to channel change → {channel}")

        # Re-point the stored file-path sources at the new channel's folders.
        # The path helpers themselves (get_cache_dir, get_user_ini_path) are
        # already channel-aware and resolve per-call — but the loader reads
        # the stored path from the registry, so we have to mirror the
        # new values into those entries the same way main() does on startup.
        # Skip any source currently set to a URL to preserve custom remote
        # configs.
        for source_name, canonical in (
            (AppSettings.SOURCE_GLOBAL, str(AppSettings.get_cache_dir() / "base.ini")),
            (AppSettings.SOURCE_USER, str(AppSettings.get_user_ini_path())),
        ):
            stored = AppSettings.get_source_path(source_name)
            if stored.startswith("http://") or stored.startswith("https://"):
                continue
            if stored != canonical:
                AppSettings.set_source_path(source_name, canonical)
                logger.info(
                    f"Re-synced {source_name} source path for channel {channel}: "
                    f"{stored or '(unset)'} → {canonical}"
                )

        self._refresh_channel_indicator()
        self.config_tab._refresh_p4k_status()
        if hasattr(self, "enhancements_tab"):
            # Use the full refresh — it updates the per-category status
            # dots (which file by file reflect whether each enhancement INI
            # exists in this channel's cache) and then calls
            # refresh_forge_status() internally for the DataForge cache
            # label. Calling only refresh_forge_status() would leave the
            # per-category dots showing the prior channel's state.
            self.enhancements_tab.refresh_enhancements_status()

        # Reset the "already prompted once" flag so the category-selection
        # dialog fires again for this channel's (potentially different) set
        # of missing enhancement files. Without this reset,
        # _check_enhancements_freshness silently runs _run_enhancements_pipeline
        # with the prior session's selections — e.g. after switching to a
        # freshly-extracted PTU where all enhancement INIs are missing,
        # the user sees enhancements regenerate with no confirmation.
        # Each channel deserves its own "which enhancements?" prompt.
        self._enhancements_prompted_on_startup = False

        # If the new channel has never been extracted, base.ini won't exist
        # and perform_merge_and_reload() would fail silently with an empty
        # result. Run the same freshness prompt the startup path uses —
        # prompts "Extract from Data.p4k now?" when base.ini is missing or
        # stale. Returns True if extraction was started, in which case the
        # finished handler will trigger the reload itself (don't double-run).
        if self._check_p4k_freshness():
            self._status_bar().showMessage(
                f"Switched to {channel} — extracting Data.p4k…"
            )
            return

        # base.ini is present and fresh for the new channel. Check whether
        # the channel's DataForge cache is stale relative to its p4k and
        # offer to re-extract if so (background — doesn't block reload).
        self._maybe_prompt_dataforge_refresh()

        self._status_bar().showMessage(f"Switched to {channel} — reloading sources…")
        self.perform_merge_and_reload()

    def _update_status_bar(self):
        """Compose sync status from all configured sources plus entry counts and game version.

        Shows per-source sync status in hierarchy order, then entry count, override count, and game version.
        Example: "Global: 4.7.0-LIVE ✓  |  Contracts: ✓  |  Ships: ✓  |  82,934 entries | 5 overrides | SC v4.7.176"
        """
        # Build status message from all configured sources in hierarchy order
        hierarchy = AppSettings.get_merge_hierarchy()
        parts = []

        for source_name in hierarchy:
            if source_name in self._source_status:
                parts.append(self._source_status[source_name])

        # Add entry and override counts if data is loaded
        if self.entries:
            modified_count = sum(1 for e in self.entries if e.status in ("Modified", "New"))
            entry_info = f"{len(self.entries):,} entries"
            if modified_count:
                entry_info += f" | {modified_count} overrides"
            parts.append(entry_info)

        # Add game version + channel suffix. Reading build_manifest.id goes
        # through get_game_install_path(), which is channel-aware post-0.9.3
        # — so when the user switches channels this already re-reads from
        # the new channel's manifest file. We tag the version with the
        # channel name (e.g. "SC v4.7.176-PTU") so the status bar version
        # is unambiguous even before the right-side channel indicator lands
        # in the user's eye.
        game_version = AppSettings.get_game_version()
        active_channel = AppSettings.get_active_channel()
        if game_version:
            version_parts = game_version.split(".")
            short_version = ".".join(version_parts[:3]) if len(version_parts) >= 3 else game_version
            parts.append(f"SC v{short_version}-{active_channel}")
        elif AppSettings.get_channel_install_path():
            # Channel selected but no manifest (folder missing / not installed);
            # surface the channel name so the user can see which one is active
            # and why the version's blank.
            parts.append(f"SC {active_channel} (manifest missing)")

        status_bar = self._status_bar()
        if parts:
            status_bar.showMessage("  |  ".join(parts))
        elif not self._has_long_running_worker():
            # Don't overwrite a progress message with "Ready" while a worker
            # is still running — the user reads the empty state as "done".
            status_bar.showMessage("Ready")

    def _set_source_status(self, source_name: str, status: str) -> None:
        """Set sync status for a specific source and update status bar.

        Args:
            source_name: Name of the source (e.g., "global", "contracts")
            status: Status string to display (e.g., "Global: 4.7.0-LIVE ✓")
        """
        self._source_status[source_name] = status
        self._update_status_bar()

    def _start_startup_sync(self):
        """Start async sync of all enabled remote sources, then load files when done.

        If no remote sources need syncing, skip directly to loading.
        """
        # Check if any sources actually need syncing (remote URL + auto-update enabled)
        has_remote_sync = any(
            AppSettings.is_source_enabled(name)
            and AppSettings.get_source_auto_update(name)
            and AppSettings.get_source_path(name).startswith("http")
            for name in AppSettings.AVAILABLE_SOURCES
        )

        if not has_remote_sync:
            # Nothing to sync — go straight to loading
            self._on_startup_sync_finished()
            return

        self._status_bar().showMessage("Starting up — syncing sources...")
        self._startup_progress = AnimatedProgressDialog(
            "Syncing sources...", parent=self, title="Starting Up"
        )
        self._startup_sync_worker = StartupSyncWorker()
        self._startup_sync_worker.source_starting.connect(self._on_startup_source_starting)
        self._startup_sync_worker.source_synced.connect(self._on_startup_source_synced)
        self._startup_sync_worker.source_error.connect(self._on_startup_source_error)
        self._startup_sync_worker.finished.connect(self._on_startup_sync_finished)
        self._startup_sync_worker.start()

    @pyqtSlot(str)
    def _on_startup_source_starting(self, source_name: str):
        self._status_bar().showMessage(f"Syncing {source_name}...")
        if self._startup_progress is not None:
            self._startup_progress.setLabelText(f"Syncing {source_name}...")

    @pyqtSlot(str, bool)
    def _on_startup_source_synced(self, source_name: str, updated: bool):
        action = "updated" if updated else "up to date"
        logger.info(f"Startup sync: {source_name} {action}")
        label = "updated ↑" if updated else "✓"
        self._set_source_status(source_name, f"{source_name.title()}: {label}")

    @pyqtSlot(str, str)
    def _on_startup_source_error(self, source_name: str, message: str):
        logger.warning(f"Startup sync error ({source_name}): {message}")
        self._set_source_status(source_name, f"{source_name.title()}: ⚠ (offline?)")

    @pyqtSlot()
    def _on_startup_sync_finished(self):
        """Sync complete — clean up worker, check p4k freshness, then load sources."""
        if self._startup_sync_worker:
            self._startup_sync_worker.quit()
            self._startup_sync_worker.wait()
            self._startup_sync_worker = None

        # Close the startup progress dialog before any modal prompts (P4K, enhancements)
        if self._startup_progress is not None:
            self._startup_progress.close()
            self._startup_progress = None

        # Prompt user to extract from p4k if base.ini is missing or outdated
        p4k_extraction_started = self._check_p4k_freshness()

        # If P4K extraction was started, don't load files yet.
        # The P4K extraction finished handler will do the loading.
        if p4k_extraction_started:
            return

        # Base.ini is fine. Separately check the DataForge XML cache, which
        # has its own freshness stamp (`.p4k_mtime`) and can be stale even
        # when base.ini is current — e.g. the last DataForge extract was
        # against an older Data.p4k, or the user patched the game since.
        # Prompt but don't defer file loading: stale DataForge only affects
        # enhancement regeneration, not the base strings in the table.
        self._maybe_prompt_dataforge_refresh()

        # Don't check enhancements during startup - defer until after file loading completes
        # to avoid concurrent I/O contention between file loader and enhancements generator
        self._check_enhancements_after_loading = True

        # Show progress dialog during file loading
        self._show_loading_progress()

    def _check_p4k_freshness(self) -> bool:
        """Prompt to extract from Data.p4k if base.ini is missing or outdated.

        Returns:
            True if P4K extraction was started (caller should defer file loading).
            False if no extraction is needed or user declined.
        """
        unp4k_exe = AppSettings.get_unp4k_exe_path()
        p4k_path = AppSettings.get_p4k_path()
        base_ini = AppSettings.get_cache_dir() / 'base.ini'

        if not unp4k_exe.exists() or not p4k_path.exists():
            return False  # silently skip — unp4k not bundled yet or game path not set

        base_missing = not base_ini.exists()
        p4k_newer = (not base_missing) and (p4k_path.stat().st_mtime > base_ini.stat().st_mtime)

        if not base_missing and not p4k_newer:
            return False  # cache is present and up to date

        if base_missing:
            msg = (
                "No base localization file found in cache.\n\n"
                "Extract global.ini from Data.p4k now?\n"
                "(Required to load and display localization strings.)"
            )
        else:
            msg = (
                "Data.p4k is newer than your cached base.ini.\n\n"
                "Extract global.ini from Data.p4k now?\n"
                "(This gives you stock strings matching your exact installed game version.)"
            )

        reply = QMessageBox.question(
            self, "Extract from Data.p4k", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_p4k_extraction()
            return True
        return False

    def _maybe_prompt_dataforge_refresh(self) -> None:
        """Prompt to re-extract DataForge if its cache is stale vs. Data.p4k.

        Called during startup after base.ini passes its freshness check.
        A stale DataForge cache doesn't block the base-string workflow — the
        table loads fine — but it means the next enhancements regeneration
        will run against old entity data, so stats/missions/blueprints will
        drift from what the current game build actually ships. Users who
        notice the passive ``DataForge: cache outdated`` label on the
        Enhancements tab want to act on it; surfacing a Yes/No dialog on
        startup consolidates the prompt into the same flow as the base.ini
        prompt above.

        Silent no-op when the cache is fresh, when unp4k or Data.p4k is
        missing (no signal to act on), when a DataForge or enhancements
        worker is already running (don't stack prompts), or when the cache
        has no stamp file yet (that's the "never extracted" case — the
        existing ``_check_enhancements_freshness`` prompt handles it via a
        category-selection dialog after the first load).

        Does NOT defer file loading — unlike the base.ini case, loading
        the table doesn't depend on DataForge. The extract runs in the
        background and chains into enhancements generation on completion.
        """
        from src.utils.pak_extractor import dataforge_cache_is_fresh

        if self._forge_worker is not None or self._enhancements_worker is not None:
            return
        p4k_path = AppSettings.get_p4k_path()
        unp4k_exe = AppSettings.get_unp4k_exe_path()
        unforge_exe = AppSettings.get_unforge_exe_path()
        if not p4k_path.exists() or not unp4k_exe.exists() or not unforge_exe.exists():
            return
        forge_dir = AppSettings.get_dataforge_cache_dir()
        if not (forge_dir / ".p4k_mtime").exists():
            # Never extracted — handled later by _check_enhancements_freshness,
            # which shows a richer category-selection dialog.
            return
        if dataforge_cache_is_fresh(p4k_path, forge_dir):
            return

        reply = QMessageBox.question(
            self, "DataForge Cache Outdated",
            "Your DataForge entity cache is older than the current Data.p4k.\n\n"
            "Re-extract DataForge and regenerate enhancements now?\n\n"
            "This takes 5–10 minutes and runs in the background — you can keep "
            "editing strings while it works. Skip for now if you'd rather not wait; "
            "you can always trigger this from the Enhancements tab.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._run_dataforge_extraction()

    def _check_enhancements_freshness(self):
        """If enabled enhancement files are missing, prompt to generate them.

        Shows a category selection dialog on startup. If called again after P4K
        extraction and we already prompted, runs generation with saved selections.
        """
        cache_dir = AppSettings.get_cache_dir()
        if not (cache_dir / 'base.ini').exists():
            return
        if self._enhancements_worker is not None or self._forge_worker is not None:
            return

        # Only check enabled categories
        enabled = AppSettings.get_enabled_enhancement_categories()
        missing = [key for key in enabled
                   if not (cache_dir / AppSettings.ENHANCEMENTS_FILES[key]).exists()]
        if not missing:
            return

        p4k_path = AppSettings.get_p4k_path()
        if not p4k_path.exists():
            return

        # If we already prompted and user chose to generate, just run with saved selections
        if self._enhancements_prompted_on_startup:
            self._run_enhancements_pipeline()
            return

        # Show category selection dialog
        self._enhancements_prompted_on_startup = True
        selected = self._show_enhancement_category_dialog(missing)
        if selected:
            self._run_enhancements_pipeline()

    def _show_enhancement_category_dialog(self, missing_keys: list[str]) -> set[str] | None:
        """Show a dialog letting the user select which enhancement categories to generate.

        Args:
            missing_keys: List of category keys that are currently missing.

        Returns:
            Set of selected category keys, or None if user clicked Skip.
        """
        from PyQt6.QtWidgets import (
            QDialog, QVBoxLayout, QLabel, QCheckBox,
            QPushButton, QHBoxLayout
        )

        # Collapse the missing-file list down to the set of category checkboxes
        # the user will actually see. The dialog is category-shaped, not
        # file-shaped — reporting the file count here confuses users because a
        # single category (e.g. ship_items) maps to multiple files.
        missing_file_keys = set(missing_keys)
        missing_checkbox_keys = set()
        for checkbox_key, file_keys in AppSettings.ENHANCEMENT_CATEGORY_FILES.items():
            if any(fk in missing_file_keys for fk in file_keys):
                missing_checkbox_keys.add(checkbox_key)

        dialog = QDialog(self)
        dialog.setWindowTitle("Generate Enhancements")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)

        n = len(missing_checkbox_keys)
        noun = "category is" if n == 1 else "categories are"
        layout.addWidget(QLabel(
            f"{n} enhancement {noun} missing.\n"
            "Select which to generate.\n"
            "You can change this later in the Enhancements tab."
        ))

        layout.addSpacing(8)

        checkboxes: dict[str, QCheckBox] = {}
        for key, label in AppSettings.ENHANCEMENT_LABELS.items():
            cb = QCheckBox(label)
            if key in missing_checkbox_keys:
                cb.setChecked(True)
                cb.setText(f"{label}  (missing)")
            else:
                cb.setChecked(False)
            checkboxes[key] = cb
            layout.addWidget(cb)

        layout.addSpacing(8)

        info = QLabel(
            "DataForge data will be extracted automatically if not already cached.\n"
            "First run takes ~5-10 minutes."
        )
        info.setProperty("role", "secondary")
        info.setStyleSheet("font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addSpacing(8)

        button_row = QHBoxLayout()
        generate_btn = QPushButton("Generate")
        generate_btn.setDefault(True)
        skip_btn = QPushButton("Skip")

        generate_btn.clicked.connect(dialog.accept)
        skip_btn.clicked.connect(dialog.reject)

        button_row.addStretch()
        button_row.addWidget(skip_btn)
        button_row.addWidget(generate_btn)
        layout.addLayout(button_row)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Only save state for categories that were missing — don't touch
            # the persisted state of categories that already have their files
            for key, cb in checkboxes.items():
                if key in missing_checkbox_keys:
                    AppSettings.set_enhancement_category_enabled(key, cb.isChecked())
            # Refresh enhancements tab checkboxes to match
            self.enhancements_tab.revert_category_checkboxes()
            self.enhancements_tab.refresh_enhancements_status()
            return AppSettings.get_enabled_enhancement_categories()

        return None

    def _show_loading_progress(self, message: str = "Loading localization strings...") -> None:
        """Show an animated progress dialog while loading files in a worker thread.

        Uses FileLoaderWorker to load files asynchronously so the progress dialog
        can animate properly. Shares the same progress dialog implementation as P4K extraction.

        Args:
            message: Status message to display in the progress dialog
        """
        # Guard against overlapping loads — clean up any prior worker first
        if self._loader_worker is not None:
            logger.warning("Previous FileLoaderWorker still exists — cleaning up before starting new load")
            try:
                self._loader_worker.finished.disconnect(self._on_loading_finished)
                self._loader_worker.error.disconnect(self._on_loading_error)
            except (TypeError, RuntimeError):
                pass  # signals already disconnected
            if self._loader_worker.isRunning():
                self._loader_worker.quit()
                self._loader_worker.wait(5000)  # 5s timeout to avoid deadlock
            self._loader_worker = None
        if self._loading_progress is not None:
            self._loading_progress.close()
            self._loading_progress = None

        # Load sources in background worker thread
        self._loader_worker = FileLoaderWorker()

        # Create reusable animated progress dialog
        self._loading_progress = AnimatedProgressDialog(message, parent=self, title="Loading")

        # Connect worker signals to progress dialog label updates
        self._loader_worker.finished.connect(self._on_loading_finished)
        self._loader_worker.error.connect(self._on_loading_error)
        self._loader_worker.progress.connect(self._loading_progress.setLabelText)
        self._loader_worker.progress_pct.connect(self._loading_progress.set_progress)
        self._loader_worker.start()

    @pyqtSlot(list, dict, list)
    @timed
    def _on_loading_finished(self, entries: list, default_values: dict, sort_keys: list):
        """Handle file loading completion.

        Args:
            entries: Merged StringEntry list.
            default_values: Global source key→value dict (for the Default Value column).
            sort_keys: Pre-computed grouped sort keys (one per entry).
        """
        # Close modal progress dialog and clean up worker FIRST so the modal
        # event loop exits before heavy synchronous UI work.
        if self._loading_progress is not None:
            self._loading_progress.close()
            self._loading_progress = None
        if self._loader_worker is not None:
            self._loader_worker.quit()
            self._loader_worker.wait()
            self._loader_worker = None

        self.default_values = default_values
        self.entries = entries
        self.update_category_combo()

        # Push data into the model — the view renders only visible rows, so this is instant
        self._model.set_data_source(
            self.entries,
            self.default_values,
            AppSettings.get_favorite_prefix(),
            sort_keys=sort_keys,
        )
        self.apply_filters()

        # Update status bar with entry counts and per-source status
        self._update_status_bar()

        # If enhancements check was deferred during startup, do it now (after file loading completes)
        # This avoids concurrent I/O contention between file loader and enhancements generator
        if self._check_enhancements_after_loading:
            self._check_enhancements_after_loading = False
            self._check_enhancements_freshness()

    @pyqtSlot(str)
    def _on_loading_error(self, error_msg: str):
        """Handle file loading error."""
        if self._loading_progress is not None:
            self._loading_progress.close()
            self._loading_progress = None
        QMessageBox.critical(self, "Error", f"Failed to load sources: {error_msg}")
        if self._loader_worker is not None:
            self._loader_worker.quit()
            self._loader_worker.wait()
            self._loader_worker = None

    def _run_enhancements_pipeline(self):
        """Entry point for the enhancements button: extract DataForge if needed, then generate enhancements."""
        if self._enhancements_worker is not None or self._forge_worker is not None:
            return  # already running

        from src.utils.pak_extractor import dataforge_cache_is_fresh
        forge_dir = AppSettings.get_dataforge_cache_dir()
        p4k_path  = AppSettings.get_p4k_path()

        if dataforge_cache_is_fresh(p4k_path, forge_dir):
            self._run_enhancements_generation()
        else:
            self._run_dataforge_extraction()

    def _run_enhancements_generation(self, categories: set[str] | None = None):
        """Launch EnhancementsGeneratorWorker in the background with animated progress dialog."""
        if self._enhancements_worker is not None:
            return  # already running

        # Use enabled categories from settings if none specified
        if categories is None:
            categories = AppSettings.get_enabled_enhancement_categories()

        status_bar = self._status_bar()
        self._enhancements_worker = EnhancementsGeneratorWorker(categories=categories)
        self.enhancements_tab.set_operation_running("Generating enhancements…")
        status_bar.showMessage("Generating enhancements in background…")

        # Show animated progress dialog
        progress_dialog = AnimatedProgressDialog(
            "Generating enhanced localizations from DataForge…\n\nThis may take a few minutes on the first run.",
            parent=self,
            title="Generating Enhancements",
        )
        self._enhancements_progress_dialog = progress_dialog

        worker = self._enhancements_worker
        worker.progress.connect(self.enhancements_tab.set_operation_progress)
        worker.progress.connect(status_bar.showMessage)
        worker.progress.connect(progress_dialog.setLabelText)
        worker.progress_pct.connect(progress_dialog.set_progress)
        worker.error.connect(self._on_enhancements_generation_error)
        worker.finished.connect(self._on_enhancements_generation_finished)
        worker.start()

    def _on_enhancements_generation_error(self, message: str):
        logger.error(f"Enhancements generation error: {message}")
        # Close progress dialog on error
        if self._enhancements_progress_dialog is not None:
            self._enhancements_progress_dialog.close()
            self._enhancements_progress_dialog = None

    def _on_enhancements_generation_finished(self, success: bool):
        # Close progress dialog
        if self._enhancements_progress_dialog is not None:
            self._enhancements_progress_dialog.close()
            self._enhancements_progress_dialog = None

        worker = self._enhancements_worker
        if worker is not None:
            worker.quit()
            worker.wait()
            self._enhancements_worker = None
        self.enhancements_tab.set_operation_idle()
        self.enhancements_tab.refresh_enhancements_status()

        status_bar = self._status_bar()
        if success:
            status_bar.showMessage("Enhancements generated — reloading entries…")
            self._show_loading_progress("Reloading strings with updated enhancements…")
        else:
            status_bar.showMessage("Enhancement generation failed — check the Log tab for details")

    def _run_dataforge_extraction(self):
        """Launch DataForgeExtractWorker in the background (non-blocking)."""
        if self._forge_worker is not None:
            return

        p4k_path    = AppSettings.get_p4k_path()
        unp4k_exe   = AppSettings.get_unp4k_exe_path()
        unforge_exe = AppSettings.get_unforge_exe_path()
        forge_dir   = AppSettings.get_dataforge_cache_dir()

        status_bar = self._status_bar()
        self._forge_worker = DataForgeExtractWorker(p4k_path, unp4k_exe, unforge_exe, forge_dir)
        self.enhancements_tab.set_operation_running("Extracting DataForge from Data.p4k…")
        status_bar.showMessage("Extracting DataForge in background — this takes several minutes…")

        progress_dialog = AnimatedProgressDialog(
            "Extracting DataForge from Data.p4k — this takes several minutes…",
            parent=self,
            title="DataForge Extraction",
        )
        self._forge_progress_dialog = progress_dialog

        worker = self._forge_worker
        worker.progress.connect(self.enhancements_tab.set_operation_progress)
        worker.progress.connect(status_bar.showMessage)
        worker.progress.connect(progress_dialog.setLabelText)
        worker.progress_pct.connect(progress_dialog.set_progress)
        worker.error.connect(self._on_dataforge_extract_error)
        worker.finished.connect(self._on_dataforge_extract_finished)
        worker.start()

    def _on_dataforge_extract_error(self, message: str):
        logger.error(f"DataForge extraction error: {message}")

    def _on_dataforge_extract_finished(self, success: bool):
        if self._forge_progress_dialog is not None:
            self._forge_progress_dialog.close()
            self._forge_progress_dialog = None
        worker = self._forge_worker
        if worker is not None:
            worker.quit()
            worker.wait()
            self._forge_worker = None
        self.enhancements_tab.refresh_forge_status()

        status_bar = self._status_bar()
        if success:
            status_bar.showMessage("DataForge extracted — generating enhancements…")
            self._run_enhancements_generation()
        else:
            self.enhancements_tab.set_operation_idle()
            status_bar.showMessage("DataForge extraction failed — check the Log tab for details")

    def _run_p4k_extraction(self):
        """Launch P4kExtractWorker with a progress dialog; reload sources on success."""
        p4k_path = AppSettings.get_p4k_path()
        output_path = AppSettings.get_cache_dir() / 'base.ini'
        unp4k_exe = AppSettings.get_unp4k_exe_path()

        self._p4k_worker = P4kExtractWorker(p4k_path, output_path, unp4k_exe)
        self._p4k_progress = AnimatedProgressDialog(
            "Extracting global.ini from Data.p4k...",
            parent=self,
            title="P4K Extraction"
        )

        self._p4k_worker.progress.connect(self._p4k_progress.setLabelText)
        self._p4k_worker.progress_pct.connect(self._p4k_progress.set_progress)
        self._p4k_worker.error.connect(lambda err: QMessageBox.warning(self, "Extraction Error", err))
        self._p4k_worker.finished.connect(self._on_p4k_extract_finished)
        self._p4k_worker.start()

    def _on_p4k_extract_finished(self, success: bool):
        """Handle P4K extraction completion."""
        if self._p4k_progress is not None:
            self._p4k_progress.close()
        worker = self._p4k_worker
        if worker is not None:
            worker.quit()
            worker.wait()
            self._p4k_worker = None

        if success:
            # Lock Global source to the local cache path with auto-update off,
            # so future startups don't overwrite the extracted file from a remote URL.
            local_path = str(AppSettings.get_cache_dir() / 'base.ini')
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, local_path)
            AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)
            # Refresh the config tab P4K status
            self.config_tab._refresh_p4k_status()

            # Defer enhancements check until after file loading completes (avoid I/O contention)
            self._check_enhancements_after_loading = True

            # Show progress dialog while reloading with extracted data
            self._show_loading_progress("Reloading with extracted base.ini...")

    def closeEvent(self, event):
        """Save state and overrides before closing."""
        # Auto-save overrides if there are unsaved edits
        if self.entries and not (self._loader_worker and self._loader_worker.isRunning()):
            try:
                from src.utils.user_ini_manager import save_user_ini
                save_user_ini(self.entries, AppSettings.get_user_ini_path())
            except Exception as e:
                logger.error(f"Failed to auto-save overrides on exit: {e}")

        # Detach log handler before widgets are destroyed
        self.log_tab.remove_handler()

        # Clean up workers
        if self._loader_worker:
            self._loader_worker.quit()
            self._loader_worker.wait()

        # Save window state
        AppSettings.set_window_geometry(self.saveGeometry())
        AppSettings.set_window_state(self.saveState())

        event.accept()

    @timed
    def _filtered_entry_indices(self) -> list[int]:
        """Return indices into self.entries for entries passing the current filters."""
        column_filters = self.filter_header.get_filter_texts()
        category_filter = self.category_combo.currentText()
        status_filter = self.status_combo.currentText()
        hide_unmodified = self.hide_unmodified_check.isChecked()
        favorites_only = self.favorites_only_check.isChecked()
        prefix = AppSettings.get_favorite_prefix()
        active_col_filters = [(i, t) for i, t in enumerate(column_filters) if t]

        result = []
        for idx, entry in enumerate(self.entries):
            show = True

            if hide_unmodified and entry.status == "Unmodified":
                show = False
            elif category_filter != "All" and entry.category != category_filter:
                show = False
            elif status_filter != "All" and entry.status != status_filter:
                show = False
            elif favorites_only and not entry.custom_value.startswith(prefix):
                show = False
            elif active_col_filters:
                row_values = [
                    entry.category.lower(),
                    entry.key.lower(),
                    self.default_values.get(entry.key, "").lower(),
                    entry.original_value.lower(),
                    "★" if entry.custom_value.startswith(prefix) else "",
                    entry.custom_value.lower(),
                    entry.status.lower(),
                ]
                for col, filter_text in active_col_filters:
                    if filter_text not in row_values[col]:
                        show = False
                        break

            if show:
                result.append(idx)
        return result

    @timed
    def update_category_combo(self):
        """Update category combo with unique categories from entries.

        Always includes standard categories (Ships, Ship Items, Missions, Other)
        plus any custom categories found in the entries.
        """
        # Get unique categories from entries
        entry_categories = set(e.category for e in self.entries)

        # Always include standard categories, even if no entries exist for them yet
        standard_categories = {"Ships", "Ship Items", "Missions", "Commodities", "Other"}
        categories = sorted(standard_categories | entry_categories)

        self.category_combo.blockSignals(True)
        self.category_combo.clear()
        self.category_combo.addItem("All")
        self.category_combo.addItems(categories)
        self.category_combo.blockSignals(False)

    def _entry_index_for_row(self, row: int) -> int:
        """Map a visual table row to an index into self.entries."""
        return self._model.entry_index_for_row(row)

    def _on_preview_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Refresh the preview pane when the selected row changes."""
        if not current.isValid() or not self.entries:
            self.preview_pane.clear()
            return
        try:
            entry = self.entries[self._entry_index_for_row(current.row())]
        except (IndexError, AttributeError):
            self.preview_pane.clear()
            return
        raw = entry.custom_value or entry.original_value or ""
        self.preview_pane.setHtml(_render_preview_html(entry.key, raw))

    @pyqtSlot()
    def apply_filters(self):
        """Apply filters by updating the model's filtered index list."""
        if not self.entries:
            return
        indices = self._filtered_entry_indices()
        self._model.set_filtered_indices(indices)
        self.table_status_label.setText(f"Showing {len(indices)} of {len(self.entries)} strings")

    @pyqtSlot()
    def _on_grouped_sort(self):
        """Apply grouped sort by Key column."""
        self._model.set_grouped_sort(True)
        self._model.sort(1, Qt.SortOrder.AscendingOrder)

    @pyqtSlot()
    def clear_filters(self):
        """Clear all filters."""
        self.category_combo.blockSignals(True)
        self.status_combo.blockSignals(True)
        self.hide_unmodified_check.blockSignals(True)
        self.favorites_only_check.blockSignals(True)

        self.filter_header.clear_all()
        self.category_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.hide_unmodified_check.setChecked(False)
        self.favorites_only_check.setChecked(False)

        self.category_combo.blockSignals(False)
        self.status_combo.blockSignals(False)
        self.hide_unmodified_check.blockSignals(False)
        self.favorites_only_check.blockSignals(False)

        self.apply_filters()

    @pyqtSlot()
    def copy_filtered_to_clipboard(self):
        """Copy all visible filtered rows to clipboard (tab-separated)."""
        lines = []
        lines.append("Key\tOriginal Value\tCurrent Value\tCustom Value\tStatus")

        for proxy_row in range(self._model.rowCount()):
            entry_idx = self._entry_index_for_row(proxy_row)
            if entry_idx >= len(self.entries):
                continue

            entry = self.entries[entry_idx]
            line = f"{entry.key}\t{entry.original_value}\t{entry.original_value}\t{entry.custom_value}\t{entry.status}"
            lines.append(line)

        if len(lines) <= 1:
            QMessageBox.information(self, "Copy Filtered", "No rows to copy.")
            return

        text_to_copy = "\n".join(lines)
        clipboard = QApplication.clipboard()
        if clipboard is None:
            QMessageBox.warning(self, "Copy Error", "Clipboard is not available.")
            return
        clipboard.setText(text_to_copy)
        QMessageBox.information(self, "Copy Filtered", f"Copied {len(lines) - 1} rows to clipboard.")

    def show_context_menu(self, position):
        """Show right-click context menu."""
        proxy_index = self.table.indexAt(position)
        if not proxy_index.isValid():
            return

        proxy_row = proxy_index.row()
        entry_idx = self._entry_index_for_row(proxy_row)
        if entry_idx >= len(self.entries):
            return

        entry = self.entries[entry_idx]
        prefix = AppSettings.get_favorite_prefix()
        is_favorite = entry.custom_value.startswith(prefix)

        menu = QMenu(self)
        menu.addAction("Copy Cell", lambda: self.copy_cell(proxy_index))
        menu.addAction("Copy Key", lambda: self.copy_key(proxy_row))
        menu.addSeparator()
        menu.addAction("Edit", lambda: self.edit_cell(proxy_row))
        menu.addAction("Reset to Original", lambda: self.reset_to_original(proxy_row))
        menu.addSeparator()
        menu.addAction("Copy All Filtered", lambda: self.copy_filtered_to_clipboard())

        if entry.category == "Ships":
            menu.addSeparator()
            if is_favorite:
                menu.addAction("★ Remove from Favorites", lambda: self.toggle_favorite(proxy_row))
            else:
                menu.addAction("★ Add to Favorites", lambda: self.toggle_favorite(proxy_row))

        menu.exec(self.table.mapToGlobal(position))

    def edit_cell(self, proxy_row: int):
        """Edit custom value cell."""
        self.table.edit(self._model.index(proxy_row, COL_CUSTOM))

    def reset_to_original(self, proxy_row: int):
        """Reset custom value to original."""
        entry_idx = self._entry_index_for_row(proxy_row)
        if entry_idx < len(self.entries):
            entry = self.entries[entry_idx]
            entry.custom_value = ""
            entry.status = "Unmodified"
            self._model.notify_entry_changed(entry_idx)

    def copy_cell(self, proxy_index: QModelIndex):
        """Copy the clicked cell's text to clipboard."""
        text = proxy_index.data(Qt.ItemDataRole.DisplayRole)
        if text:
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(str(text))

    def copy_key(self, proxy_row: int):
        """Copy key to clipboard."""
        entry_idx = self._entry_index_for_row(proxy_row)
        if entry_idx < len(self.entries):
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(self.entries[entry_idx].key)
                self._status_bar().showMessage(f"Copied: {self.entries[entry_idx].key}")

    @pyqtSlot(QModelIndex)
    def _on_cell_clicked(self, proxy_index: QModelIndex):
        """Handle cell clicks — col 4 (★) toggles favorite for Ship rows."""
        if proxy_index.column() == COL_STAR:
            entry_idx = self._entry_index_for_row(proxy_index.row())
            if entry_idx < len(self.entries) and self.entries[entry_idx].category == "Ships":
                self.toggle_favorite(proxy_index.row())

    def toggle_favorite(self, proxy_row: int):
        """Add or remove the sort prefix from a ship's custom value."""
        entry_idx = self._entry_index_for_row(proxy_row)
        if entry_idx >= len(self.entries):
            return

        entry = self.entries[entry_idx]
        prefix = AppSettings.get_favorite_prefix()

        if entry.custom_value.startswith(prefix):
            new_value = entry.custom_value[len(prefix):]
            entry.custom_value = new_value if new_value != entry.original_value else ""
        else:
            base = entry.custom_value if entry.custom_value else entry.original_value
            entry.custom_value = prefix + base

        entry.status = "Modified" if entry.custom_value else "Unmodified"

        # Notify the model — view updates automatically
        self._model.notify_entry_changed(entry_idx)

    def restore_window_state(self):
        """Restore window geometry and state."""
        geometry = AppSettings.get_window_geometry()
        state = AppSettings.get_window_state()

        if geometry:
            self.restoreGeometry(geometry)
        if state:
            self.restoreState(state)

    def create_anchor_id(self, text: str) -> str:
        """Convert text to anchor ID (used in markdown links)."""
        return text.lower().replace(" ", "-").replace(".", "").replace("&", "and")

    def markdown_to_html(self, markdown_text: str) -> str:
        """Convert markdown to HTML with theme-aware styling."""
        # Pull directly from the application palette so this is stable even when
        # called synchronously right after QApplication.setPalette (widget-local
        # palettes can lag one event-loop tick behind the app palette).
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QPalette
        palette = QApplication.palette()
        text_color = palette.color(QPalette.ColorRole.Text).name()
        base_color = palette.color(QPalette.ColorRole.Base).name()
        link_color = palette.color(QPalette.ColorRole.Link).name()

        # Build HTML with styling
        html = "<html><head><style>"
        html += f"body {{ font-family: Segoe UI, Arial, sans-serif; line-height: 1.8; padding: 20px; font-size: 15px; color: {text_color}; background-color: {base_color}; }}"
        html += f"h1 {{ color: {link_color}; border-bottom: 3px solid {link_color}; padding-bottom: 10px; font-size: 32px; font-weight: bold; margin-top: 20px; }}"
        html += f"h2 {{ color: {link_color}; border-bottom: 2px solid {link_color}; padding-bottom: 5px; margin-top: 30px; font-size: 24px; font-weight: bold; }}"
        html += f"h3 {{ color: {link_color}; margin-top: 20px; font-size: 20px; font-weight: bold; }}"
        html += f"p {{ font-size: 15px; margin: 10px 0; color: {text_color}; }}"
        html += f"li {{ font-size: 15px; margin: 5px 0; color: {text_color}; }}"
        html += f"a {{ color: {link_color}; text-decoration: underline; font-weight: 500; }}"
        html += f"a:hover {{ text-decoration: underline; opacity: 0.8; cursor: pointer; }}"
        html += f"code {{ background-color: rgba(0,0,0,0.05); padding: 2px 6px; border-radius: 3px; font-family: 'Courier New', monospace; font-size: 14px; }}"
        html += f"pre {{ background-color: rgba(0,0,0,0.05); padding: 10px; border-radius: 5px; overflow-x: auto; font-size: 14px; }}"
        html += f"ul {{ margin-left: 20px; font-size: 15px; }}"
        html += f"ol {{ margin-left: 20px; font-size: 15px; }}"
        html += f"strong {{ font-weight: bold; }}"
        html += f"blockquote {{ border-left: 4px solid {link_color}; padding-left: 15px; font-style: italic; font-size: 15px; }}"
        html += "</style></head><body>"

        lines = markdown_text.split('\n')
        in_code_block = False
        in_list = False
        list_type = None
        prev_blank = False

        for line in lines:
            # Code blocks
            if line.strip().startswith('```'):
                if in_code_block:
                    html += "</pre>"
                    in_code_block = False
                else:
                    html += "<pre><code>"
                    in_code_block = True
                continue

            if in_code_block:
                html += line + "\n"
                continue

            # Headers
            if line.startswith('# '):
                if in_list:
                    html += f"</{list_type}>"
                    in_list = False
                header_text = line[2:].strip()
                anchor_id = self.create_anchor_id(header_text)
                html += f"<h1 id='{anchor_id}'>{self._convert_markdown_inline(header_text)}</h1>"
                prev_blank = False
            elif line.startswith('## '):
                if in_list:
                    html += f"</{list_type}>"
                    in_list = False
                header_text = line[3:].strip()
                anchor_id = self.create_anchor_id(header_text)
                html += f"<h2 id='{anchor_id}'>{self._convert_markdown_inline(header_text)}</h2>"
                prev_blank = False
            elif line.startswith('### '):
                if in_list:
                    html += f"</{list_type}>"
                    in_list = False
                header_text = line[4:].strip()
                anchor_id = self.create_anchor_id(header_text)
                html += f"<h3 id='{anchor_id}'>{self._convert_markdown_inline(header_text)}</h3>"
                prev_blank = False
            # Lists
            elif line.strip().startswith('- ') or line.strip().startswith('* '):
                if not in_list or list_type != 'ul':
                    if in_list:
                        html += f"</{list_type}>"
                    html += "<ul>"
                    in_list = True
                    list_type = 'ul'
                list_text = line.strip()[2:].strip()
                list_text = self._convert_markdown_inline(list_text)
                html += f"<li>{list_text}</li>"
                prev_blank = False
            elif line.strip() and line[0].isdigit() and '. ' in line:
                if not in_list or list_type != 'ol':
                    if in_list:
                        html += f"</{list_type}>"
                    html += "<ol>"
                    in_list = True
                    list_type = 'ol'
                list_text = line.strip()
                # Remove number and period
                list_text = list_text[list_text.index('. ') + 2:].strip()
                list_text = self._convert_markdown_inline(list_text)
                html += f"<li>{list_text}</li>"
                prev_blank = False
            # Empty lines (skip consecutive blank lines)
            elif not line.strip():
                if in_list:
                    html += f"</{list_type}>"
                    in_list = False
                    prev_blank = True
                elif not prev_blank:
                    # Only add one blank line, not consecutive ones
                    prev_blank = True
                continue
            # Paragraphs
            else:
                if in_list:
                    html += f"</{list_type}>"
                    in_list = False
                line = self._convert_markdown_inline(line)
                html += f"<p>{line}</p>"
                prev_blank = False

        # Close any open tags
        if in_list:
            html += f"</{list_type}>"
        if in_code_block:
            html += "</pre>"

        html += "</body></html>"
        return html

    def _convert_markdown_links(self, text: str) -> str:
        """Convert markdown links [text](url) to HTML links."""
        import re
        # Match [text](url) pattern
        pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        replacement = r'<a href="\2">\1</a>'
        return re.sub(pattern, replacement, text)

    def _convert_markdown_inline(self, text: str) -> str:
        """Apply inline Markdown (code, links, bold, italic) to a single line.

        Order matters: inline ``code`` is stashed first so ``**`` or ``_``
        inside a code span stay literal, then links / bold / italic run over
        the remaining text. Bold runs before italic so a ``**`` pair isn't
        mis-parsed as two ``*italic*`` brackets.
        """
        import re
        from html import escape

        # 1. Stash inline code spans behind opaque placeholders so bold/italic
        #    regexes can't touch their content (e.g. `vehicle_Name*` shouldn't
        #    become vehicle_Name<em>).
        code_spans: list[str] = []

        def _stash(match):
            code_spans.append(match.group(1))
            return f"\x00CODE{len(code_spans) - 1}\x00"

        text = re.sub(r"`([^`]+)`", _stash, text)

        # 2. Links — do before bold/italic so '_' inside URLs doesn't get
        #    chewed.
        text = self._convert_markdown_links(text)

        # 3. Bold: **...** and __...__.
        text = re.sub(r"\*\*([^*]+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"__([^_]+?)__", r"<strong>\1</strong>", text)

        # 4. Italic: *...* (only; '_' is too common in loc-keys/identifiers
        #    to italicize safely without a proper tokenizer). Require no '*'
        #    on either side of the pair so we don't steal halves of a '**'
        #    bold run that happened to not match step 3.
        text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<em>\1</em>", text)

        # 5. Restore code spans — escape the content so any stray angle
        #    brackets inside a backtick span render as literal text.
        for i, content in enumerate(code_spans):
            text = text.replace(f"\x00CODE{i}\x00", f"<code>{escape(content)}</code>")

        return text
