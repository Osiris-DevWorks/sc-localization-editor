"""Main window for Open Strings."""

import html as _html_mod
import logging
import os
import re as _re_mod
from pathlib import Path

from PyQt6.QtCore import QModelIndex, Qt, QTimer, QUrl, pyqtSlot
from PyQt6.QtGui import QDesktopServices, QFont, QIcon
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QStatusBar,
    QTableView,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from src.gui.coach_mark import CoachMarkStep, TutorialTour
from src.gui.config_tab import ConfigTab
from src.gui.enhancements_tab import EnhancementsTab
from src.gui.filter_header import FilterHeaderView
from src.gui.log_tab import LogTab
from src.gui.string_table_model import (
    COL_CUSTOM,
    COL_STAR,
    StringTableModel,
)
from src.gui.theme import BRAND_FONT_FAMILY, get_button_color, get_button_text_color, get_tagline_color, get_title_color
from src.gui.workers import (
    AnimatedProgressDialog,
    AppUpdateCheckerWorker,
    DataForgeExtractWorker,
    EnhancementsGeneratorWorker,
    FileLoaderWorker,
    P4kExtractWorker,
    SelectAllDelegate,
    StartupSyncWorker,
    get_resource_path,
)
from src.merger.ini_merger import merge_sources_by_hierarchy
from src.models.string_model import StringEntry
from src.parser.ini_parser import load_source_files, load_sources_from_settings
from src.utils.applied_file_validator import validate_applied_file
from src.utils.entry_filter import filter_entry_indices
from src.utils.perf import timed
from src.utils.settings import AppSettings
from src.utils.version import get_version

logger = logging.getLogger(__name__)

# Preview-pane token translation — turns the raw loc-string format the game
# reads into styled HTML that mirrors the in-game feel. Patterns:
#   \n              → line break
#   <EM3>X</EM3>    → block-level heading (section dividers)
#   <EM4>X</EM4>    → inline emphasis (stats / tag values)
#   ~mission(Foo)   → greyed placeholder [Foo] (game substitutes at runtime)
# Escape first, then substitute against the escaped tags so raw text
# containing < or & can't break rendering.

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


class MainWindow(QMainWindow):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Open Strings v{get_version()}")
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
        self._loader_worker: FileLoaderWorker | None = None

        # Startup sync worker
        self._startup_sync_worker: StartupSyncWorker | None = None

        # App update checker worker
        self._update_checker_worker: AppUpdateCheckerWorker | None = None

        # P4K extraction worker and progress dialog
        self._p4k_worker: P4kExtractWorker | None = None
        self._p4k_progress: QProgressDialog | None = None

        # Enhancements generation worker
        self._enhancements_worker: EnhancementsGeneratorWorker | None = None
        self._enhancements_progress_dialog: AnimatedProgressDialog | None = None

        # DataForge extraction worker
        self._forge_worker: DataForgeExtractWorker | None = None
        self._forge_progress_dialog: AnimatedProgressDialog | None = None

        # Track whether we've prompted for enhancements on startup (prevents duplicate dialogs)
        self._enhancements_prompted_on_startup = False
        # Flag to defer enhancements checking until after file loading completes (avoid I/O contention)
        self._check_enhancements_after_loading = False

        # Status bar state (composed message) - tracks sync status per source
        self._source_status: dict[str, str] = {}  # source_name -> status_string

        # Progress dialogs
        self._startup_progress: AnimatedProgressDialog | None = None
        self._loading_progress: QProgressDialog | None = None

        self.help_dock: QDockWidget | None = None
        self._tutorial_tour: TutorialTour | None = None
        self._channel_indicator: QLabel | None = None
        self._app_version_indicator: QLabel | None = None

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

        QTimer.singleShot(0, ensure_user_cfg_language)

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
        self.title_label = QLabel("OPEN STRINGS")
        title_font = QFont(BRAND_FONT_FAMILY)
        title_font.setPointSize(22)
        self.title_label.setFont(title_font)
        main_layout.addWidget(self.title_label)

        self.tagline_label = QLabel("STRING EDITOR FOR STAR CITIZEN")
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
        self.preview_pane.setPlaceholderText("Select a row to preview its rendered text.")
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

        # Help side-panel. Created eagerly (before restore_window_state runs)
        # so Qt's native saveState/restoreState can persist its open/closed
        # width across sessions — a dock only gets remembered if it exists
        # with a stable objectName at restoreState() time. Start hidden so
        # first-launch users aren't surprised by a panel they didn't ask for;
        # restoreState will reopen it if the user had it open last session.
        self._ensure_help_dock()
        if self.help_dock is not None:
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
        self.open_loc_dir_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.open_loc_dir_btn.setToolTip("Open the game's localization directory in Windows Explorer")
        self.open_loc_dir_btn.clicked.connect(self.open_localization_dir)
        button_layout.addWidget(self.open_loc_dir_btn)

        # Green — commit
        self.apply_btn = QPushButton("Apply to Game")
        self.apply_btn.setStyleSheet(
            f"background-color: {get_button_color('apply')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.apply_btn.setToolTip(
            "Write the merged table contents to the game's global.ini. A timestamped backup of the current global.ini is created first."
        )
        self.apply_btn.clicked.connect(self.apply_to_game)
        button_layout.addWidget(self.apply_btn)

        # Red-orange — rollback
        self.restore_backup_btn = QPushButton("Restore Backup")
        self.restore_backup_btn.setStyleSheet(
            f"background-color: {get_button_color('restore')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.restore_backup_btn.setToolTip(
            "Restore a previous global.ini from Documents\\Open Strings\\backups\\. Up to 5 timestamped backups are kept; the oldest is pruned when a new one is created."
        )
        self.restore_backup_btn.clicked.connect(self.restore_backup)
        button_layout.addWidget(self.restore_backup_btn)

        # Gray group — cleanup
        self.clear_loc_btn = QPushButton("Clear Localization")
        self.clear_loc_btn.setStyleSheet(
            f"background-color: {get_button_color('clear')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.clear_loc_btn.setToolTip(
            "Delete the applied global.ini from the game's localization directory, reverting to vanilla game text"
        )
        self.clear_loc_btn.clicked.connect(self.clear_localization)
        button_layout.addWidget(self.clear_loc_btn)

        self.clear_cache_btn = QPushButton("Clear Cache")
        self.clear_cache_btn.setStyleSheet(
            f"background-color: {get_button_color('clear')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.clear_cache_btn.setToolTip(
            "Delete all cached source files (base.ini, contracts.ini, etc.) from the local cache directory"
        )
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        button_layout.addWidget(self.clear_cache_btn)

        # Help — sits with the other toolbar buttons rather than floating
        # right; uses the 'open' role so it shares the blue/cyan/gold
        # information-action palette with Open Localization Dir.
        self.help_btn = QPushButton("Help")
        self.help_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.help_btn.setCheckable(True)
        self.help_btn.setToolTip("Toggle the Help side-panel")
        self.help_btn.clicked.connect(self.show_help)
        button_layout.addWidget(self.help_btn)

        # Tutorial — shares the 'open' blue/cyan/gold info-action role with
        # Help so the two read as a pair. Always restartable on demand.
        self.tutorial_btn = QPushButton("Tutorial")
        self.tutorial_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;"
        )
        self.tutorial_btn.setToolTip(
            "Start the guided tour of the workflow — runs automatically on first launch; click here anytime to replay."
        )
        self.tutorial_btn.clicked.connect(self._start_tutorial)
        button_layout.addWidget(self.tutorial_btn)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        # Filter row
        filter_layout = QHBoxLayout()

        filter_layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(200)
        self.category_combo.setToolTip(
            "Filter rows by domain (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other). Categories are derived from the loc-key prefix."
        )
        self.category_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.category_combo)

        filter_layout.addWidget(QLabel("Status:"))
        self.status_combo = QComboBox()
        self.status_combo.addItems(["All", "Modified", "Unmodified", "New"])
        self.status_combo.setMaximumWidth(120)
        self.status_combo.setToolTip(
            "Filter by modification status. Modified = you've set a Custom Value; New = key exists only in enhancements/user.ini, not in the base file; Unmodified = default text only."
        )
        self.status_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_combo)

        self.hide_unmodified_check = QCheckBox("Hide Unmodified")
        self.hide_unmodified_check.setToolTip(
            "Show only rows where you've set a Custom Value. Same as the Status filter's Modified option but togglable on its own."
        )
        self.hide_unmodified_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.hide_unmodified_check)

        self.favorites_only_check = QCheckBox("★ Favorites Only")
        self.favorites_only_check.setToolTip(
            "Show only rows you've starred as favorites. Favorites get a configurable prefix prepended to their name so they sort to the top of the in-game list."
        )
        self.favorites_only_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.favorites_only_check)

        self.grouped_sort_btn = QPushButton("Group Sort")
        self.grouped_sort_btn.setToolTip("Sort titles and descriptions together for the same entity")
        self.grouped_sort_btn.setMaximumWidth(100)
        self.grouped_sort_btn.clicked.connect(self._on_grouped_sort)
        filter_layout.addWidget(self.grouped_sort_btn)

        self.clear_filters_btn = QPushButton("Clear Filters")
        self.clear_filters_btn.setMaximumWidth(100)
        self.clear_filters_btn.setToolTip(
            "Reset every filter (category, status, search, per-column boxes, checkboxes) so the full table is shown."
        )
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
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)  # Key
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # Default Value
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)  # Current Value
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # ★
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)  # Custom Value
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

        btn_row = QHBoxLayout()
        self._check_update_btn = QPushButton("Check for Updates")
        self._check_update_btn.setMaximumWidth(180)
        self._check_update_btn.setToolTip("Check whether a newer version of Open Strings is available on GitHub")
        self._check_update_btn.clicked.connect(lambda: self._check_for_app_update(manual=True))
        btn_row.addWidget(self._check_update_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

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
            with open(about_path, encoding="utf-8") as f:
                about_content = f.read()
            about_content = about_content.replace("# Open Strings", f"# Open Strings v{get_version()}")
            self.about_browser.setHtml(self.markdown_to_html(about_content))
        except Exception as e:
            logger.error(f"Error loading ABOUT.md: {e}", exc_info=True)
            self.about_browser.setHtml(
                f"<h1>About</h1><p>Unable to load about information.</p><p style='color: gray;'>{str(e)}</p>"
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
            logger.debug(
                f"Cache file not found: {cache_file}. Default values will be empty until sources are downloaded."
            )

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
                backup_files = sorted(backup_dir.glob("global.ini.bak_*"), key=lambda f: f.stat().st_mtime)

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
                name
                for name in hierarchy
                if name in active_source_names
                and name != AppSettings.SOURCE_USER
                and name != "enhancements"
                and name not in sources_dict
                and AppSettings.is_source_enabled(name)
            ]
            if missing_sources:
                names = ", ".join(missing_sources)
                reply = QMessageBox.warning(
                    self,
                    "Missing Sources",
                    f"The following enabled sources could not be loaded:\n\n  {names}\n\n"
                    "Their customizations will NOT be included in the applied file.\n\n"
                    "Apply anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

            # Build user overrides dict from entries with custom_value
            user_overrides_dict = {entry.key: entry.custom_value for entry in self.entries if entry.custom_value}

            # Merge all sources in hierarchy order, with user edits on top
            merged_dict = merge_sources_by_hierarchy(sources_dict, hierarchy, user_overrides_dict)

            # Get a base file to use for structure preservation
            # Use the first source file from hierarchy
            base_file = None
            for source_name in hierarchy:
                source_path = AppSettings.get_source_path(source_name)
                # Check if it's a URL (remote source) - use cache
                if source_path and (source_path.startswith("http://") or source_path.startswith("https://")):
                    # Map source name to cache file
                    cache_mapping = {
                        AppSettings.SOURCE_GLOBAL: "base.ini",
                    }
                    if source_name in cache_mapping:
                        cache_file = AppSettings.get_cache_dir() / cache_mapping[source_name]
                        if cache_file.exists():
                            base_file = cache_file
                            break
                # Otherwise check if it's a local file that exists
                elif source_path and Path(source_path).exists():
                    base_file = Path(source_path)
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
            stock_keys_hint = set(sources_dict["global"].keys()) if AppSettings.SOURCE_GLOBAL in sources_dict else None
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

                self._status_bar().showMessage("Apply failed — validation error")
                QMessageBox.critical(
                    self,
                    "Validation Failed",
                    f"The written file failed validation and has been deleted.\n\n{validation_msg}{restore_note}",
                )
                return

            # Save user overrides to AppData
            from src.utils.user_ini_manager import save_user_ini

            user_count = save_user_ini(self.entries, AppSettings.get_user_ini_path())

            # Count enhancement entries
            enhancement_count = sum(1 for entry in self.entries if entry.source_file == "enhancements")

            # Ensure user.cfg has language setting
            from src.utils.user_cfg import ensure_user_cfg_language

            QTimer.singleShot(0, ensure_user_cfg_language)

            logger.info(f"Applied to game: {target_path}")
            self._status_bar().showMessage(
                f"Applied to game | {user_count} user edits | {enhancement_count} enhancements"
            )
            QMessageBox.information(
                self,
                "Success",
                f"Applied to {target_path}\n\n  User edits: {user_count}\n  Enhancements: {enhancement_count}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to apply to game: {e}")
            logger.error(f"Error applying to game: {e}")

    def _validate_applied_file(
        self,
        written_path: Path,
        stock_keys: set[str] | None = None,
    ) -> str:
        """Validate the written global.ini. Delegates to applied_file_validator."""
        return validate_applied_file(written_path, AppSettings.get_cache_dir(), stock_keys)

    @pyqtSlot()
    def clear_localization(self):
        """Delete global.ini from the active channel's localization directory, reverting to vanilla text."""
        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, "Warning", "Please configure game install path in Config tab")
            return

        global_ini = AppSettings.get_global_ini_path()
        loc_dir = global_ini.parent

        if not global_ini.exists():
            QMessageBox.information(
                self,
                "Nothing to Clear",
                "No custom global.ini found in the game's localization directory.\n"
                "The game is already using vanilla text.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Clear Localization",
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
            self._status_bar().showMessage("Localization cleared — game reverted to vanilla text")
            QMessageBox.information(
                self,
                "Done",
                "Custom localization removed.\n"
                "The game will now use its default text.\n\n"
                "To re-apply your overrides and stat descriptions, click Apply to Game.",
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to delete global.ini: {e}")
            logger.error(f"Error clearing localization: {e}")

    @pyqtSlot()
    def clear_cache(self):
        """Delete cached source files from the cache directory. Optionally clear DataForge cache."""
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
            self,
            "Clear Cache",
            msg,
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
                self,
                "Clear DataForge Cache?",
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
                self,
                "Directory Not Found",
                f"Localization directory not found:\n{loc_dir}\n\nCheck your game install path in the Config tab.",
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
                QMessageBox.warning(
                    self, "Warning", "No sources configured. Please configure data sources in Config tab."
                )
                return

            self._status_bar().showMessage("Merging sources...")

            try:
                # Load synchronously in main thread
                logger.info("Merging configured sources...")
                entries = load_source_files(
                    sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories
                )
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
                self._status_bar().showMessage("Merge failed")

        except Exception as e:
            logger.exception(f"Error in perform_merge_and_reload: {e}")
            QMessageBox.critical(self, "Error", f"Failed to load sources: {e}")

    # ── INI Import ────────────────────────────────────────────────────────────

    @pyqtSlot()
    def _apply_branding_styles(self):
        """Apply per-theme colors to the title + tagline header labels."""
        self.title_label.setStyleSheet(f"color: {get_title_color()};")
        self.tagline_label.setStyleSheet(f"font-size: 11px; letter-spacing: 2px; color: {get_tagline_color()};")

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
        import tempfile
        import urllib.request

        from PyQt6.QtWidgets import (
            QDialog,
        )

        from src.parser.ini_parser import parse_ini_file
        from src.utils.user_ini_manager import save_user_ini_dict

        # Step 1: Get source path/URL from user
        source = self._get_import_source()
        if not source:
            return

        temp_file = None
        try:
            # Step 2: Resolve to local file
            if source.startswith("https://") or source.startswith("http://"):
                if source.startswith("http://"):
                    QMessageBox.warning(
                        self,
                        "Insecure URL",
                        "Only HTTPS URLs are accepted. The URL you entered uses HTTP and will not be downloaded.",
                    )
                    return
                # Auto-convert GitHub web URLs to raw URLs
                if source.startswith("https://github.com/"):
                    source = source.replace("https://github.com/", "https://raw.githubusercontent.com/")
                    source = source.replace("/blob/", "/")

                self._status_bar().showMessage("Downloading INI file...")
                try:
                    temp_file = tempfile.NamedTemporaryFile(suffix=".ini", delete=False)
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
                QMessageBox.warning(self, "No Base Data", "Base INI not loaded yet. Extract from Data.p4k first.")
                return

            valid_keys = {k: v for k, v in imported.items() if k in self.default_values}
            excluded_count = len(imported) - len(valid_keys)

            if not valid_keys:
                QMessageBox.warning(
                    self,
                    "No Valid Keys",
                    f"None of the {len(imported)} imported keys exist in base.ini.\nAll keys were excluded.",
                )
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
                QMessageBox.information(
                    self, "Nothing to Import", "All imported keys already exist in user.ini with the same values."
                )
                return

            if not conflicts:
                reply = QMessageBox.question(
                    self,
                    "Import INI",
                    f"{len(auto_add)} new keys will be added to user.ini.\n"
                    f"{excluded_count} keys excluded (not in base.ini).\n\n"
                    "Proceed?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
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
            QMessageBox.information(
                self,
                "Import Complete",
                f"Import successful.\n\n"
                f"  Added: {len(auto_add)} keys\n"
                f"  Conflicts resolved: {len(resolutions)} keys\n"
                f"  Excluded: {excluded_count} keys",
            )

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
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
            QVBoxLayout,
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
            path, _ = QFileDialog.getOpenFileName(dialog, "Select INI File", "", "INI Files (*.ini);;All Files (*)")
            if path:
                line_edit.setText(path)

        browse_btn.clicked.connect(browse)
        input_row.addWidget(browse_btn)
        layout.addLayout(input_row)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
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
            "Backup Files (*.bak_*);;INI Files (*.ini);;All Files (*)",
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
                self.entries,
                self.default_values,
                AppSettings.get_favorite_prefix(),
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
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
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
        reloads HELP.md (bundled via OpenStrings.spec). Falls back to a
        short stub if the file is missing so a misconfigured build still
        shows something usable instead of a blank panel.
        """
        if not hasattr(self, "help_browser"):
            return
        from PyQt6.QtWidgets import QApplication

        self.help_browser.setPalette(QApplication.palette())
        try:
            help_path = get_resource_path("HELP.md")
            with open(help_path, encoding="utf-8") as f:
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
        PyInstaller onedir via OpenStrings.spec). The first call creates the
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
            "welcome": {"target": lambda: None, "pre_action": None},
            "extract": {"target": lambda: self.config_tab._extract_btn, "pre_action": _switch_to(config_tab)},
            "edit": {"target": lambda: self.table, "pre_action": _switch_to(strings_tab)},
            "preview": {"target": lambda: self.preview_pane, "pre_action": _switch_to(strings_tab)},
            "apply": {"target": lambda: self.apply_btn, "pre_action": None},
            "enhancements": {
                "target": lambda: self.enhancements_tab._generate_enhancements_btn,
                "pre_action": _switch_to(enh_tab),
            },
            "help": {"target": lambda: self.help_btn, "pre_action": _switch_to(strings_tab)},
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
                logger.warning(f"Tutorial step id {step_id!r} has no wiring entry in _tutorial_step_wiring(); skipped")
                continue
            title = raw.get("title", "")
            description = raw.get("description", "")
            if not title or not description:
                logger.warning(f"Tutorial step {step_id!r} missing title/description; skipped")
                continue
            steps.append(
                CoachMarkStep(
                    target=w["target"],
                    title=title,
                    description=description,
                    pre_action=w.get("pre_action"),
                    preferred_side=raw.get("preferred_side", "auto"),
                )
            )

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
        self._check_for_app_update(manual=False)

    # ── App update check ─────────────────────────────────────────────────────

    _UPDATE_CHECK_INTERVAL = 6 * 60 * 60  # 6 hours between auto-checks

    def _check_for_app_update(self, manual: bool = False) -> None:
        """Start an async app-update check.

        Auto-checks are throttled to once every 6 hours.  Manual checks
        (triggered from the About tab button) always run and show feedback
        regardless of outcome.  A second call while a check is already
        running is silently ignored.
        """
        import time

        if self._update_checker_worker is not None and self._update_checker_worker.isRunning():
            return

        if not manual:
            last = AppSettings.get_last_update_check_epoch()
            if last and (time.time() - last) < self._UPDATE_CHECK_INTERVAL:
                return

        self._update_checker_worker = AppUpdateCheckerWorker()
        self._update_checker_worker.finished.connect(
            lambda ok, ver, url: self._on_update_check_finished(ok, ver, url, manual=manual)
        )
        self._update_checker_worker.error.connect(lambda msg: self._on_update_check_error(msg, manual=manual))
        self._update_checker_worker.start()

        if manual:
            self._status_bar().showMessage("Checking for updates…")

    @pyqtSlot(bool, str, str)
    def _on_update_check_finished(
        self, update_available: bool, new_version: str, release_url: str, *, manual: bool
    ) -> None:
        """Handle the result of an update check."""
        if self._update_checker_worker is not None:
            self._update_checker_worker.quit()
            self._update_checker_worker.wait()
            self._update_checker_worker = None

        if update_available:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Update Available")
            msg_box.setIcon(QMessageBox.Icon.Information)
            msg_box.setText(f"<b>Open Strings v{new_version}</b> is available.")
            msg_box.setInformativeText(
                "Click <b>Open Release Page</b> to download the new version,\nor <b>Later</b> to dismiss."
            )
            open_btn = msg_box.addButton("Open Release Page", QMessageBox.ButtonRole.AcceptRole)
            msg_box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
            msg_box.exec()
            if msg_box.clickedButton() is open_btn:
                QDesktopServices.openUrl(QUrl(release_url))
        elif manual:
            QMessageBox.information(self, "Up to Date", f"You are running the latest version ({get_version()}).")

        if manual:
            self._status_bar().showMessage("Ready")

    def _on_update_check_error(self, message: str, *, manual: bool) -> None:
        """Handle update check network failure."""
        if self._update_checker_worker is not None:
            self._update_checker_worker.quit()
            self._update_checker_worker.wait()
            self._update_checker_worker = None

        if manual:
            QMessageBox.warning(
                self,
                "Update Check Failed",
                f"Could not reach the update server.\n\nDetail: {message}",
            )
            self._status_bar().showMessage("Ready")

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
        if (
            event.key() == Qt.Key.Key_C
            and event.modifiers() == Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
        ):
            # Ctrl+Shift+C: Copy filtered rows
            self.copy_filtered_to_clipboard()
        else:
            super().keyPressEvent(event)

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
        """Install a permanent status-bar widget showing the app version."""
        if self._app_version_indicator is not None:
            return
        self._app_version_indicator = QLabel(f"v{get_version()}")
        self._app_version_indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
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
                    f"Re-synced {source_name} source path for channel {channel}: {stored or '(unset)'} → {canonical}"
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
            self._status_bar().showMessage(f"Switched to {channel} — extracting Data.p4k…")
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
        self._startup_progress = AnimatedProgressDialog("Syncing sources...", parent=self, title="Starting Up")
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
        base_ini = AppSettings.get_cache_dir() / "base.ini"

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
            self,
            "Extract from Data.p4k",
            msg,
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
            self,
            "DataForge Cache Outdated",
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
        if not (cache_dir / "base.ini").exists():
            return
        if self._enhancements_worker is not None or self._forge_worker is not None:
            return

        # Only check enabled categories
        enabled = AppSettings.get_enabled_enhancement_categories()
        missing = [key for key in enabled if not (cache_dir / AppSettings.ENHANCEMENTS_FILES[key]).exists()]
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
        from PyQt6.QtWidgets import QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

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
        layout.addWidget(
            QLabel(
                f"{n} enhancement {noun} missing.\n"
                "Select which to generate.\n"
                "You can change this later in the Enhancements tab."
            )
        )

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
            "DataForge data will be extracted automatically if not already cached.\nFirst run takes ~5-10 minutes."
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
            except (TypeError, RuntimeError) as _disc_err:
                # TypeError  — signal was never connected (harmless)
                # RuntimeError — underlying C++ object already deleted (harmless)
                # Any other exception propagates normally.
                if "disconnect" not in str(_disc_err).lower() and not isinstance(_disc_err, TypeError):
                    raise
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
        if self._loader_worker is not None:
            self._loader_worker.quit()
            self._loader_worker.wait()
            self._loader_worker = None
        if "No sources configured" in error_msg or "file not found" in error_msg.lower():
            self._status_bar().showMessage(
                'Base localization file not found — use "Extract from Data.p4k" in the Config tab to get started.'
            )
            self.tabs.setCurrentIndex(self._config_tab_index)
            return
        QMessageBox.critical(self, "Error", f"Failed to load sources: {error_msg}")

    def _run_enhancements_pipeline(self):
        """Entry point for the enhancements button: extract DataForge if needed, then generate enhancements."""
        if self._enhancements_worker is not None or self._forge_worker is not None:
            return  # already running

        from src.utils.pak_extractor import dataforge_cache_is_fresh

        forge_dir = AppSettings.get_dataforge_cache_dir()
        p4k_path = AppSettings.get_p4k_path()

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

        p4k_path = AppSettings.get_p4k_path()
        unp4k_exe = AppSettings.get_unp4k_exe_path()
        unforge_exe = AppSettings.get_unforge_exe_path()
        forge_dir = AppSettings.get_dataforge_cache_dir()

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
        output_path = AppSettings.get_cache_dir() / "base.ini"
        unp4k_exe = AppSettings.get_unp4k_exe_path()

        self._p4k_worker = P4kExtractWorker(p4k_path, output_path, unp4k_exe)
        self._p4k_progress = AnimatedProgressDialog(
            "Extracting global.ini from Data.p4k...", parent=self, title="P4K Extraction"
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
            local_path = str(AppSettings.get_cache_dir() / "base.ini")
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

        # Cleanly shut down all background workers before the window is destroyed.
        # Without this, Qt may tear down the window mid-operation and leave threads
        # in an undefined state or DataForge temp files half-written.
        _workers = (
            self._loader_worker,
            self._startup_sync_worker,
            self._update_checker_worker,
            self._p4k_worker,
            self._enhancements_worker,
            self._forge_worker,
        )
        for _w in _workers:
            if _w is not None and _w.isRunning():
                _w.quit()
                if not _w.wait(5000):  # 5 s — generous for DataForge, avoids deadlock
                    logger.warning("Worker %s did not stop within 5 s on close", type(_w).__name__)

        # Flush registry writes
        AppSettings.settings().sync()

        # Save window state
        AppSettings.set_window_geometry(self.saveGeometry().data())
        AppSettings.set_window_state(self.saveState().data())

        event.accept()

    @timed
    def _filtered_entry_indices(self) -> list[int]:
        """Return indices into self.entries for entries passing the current filters."""
        return filter_entry_indices(
            entries=self.entries,
            default_values=self.default_values,
            column_filters=self.filter_header.get_filter_texts(),
            category_filter=self.category_combo.currentText(),
            status_filter=self.status_combo.currentText(),
            hide_unmodified=self.hide_unmodified_check.isChecked(),
            favorites_only=self.favorites_only_check.isChecked(),
            favorite_prefix=AppSettings.get_favorite_prefix(),
        )

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
            new_value = entry.custom_value[len(prefix) :]
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
        """Convert text to anchor ID."""
        from src.gui.markdown_renderer import create_anchor_id

        return create_anchor_id(text)

    def markdown_to_html(self, markdown_text: str) -> str:
        """Convert markdown to HTML with theme-aware styling."""
        from PyQt6.QtGui import QPalette
        from PyQt6.QtWidgets import QApplication

        from src.gui.markdown_renderer import markdown_to_html as _render

        palette = QApplication.palette()
        return _render(
            markdown_text,
            text_color=palette.color(QPalette.ColorRole.Text).name(),
            base_color=palette.color(QPalette.ColorRole.Base).name(),
            link_color=palette.color(QPalette.ColorRole.Link).name(),
        )

    def _convert_markdown_links(self, text: str) -> str:
        """Delegate to markdown_renderer module."""
        from src.gui.markdown_renderer import _convert_markdown_links

        return _convert_markdown_links(text)

    def _convert_markdown_inline(self, text: str) -> str:
        """Delegate to markdown_renderer module."""
        from src.gui.markdown_renderer import _convert_markdown_inline

        return _convert_markdown_inline(text)
