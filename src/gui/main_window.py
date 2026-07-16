"""Main window for Smart Citizen."""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread, pyqtSignal, QModelIndex, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QCheckBox,
    QFileDialog, QMessageBox, QTabWidget,
    QHeaderView, QStatusBar, QFrame, QStyledItemDelegate,
    QAbstractItemView, QMenu, QProgressDialog, QProgressBar, QTextBrowser,
    QTableView, QStackedLayout, QStackedWidget, QGraphicsOpacityEffect,
    QDockWidget, QPlainTextEdit, QInputDialog,
)
from PyQt6.QtGui import QColor, QFont, QCursor, QPixmap, QIcon, QPalette
from PyQt6.QtCore import QUrl
from PyQt6.QtGui import QDesktopServices

from src.gui.blueprint_tracker_tab import BlueprintTrackerTab
from src.gui.coach_mark import CoachMarkStep, TutorialTour
from src.gui.config_tab import ConfigTab
from src.gui.error_dialog import ErrorDialogHandler, _ErrorDialogEmitter
from src.gui.enhancements_tab import EnhancementsTab
from src.gui.filter_header import FilterHeaderView
from src.gui.log_tab import LogTab
from src.gui.simple_mode_widget import SimpleModeWidget
from src.gui.markdown_renderer import markdown_to_html as _md_to_html
from src.gui.string_table_model import (
    StringTableModel, COL_CATEGORY, COL_KEY, COL_DEFAULT, COL_CURRENT,
    COL_STAR, COL_ORDER, COL_CUSTOM, COL_STATUS, COL_OWNED,
    status_color,
)
from src.gui.theme import (
    BRAND_FONT_FAMILY, get_button_color, get_button_text_color,
    get_tagline_color, get_title_color,
)
from src.gui.workers import (
    AnimatedProgressDialog,
    BlueprintLogScanWorker,
    DataForgeExtractWorker,
    EnhancementsGeneratorWorker,
    FileLoaderWorker,
    LanguageBaseDownloadWorker,
    OrderSpinBoxDelegate,
    P4kExtractWorker,
    SelectAllDelegate,
    StartupSyncWorker,
)
from src.merger.ini_merger import merge_sources_by_hierarchy
from src.models.string_model import StringEntry
from src.parser.ini_parser import load_source_files, load_sources_from_settings, parse_ini_file
from src.gui.update_dialog import UpdateDialog
from src.utils.app_updater import AppUpdateCheckWorker, AppUpdateDownloadWorker
from src.utils.applied_file_validator import validate_applied_file as _validate_applied_file_impl
from src.utils.build_mode import IS_PORTABLE
from src.utils.entry_filter import filter_entry_indices as _filter_entry_indices_impl
from src.utils.perf import timed
from src.utils.resource_path import get_resource_path
from src.utils.settings import AppSettings
from src.utils.i18n import tr
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
import html as _html_mod
import re as _re_mod

_EM3_RE = _re_mod.compile(r"&lt;EM3&gt;(.*?)&lt;/EM3&gt;", _re_mod.DOTALL)
_EM4_RE = _re_mod.compile(r"&lt;EM4&gt;(.*?)&lt;/EM4&gt;", _re_mod.DOTALL)
_MISSION_TOKEN_RE = _re_mod.compile(r"~mission\(([^|)]+)(?:\|[^)]*)?\)")

# Trailing "[Edited with Smart Citizen vX.Y.Z]" tag (with the literal-\n
# leading separators the loc-string format uses for line breaks). Stripped
# from prior values before re-stamping so successive applies don't
# accumulate tags and a version bump rolls the stamp forward cleanly.
_JOURNAL_STAMP_RE = _re_mod.compile(
    r"(?:\\n)*\[Edited with Smart Citizen v[^\]]+\]\s*$"
)

# Title-like journal keys we should NOT stamp — the stamp belongs at the
# end of journal body content, not in titles, short titles, sub-headings,
# or the "From:" sender line. ",P" is CIG's parallel-form suffix and
# should match alongside the bare key. Match is case-insensitive on the
# suffix so ``_Title``, ``_title``, and ``_TITLE`` all skip.
_JOURNAL_TITLE_KEY_RE = _re_mod.compile(
    r"_(?:title|shorttitle|subtitle|subheading|from)(?:,P)?$",
    _re_mod.IGNORECASE,
)

# Frontend version chip (main-menu watermark). CIG ships a key called
# ``Frontend_PU_Version`` whose value the main menu renders verbatim.
# We append " | Localizations Enhanced with Smart Citizen vX.Y.Z" so
# users (and their screenshots / support tickets) can see at a glance
# that the localization has been customized. Idempotency works the same
# way as the journal stamp: ``_FRONTEND_VERSION_STAMP_RE`` strips any
# prior watermark before re-appending the current one, so successive
# applies and version bumps don't accumulate suffixes. The regex is
# intentionally permissive — it matches the current "Enhanced with"
# phrasing as well as the two legacy phrasings ("Enhanced by",
# "Enhanced with <3 by"), with or without a leading ``v`` on the
# version, so installs that already have an older watermark on disk
# roll forward cleanly on the next apply.
_FRONTEND_VERSION_KEY = "Frontend_PU_Version"
_FRONTEND_VERSION_STAMP_RE = _re_mod.compile(
    r"\s*\|\s*(?:Localizations Enhanced (?:with|by)|Enhanced with <3 by)\s+Smart Citizen\s+v?[^\s|]+\s*$"
)


def _stamp_frontend_version(merged: dict) -> dict:
    """Append the Smart Citizen watermark to Frontend_PU_Version in place.

    Skips entirely if the key is not present in *merged* — we don't
    fabricate the key when stock doesn't have it. Mutates and returns
    *merged* so the call site reads symmetrically with the journal stamp.
    """
    if _FRONTEND_VERSION_KEY not in merged:
        return merged
    from src.utils.version import get_version
    base = _FRONTEND_VERSION_STAMP_RE.sub("", merged[_FRONTEND_VERSION_KEY]).rstrip()
    merged[_FRONTEND_VERSION_KEY] = f"{base} | Localizations Enhanced with Smart Citizen v{get_version()}"
    return merged


def _stamp_journal_entries(merged: dict, stock: dict | None = None) -> dict:
    """Append a Smart Citizen version stamp to Journal entries SC produced or modified.

    A Journal entry counts as "modified by Smart Citizen" if its merged
    value differs from the stock CIG value, or if it's a key SC added that
    doesn't exist in stock at all. That covers both user-edited journals
    AND auto-generated enhancements (Mining Compendium etc.) while leaving
    untouched stock CIG entries alone.

    *stock* is the stock-only key→value dict (typically the parsed base.ini).
    Passing None disables the stock comparison and stamps every Journal key
    in *merged* — kept as a fallback for callers that don't have stock.

    Idempotent: re-applying with no edits produces byte-identical output.
    The trailing stamp regex strips a prior version's tag before appending
    the current one, so version bumps roll the stamp forward cleanly.
    """
    from src.utils.version import get_version
    version = get_version()
    new_stamp = f"\\n\\n[Edited with Smart Citizen v{version}]"
    stock = stock or {}
    out: dict = {}
    for key, value in merged.items():
        if StringEntry.extract_category(key) != "Journal":
            out[key] = value
            continue
        # Title-like keys (Title / ShortTitle / SubTitle / SubHeading /
        # From) belong to the journal's header chrome, not its body —
        # stamping them would put the version tag in the entry title,
        # which the user explicitly does not want.
        if _JOURNAL_TITLE_KEY_RE.search(key):
            out[key] = value
            continue
        # Strip any prior stamp from the merged value before deciding
        # whether SC modified it — otherwise an already-stamped value from
        # a previous apply would compare unequal to stock and re-stamp,
        # which is benign but wasteful.
        unstamped = _JOURNAL_STAMP_RE.sub("", value).rstrip()
        if stock and stock.get(key, _SENTINEL_MISSING) == unstamped:
            # Stock-equivalent content; SC didn't produce or modify it.
            out[key] = unstamped
            continue
        out[key] = unstamped + new_stamp
    return out


# Sentinel used for "key not in stock" so we can distinguish that from
# "stock has empty string for this key" — the empty-string case is a
# legitimate stock value that should still match an empty merged value.
_SENTINEL_MISSING = object()


def _journal_stamp_for_entry(entry) -> str | None:
    """Return the rendered stamp text for *entry*'s preview, or None.

    Mirrors the apply-time stamp policy at the entry level: an entry
    qualifies for a stamp if it's a Journal entry whose key is body
    content (not a title/header field) and that's either user-edited
    (non-empty ``custom_value``) or enhancement-sourced. Stock CIG
    entries with no user touch, and any title-like key, return None.
    """
    if entry.category != "Journal":
        return None
    if _JOURNAL_TITLE_KEY_RE.search(entry.key):
        return None
    if not (entry.custom_value or entry.source_file == "enhancements"):
        return None
    from src.utils.version import get_version
    return f"[Edited with Smart Citizen v{get_version()}]"


def _render_preview_html(key: str, raw: str, stamp: str | None = None) -> str:
    """Render *raw* loc-string value as styled HTML for the preview pane.

    If *stamp* is provided, append it to the raw value with two literal
    line breaks first, so the preview shows the same trailing version
    stamp that will be written to the game's global.ini at apply-time.
    Purely cosmetic on this side — the stamp is never persisted into
    user.ini or the entry, just rendered here to give users a faithful
    in-app preview of what the in-game text will look like.
    """
    # Append the stamp on the raw side, before HTML rendering, so the
    # standard `\n` → `<br>` transform handles the spacing in lockstep.
    if stamp:
        raw = (raw or "") + "\\n\\n" + stamp
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
        self.setWindowTitle(tr("window.title", version=get_version()))
        # Position only; the size is set after the UI is built — restored from
        # saved geometry, or sized to the compact content hint on first run
        # (#180 follow-up: open as small as the layout allows). See
        # restore_window_state().
        self.move(100, 100)

        # Set window icon (taskbar + window title bar + favicon)
        icon_path = get_resource_path(os.path.join("assets", "logo.ico"))
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # Data
        self.entries: list[StringEntry] = []
        self.filtered_row_indices: list[int] = []
        self.default_values: dict = {}  # Store default values from cached base source

        # File loader worker
        self._loader_worker: Optional[FileLoaderWorker] = None

        # Startup sync worker
        self._startup_sync_worker: Optional[StartupSyncWorker] = None

        # Per-language base.ini download worker (#30)
        self._lang_dl_worker: Optional[LanguageBaseDownloadWorker] = None

        # P4K extraction worker and progress dialog
        self._p4k_worker: Optional[P4kExtractWorker] = None
        self._p4k_progress: Optional[QProgressDialog] = None

        # Enhancements generation worker
        self._enhancements_worker: Optional[EnhancementsGeneratorWorker] = None
        self._enhancements_progress_dialog: Optional[AnimatedProgressDialog] = None

        # Apply-to-game dirty tracking (same grey-until-changed pattern as
        # Generate Enhancements / Save Tag Changes / Apply Owned Tags).
        # Starts True (clickable) — we can't cheaply verify at launch whether
        # the loaded state already matches what's live in the game's
        # global.ini, and wrongly greying out the app's one write-to-disk
        # action would be a much worse failure than an occasional redundant
        # enabled state. See _mark_apply_dirty / _clear_apply_dirty.
        self._apply_dirty = True

        # Tracks whether *this session* has produced a genuine unapplied
        # change, as opposed to _apply_dirty's conservative "we can't verify
        # at boot" default above. Used only to decide whether closeEvent
        # should warn about unapplied changes — _initial_load_done gates it
        # so the very first (startup) load doesn't itself count as a
        # user-made change; see _mark_apply_dirty and _on_loading_finished.
        self._initial_load_done = False
        self._session_has_unapplied_edit = False

        # DataForge extraction worker
        self._forge_worker: Optional[DataForgeExtractWorker] = None

        # #180: when True, the Simple-mode one-button flow is running and the
        # enhancements-generation-finished slot should continue into
        # apply_to_game. Cleared on completion or any failure.
        self._simple_run_active = False

        # #157: item names (normalized) that appear in any POTENTIAL BLUEPRINTS
        # list — the rows eligible for the Owned star. Recomputed on each load.
        self._bp_item_names: set[str] = set()
        # #157 follow-up: per-blueprint-item metadata (mission names + ship
        # component type/class/size/grade) for the Blueprints shuttle filters.
        # Built once per load (pure function of the loaded strings), so
        # owned-toggles only re-partition rather than rescan ~87k entries.
        self._blueprint_meta: dict = {}

        # Track whether we've prompted for enhancements on startup (prevents duplicate dialogs)
        self._enhancements_prompted_on_startup = False
        # Flag to defer enhancements checking until after file loading completes (avoid I/O contention)
        self._check_enhancements_after_loading = False

        # Status bar state (composed message) - tracks sync status per source
        self._source_status: dict[str, str] = {}  # source_name -> status_string

        # Progress dialogs
        self._startup_progress: Optional[AnimatedProgressDialog] = None
        self._loading_progress: Optional[QProgressDialog] = None

        # App self-update check
        self._update_check_worker: Optional[AppUpdateCheckWorker] = None
        self._latest_release_url: Optional[str] = None
        # #211: True while the rest of startup (source sync, extraction
        # prompts, OneDrive warning) waits on the update check to resolve.
        self._startup_gate_pending = False
        self._update_download_worker: Optional[AppUpdateDownloadWorker] = None
        self._update_download_progress: Optional[AnimatedProgressDialog] = None

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

    def setup_ui(self):
        """Build user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)

        # Title bar — branded font (Hyperspace Race Expanded Bold)
        self.title_label = QLabel(tr("branding.title"))
        title_font = QFont(BRAND_FONT_FAMILY)
        title_font.setPointSize(22)
        self.title_label.setFont(title_font)
        main_layout.addWidget(self.title_label)

        self.tagline_label = QLabel(tr("branding.tagline"))
        main_layout.addWidget(self.tagline_label)
        self._apply_branding_styles()

        toolbar_layout = self.create_toolbar()

        # Wrapped in a container so Simple mode (#180) can hide the whole
        # advanced toolbar as a unit (a layout can't be hidden).
        self.toolbar_container = QWidget()
        self.toolbar_container.setLayout(toolbar_layout)
        main_layout.addWidget(self.toolbar_container)

        self.tabs = QTabWidget()
        self._strings_tab_index = self.tabs.addTab(self.create_strings_tab(), tr("tabs.string_editor"))

        # Config tab
        self.config_tab = ConfigTab()
        self.config_tab.merge_requested.connect(self.perform_merge_and_reload)
        self.config_tab.p4k_extract_requested.connect(self._run_p4k_extraction)
        self.config_tab.import_ini_requested.connect(self._handle_import_ini)
        self.config_tab.reset_user_ini_requested.connect(self._handle_reset_user_ini)
        self.config_tab.restore_user_ini_requested.connect(self._handle_restore_user_ini)
        self.config_tab.channel_changed.connect(self._on_channel_changed)
        self.config_tab.language_changed.connect(self._on_language_changed)
        self.config_tab.check_updates_requested.connect(self._on_check_updates_clicked)
        self.config_tab.data_dir_changed.connect(self._on_data_dir_changed)
        self.config_tab.cache_dir_changed.connect(self._on_cache_dir_changed)
        self._config_tab_index = self.tabs.addTab(self.config_tab, tr("tabs.config"))

        # Enhancements tab
        self.enhancements_tab = EnhancementsTab()
        self.enhancements_tab.merge_requested.connect(self.perform_merge_and_reload)
        self.enhancements_tab.enhancements_pipeline_requested.connect(self._run_enhancements_pipeline)
        self.enhancements_tab.favorite_prefix_changed.connect(self._on_favorite_prefix_changed)
        self._enhancements_tab_index = self.tabs.addTab(self.enhancements_tab, tr("tabs.enhancements"))

        # Blueprint Tracker tab (#222: split out of the Enhancements tab)
        self.blueprint_tracker_tab = BlueprintTrackerTab()
        self.blueprint_tracker_tab.owned_items_changed.connect(self._recompute_owned)
        self.blueprint_tracker_tab.scan_logs_requested.connect(self._run_blueprint_log_scan)
        self.blueprint_tracker_tab.apply_owned_requested.connect(self._on_apply_owned_tags_clicked)
        self._blueprint_tracker_tab_index = self.tabs.addTab(
            self.blueprint_tracker_tab, tr("tabs.blueprint_tracker")
        )
        self._bp_log_scan_worker = None
        self._bp_log_scan_progress = None

        self.log_tab = LogTab()
        self._log_tab_index = self.tabs.addTab(self.log_tab, tr("tabs.log"))

        self._about_tab_index = self.tabs.addTab(self.create_about_tab(), tr("tabs.about"))
        self._faq_tab_index = self.tabs.addTab(self.create_faq_tab(), tr("tabs.faq"))
        self._legal_tab_index = self.tabs.addTab(self.create_legal_tab(), tr("tabs.legal"))

        # Error-dialog handler: surfaces ERROR/CRITICAL log records as a
        # modal QMessageBox so users see failures without having to open
        # the Log tab. State below is consumed by _show_error_dialog —
        # it implements a per-cooldown-window suppression so a burst of
        # errors (e.g. 50 parse failures during DataForge extraction)
        # doesn't open 50 dialogs.
        self._error_dialog_showing = False
        self._last_error_dialog_time = 0.0
        self._suppressed_error_count = 0
        self._error_dialog_emitter = _ErrorDialogEmitter()
        self._error_dialog_handler = ErrorDialogHandler(self._error_dialog_emitter)
        self._error_dialog_emitter.error_emitted.connect(self._show_error_dialog)
        logging.getLogger().addHandler(self._error_dialog_handler)

        # Revert unapplied enhancement checkbox changes when leaving the tab
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._previous_tab_index = self.tabs.currentIndex()

        # #180: Simple/Advanced view switch. The tabbed UI (Advanced) and the
        # one-button Simple page share a QStackedWidget so switching is a page
        # swap rather than a teardown, and the QTabWidget keeps its stretch=1
        # placement inside the stack.
        self.simple_page = SimpleModeWidget()
        self.simple_page.generate_and_apply_requested.connect(self._run_simple_apply)
        self.simple_page.switch_to_advanced_requested.connect(
            lambda: self._apply_ui_mode(AppSettings.UI_MODE_ADVANCED)
        )
        self.view_stack = QStackedWidget()
        self.view_stack.addWidget(self.tabs)         # Advanced
        self.view_stack.addWidget(self.simple_page)  # Simple
        main_layout.addWidget(self.view_stack, 1)

        # Footer
        footer_layout = self.create_footer()
        main_layout.addLayout(footer_layout)

        # Help side-panel. Created eagerly so restoreState can persist its state.
        self._ensure_help_dock()
        self.help_dock.hide()

        # Editor side-panel — same eager-create rationale as the help dock:
        # restoreState only remembers docks that exist with a stable
        # objectName at restore time. Hidden by default so first-launch
        # users aren't surprised.
        self._ensure_editor_dock()
        self.editor_dock.hide()

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

        # #180: apply the saved Simple/Advanced view last, once every widget
        # the toggle touches exists.
        self._apply_ui_mode(AppSettings.get_ui_mode())

    def _apply_ui_mode(self, mode: str) -> None:
        """Switch between the Simple and Advanced views and persist the choice (#180).

        Simple shows the one-button page and hides the advanced toolbar +
        preview; Advanced restores the full tabbed UI. Safe to call before or
        after the window is shown.
        """
        if mode not in (AppSettings.UI_MODE_SIMPLE, AppSettings.UI_MODE_ADVANCED):
            mode = AppSettings.UI_MODE_SIMPLE
        from PyQt6.QtWidgets import QSizePolicy

        simple = mode == AppSettings.UI_MODE_SIMPLE
        self.view_stack.setCurrentWidget(self.simple_page if simple else self.tabs)
        self.toolbar_container.setVisible(not simple)
        # Only the visible page should drive the window's size hint. A
        # QStackedWidget otherwise sizes to its largest page, so the compact
        # Simple page would be inflated by the big Advanced tabs. Setting the
        # hidden page's policy to Ignored zeroes its contribution to the hint,
        # letting Simple shrink to its own minimum.
        ignored = QSizePolicy.Policy.Ignored
        live = QSizePolicy.Policy.Expanding
        self.simple_page.setSizePolicy(live if simple else ignored,
                                       live if simple else ignored)
        self.tabs.setSizePolicy(ignored if simple else live,
                                ignored if simple else live)
        AppSettings.set_ui_mode(mode)
        # Resize to suit the new view on a live switch. At startup the window
        # isn't shown yet (isVisible() is False) — showEvent applies the
        # initial size once instead. isVisible() also lets the unit-test stub
        # exercise the swap without the sizing helper.
        if self.isVisible():
            self._size_window_for_mode(mode)

    def _size_window_for_mode(self, mode: str) -> None:
        """Size the window to suit the active view (#180 follow-up).

        Advanced always opens maximized (the full table wants the room);
        Simple shrinks to the smallest size that still fits its one-button
        page — the hidden Advanced page is set to Ignored in _apply_ui_mode so
        it no longer inflates the stacked-widget hint. Called once at first
        show and on every live mode switch, so the size tracks the mode rather
        than whatever the window was last left at.
        """
        if mode == AppSettings.UI_MODE_ADVANCED:
            self.showMaximized()
        elif self.isMaximized() or self.isFullScreen():
            # showNormal() restores the prior (maximized) geometry on the next
            # event-loop tick, so a synchronous resize here would be clobbered.
            # Shrink after that restore lands; guarded so a quick switch back
            # to Advanced isn't shrunk out from under us.
            self.showNormal()
            QTimer.singleShot(0, lambda: self._shrink_to_fit_if_simple())
        else:
            # First show / already-normal window: no pending restore to race.
            self.resize(self.minimumSizeHint())

    def _shrink_to_fit_if_simple(self) -> None:
        """Resize to the minimum that fits the Simple page, if still in Simple
        mode. Deferred from _size_window_for_mode after an un-maximize so the
        async geometry restore doesn't clobber the shrink."""
        if AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE:
            self.resize(self.minimumSizeHint())

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

        # Green when up to date, red when a change needs applying — color
        # itself is set by _set_apply_btn_dirty below.
        self.apply_btn = QPushButton(tr("toolbar.apply_btn"))
        self.apply_btn.clicked.connect(self.apply_to_game)
        button_layout.addWidget(self.apply_btn)
        self._set_apply_btn_dirty(self._apply_dirty)

        # Editor: toggles the side-docked String Editor for editing long
        # values comfortably. Shares the 'open' info-action role so it pairs
        # visually with Help/Tutorial as a panel-toggle.
        self.editor_btn = QPushButton(tr("toolbar.editor_btn"))
        self.editor_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.editor_btn.setCheckable(True)
        self.editor_btn.setToolTip(tr("toolbar.editor_tooltip"))
        self.editor_btn.clicked.connect(self.show_editor_dock)
        button_layout.addWidget(self.editor_btn)

        self.help_btn = QPushButton(tr("toolbar.help_btn"))
        self.help_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.help_btn.setCheckable(True)
        self.help_btn.setToolTip(tr("toolbar.help_tooltip"))
        self.help_btn.clicked.connect(self.show_help)
        button_layout.addWidget(self.help_btn)

        self.tutorial_btn = QPushButton(tr("toolbar.tutorial_btn"))
        self.tutorial_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.tutorial_btn.setToolTip(tr("toolbar.tutorial_tooltip"))
        self.tutorial_btn.clicked.connect(self._start_tutorial)
        button_layout.addWidget(self.tutorial_btn)

        # More: overflow menu for the less-frequent actions (rollback, cleanup,
        # import/export, open folder). Keeps the row focused on the core
        # edit-and-commit workflow. Issue #128. The QActions are kept as
        # attributes so retranslate_ui() can relabel them on a language swap.
        more_menu = QMenu(self)
        self._action_restore_backup = more_menu.addAction(
            tr("toolbar.restore_backup_btn"), self.restore_backup
        )
        self._action_restore_backup.setToolTip(tr("toolbar.restore_backup_tooltip"))
        more_menu.addSeparator()
        self._action_clear_loc = more_menu.addAction(tr("toolbar.menu_clear_localization"), self.clear_localization)
        self._action_clear_cache = more_menu.addAction(tr("toolbar.menu_clear_cache"), self.clear_cache)
        more_menu.addSeparator()
        self._action_import_ini = more_menu.addAction(tr("toolbar.menu_import_ini"), self._handle_import_ini)
        self._action_export_ini = more_menu.addAction(tr("toolbar.menu_export_ini"), self.export_locpack)
        more_menu.addSeparator()
        self._action_open_loc_dir = more_menu.addAction(
            tr("toolbar.open_loc_dir_btn"), self.open_localization_dir
        )
        more_menu.addSeparator()
        self._action_test_plan = more_menu.addAction(
            tr("toolbar.menu_test_plan"), self.show_test_plan
        )
        self._action_test_plan.setToolTip(tr("toolbar.test_plan_tooltip"))
        more_menu.addSeparator()
        # #180: jump to the simplified one-button view. Lives in the toolbar
        # (Advanced-only); the way back is the Simple page's own button.
        self._action_switch_to_simple = more_menu.addAction(
            tr("toolbar.menu_switch_to_simple"),
            lambda: self._apply_ui_mode(AppSettings.UI_MODE_SIMPLE),
        )
        self._action_switch_to_simple.setToolTip(tr("toolbar.switch_to_simple_tooltip"))

        self.more_btn = QPushButton(tr("toolbar.more_btn"))
        self.more_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {get_button_text_color()}; font-weight: bold; padding: 6px;")
        self.more_btn.setToolTip(tr("toolbar.more_tooltip"))
        self.more_btn.setMenu(more_menu)
        button_layout.addWidget(self.more_btn)

        button_layout.addStretch()

        layout.addLayout(button_layout)

        return layout

    def create_string_filter_row(self) -> QHBoxLayout:
        """Create the String Editor's filter row (category/status/search
        toggles). Lives on the strings tab itself (not the shared toolbar)
        so it's only visible while that tab is active."""
        filter_layout = QHBoxLayout()

        self._category_label = QLabel(tr("filters.category_label"))
        filter_layout.addWidget(self._category_label)
        self.category_combo = QComboBox()
        self.category_combo.setMinimumWidth(200)
        self.category_combo.setToolTip(tr("filters.category_tooltip"))
        self.category_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.category_combo)

        self._status_label = QLabel(tr("filters.status_label"))
        filter_layout.addWidget(self._status_label)
        self.status_combo = QComboBox()
        # userData stores the English internal value used by the filter engine;
        # display text is translated so the label localizes without breaking comparisons.
        for _internal, _key in [
            ("All",        "filters.status_all"),
            ("Modified",   "filters.status_modified"),
            ("Enhanced",   "filters.status_enhanced"),
            ("Unmodified", "filters.status_unmodified"),
            ("New",        "filters.status_new"),
        ]:
            self.status_combo.addItem(tr(_key), userData=_internal)
        self.status_combo.setMaximumWidth(120)
        self.status_combo.setToolTip(tr("filters.status_tooltip"))
        self.status_combo.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_combo)

        self.hide_unmodified_check = QCheckBox(tr("filters.hide_unmodified"))
        self.hide_unmodified_check.setToolTip(tr("filters.hide_unmodified_tooltip"))
        self.hide_unmodified_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.hide_unmodified_check)

        self.favorites_only_check = QCheckBox(tr("filters.favorites_only"))
        self.favorites_only_check.setToolTip(tr("filters.favorites_only_tooltip"))
        self.favorites_only_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.favorites_only_check)

        # #156: isolate blueprint missions. BP Titles keeps title rows tagged
        # [BP]/[BP?]; BP Descriptions keeps bodies with a POTENTIAL BLUEPRINTS
        # section. Checking both shows either.
        self.bp_titles_check = QCheckBox(tr("filters.bp_titles_only"))
        self.bp_titles_check.setToolTip(tr("filters.bp_titles_only_tooltip"))
        self.bp_titles_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.bp_titles_check)

        self.bp_descs_check = QCheckBox(tr("filters.bp_descs_only"))
        self.bp_descs_check.setToolTip(tr("filters.bp_descs_only_tooltip"))
        self.bp_descs_check.stateChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.bp_descs_check)

        self.grouped_sort_btn = QPushButton(tr("filters.group_sort_btn"))
        self.grouped_sort_btn.setToolTip(tr("filters.group_sort_tooltip"))
        self.grouped_sort_btn.setMaximumWidth(100)
        self.grouped_sort_btn.clicked.connect(self._on_grouped_sort)
        filter_layout.addWidget(self.grouped_sort_btn)

        self.clear_filters_btn = QPushButton(tr("filters.clear_filters_btn"))
        self.clear_filters_btn.setMaximumWidth(100)
        self.clear_filters_btn.setToolTip(tr("filters.clear_filters_tooltip"))
        self.clear_filters_btn.clicked.connect(self.clear_filters)
        filter_layout.addWidget(self.clear_filters_btn)

        self.copy_filtered_btn = QPushButton(tr("filters.copy_filtered_btn"))
        self.copy_filtered_btn.setMaximumWidth(100)
        self.copy_filtered_btn.setToolTip(tr("filters.copy_filtered_tooltip"))
        self.copy_filtered_btn.clicked.connect(self.copy_filtered_to_clipboard)
        filter_layout.addWidget(self.copy_filtered_btn)

        filter_layout.addStretch()
        return filter_layout

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
        osiris_glow_path  = get_resource_path(os.path.join("assets", "osiris-eye-glow.png"))

        if os.path.exists(osiris_image_path) and os.path.exists(osiris_glow_path):
            self.osiris_button = QWidget()
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
            self.osiris_button.setToolTip(tr("toolbar.osiris_github_tooltip"))
            self.osiris_button.mousePressEvent = self.open_osiris_github
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
            self.osiris_button = QLabel("Osiris DevWorks")
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
            self.osiris_button.setToolTip(tr("toolbar.osiris_github_tooltip"))
            self.osiris_button.mousePressEvent = self.open_osiris_github
            footer_layout.addWidget(self.osiris_button)

        # Feedback button — sits immediately to the right of the Osiris logo.
        # Image link to the dedicated Smart Citizen channel in the Osiris
        # DevWorks Discord; falls back to a styled text label if the asset
        # is missing.
        footer_layout.addSpacing(10)
        self.feedback_label = QLabel()
        discord_image_path = get_resource_path(os.path.join("assets", "discord.png"))
        if os.path.exists(discord_image_path):
            discord_pixmap = QPixmap(discord_image_path)
            if discord_pixmap.height() > 40:
                discord_pixmap = discord_pixmap.scaledToHeight(40, Qt.TransformationMode.SmoothTransformation)
            self.feedback_label.setPixmap(discord_pixmap)
        else:
            self.feedback_label.setText(tr("toolbar.feedback_fallback_text"))
            self.feedback_label.setStyleSheet("font-size: 12px;")
        self.feedback_label.setToolTip(tr("toolbar.feedback_tooltip"))
        self.feedback_label.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.feedback_label.mousePressEvent = self.open_feedback_link
        footer_layout.addWidget(self.feedback_label)

        # Stretch to push the donation cluster to the right.
        footer_layout.addStretch()

        # PayPal button (right side)
        self.paypal_button = QLabel()
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
            self.paypal_button.setText(tr("toolbar.paypal_fallback_text"))
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
        self.paypal_button.mousePressEvent = self.open_paypal_donation
        footer_layout.addWidget(self.paypal_button)

        # Spacer between PayPal and Venmo
        footer_layout.addSpacing(10)

        # Venmo button (right side)
        self.venmo_button = QLabel()
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
            self.venmo_button.setText(tr("toolbar.venmo_fallback_text"))
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
        self.venmo_button.mousePressEvent = self.open_venmo_donation
        footer_layout.addWidget(self.venmo_button)

        return footer_layout

    def open_osiris_github(self, event):
        """Open the Osiris DevWorks GitHub organization in browser."""
        QDesktopServices.openUrl(QUrl("https://github.com/Osiris-DevWorks"))

    def open_feedback_link(self, event):
        """Open the dedicated Smart Citizen feedback channel in browser."""
        feedback_url = "https://discord.com/channels/1438175448420057323/1472394204347895890"
        QDesktopServices.openUrl(QUrl(feedback_url))

    def open_paypal_donation(self, event):
        """Open PayPal donation link in browser."""
        paypal_url = "https://paypal.me/RighteousKill"
        QDesktopServices.openUrl(QUrl(paypal_url))

    def open_venmo_donation(self, event):
        """Open Venmo donation link in browser."""
        venmo_url = "https://venmo.com/u/Amr-Abouelleil"
        QDesktopServices.openUrl(QUrl(venmo_url))

    # ── App self-update ─────────────────────────────────────────────────────

    # The startup check runs on every launch (#211) — one unauthenticated API
    # call per launch, far under GitHub's 60-req/hr cap. The former 6-hour
    # throttle was removed when the check became the gate for the rest of
    # startup.

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
        self.config_tab.set_update_status(tr("status_bar.update_checking"))
        worker.start()

    @pyqtSlot(str, str, str, str, int)
    def _on_update_available(self, latest: str, url: str, body: str,
                             asset_url: str, asset_size: int) -> None:
        current = get_version()
        self._latest_release_url = url
        self._update_check_state = ("available", latest)
        self._app_version_indicator.setStyleSheet(
            "font-size: 11px; padding: 0 8px; color: #c9a961; font-weight: bold;"
        )
        self._app_version_indicator.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._app_version_indicator.setToolTip(tr("status_bar.open_release_page_tooltip", version=latest))
        self._refresh_update_indicator_texts()

        # Auto-update needs an installer asset on the release and a registry
        # build — the portable variant has no installer to run, so it keeps
        # the link-only prompt (#211).
        can_auto_update = bool(asset_url) and not IS_PORTABLE

        dlg = UpdateDialog(
            self,
            latest=latest,
            current=current,
            notes_html=self.markdown_to_html(body.strip()),
            can_auto_update=can_auto_update,
        )
        dlg.exec()

        if dlg.choice == UpdateDialog.CHOICE_UPDATE:
            # Gate stays closed: the app exits to install. On download or
            # launch failure the handlers reopen it so startup continues.
            self._start_update_download(latest, url, asset_url, asset_size)
            return
        if dlg.choice == UpdateDialog.CHOICE_OPEN_PAGE:
            QDesktopServices.openUrl(QUrl(url))
        # Whether declined or sent to the release page, the app keeps
        # running — open the startup gate.
        self._continue_startup_after_update_gate()

    def _start_update_download(self, latest: str, url: str, asset_url: str,
                               asset_size: int) -> None:
        """Download the release installer with progress, then install (#211)."""
        label = tr("dialogs.update_download_label", latest=latest)
        self._update_download_progress = AnimatedProgressDialog(
            label, parent=self, title=tr("dialogs.update_download_title")
        )
        self._latest_release_url = url

        worker = AppUpdateDownloadWorker(asset_url, asset_size, self)
        self._update_download_worker = worker
        worker.progress_pct.connect(
            lambda done, total, msg: (
                self._update_download_progress.set_progress(
                    done, total, f"{label}\n{msg}"
                )
                if self._update_download_progress is not None
                else None
            )
        )
        worker.download_finished.connect(self._on_update_download_finished)
        worker.download_error.connect(self._on_update_download_error)
        worker.finished.connect(self._on_update_download_worker_done)
        worker.start()

    @pyqtSlot(str)
    def _on_update_download_finished(self, installer_path: str) -> None:
        self._close_update_download_progress()
        self._launch_installer_and_quit(installer_path)

    @pyqtSlot(str)
    def _on_update_download_error(self, message: str) -> None:
        self._close_update_download_progress()
        logger.error(f"Update download failed: {message}")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("dialogs.update_download_failed_title"))
        box.setText(tr("dialogs.update_download_failed_body", message=message))
        page_btn = box.addButton(
            tr("dialogs.update_open_release"), QMessageBox.ButtonRole.AcceptRole
        )
        box.addButton(tr("dialogs.update_later"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is page_btn and self._latest_release_url:
            QDesktopServices.openUrl(QUrl(self._latest_release_url))
        # The update didn't happen — let startup proceed normally.
        self._continue_startup_after_update_gate()

    @pyqtSlot()
    def _on_update_download_worker_done(self) -> None:
        self._reap_worker(self._update_download_worker)
        self._update_download_worker = None

    def _close_update_download_progress(self) -> None:
        if self._update_download_progress is not None:
            self._update_download_progress.close()
            self._update_download_progress = None

    def _launch_installer_and_quit(self, installer_path: str) -> None:
        """Spawn the silent installer and exit so file locks release (#211).

        ShellExecuteW honors the installer's admin manifest, so this call is
        what raises the UAC prompt — and it returns only after the user
        answers it. A declined prompt (or any launch failure) returns <= 32,
        in which case the app keeps running and startup proceeds normally.

        Installer switches: /SILENT /NORESTART run the upgrade with just a
        progress bar; /SUPPRESSMSGBOXES auto-answers the "previous version
        found" box with its default (Yes = upgrade in place); /AUTOUPDATE=1
        tells installer.iss to relaunch Smart Citizen when the install
        finishes (the normal postinstall Run entry is skipifsilent).
        """
        import ctypes

        args = "/SILENT /NORESTART /SUPPRESSMSGBOXES /AUTOUPDATE=1"
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "open", installer_path, args, None, 1
        )
        if ret <= 32:
            logger.error(
                f"Update installer launch failed or was declined "
                f"(ShellExecuteW returned {ret}) for {installer_path}"
            )
            QMessageBox.warning(
                self,
                tr("dialogs.update_launch_failed_title"),
                tr("dialogs.update_launch_failed_body", path=installer_path),
            )
            self._continue_startup_after_update_gate()
            return

        logger.info(f"Update installer launched ({installer_path}); exiting to install")
        self.close()

    @pyqtSlot(str)
    def _on_update_up_to_date(self, current: str) -> None:
        self._latest_release_url = None
        self._update_check_state = ("up_to_date", current)
        self._app_version_indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        self._app_version_indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._app_version_indicator.setToolTip("")
        self._refresh_update_indicator_texts()
        if getattr(self, "_force_update_dialog", False):
            QMessageBox.information(
                self,
                tr("dialogs.up_to_date_title"),
                tr("dialogs.up_to_date_body", current=current),
            )
        self._continue_startup_after_update_gate()

    @pyqtSlot(str)
    def _on_update_check_error(self, message: str) -> None:
        self._latest_release_url = None
        self._update_check_state = ("failed", None)
        self._app_version_indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        self._app_version_indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._app_version_indicator.setToolTip(message)
        self._refresh_update_indicator_texts()
        logger.warning(f"App update check error: {message}")
        if getattr(self, "_force_update_dialog", False):
            QMessageBox.warning(
                self,
                tr("dialogs.update_check_failed_title"),
                tr("dialogs.update_check_failed_body", message=message),
            )
        self._continue_startup_after_update_gate()

    def _reap_worker(self, worker) -> None:
        """Standard QThread cleanup (quit + wait + deleteLater) for a
        finished worker. See the threading model in root CLAUDE.md."""
        if worker is not None:
            worker.quit()
            worker.wait()
            worker.deleteLater()

    @pyqtSlot()
    def _on_update_check_finished(self) -> None:
        self._reap_worker(self._update_check_worker)
        self._update_check_worker = None
        self._force_update_dialog = False
        self.config_tab.set_check_updates_enabled(True)

    def _on_version_label_clicked(self, _event) -> None:
        """Footer version label click — opens the release page when available."""
        if self._latest_release_url:
            QDesktopServices.openUrl(QUrl(self._latest_release_url))

    def create_strings_tab(self) -> QWidget:
        """Create strings table tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Rendered-preview pane: shows the currently-selected row's effective
        # value (custom override if present, else the merged baseline) with
        # the game's EM3/EM4/~mission(...) tokens translated into styled HTML
        # so mission and journal blocks read like in-game text instead of
        # wall-of-tag. Lives here (not the shared toolbar) so it's only
        # visible while the String Editor tab is active.
        self.preview_pane = QTextBrowser()
        self.preview_pane.setReadOnly(True)
        self.preview_pane.setOpenExternalLinks(False)
        self.preview_pane.setPlaceholderText(tr("strings_tab.preview_placeholder"))
        self.preview_pane.setMinimumWidth(420)
        # Capped so the row doesn't inflate when there's slack vertical space
        # to redistribute (the post-1.3.0 Config / Enhancements gap bug —
        # QTextBrowser's default Expanding vertical sizePolicy let the pane
        # grow to its old 200px ceiling). The Preferred sizePolicy prevents
        # the greedy expansion; the cap is a belt-and-braces upper bound and
        # answers "how many lines of preview do I want at most." 60 fits
        # ~2–3 lines of rendered HTML; anything longer (mission journals,
        # multi-line descriptions) overflows into the built-in scrollbar
        # rather than growing the pane.
        from PyQt6.QtWidgets import QSizePolicy
        self.preview_pane.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.preview_pane.setMaximumHeight(60)

        # Filter row: category/status/search toggles. Lives here (not the
        # shared toolbar) so it's only visible while this tab is active.
        filter_and_preview_row = QHBoxLayout()
        filter_and_preview_row.setSpacing(12)
        filter_and_preview_row.addLayout(self.create_string_filter_row(), 2)
        filter_and_preview_row.addWidget(self.preview_pane, 1)
        layout.addLayout(filter_and_preview_row)

        # Model
        self._model = StringTableModel(self)
        # Single chokepoint for instant cross-pane sync: every code path that
        # mutates an entry (inline edit, favorite toggle, editor-dock edit,
        # reset-to-original, …) ends up emitting dataChanged on the model.
        # Subscribing here means the preview pane and the editor dock both
        # track those edits live without each mutator having to know which
        # other surfaces to nudge.
        self._model.dataChanged.connect(self._on_model_data_changed)

        # Table view
        self.table = QTableView()
        self.table.setModel(self._model)

        # Per-column filter header
        column_names = [
            tr("strings_tab.col_category"),
            tr("strings_tab.col_key"),
            tr("strings_tab.col_default_value"),
            tr("strings_tab.col_current_value"),
            tr("strings_tab.col_star"),
            tr("strings_tab.col_order"),
            tr("strings_tab.col_custom_value"),
            tr("strings_tab.col_status"),
        ]
        # Skip text-filter boxes on the non-text columns: category, ★,
        # order (a spin box), and status.
        self.filter_header = FilterHeaderView(
            column_names, self.table,
            skip_columns={COL_CATEGORY, COL_STAR, COL_ORDER, COL_STATUS},
        )
        self.table.setHorizontalHeader(self.filter_header)
        self.filter_header.filter_changed.connect(self.apply_filters)

        # Table settings
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)

        # Hide row numbers
        self.table.verticalHeader().setVisible(False)

        # Set column widths
        header = self.filter_header
        header.setSectionResizeMode(COL_CATEGORY, QHeaderView.ResizeMode.ResizeToContents)  # Category
        header.setSectionResizeMode(COL_KEY, QHeaderView.ResizeMode.Stretch)                # Key
        header.setSectionResizeMode(COL_DEFAULT, QHeaderView.ResizeMode.Stretch)            # Default Value
        header.setSectionResizeMode(COL_CURRENT, QHeaderView.ResizeMode.Stretch)            # Current Value
        header.setSectionResizeMode(COL_STAR, QHeaderView.ResizeMode.ResizeToContents)      # ★
        header.setSectionResizeMode(COL_ORDER, QHeaderView.ResizeMode.ResizeToContents)     # Order #
        header.setSectionResizeMode(COL_CUSTOM, QHeaderView.ResizeMode.Stretch)             # Custom Value
        header.setSectionResizeMode(COL_STATUS, QHeaderView.ResizeMode.ResizeToContents)    # Status
        header.setSectionResizeMode(COL_OWNED, QHeaderView.ResizeMode.ResizeToContents)     # Owned (#157)

        # Set custom delegates: Custom Value text editor + Sort Order spin box.
        # Parent each to the table so Qt's object tree owns them: the view does
        # not take ownership, and PyQt's per-method keep-reference holds only the
        # last delegate, so a second unparented setItemDelegateForColumn would
        # let the first (Custom Value) delegate be garbage-collected.
        self._custom_value_delegate = SelectAllDelegate(self.table)
        self.table.setItemDelegateForColumn(COL_CUSTOM, self._custom_value_delegate)
        self.table.setItemDelegateForColumn(COL_ORDER, OrderSpinBoxDelegate(self.table))
        # Star column click handling
        self.table.clicked.connect(self._on_cell_clicked)
        # Double-click: copy Current Value → Custom Value and open for edit
        self.table.doubleClicked.connect(self._on_cell_double_clicked)

        layout.addWidget(self.table)

        # Hook selection after the model is attached so selectionModel() exists.
        # Drives the top-right preview pane created in setup_ui().
        self.table.selectionModel().currentRowChanged.connect(
            self._on_preview_row_changed
        )

        # Status label
        self.table_status_label = QLabel(tr("strings_tab.no_data"))
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
            about_path = AppSettings.get_localized_doc_path("ABOUT.md")
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
                f"<h1>{tr('tabs.about')}</h1><p>{tr('tabs.about_load_failed')}</p>"
                f"<p style='color: gray;'>{str(e)}</p>"
            )

    # Cooldown window (seconds) between consecutive error dialogs. Within
    # this window, additional errors are silently counted and surfaced as
    # "(+N errors suppressed — see Log tab)" in the body of the next
    # dialog to fire. 5 s is a balance between "user notices each error"
    # and "burst of 50 parse failures during extraction doesn't open 50
    # dialogs".
    _ERROR_DIALOG_COOLDOWN_SEC = 5.0

    @pyqtSlot(str, str)
    def _show_error_dialog(self, message: str, traceback_text: str) -> None:
        """Show a modal error dialog for an ``ERROR``-or-above log record.

        Slot for ``ErrorDialogHandler``'s ``error_emitted`` signal. Always
        invoked on the main thread (signals from worker threads queue
        across the thread boundary, which is the whole point of the
        emitter pattern).

        Spam protection: a dialog is shown at most once per
        ``_ERROR_DIALOG_COOLDOWN_SEC`` window. Errors arriving while a
        dialog is open, or during the cooldown window after one closes,
        increment a counter; the next eligible dialog prepends a
        "(+N suppressed)" line so the suppressed errors aren't silently
        lost — they're still in the Log tab regardless.
        """
        import time

        # Guard 1: a dialog is currently on-screen. Count and bail.
        if self._error_dialog_showing:
            self._suppressed_error_count += 1
            return

        # Guard 2: still inside the cooldown window after the previous
        # dialog closed. Count and bail.
        elapsed = time.monotonic() - self._last_error_dialog_time
        if elapsed < self._ERROR_DIALOG_COOLDOWN_SEC:
            self._suppressed_error_count += 1
            return

        self._error_dialog_showing = True
        try:
            if self._suppressed_error_count > 0:
                suffix = tr(
                    "dialogs.suppressed_errors_suffix",
                    count=self._suppressed_error_count,
                    plural="s" if self._suppressed_error_count != 1 else "",
                )
                body = message + suffix
                self._suppressed_error_count = 0
            else:
                body = message

            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(tr("dialogs.crash_error_title"))
            box.setText(body)
            if traceback_text:
                box.setDetailedText(traceback_text)
            show_log_btn = box.addButton(tr("dialogs.show_log_btn"), QMessageBox.ButtonRole.ActionRole)
            box.addButton(tr("dialogs.dismiss_btn"), QMessageBox.ButtonRole.AcceptRole)
            box.exec()
            if box.clickedButton() is show_log_btn:
                log_idx = self.tabs.indexOf(self.log_tab)
                if log_idx >= 0:
                    self.tabs.setCurrentIndex(log_idx)
        finally:
            self._error_dialog_showing = False
            self._last_error_dialog_time = time.monotonic()

    def create_faq_tab(self) -> QWidget:
        """Create the FAQ tab (#152). Content lives in docs/FAQ.md (bundled
        into the frozen build via SmartCitizen.spec and build_exe.py) and
        renders through the same markdown_to_html pipeline as About/Legal so
        theme swaps recolor it consistently."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.faq_browser = QTextBrowser()
        self.faq_browser.setOpenExternalLinks(True)
        self._render_faq_html()
        layout.addWidget(self.faq_browser)
        return widget

    def _render_faq_html(self):
        """(Re)render the FAQ tab HTML. Mirrors _render_legal_html (sans badge);
        force the browser palette to track the theme for live theme swaps."""
        from PyQt6.QtWidgets import QApplication
        self.faq_browser.setPalette(QApplication.palette())
        try:
            faq_path = AppSettings.get_localized_doc_path("FAQ.md")
            with open(faq_path, 'r', encoding='utf-8') as f:
                faq_content = f.read()
            self.faq_browser.setHtml(self.markdown_to_html(faq_content))
        except Exception as e:
            logger.error(f"Error loading FAQ.md: {e}", exc_info=True)
            self.faq_browser.setHtml(
                f"<h1>{tr('tabs.faq')}</h1><p>{tr('tabs.faq_load_failed')}</p>"
                f"<p style='color: gray;'>{str(e)}</p>"
            )

    def create_legal_tab(self) -> QWidget:
        """Create the Legal tab — CIG community-content compliance, license
        notices, privacy/data disclosure, and AI-use statement. Content lives
        in docs/LEGAL.md (bundled into the frozen build via
        SmartCitizen.spec) and renders through the same markdown_to_html
        pipeline as About and Help so theme swaps recolor it consistently.
        """
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.legal_browser = QTextBrowser()
        self.legal_browser.setOpenExternalLinks(True)
        self._render_legal_html()
        layout.addWidget(self.legal_browser)
        return widget

    def _render_legal_html(self):
        """(Re)render the Legal tab HTML. Mirrors _render_about_html — force
        the browser palette to track the current theme so the viewport
        background and scrollbar chrome update on live theme swap.

        Also splices the CIG-compliant "Made by the Community" badge in
        right before the closing ``</body>`` so it sits as a footer
        beneath the legal text. Splicing the ``<img>`` post-conversion
        (rather than embedding it in LEGAL.md) avoids the markdown
        renderer wrapping it in a ``<p>`` and lets the absolute file
        path resolve through ``get_resource_path`` so the frozen build
        finds it under ``_MEIPASS\\assets\\``.
        """
        from PyQt6.QtWidgets import QApplication
        self.legal_browser.setPalette(QApplication.palette())
        try:
            legal_path = AppSettings.get_localized_doc_path("LEGAL.md")
            with open(legal_path, 'r', encoding='utf-8') as f:
                legal_content = f.read()
            html = self.markdown_to_html(legal_content)

            # File-URL the bundled CIG badge so QTextBrowser can load it.
            # Forward slashes only — Qt's URL parser chokes on backslashes
            # even on Windows.
            badge_path = str(get_resource_path("assets/sc-community.png"))
            badge_url = "file:///" + badge_path.replace("\\", "/")
            badge_html = (
                f'<div style="text-align: center; margin: 30px 0 10px 0;">'
                f'<img src="{badge_url}" alt="Made by the Community" width="200" />'
                f'</div>'
            )
            # Inject the badge immediately before </body> so it sits as
            # a footer beneath the legal text. The renderer always emits
            # a literal "</body>" so a plain string replace is safe.
            html = html.replace("</body>", badge_html + "</body>", 1)

            self.legal_browser.setHtml(html)
        except Exception as e:
            logger.error(f"Error loading LEGAL.md: {e}", exc_info=True)
            self.legal_browser.setHtml(
                f"<h1>{tr('tabs.legal')}</h1><p>{tr('tabs.legal_load_failed')}</p>"
                f"<p style='color: gray;'>{str(e)}</p>"
            )

    @pyqtSlot()
    def _set_toolbar_enabled(self, enabled: bool):
        """Toggle toolbar button enabled states."""
        self.apply_btn.setEnabled(enabled)
        # restore/clear/import/export and open-loc-dir now live under More, so
        # disabling the one button gates all of them during operations.
        self.more_btn.setEnabled(enabled)

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

    def _set_apply_btn_dirty(self, dirty: bool) -> None:
        """Single chokepoint for the button's enabled state, tooltip, and
        color so none of the three can drift apart. Red (needs_apply) means
        a change is waiting to be applied; green (apply) means the game
        already matches what's loaded. The :disabled selector is set
        explicitly so Qt's native greyed-out look doesn't wash out the
        color — the color itself is the signal here, not the enabled state.
        Same enabled/disabled tooltip pattern as the Enhancements tab's
        Generate Enhancements / Save Tag Changes buttons; resolved via tr()
        here (not cached class constants) so it always reflects the active
        language."""
        self._apply_dirty = dirty
        self.apply_btn.setEnabled(dirty)
        self.apply_btn.setToolTip(
            tr("toolbar.apply_enabled_tooltip") if dirty else tr("toolbar.apply_disabled_tooltip")
        )
        color = get_button_color("needs_apply" if dirty else "apply")
        text = get_button_text_color()
        self.apply_btn.setStyleSheet(
            f"QPushButton {{ background-color: {color}; color: {text}; "
            f"font-weight: bold; padding: 6px; }}"
            f"QPushButton:disabled {{ background-color: {color}; color: {text}; }}"
        )

    def _mark_apply_dirty(self, *_args):
        """Something that Apply to Game would pick up changed — light the
        button back up. Wired to: any table edit (via the model's
        dataChanged chokepoint), every entries reload (covers Apply Category
        Changes / Generate Enhancements / Save Tag Changes / language+channel
        switches / import / restore, which all funnel through a reload), and
        the Owned-tag re-weave (which doesn't reload but does change what
        Apply would write)."""
        self._set_apply_btn_dirty(True)
        if self._initial_load_done:
            self._session_has_unapplied_edit = True

    @pyqtSlot()
    @timed
    def apply_to_game(self):
        """Apply merged sources + user edits to game installation and backup existing file."""
        if not self.entries:
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_file_loaded"))
            return

        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_game_path"))
            return

        # Save user.ini FIRST, before touching the game file. Pre-1.4.1 the
        # save ran AFTER the game write succeeded; an OS-level write failure
        # (Controlled Folder Access on the game-folder portable install, a
        # locked file, a quarantined path) left the game with the new
        # favourites but user.ini empty — the user's edits were lost on the
        # next launch even though the in-game state looked correct. Bailing
        # here on save failure keeps the game file untouched so a retry can
        # land both halves consistently.
        try:
            from src.utils.user_ini_manager import save_user_ini
            user_ini_path = AppSettings.get_user_ini_path()
            user_count = save_user_ini(self.entries, user_ini_path)
        except Exception as e:
            logger.exception(f"Failed to save user.ini before applying to game: {e}")
            QMessageBox.critical(
                self, tr("apply.cannot_save_edits_title"),
                tr("apply.cannot_save_edits_body",
                   path=user_ini_path, error_type=type(e).__name__, error=e),
            )
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
                    self, tr("dialogs.missing_sources_title"),
                    tr("dialogs.missing_sources_body", names=names),
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

            # When "Include discovered items" is off, strip discovered items
            # (status "New" with no user override) from the enhancements
            # source so they don't flow into the applied global.ini.
            if not AppSettings.get_include_new_lines():
                new_keys = {
                    entry.key for entry in self.entries
                    if entry.status == "New" and not entry.custom_value
                }
                if new_keys and "enhancements" in sources_dict:
                    sources_dict["enhancements"] = {
                        k: v for k, v in sources_dict["enhancements"].items()
                        if k not in new_keys
                    }

            # Merge all sources in hierarchy order, with user edits on top
            merged_dict = merge_sources_by_hierarchy(sources_dict, hierarchy, user_overrides_dict)

            # #157: weave [Owned] into blueprint lists so the tag reaches the
            # applied game file (apply re-loads sources from disk, where the
            # live owned overlay isn't baked in). Idempotent.
            _owned = AppSettings.get_owned_items()
            if _owned:
                from src.utils.owned_items import apply_owned_to_value
                for _k, _v in list(merged_dict.items()):
                    _nv = apply_owned_to_value(_v, _owned)
                    if _nv != _v:
                        merged_dict[_k] = _nv

            # Stamp Journal entries Smart Citizen produced or modified —
            # both user-edited journals AND auto-generated journal
            # enhancements (Mining Compendium etc.) qualify; stock CIG
            # content is left alone. Comparison is against the stock
            # base.ini values from sources_dict["global"], so any merged
            # value that diverges from stock gets the stamp. Purely
            # write-time and idempotent across re-applies.
            stock_dict = sources_dict.get(AppSettings.SOURCE_GLOBAL, {})
            merged_dict = _stamp_journal_entries(merged_dict, stock_dict)

            # Stamp the main-menu version chip so the game shows that
            # Smart Citizen is active. Idempotent across re-applies and
            # version bumps; skipped if stock doesn't ship the key.
            merged_dict = _stamp_frontend_version(merged_dict)

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

                self.statusBar().showMessage(tr("dialogs.apply_failed_status"))
                QMessageBox.critical(
                    self, tr("dialogs.validation_failed_title"),
                    tr("dialogs.validation_failed_body", msg=validation_msg, restore_note=restore_note),
                )
                return

            # user.ini was already saved at the top of apply_to_game (before
            # the game-side writes). Reach for the count here purely for the
            # success-dialog summary — the save itself is locked in by now.

            # Count enhancement entries, broken down by category. Sorted
            # descending by count so the dialog leads with the biggest
            # buckets (typically Missions / Ship Items). "SCLE" was the
            # legacy app name (SC Localization Editor); the label now
            # matches the rebrand to "Smart Citizen".
            from collections import Counter
            enhancement_categories = Counter(
                entry.category for entry in self.entries
                if entry.source_file == "enhancements"
            )
            enhancement_count = sum(enhancement_categories.values())

            # Copy languages.ini to {channel}/data/languages.ini if available
            import shutil as _shutil
            lang_ini_src = AppSettings.get_language_languages_ini_path()
            if lang_ini_src is not None:
                lang_ini_dest = AppSettings.get_languages_ini_dest_path()
                lang_ini_dest.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copy2(lang_ini_src, lang_ini_dest)
                logger.info(f"Copied languages.ini to {lang_ini_dest}")
            else:
                logger.debug(
                    f"No languages.ini found for language "
                    f"'{AppSettings.get_selected_language()}'; skipping copy"
                )

            # Ensure user.cfg has the selected language
            from src.utils.user_cfg import ensure_user_cfg_language
            ensure_user_cfg_language()

            logger.info(f"Applied to game: {target_path}")
            self.statusBar().showMessage(
                tr("dialogs.apply_status", user_count=user_count, enhancement_count=enhancement_count)
            )
            if enhancement_categories:
                breakdown = "\n".join(
                    f"    {cat}: {count:,}"
                    for cat, count in enhancement_categories.most_common()
                )
                enhancement_block = (
                    f"  Smart Citizen enhancements ({enhancement_count:,} total):\n"
                    f"{breakdown}"
                )
            else:
                enhancement_block = f"  Smart Citizen enhancements: 0"
            QMessageBox.information(
                self, tr("dialogs.success_title"),
                tr("apply.applied_body", target_path=target_path, user_count=f"{user_count:,}",
                   enhancement_block=enhancement_block),
            )
            self._set_apply_btn_dirty(False)
            self._session_has_unapplied_edit = False
        except Exception as e:
            QMessageBox.critical(self, tr("dialogs.error_title"), tr("apply.failed_body", error=e))
            logger.error(f"Error applying to game: {e}")

    def _validate_applied_file(
        self,
        written_path: Path,
        stock_keys: set[str] | None = None,
    ) -> str:
        """Thin Qt-side wrapper around src.utils.applied_file_validator.

        Resolves the cache directory from AppSettings and forwards to the
        pure-Python implementation. Kept as an instance method so existing
        call sites (apply_to_game) don't change.
        """
        return _validate_applied_file_impl(
            written_path,
            AppSettings.get_cache_dir(),
            stock_keys=stock_keys,
        )

    @pyqtSlot()
    def clear_localization(self):
        """Delete global.ini from the active channel's localization directory, reverting to vanilla text."""
        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_game_path"))
            return

        global_ini = AppSettings.get_global_ini_path()
        loc_dir = global_ini.parent

        if not global_ini.exists():
            QMessageBox.information(self, tr("dialogs.nothing_to_clear_title"),
                tr("dialogs.nothing_to_clear_body"))
            return

        reply = QMessageBox.question(
            self, tr("dialogs.clear_localization_title"),
            tr("dialogs.clear_localization_body", loc_dir=loc_dir),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            global_ini.unlink()
            logger.info(f"Deleted {global_ini}")
            self.statusBar().showMessage(tr("dialogs.clear_localization_status"))
            QMessageBox.information(self, tr("dialogs.clear_localization_done_title"),
                tr("dialogs.clear_localization_done_body"))
        except Exception as e:
            QMessageBox.critical(self, tr("dialogs.error_title"), tr("dialogs.failed_to_delete_global_ini", error=e))
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
            QMessageBox.information(self, tr("dialogs.cache_empty_title"), tr("dialogs.cache_empty_body"))
            return

        # First dialog: clear regular cache files
        file_list = "\n".join(f"  {f.name}" for f in sorted(cached_files))
        msg = f"This will delete the following cached files:\n\n{file_list}\n\n"
        msg += "base.ini will need to be re-extracted from Data.p4k before strings can be loaded."

        reply = QMessageBox.question(
            self, tr("dialogs.clear_cache_title"), msg,
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
                self, tr("dialogs.dataforge_cache_title"),
                "Also clear the DataForge entity cache?\n\n"
                "⚠️  Warning: Recreating the DataForge cache takes a few minutes on first run.\n\n"
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
                from src.utils.pak_extractor import robust_rmtree
                robust_rmtree(dataforge_dir)
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
            msg += f"\n\nFailed to delete:\n" + "\n".join(failed)
        QMessageBox.information(self, tr("dialogs.cache_cleared_title"), msg)

        # Re-sync all remote sources so they're available for the next Apply.
        # The sync completion will also prompt for p4k extraction if base.ini is missing.
        if self._startup_sync_worker is None:
            self._start_startup_sync()

    @pyqtSlot()
    def open_localization_dir(self):
        """Open the active channel's localization directory in Windows Explorer."""
        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_game_path"))
            return

        loc_dir = AppSettings.get_global_ini_path().parent

        if not loc_dir.exists():
            QMessageBox.warning(
                self, tr("dialogs.dir_not_found_title"),
                f"Localization directory not found:\n{loc_dir}\n\n"
                "Check your game install path in the Config tab."
            )
            return

        QDesktopServices.openUrl(QUrl.fromLocalFile(str(loc_dir)))

    @pyqtSlot()
    def export_locpack(self):
        """Package the currently-applied global.ini into a shareable zip.

        Reads the already-written game file rather than re-merging in
        memory — keeps the export aligned with what the user has actually
        validated in-game, and makes "Export" a no-side-effect action
        (no implicit re-apply, no surprises).
        """
        from src.utils.locpack_exporter import default_locpack_filename, write_locpack_zip

        if not AppSettings.get_game_install_path():
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_game_path"))
            return

        global_ini = AppSettings.get_global_ini_path()
        if not global_ini.exists():
            QMessageBox.information(
                self, tr("dialogs.nothing_to_export_title"),
                tr("dialogs.nothing_to_export_body"),
            )
            return

        channel = AppSettings.get_active_channel()
        default_name = default_locpack_filename(channel)
        # Suggest the user's Downloads folder as the default save location —
        # most natural place for a "share this file" output.
        downloads_dir = Path.home() / "Downloads"
        if not downloads_dir.exists():
            downloads_dir = Path.home()
        default_path = str(downloads_dir / default_name)

        out_path_str, _ = QFileDialog.getSaveFileName(
            self,
            tr("dialogs.export_loc_pack_title"),
            default_path,
            "Zip files (*.zip);;All files (*)",
        )
        if not out_path_str:
            return  # user cancelled

        out_path = Path(out_path_str)
        try:
            source_size = write_locpack_zip(global_ini, out_path)
        except Exception as e:
            logger.exception("Loc-pack export failed")
            QMessageBox.critical(
                self, tr("dialogs.export_failed_title"),
                tr("dialogs.export_failed_body", error=e),
            )
            return

        zip_size = out_path.stat().st_size
        QMessageBox.information(
            self, tr("dialogs.export_complete_title"),
            tr("dialogs.export_complete_body",
               out_path=out_path, channel=channel,
               source_size=source_size, zip_size=zip_size),
        )

    @pyqtSlot()
    @timed
    def _snapshot_pending_user_edits(self) -> dict:
        """Return {key: custom_value} for in-memory edits that may not be on disk.

        Reload paths (Config-tab save, Generate Enhancements completion, etc.)
        rebuild self.entries from disk sources — which means custom_value comes
        only from user.ini. Edits the user made but hasn't yet Applied live
        only in memory; without snapshotting them here they'd be silently
        wiped by the reload.
        """
        return {
            e.key: e.custom_value
            for e in self.entries
            if e.custom_value
        }

    def _restore_pending_user_edits(self, entries: list, snapshot: dict) -> int:
        """Re-apply *snapshot* on top of freshly-loaded *entries*.

        Mirrors inline-edit setData semantics: status flips Modified if the
        restored value differs from the new original, Unmodified otherwise.
        Returns the count actually restored.
        """
        if not snapshot:
            return 0
        restored = 0
        for e in entries:
            pending = snapshot.get(e.key)
            if pending is None or pending == e.custom_value:
                continue
            e.custom_value = pending
            e.status = "Modified" if pending != e.original_value else "Unmodified"
            restored += 1
        return restored

    @pyqtSlot(str, str)
    def _on_favorite_prefix_changed(self, old_prefix: str, new_prefix: str):
        """Re-prefix in-memory favourites after the sort prefix changed (#140).

        ``_apply_favorite_prefix`` already migrated ``user.ini`` on disk, but
        ``perform_merge_and_reload`` snapshots the current in-memory
        ``custom_value``s and restores them over the freshly-loaded entries.
        Without re-prefixing memory here, that snapshot still holds the old
        prefix and clobbers the migrated value straight back. Re-prefix in
        memory first so the snapshot carries the new prefix and the restore is
        a no-op. Mirrors the user.ini migration's ``startswith`` rule.
        """
        if old_prefix and old_prefix != new_prefix:
            for e in self.entries:
                if e.custom_value.startswith(old_prefix):
                    e.custom_value = new_prefix + e.custom_value[len(old_prefix):]
        self.perform_merge_and_reload()

    def perform_merge_and_reload(self):
        """Perform merge of configured sources and reload table.

        Called when user saves configuration in Config tab. Loads all configured
        sources, merges them in hierarchy order, and updates the table display.
        """
        pending_edits = self._snapshot_pending_user_edits()
        try:
            # Load all configured sources
            sources_dict, hierarchy, enhancements_key_categories = load_sources_from_settings()

            if not sources_dict or not hierarchy:
                QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_sources_body"))
                return

            self.statusBar().showMessage(tr("dialogs.merging_sources"))

            try:
                # Load synchronously in main thread
                logger.info("Merging configured sources...")
                entries = load_source_files(sources_dict, hierarchy, enhancements_key_categories=enhancements_key_categories)
                logger.info(f"Merge complete: {len(entries)} entries")
                restored = self._restore_pending_user_edits(entries, pending_edits)
                if restored:
                    logger.info(f"Restored {restored} in-memory user edits not yet persisted to user.ini")
                self.entries = entries
                self.default_values = dict(sources_dict.get("global", {}))
                self.update_category_combo()
                self._model.set_data_source(
                    self.entries,
                    self.default_values,
                    AppSettings.get_favorite_prefix(),
                )
                self.apply_filters()
                self._rebuild_blueprint_metadata()  # #157 follow-up: filter data
                self._recompute_owned()  # #157

                # Update status bar with entry counts and per-source status
                self._update_status_bar()
            except Exception as e:
                logger.exception(f"Error during merge: {e}")
                QMessageBox.critical(self, tr("dialogs.error_title"), tr("dialogs.failed_to_merge_sources", error=e))
                self.statusBar().showMessage(tr("dialogs.merge_failed"))

        except Exception as e:
            logger.exception(f"Error in perform_merge_and_reload: {e}")
            QMessageBox.critical(self, tr("dialogs.error_title"), tr("dialogs.failed_to_load_sources", error=e))

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
        self._set_apply_btn_dirty(self._apply_dirty)  # re-picks green/red for the new theme
        self.more_btn.setStyleSheet(f"background-color: {get_button_color('clear')}; color: {text}; {base}")
        self.editor_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {text}; {base}")
        self.help_btn.setStyleSheet(f"background-color: {get_button_color('open')}; color: {text}; {base}")
        if hasattr(self, "about_browser"):
            self._render_about_html()
        if hasattr(self, "help_browser"):
            self._render_help_html()
        if hasattr(self, "legal_browser"):
            self._render_legal_html()
        if hasattr(self, "faq_browser"):
            self._render_faq_html()
        self._apply_editor_dock_canvas_tint()

    def _handle_reset_user_ini(self):
        """Confirm + delete the active channel's user.ini, preserving a backup.

        Flow:
          1. Resolve the channel-scoped user.ini path. If absent, surface
             "nothing to reset" and return.
          2. Show a destructive-action confirmation dialog (default = No)
             listing the path, file size, and what the backup will be named.
          3. Rename user.ini → user.ini.bak-YYYYMMDD-HHMMSS via
             user_ini_manager.reset_user_ini. On OSError (locked file,
             permissions), surface the error and bail without changing
             in-memory state.
          4. Clear ``custom_value`` on every in-memory entry so the
             close-time autosave guard doesn't see them as modifications
             and re-write the file we just removed. The async reload that
             follows replaces self.entries wholesale, but the window
             between delete and reload completion is a real one where
             closeEvent could fire and undo the reset.
          5. Kick off a full FileLoaderWorker reload via
             _show_loading_progress so the table reflects stock values
             with the user-override layer gone.
        """
        from src.utils.user_ini_manager import reset_user_ini

        user_ini_path = AppSettings.get_user_ini_path()
        channel = AppSettings.get_active_channel()

        if not user_ini_path.exists():
            QMessageBox.information(
                self,
                tr("dialogs.nothing_to_reset_title"),
                tr("dialogs.nothing_to_reset_body", channel=channel, path=user_ini_path),
            )
            return

        try:
            size_kb = user_ini_path.stat().st_size / 1024
            size_str = f"{size_kb:.1f} KB"
        except OSError:
            size_str = "unknown size"

        reply = QMessageBox.warning(
            self,
            tr("dialogs.reset_user_ini_title"),
            f"This will remove every custom string override for the "
            f"{channel} channel.\n\n"
            f"File: {user_ini_path}\n"
            f"Size: {size_str}\n\n"
            f"A timestamped backup will be saved next to the original "
            f"(user.ini.bak-YYYYMMDD-HHMMSS) so you can restore by renaming it "
            f"back to user.ini.\n\n"
            f"This does NOT touch the game's global.ini — to revert what "
            f"the game sees in-game, run Apply Enhancements after the reset, or "
            f"use Restore Backup.\n\n"
            f"Proceed?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            backup_path = reset_user_ini(user_ini_path, backup=True)
        except OSError as e:
            logger.exception(f"Failed to reset user.ini at {user_ini_path}")
            QMessageBox.critical(
                self,
                tr("dialogs.reset_failed_title"),
                tr("dialogs.reset_failed_body", error=e),
            )
            return

        # In-memory wipe before the async reload — see step 4 docstring.
        for entry in self.entries:
            if entry.custom_value:
                entry.custom_value = ""

        self._show_loading_progress(
            f"Reloading {channel} after user.ini reset..."
        )

        backup_note = tr("user_ini_reset.backup_note", path=backup_path) if backup_path else ""
        self.statusBar().showMessage(
            tr("status_bar.user_ini_reset", channel=channel), 5000
        )
        QMessageBox.information(
            self,
            tr("user_ini_reset.complete_title"),
            tr("user_ini_reset.complete_body", channel=channel, backup_note=backup_note),
        )

    def _handle_restore_user_ini(self):
        """Let the user restore user.ini from an automatic snapshot (#172).

        Lists the rotating snapshots (newest first), lets the user pick one,
        confirms, restores it (snapshotting the current file first so the
        restore is itself reversible), and reloads the table. The reset-button
        siblings (user.ini.bak-*) are intentionally not listed here — those are
        restored by renaming, as the Reset dialog explains.
        """
        from src.utils.user_ini_manager import (
            list_user_ini_backups,
            restore_user_ini_backup,
        )

        user_ini_path = AppSettings.get_user_ini_path()
        channel = AppSettings.get_active_channel()
        backups = list_user_ini_backups(user_ini_path)

        if not backups:
            QMessageBox.information(
                self,
                tr("restore_user_ini.no_snapshots_title"),
                tr("restore_user_ini.no_snapshots_body", channel=channel),
            )
            return

        # Build "YYYY-MM-DD HH:MM:SS — N lines, M KB" labels mapped to paths.
        from datetime import datetime as _dt

        labels = []
        for b in backups:
            try:
                st = b.stat()
                when = _dt.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
                lines = b.read_text(encoding="utf-8", errors="replace").count("\n")
                size_kb = st.st_size / 1024
                labels.append(tr("restore_user_ini.snapshot_label", when=when, lines=lines, size_kb=f"{size_kb:.1f}"))
            except OSError:
                labels.append(b.name)

        choice, ok = QInputDialog.getItem(
            self,
            tr("restore_user_ini.picker_title"),
            tr("restore_user_ini.picker_label", channel=channel),
            labels,
            0,
            False,
        )
        if not ok:
            return
        chosen = backups[labels.index(choice)]

        try:
            restore_user_ini_backup(chosen, user_ini_path)
        except OSError as e:
            logger.exception(f"Failed to restore user.ini from {chosen}")
            QMessageBox.critical(
                self, tr("restore_user_ini.restore_failed_title"),
                tr("restore_user_ini.restore_failed_body", error_type=type(e).__name__, error=e),
            )
            return

        self._show_loading_progress(tr("progress.reloading_after_user_ini_restore", channel=channel))
        self.statusBar().showMessage(tr("status_bar.user_ini_restored", channel=channel), 5000)
        QMessageBox.information(
            self, tr("restore_user_ini.restored_title"),
            tr("restore_user_ini.restored_body", channel=channel, name=chosen.name),
        )

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

                self.statusBar().showMessage(tr("status_bar.downloading_ini"))
                try:
                    temp_file = tempfile.NamedTemporaryFile(suffix='.ini', delete=False)
                    temp_file.close()
                    urllib.request.urlretrieve(source, temp_file.name)
                    resolved_path = temp_file.name
                except Exception as e:
                    QMessageBox.critical(
                        self, tr("import_flow.download_error_title"),
                        tr("import_flow.download_error_body", source=source, error=e),
                    )
                    return
            else:
                resolved_path = source
                if not Path(resolved_path).exists():
                    QMessageBox.warning(self, tr("dialogs.file_not_found_title"), tr("dialogs.file_not_found_body", path=resolved_path))
                    return

            # Step 3: Parse imported file
            imported = parse_ini_file(resolved_path)
            if not imported:
                QMessageBox.warning(self, tr("dialogs.empty_file_title"), tr("dialogs.empty_file_body"))
                return

            # Step 4: Validate against base.ini keys
            if not self.default_values:
                QMessageBox.warning(
                    self, tr("import_flow.no_base_data_title"),
                    tr("import_flow.no_base_data_body"),
                )
                return

            valid_keys = {k: v for k, v in imported.items() if k in self.default_values}
            excluded_count = len(imported) - len(valid_keys)

            if not valid_keys:
                QMessageBox.warning(
                    self, tr("import_flow.no_valid_keys_title"),
                    tr("import_flow.no_valid_keys_body", count=len(imported)),
                )
                return

            # Step 5: Load current user.ini (strip_values=False so leading-space
            # favourite prefixes round-trip verbatim — see issue #100).
            user_ini_path = AppSettings.get_user_ini_path()
            current_user = parse_ini_file(user_ini_path, strip_values=False) if user_ini_path.exists() else {}

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
                    self, tr("import_flow.nothing_to_import_title"),
                    tr("import_flow.nothing_to_import_body"),
                )
                return

            if not conflicts:
                reply = QMessageBox.question(
                    self, tr("import_flow.confirm_title"),
                    tr("import_flow.confirm_body", new_count=len(auto_add), excluded_count=excluded_count),
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
            self._show_loading_progress(tr("import_flow.reload_status"))

            # Step 11: Summary
            QMessageBox.information(
                self, tr("import_flow.complete_title"),
                tr("import_flow.complete_body", added=len(auto_add),
                   resolved=len(resolutions), excluded=excluded_count),
            )

        except Exception as e:
            logger.exception(f"Import failed: {e}")
            QMessageBox.critical(self, tr("import_flow.error_title"), tr("import_flow.error_body", error=e))
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
        dialog.setWindowTitle(tr("import_flow.source_dialog_title"))
        dialog.setMinimumWidth(500)
        layout = QVBoxLayout(dialog)

        layout.addWidget(QLabel(tr("import_flow.source_dialog_label")))

        input_row = QHBoxLayout()
        line_edit = QLineEdit()
        line_edit.setPlaceholderText(tr("import_flow.source_dialog_placeholder"))
        input_row.addWidget(line_edit)

        browse_btn = QPushButton(tr("import_flow.browse_btn"))
        browse_btn.setToolTip(tr("dialogs.browse_ini_tooltip"))
        def browse():
            path, _ = QFileDialog.getOpenFileName(
                dialog, tr("import_flow.select_ini_file_title"), "", tr("import_flow.ini_file_filter"))
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
            QMessageBox.warning(self, tr("dialogs.warning_title"), tr("dialogs.no_game_path"))
            return

        backup_dir = AppSettings.get_backups_dir()

        # Open file dialog to select backup
        backup_file, _ = QFileDialog.getOpenFileName(
            self,
            tr("restore_backup.select_file_title"),
            str(backup_dir),
            tr("restore_backup.file_filter"),
        )

        if not backup_file:
            return

        try:
            import shutil

            target_path = AppSettings.get_global_ini_path()
            backup_file_path = Path(backup_file)

            # Restore the backup
            shutil.copy2(str(backup_file_path), str(target_path))

            # Refresh the table from configured sources. The restore writes the
            # game's global.ini (merged output); the editor view is source-backed
            # (base.ini + user.ini + enhancements), so reload from settings rather
            # than parsing the restored output file as if it were a source.
            self.perform_merge_and_reload()

            logger.info(f"Restored backup from {backup_file} to {target_path}")
            QMessageBox.information(
                self, tr("dialogs.success_title"),
                tr("restore_backup.success_body", name=backup_file_path.name),
            )
        except Exception as e:
            QMessageBox.critical(
                self, tr("dialogs.error_title"),
                tr("restore_backup.error_body", error=e),
            )
            logger.error(f"Error restoring backup: {e}")

    @pyqtSlot()
    def _ensure_help_dock(self) -> QDockWidget:
        """Create the side-docked Help panel on first use and return it."""
        if getattr(self, "help_dock", None) is not None:
            return self.help_dock

        dock = QDockWidget("Help", self)
        dock.setObjectName("helpDock")
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

        dock.visibilityChanged.connect(self._on_help_dock_visibility_changed)
        self._render_help_html()
        return dock

    def _on_help_dock_visibility_changed(self, visible: bool):
        """Keep the toolbar Help button's checked state in sync with the dock."""
        if hasattr(self, "help_btn"):
            was_blocked = self.help_btn.blockSignals(True)
            try:
                self.help_btn.setChecked(visible)
            finally:
                self.help_btn.blockSignals(was_blocked)

    def show_help(self):
        """Toggle the Help side-panel."""
        dock = self._ensure_help_dock()
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            dock.raise_()

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
            help_path = AppSettings.get_localized_doc_path("HELP.md")
            with open(help_path, "r", encoding="utf-8") as f:
                help_markdown = f.read()
            self.help_browser.setHtml(self.markdown_to_html(help_markdown))
        except Exception as e:
            logger.error(f"Error loading HELP.md: {e}", exc_info=True)
            self.help_browser.setHtml(
                "<h1>Help</h1><p>Help content could not be loaded. "
                "See the About tab or the project README for usage details.</p>"
            )

    # ── Side-docked Test Plan (#144) ─────────────────────────────────────────

    def _ensure_test_plan_dock(self) -> QDockWidget:
        """Create the side-docked tester Test Plan on first use and return it."""
        if getattr(self, "test_plan_dock", None) is not None:
            return self.test_plan_dock

        from src.gui.test_plan_panel import TestPlanPanel

        dock = QDockWidget(tr("toolbar.menu_test_plan"), self)
        dock.setObjectName("testPlanDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )
        self.test_plan_panel = TestPlanPanel(dock)
        dock.setWidget(self.test_plan_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.test_plan_dock = dock
        return dock

    def show_test_plan(self):
        """Toggle the Test Plan side-panel."""
        dock = self._ensure_test_plan_dock()
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            dock.raise_()

    # ── Side-docked String Editor ────────────────────────────────────────────

    def _ensure_editor_dock(self) -> QDockWidget:
        """Create the side-docked String Editor on first use and return it.

        Provides a multi-line editing canvas for the currently-selected
        row's custom value — useful for long mission descriptions and
        journal entries that don't fit comfortably in a single-line table
        cell. Lives as a QDockWidget so users can drag it to either side,
        undock it into a free-floating window, resize freely, or close it
        via the title-bar X. State persists across sessions through
        saveState/restoreState, which keys docks by objectName.

        The loc-string format stores line breaks as the literal two-char
        sequence ``\\n``; the dock displays them as real newlines for
        readability and converts both directions on load/save so values
        round-trip cleanly with the inline cell editor.
        """
        if getattr(self, "editor_dock", None) is not None:
            return self.editor_dock

        dock = QDockWidget(tr("strings_tab.editor_dock_title"), self)
        dock.setObjectName("editorDock")
        dock.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea
            | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        container = QWidget(dock)
        vlayout = QVBoxLayout(container)
        vlayout.setContentsMargins(8, 8, 8, 8)
        vlayout.setSpacing(6)

        self.editor_dock_key_label = QLabel(tr("strings_tab.no_row_selected"))
        self.editor_dock_key_label.setProperty("role", "secondary")
        key_font = QFont("Consolas")
        key_font.setPointSize(9)
        self.editor_dock_key_label.setFont(key_font)
        self.editor_dock_key_label.setWordWrap(True)
        vlayout.addWidget(self.editor_dock_key_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._editor_underline_btn = QPushButton(tr("strings_tab.editor_underline_btn"))
        self._editor_underline_btn.setToolTip(tr("strings_tab.editor_underline_tooltip"))
        self._editor_underline_btn.clicked.connect(lambda: self._editor_dock_wrap("EM3"))
        btn_row.addWidget(self._editor_underline_btn)
        self._editor_highlight_btn = QPushButton(tr("strings_tab.editor_highlight_btn"))
        self._editor_highlight_btn.setToolTip(tr("strings_tab.editor_highlight_tooltip"))
        self._editor_highlight_btn.clicked.connect(lambda: self._editor_dock_wrap("EM4"))
        btn_row.addWidget(self._editor_highlight_btn)
        btn_row.addStretch()
        vlayout.addLayout(btn_row)

        self.editor_dock_text = QPlainTextEdit()
        self.editor_dock_text.setPlaceholderText(tr("strings_tab.editor_placeholder"))
        self.editor_dock_text.setEnabled(False)
        self.editor_dock_text.textChanged.connect(self._on_editor_dock_text_changed)
        self.editor_dock_text.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor_dock_text.customContextMenuRequested.connect(self._show_editor_dock_menu)
        vlayout.addWidget(self.editor_dock_text, stretch=1)
        # Tint the canvas with the lighter of the table's two row colors so
        # the editing surface stands apart from the dock's frame/border —
        # especially important when the dock is undocked into its own window.
        self._apply_editor_dock_canvas_tint()

        self.editor_dock_status_label = QLabel("")
        self.editor_dock_status_label.setProperty("role", "secondary")
        vlayout.addWidget(self.editor_dock_status_label)

        dock.setWidget(container)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
        self.editor_dock = dock
        self._editor_dock_entry_idx: Optional[int] = None
        # Set during programmatic load so textChanged doesn't echo back
        # into the model and re-flag the row as Modified.
        self._editor_dock_loading = False

        dock.visibilityChanged.connect(self._on_editor_dock_visibility_changed)
        return dock

    def _apply_editor_dock_canvas_tint(self):
        """Tint the editor canvas with the lighter of Base/AlternateBase.

        The two roles drive the table's alternating row stripes; whichever is
        lighter visually reads as the 'foreground' band. Using it for the
        editing surface keeps the canvas distinct from the dock's frame
        and gives the pop-out window a clear inner/outer separation.
        Light theme has Base lighter than AlternateBase; the dark and
        branded themes invert that — so pick by lightness rather than
        hard-coding either role.
        """
        if not getattr(self, "editor_dock_text", None):
            return
        from PyQt6.QtWidgets import QApplication
        app_pal = QApplication.palette()
        base = app_pal.color(QPalette.ColorRole.Base)
        alt = app_pal.color(QPalette.ColorRole.AlternateBase)
        canvas = base if base.lightness() >= alt.lightness() else alt
        # QPlainTextEdit paints its viewport via the style; the most
        # reliable way to recolor the canvas without disturbing scrollbars
        # or selection rendering is a scoped stylesheet on the widget.
        self.editor_dock_text.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {canvas.name()}; }}"
        )

    def _on_editor_dock_visibility_changed(self, visible: bool):
        """Keep the toolbar Editor button's checked state in sync with the dock."""
        if hasattr(self, "editor_btn"):
            was_blocked = self.editor_btn.blockSignals(True)
            try:
                self.editor_btn.setChecked(visible)
            finally:
                self.editor_btn.blockSignals(was_blocked)
        # Sync content if the dock was just shown — restoreState may have
        # opened it before any selection-change event fires.
        if visible and getattr(self, "table", None) and self.table.selectionModel():
            idx = self.table.selectionModel().currentIndex()
            if idx.isValid():
                self._load_editor_dock_from_row(idx.row())

    def show_editor_dock(self):
        """Toggle the String Editor side-panel."""
        dock = self._ensure_editor_dock()
        if dock.isVisible():
            dock.hide()
        else:
            dock.show()
            dock.raise_()
            self.editor_dock_text.setFocus()

    def _clear_editor_dock(self):
        """Reset the editor dock to its 'no row selected' state."""
        if not getattr(self, "editor_dock", None):
            return
        self._editor_dock_entry_idx = None
        self._editor_dock_loading = True
        try:
            self.editor_dock_text.setPlainText("")
            self.editor_dock_text.setEnabled(False)
        finally:
            self._editor_dock_loading = False
        self.editor_dock_key_label.setText(tr("strings_tab.no_row_selected"))
        self.editor_dock_status_label.setText("")

    def _load_editor_dock_from_row(self, row: int) -> None:
        """Populate the editor dock from the given table row (visual row)."""
        if not getattr(self, "editor_dock", None):
            return
        if not self.entries:
            self._clear_editor_dock()
            return
        try:
            entry_idx = self._entry_index_for_row(row)
            entry = self.entries[entry_idx]
        except (IndexError, AttributeError):
            self._clear_editor_dock()
            return
        self._editor_dock_entry_idx = entry_idx
        self.editor_dock_key_label.setText(entry.key)
        # Show real newlines while editing, even though the loc-string
        # format stores them as the literal two-char escape "\n".
        raw = entry.custom_value if entry.custom_value else entry.original_value
        visual = (raw or "").replace("\\n", "\n")
        self._editor_dock_loading = True
        try:
            self.editor_dock_text.setPlainText(visual)
            self.editor_dock_text.setEnabled(True)
        finally:
            self._editor_dock_loading = False
        self.editor_dock_status_label.setText(entry.status)

    def _on_editor_dock_text_changed(self):
        """Push edits in the dock back to the entry, mirroring inline-edit semantics."""
        if self._editor_dock_loading:
            return
        if self._editor_dock_entry_idx is None:
            return
        if self._editor_dock_entry_idx >= len(self.entries):
            return
        entry = self.entries[self._editor_dock_entry_idx]
        # QTextCursor uses U+2029 as paragraph separator in some APIs; the
        # plain-text path here returns "\n" so a direct conversion is safe.
        visual = self.editor_dock_text.toPlainText()
        new_value = visual.replace("\n", "\\n")
        if new_value == entry.custom_value:
            return
        entry.custom_value = new_value
        entry.status = "Modified" if new_value != entry.original_value else "Unmodified"
        self._model.notify_entry_changed(self._editor_dock_entry_idx)
        self.editor_dock_status_label.setText(entry.status)

    def _show_editor_dock_menu(self, pos):
        """Right-click menu: standard edit actions plus EM3/EM4 wrap."""
        menu = self.editor_dock_text.createStandardContextMenu()
        menu.addSeparator()
        cursor = self.editor_dock_text.textCursor()
        has_sel = cursor.hasSelection()
        em3 = menu.addAction(tr("strings_tab.context_underline"))
        em3.setEnabled(has_sel)
        em3.triggered.connect(lambda: self._editor_dock_wrap("EM3"))
        em4 = menu.addAction(tr("strings_tab.context_highlight"))
        em4.setEnabled(has_sel)
        em4.triggered.connect(lambda: self._editor_dock_wrap("EM4"))
        menu.exec(self.editor_dock_text.mapToGlobal(pos))

    def _editor_dock_wrap(self, tag: str):
        """Wrap the current selection in <tag>...</tag>."""
        if not getattr(self, "editor_dock", None):
            return
        cursor = self.editor_dock_text.textCursor()
        if not cursor.hasSelection():
            return
        # QTextCursor.selectedText() returns U+2029 for paragraph breaks;
        # normalize back to newlines so wrapping multi-line selections
        # preserves their structure.
        sel = cursor.selectedText().replace(" ", "\n")
        cursor.insertText(f"<{tag}>{sel}</{tag}>")

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
        bp_tab = getattr(self, "_blueprint_tracker_tab_index", 3)

        return {
            "welcome":               {"target": lambda: None,                                                  "pre_action": None},
            "extract":               {"target": lambda: self.config_tab._extract_btn,                          "pre_action": _switch_to(config_tab)},
            "edit":                  {"target": lambda: self.table,                                            "pre_action": _switch_to(strings_tab)},
            "filter_row":            {"target": lambda: self.filter_header,                                    "pre_action": _switch_to(strings_tab)},
            "editor":                {"target": lambda: self.editor_btn,                                       "pre_action": _switch_to(strings_tab)},
            "preview":               {"target": lambda: self.preview_pane,                                     "pre_action": _switch_to(strings_tab)},
            "apply":                 {"target": lambda: self.apply_btn,                                        "pre_action": None},
            "enhancements":          {"target": lambda: self.enhancements_tab._generate_enhancements_btn,      "pre_action": _switch_to(enh_tab)},
            # Enhancements tab section deep-dive
            "enh_categories":        {"target": lambda: self.enhancements_tab._enhancements_group,             "pre_action": _switch_to(enh_tab)},
            "enh_favorites":         {"target": lambda: self.enhancements_tab._favorites_group,                "pre_action": _switch_to(enh_tab)},
            "enh_mission_labels":    {"target": lambda: self.enhancements_tab.mission_labels_group,            "pre_action": _switch_to(enh_tab)},
            "enh_tag_builder":       {"target": lambda: self.enhancements_tab._tag_builder_group,              "pre_action": _switch_to(enh_tab)},
            "blueprint_tracker":     {"target": lambda: self.blueprint_tracker_tab._blueprints_available_list, "pre_action": _switch_to(bp_tab)},
            # Config tab section deep-dive
            "cfg_appearance":        {"target": lambda: self.config_tab._appearance_group,                     "pre_action": _switch_to(config_tab)},
            "cfg_sc_install":        {"target": lambda: self.config_tab._loc_group,                            "pre_action": _switch_to(config_tab)},
            "cfg_data_folder":       {"target": lambda: self.config_tab._data_group,                           "pre_action": _switch_to(config_tab)},
            "cfg_p4k_extraction":    {"target": lambda: self.config_tab._p4k_group,                            "pre_action": _switch_to(config_tab)},
            "cfg_tools":             {"target": lambda: self.config_tab._tools_group,                          "pre_action": _switch_to(config_tab)},
            "help":                  {"target": lambda: self.help_btn,                                         "pre_action": _switch_to(strings_tab)},
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
            # Language overlay (#30): a translation may carry this step's copy
            # under tutorial.<id>.title / .description in its ui.json. tr()
            # returns the bare key on a miss, so absent keys keep the English
            # copy from this file (English ui.json has no tutorial section).
            t_key = f"tutorial.{step_id}.title"
            d_key = f"tutorial.{step_id}.description"
            translated_title = tr(t_key)
            if translated_title != t_key:
                title = translated_title
            translated_desc = tr(d_key)
            if translated_desc != d_key:
                description = translated_desc
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
        if getattr(self, "_tutorial_tour", None) is not None and self._tutorial_tour.is_running():
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
        """Record either Finish or Skip as "tutorial seen for this version"
        so we don't auto-replay on every install/version bump.

        Prior behavior only persisted on Finish, on the theory that a user
        who hit Skip by accident would still get the tour next launch.
        Community feedback was the opposite: power users who deliberately
        skip get re-prompted on every release, which is more annoying than
        the accidental-skip protection is worth. The Tutorial button on
        the toolbar is always available to replay on demand, so persisting
        Skip costs nothing for the rare accidental case.
        """
        AppSettings.set_tutorial_completed_version(get_version())
        self._tutorial_tour = None
        # Now that the user is past (or has skipped) the tour, fire the
        # deferred startup tasks. Their modal prompts would otherwise pop
        # over the coach-mark overlay and break first-run.
        self._start_post_tutorial_tasks()

    def _start_post_tutorial_tasks(self) -> None:
        """Fire the deferred startup tasks once, app-update check first (#211).

        Held back until the guided tour finishes so its modal prompts (P4K
        extraction, app-update dialog, enhancements pipeline) don't pop over
        the coach-mark overlay during first-run. Idempotent — safe to call
        from multiple paths (no-tutorial branch, tour-finished, tour-skipped).

        The update check gates everything else: source sync (and the P4K /
        DataForge extraction prompts behind it) plus the OneDrive warning wait
        in _continue_startup_after_update_gate until the check resolves. An
        accepted update exits the app to install — starting an extraction that
        exit would interrupt helps nobody.
        """
        if getattr(self, "_post_tutorial_tasks_started", False):
            return
        self._post_tutorial_tasks_started = True
        self._startup_gate_pending = True
        self._run_app_update_check(force_dialog=False)

    def _continue_startup_after_update_gate(self) -> None:
        """Run the gated startup tasks once the update check resolves (#211).

        Called from every terminal outcome of the startup update check: up to
        date, check failed, or update offered but not installed. Guarded by
        the pending flag, so a later manual Config-tab check landing on the
        same handlers can't restart the sequence.
        """
        if not getattr(self, "_startup_gate_pending", False):
            return
        self._startup_gate_pending = False
        self._start_startup_sync()
        self._maybe_warn_onedrive_data_dir()

    def _maybe_warn_onedrive_data_dir(self) -> None:
        """Warn once when the data root is inside a OneDrive-managed folder (#172).

        OneDrive can sync and dehydrate/empty files under its tree, which has
        emptied user.ini. The default data root resolves Documents via the shell
        Personal folder, so on a OneDrive-redirected machine the per-user data
        lands inside OneDrive. Offers a one-click move to a local folder and a
        'don't warn again' opt-out.
        """
        if AppSettings.get_onedrive_warning_dismissed():
            return
        from src.utils.onedrive import is_onedrive_path, suggest_local_data_dir

        data_dir = AppSettings.get_user_data_dir()
        if not is_onedrive_path(data_dir):
            return

        local = suggest_local_data_dir()
        from PyQt6.QtWidgets import QCheckBox

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(tr("onedrive.warning_title"))
        box.setText(tr("onedrive.warning_body", data_dir=data_dir, local=local))
        move_btn = box.addButton(tr("onedrive.move_btn"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("onedrive.keep_here_btn"), QMessageBox.ButtonRole.RejectRole)
        dont_warn = QCheckBox(tr("onedrive.dont_warn_again"))
        box.setCheckBox(dont_warn)
        box.exec()

        if dont_warn.isChecked():
            AppSettings.set_onedrive_warning_dismissed(True)

        if box.clickedButton() is move_btn:
            # Route through the Config tab's validated save + migrate + reload.
            self.config_tab.change_data_dir_to(str(local))

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
        # #180: the guided tour spotlights the tabs and toolbar, which are
        # hidden in Simple mode (the default for new installs). Skip it there —
        # Simple mode is self-explanatory (one button), and the tour is one
        # click away from the toolbar once the user switches to Advanced. Still
        # fire the deferred startup tasks so first-run source sync / update /
        # OneDrive checks aren't lost.
        if AppSettings.get_ui_mode() == AppSettings.UI_MODE_SIMPLE:
            QTimer.singleShot(0, self._start_post_tutorial_tasks)
            return
        if AppSettings.get_tutorial_disabled():
            QTimer.singleShot(0, self._start_post_tutorial_tasks)
            return
        last_seen = AppSettings.get_tutorial_completed_version()
        current = get_version()
        if last_seen == current:
            QTimer.singleShot(0, self._start_post_tutorial_tasks)
            return
        QTimer.singleShot(400, self._start_tutorial)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Apply the mode-driven window size once, on first show: Advanced opens
        # maximized, Simple opens compact. Deferred to here (not __init__) so
        # showMaximized/showNormal act on a window that is actually visible —
        # doing it pre-show is unreliable. Guarded so it runs a single time.
        if not getattr(self, "_initial_size_applied", False):
            self._initial_size_applied = True
            self._size_window_for_mode(AppSettings.get_ui_mode())
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
        if self._eye_pulse is None or self._eye_glow is None:
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
        if getattr(self, "_channel_indicator", None) is not None:
            return
        from PyQt6.QtWidgets import QLabel as _QLabel
        self._channel_indicator = _QLabel()
        self._channel_indicator.setStyleSheet("font-size: 11px; font-weight: bold; padding: 0 8px;")
        self.statusBar().addPermanentWidget(self._channel_indicator)
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
        if getattr(self, "_app_version_indicator", None) is not None:
            return
        from PyQt6.QtWidgets import QLabel as _QLabel
        self._app_version_indicator = _QLabel(f"v{get_version()}")
        self._app_version_indicator.setStyleSheet("font-size: 11px; padding: 0 8px;")
        self._app_version_indicator.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
        self._app_version_indicator.mousePressEvent = self._on_version_label_clicked
        self.statusBar().addPermanentWidget(self._app_version_indicator)

    def _refresh_update_indicator_texts(self) -> None:
        """Render the version indicator + Config-tab update status in the
        current UI language from the last update-check state.

        The check slots set ``_update_check_state`` and delegate text here so
        a language switch can re-render via retranslate_ui() — pre-fix the
        labels kept whatever language was active when the check ran (#30).
        """
        label = getattr(self, "_app_version_indicator", None)
        if label is None:
            return
        current = get_version()
        state, version = getattr(self, "_update_check_state", (None, None))
        if state == "available":
            label.setText(tr("status_bar.update_indicator_available", current=current))
            label.setToolTip(tr("status_bar.open_release_page_tooltip", version=version))
            self.config_tab.set_update_status(tr("status_bar.update_available", version=version))
        elif state == "up_to_date":
            label.setText(tr("status_bar.update_indicator_up_to_date", current=current))
            self.config_tab.set_update_status(tr("status_bar.update_up_to_date", version=version))
        elif state == "failed":
            label.setText(tr("status_bar.update_indicator_failed", current=current))
            self.config_tab.set_update_status(tr("status_bar.update_check_failed"))
        else:
            # No check has completed yet — plain version, no status text.
            label.setText(f"v{current}")

    def _refresh_channel_indicator(self) -> None:
        """Update the status-bar channel label to reflect AppSettings.get_active_channel()."""
        if getattr(self, "_channel_indicator", None) is None:
            return
        self._channel_indicator.setText(tr("status_bar.channel_indicator", channel=AppSettings.get_active_channel()))

    def _sync_canonical_source_paths(self, context: str) -> None:
        """Mirror canonical file-backed source paths into QSettings."""
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
                    f"Re-synced {source_name} source path {context}: "
                    f"{stored or '(unset)'} → {canonical}"
                )

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
        self._sync_canonical_source_paths(f"for channel {channel}")

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
            self.statusBar().showMessage(
                tr("status_bar.channel_switched_extracting", channel=channel)
            )
            return

        # base.ini is present and fresh for the new channel. Check whether
        # the channel's DataForge cache is stale relative to its p4k and
        # offer to re-extract if so (background — doesn't block reload).
        self._maybe_prompt_dataforge_refresh()

        self.statusBar().showMessage(tr("status_bar.channel_switched_reloading", channel=channel))
        self.perform_merge_and_reload()

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self.setWindowTitle(tr("window.title", version=get_version()))
        self.title_label.setText(tr("branding.title"))
        self.tagline_label.setText(tr("branding.tagline"))

        # Tab bar
        self.tabs.setTabText(self._strings_tab_index, tr("tabs.string_editor"))
        self.tabs.setTabText(self._config_tab_index, tr("tabs.config"))
        self.tabs.setTabText(self._enhancements_tab_index, tr("tabs.enhancements"))
        self.tabs.setTabText(self._blueprint_tracker_tab_index, tr("tabs.blueprint_tracker"))
        self.tabs.setTabText(self._log_tab_index, tr("tabs.log"))
        self.tabs.setTabText(self._about_tab_index, tr("tabs.about"))
        self.tabs.setTabText(self._faq_tab_index, tr("tabs.faq"))
        self.tabs.setTabText(self._legal_tab_index, tr("tabs.legal"))

        # Toolbar buttons
        self.apply_btn.setText(tr("toolbar.apply_btn"))
        self._set_apply_btn_dirty(self._apply_dirty)
        self.editor_btn.setText(tr("toolbar.editor_btn"))
        self.editor_btn.setToolTip(tr("toolbar.editor_tooltip"))
        self.help_btn.setText(tr("toolbar.help_btn"))
        self.help_btn.setToolTip(tr("toolbar.help_tooltip"))
        self.tutorial_btn.setText(tr("toolbar.tutorial_btn"))
        self.tutorial_btn.setToolTip(tr("toolbar.tutorial_tooltip"))
        self.more_btn.setText(tr("toolbar.more_btn"))
        self.more_btn.setToolTip(tr("toolbar.more_tooltip"))

        # More-menu actions
        self._action_restore_backup.setText(tr("toolbar.restore_backup_btn"))
        self._action_restore_backup.setToolTip(tr("toolbar.restore_backup_tooltip"))
        self._action_clear_loc.setText(tr("toolbar.menu_clear_localization"))
        self._action_clear_cache.setText(tr("toolbar.menu_clear_cache"))
        self._action_import_ini.setText(tr("toolbar.menu_import_ini"))
        self._action_export_ini.setText(tr("toolbar.menu_export_ini"))
        self._action_open_loc_dir.setText(tr("toolbar.open_loc_dir_btn"))
        self._action_test_plan.setText(tr("toolbar.menu_test_plan"))
        self._action_test_plan.setToolTip(tr("toolbar.test_plan_tooltip"))
        self._action_switch_to_simple.setText(tr("toolbar.menu_switch_to_simple"))
        self._action_switch_to_simple.setToolTip(tr("toolbar.switch_to_simple_tooltip"))

        # Footer
        self.osiris_button.setToolTip(tr("toolbar.osiris_github_tooltip"))
        self.feedback_label.setToolTip(tr("toolbar.feedback_tooltip"))

        # Simple-mode page (#180)
        self.simple_page.retranslate_ui()

        # Filter row
        self._category_label.setText(tr("filters.category_label"))
        self.category_combo.setToolTip(tr("filters.category_tooltip"))
        self._status_label.setText(tr("filters.status_label"))
        self.status_combo.setToolTip(tr("filters.status_tooltip"))
        self.hide_unmodified_check.setText(tr("filters.hide_unmodified"))
        self.hide_unmodified_check.setToolTip(tr("filters.hide_unmodified_tooltip"))
        self.favorites_only_check.setText(tr("filters.favorites_only"))
        self.favorites_only_check.setToolTip(tr("filters.favorites_only_tooltip"))
        self.bp_titles_check.setText(tr("filters.bp_titles_only"))
        self.bp_titles_check.setToolTip(tr("filters.bp_titles_only_tooltip"))
        self.bp_descs_check.setText(tr("filters.bp_descs_only"))
        self.bp_descs_check.setToolTip(tr("filters.bp_descs_only_tooltip"))
        self.grouped_sort_btn.setText(tr("filters.group_sort_btn"))
        self.grouped_sort_btn.setToolTip(tr("filters.group_sort_tooltip"))
        self.clear_filters_btn.setText(tr("filters.clear_filters_btn"))
        self.clear_filters_btn.setToolTip(tr("filters.clear_filters_tooltip"))
        self.copy_filtered_btn.setText(tr("filters.copy_filtered_btn"))
        self.copy_filtered_btn.setToolTip(tr("filters.copy_filtered_tooltip"))

        # Status combo display text (userData internal values are preserved)
        self.status_combo.blockSignals(True)
        try:
            for i, (_internal, _key) in enumerate([
                ("All",        "filters.status_all"),
                ("Modified",   "filters.status_modified"),
                ("Enhanced",   "filters.status_enhanced"),
                ("Unmodified", "filters.status_unmodified"),
                ("New",        "filters.status_new"),
            ]):
                self.status_combo.setItemText(i, tr(_key))
        finally:
            self.status_combo.blockSignals(False)

        # Table column headers and filter placeholder text
        new_column_names = [
            tr("strings_tab.col_category"),
            tr("strings_tab.col_key"),
            tr("strings_tab.col_default_value"),
            tr("strings_tab.col_current_value"),
            tr("strings_tab.col_star"),
            tr("strings_tab.col_order"),
            tr("strings_tab.col_custom_value"),
            tr("strings_tab.col_status"),
            tr("strings_tab.col_owned"),
        ]
        self.filter_header.update_column_names(new_column_names)
        self._model.retranslate()

        # Preview pane placeholder
        self.preview_pane.setPlaceholderText(tr("strings_tab.preview_placeholder"))

        # Status label (only update if no data is loaded — otherwise it shows row count)
        if not self.entries:
            self.table_status_label.setText(tr("strings_tab.no_data"))

        # Side-docked String Editor (built lazily on first use — skip if never opened)
        if getattr(self, "editor_dock", None) is not None:
            self.editor_dock.setWindowTitle(tr("strings_tab.editor_dock_title"))
            self._editor_underline_btn.setText(tr("strings_tab.editor_underline_btn"))
            self._editor_underline_btn.setToolTip(tr("strings_tab.editor_underline_tooltip"))
            self._editor_highlight_btn.setText(tr("strings_tab.editor_highlight_btn"))
            self._editor_highlight_btn.setToolTip(tr("strings_tab.editor_highlight_tooltip"))
            self.editor_dock_text.setPlaceholderText(tr("strings_tab.editor_placeholder"))
            # Only reset the key label if it's still showing the empty-state
            # text — a real row's key is the current content otherwise, and
            # that shouldn't be clobbered by a language switch.
            if self._editor_dock_entry_idx is None:
                self.editor_dock_key_label.setText(tr("strings_tab.no_row_selected"))

        # Side-docked Test Plan (built lazily on first use — skip if never opened)
        if getattr(self, "test_plan_dock", None) is not None:
            self.test_plan_dock.setWindowTitle(tr("toolbar.menu_test_plan"))
            self.test_plan_panel.retranslate_ui()

        # Footer donation fallback text (only set when the image asset failed
        # to load — leave pixmap-backed buttons alone).
        if self.feedback_label.pixmap() is None or self.feedback_label.pixmap().isNull():
            self.feedback_label.setText(tr("toolbar.feedback_fallback_text"))
        if self.paypal_button.pixmap() is None or self.paypal_button.pixmap().isNull():
            self.paypal_button.setText(tr("toolbar.paypal_fallback_text"))
        if self.venmo_button.pixmap() is None or self.venmo_button.pixmap().isNull():
            self.venmo_button.setText(tr("toolbar.venmo_fallback_text"))

        # Cascade to child tabs
        self.config_tab.retranslate_ui()
        self.enhancements_tab.retranslate_ui()
        self.blueprint_tracker_tab.retranslate_ui()

        # Status-bar version indicator + Config-tab update status hold the
        # last update-check result; re-render them in the new language
        # (after the cascade so this write wins).
        self._refresh_update_indicator_texts()
        self._refresh_channel_indicator()
        self.log_tab.retranslate_ui()

    @pyqtSlot(str)
    def _on_language_changed(self, language: str) -> None:
        """Handle a language switch from the Config tab."""
        if self._loader_worker is not None and self._loader_worker.isRunning():
            logger.info("Language switch: cancelling in-flight FileLoaderWorker")
            try:
                self._loader_worker.finished.disconnect(self._on_loading_finished)
                self._loader_worker.error.disconnect(self._on_loading_error)
            except (TypeError, RuntimeError):
                pass
            self._loader_worker.quit()
            self._loader_worker.wait(5000)
            self._loader_worker = None
            if self._loading_progress is not None:
                self._loading_progress.close()
                self._loading_progress = None
        from src.utils import i18n
        i18n.set_language(language)
        logger.info(f"MainWindow reacting to language change → {language}")
        self.retranslate_ui()
        self.statusBar().showMessage(tr("dialogs.language_changed_status", language=language))
        # Point the `global` base source at this language's base.ini (English
        # = the P4K extraction; other languages = a downloaded global.ini),
        # downloading it first if needed, then reload. See #30.
        self._apply_language_base_source(language)

    def _apply_language_base_source(self, language: str) -> None:
        """Repoint the `global` merge source at *language*'s base.ini, then
        reload. English uses the local P4K base.ini. Other languages use a
        per-language download; if a mapped URL exists we fetch it (freshness-
        checked), otherwise we fall back to any cached copy or to English.
        """
        english_base = AppSettings.get_base_ini_path(AppSettings.DEFAULT_LANGUAGE)

        if language == AppSettings.DEFAULT_LANGUAGE:
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(english_base))
            self._show_loading_progress(tr("dialogs.merging_sources"))
            return

        dest = AppSettings.get_base_ini_path(language)
        url = AppSettings.get_language_base_url(language)

        if not url:
            # No URL mapped for this language. Use a cached copy if we have one,
            # otherwise fall back to the English base so the table still loads.
            if dest.exists():
                AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(dest))
                self._reload_with_language_enhancements(language)
            else:
                logger.warning(f"No base.ini URL mapped for {language!r}; using English base.")
                AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(english_base))
                self.statusBar().showMessage(
                    tr("dialogs.language_no_url", language=language)
                )
                self._show_loading_progress(tr("dialogs.merging_sources"))
            return

        # Have a URL — download (freshness-checked) on a worker, then repoint.
        dialog = AnimatedProgressDialog(
            tr("dialogs.language_downloading", language=language),
            parent=self, title=tr("dialogs.app_title"),
        )
        self._lang_dl_worker = LanguageBaseDownloadWorker(url, dest)
        self._lang_dl_worker.finished.connect(
            lambda ok, lang=language, d=dest, dlg=dialog: self._on_language_base_ready(lang, d, dlg, ok)
        )
        self._lang_dl_worker.start()

    def _on_language_base_ready(self, language: str, dest, dialog, ok: bool) -> None:
        """Finish a language switch once its base.ini download settled."""
        if dialog is not None:
            dialog.close()
        if self._lang_dl_worker is not None:
            self._lang_dl_worker.quit()
            self._lang_dl_worker.wait()
            self._lang_dl_worker = None

        if dest.exists():
            # Downloaded fresh, or a usable cached copy is already present.
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, str(dest))
            self._reload_with_language_enhancements(language)
        else:
            # Download failed and nothing cached — fall back to English so the
            # app stays usable, and tell the user.
            logger.warning(f"{language!r} base.ini unavailable; falling back to English base.")
            AppSettings.set_source_path(
                AppSettings.SOURCE_GLOBAL,
                str(AppSettings.get_base_ini_path(AppSettings.DEFAULT_LANGUAGE)),
            )
            QMessageBox.warning(
                self, tr("dialogs.app_title"),
                tr("dialogs.language_download_failed", language=language),
            )
            self._show_loading_progress(tr("dialogs.merging_sources"))

    def _language_enhancements_fresh(self, language: str) -> bool:
        """True if *language*'s enhancement files are present and were built
        against the current DataForge extraction.

        Stale (or absent) means the generator must re-run before the reload so
        the table shows this language's prose with up-to-date English stat
        blocks. With no enhancement categories enabled there is nothing to
        generate, so the answer is trivially fresh.
        """
        enabled = AppSettings.get_enabled_enhancement_categories()
        if not enabled:
            return True
        stamp = AppSettings.get_enhancements_stamp(language)
        if not stamp or stamp != AppSettings.get_dataforge_build_key():
            return False
        enh_dir = AppSettings.get_enhancements_dir(language)
        for label in enabled:
            filename = AppSettings.ENHANCEMENTS_FILES.get(label)
            if filename and not (enh_dir / filename).exists():
                return False
        return True

    def _reload_with_language_enhancements(self, language: str) -> None:
        """Reload after a language switch, regenerating that language's
        enhancements first when they are missing or stale.

        Fresh (or nothing to generate) → reload straight away. Stale and a
        DataForge cache is present → run the generator for this language; its
        finished handler triggers the reload. Stale but no DataForge cache →
        reload the language prose alone (degraded, no stat blocks) since stats
        can't be generated without an extraction.
        """
        if self._language_enhancements_fresh(language):
            self._show_loading_progress(tr("dialogs.merging_sources"))
            return

        records = (
            AppSettings.get_dataforge_cache_dir()
            / "raw" / "libs" / "foundry" / "records"
        )
        if not records.exists():
            logger.warning(
                f"{language!r} enhancements are stale/missing but no DataForge "
                "cache is present; loading language prose without stat overlays."
            )
            self._show_loading_progress(tr("dialogs.merging_sources"))
            return

        logger.info(f"Regenerating enhancements for {language!r} against its base.ini")
        self.statusBar().showMessage(
            tr("dialogs.language_generating_enhancements", language=language)
        )
        self._run_enhancements_generation(language=language)

    @pyqtSlot(str)
    def _on_data_dir_changed(self, data_dir: str) -> None:
        """Reload the app against a newly selected Smart Citizen data folder."""
        logger.info(f"MainWindow reacting to data folder change → {data_dir}")

        AppSettings.ensure_user_ini_file()
        self._sync_canonical_source_paths(f"for data folder {data_dir}")
        self.config_tab._refresh_p4k_status()
        if hasattr(self, "enhancements_tab"):
            self.enhancements_tab.refresh_enhancements_status()

        self._enhancements_prompted_on_startup = False

        if self._check_p4k_freshness():
            self.statusBar().showMessage(
                tr("status_bar.data_folder_changed_extracting", data_dir=data_dir)
            )
            return

        self._maybe_prompt_dataforge_refresh()
        self.statusBar().showMessage(
            tr("status_bar.data_folder_changed_reloading", data_dir=data_dir)
        )
        self.perform_merge_and_reload()

    @pyqtSlot(str)
    def _on_cache_dir_changed(self, new_cache_leaf: str) -> None:
        """Kick off a DataForge re-extraction against the new cache location.

        Config tab handles the user prompt + persists the override + queues
        the old cache for cleanup (via ``PENDING_CACHE_CLEANUP``). Our job is
        just to trigger the re-extract; ``_on_dataforge_extract_finished``
        drains the cleanup queue on success.
        """
        logger.info(f"MainWindow reacting to cache folder change → {new_cache_leaf}")
        self.statusBar().showMessage(
            tr("status_bar.cache_folder_changed")
        )
        self._run_dataforge_extraction()

    def _cleanup_pending_old_cache(self) -> None:
        """Remove the orphaned old cache directory queued by the Config tab.

        Called from ``_on_dataforge_extract_finished`` after a successful
        re-extract. No-op when nothing is queued. Failure to delete is
        logged but doesn't surface as an error — the user can always remove
        the orphan manually, and partial cleanup is preferable to blocking
        the post-extract reload flow.
        """
        queued = AppSettings.get_pending_cache_cleanup()
        if not queued:
            return
        old_path = Path(queued)
        # Clear the setting first — even if rmtree fails partway, we don't
        # want to retry it on every subsequent extraction and stomp on a
        # half-deleted tree.
        AppSettings.set_pending_cache_cleanup(None)
        if not old_path.exists():
            logger.info(f"Queued cache cleanup target already absent: {old_path}")
            return
        try:
            # robust_rmtree (not a raw shutil.rmtree) so this survives both
            # transient Windows locks and a deep old cache path past the
            # 260-char MAX_PATH (long-path-wraps internally — see
            # win_paths.win_long_path).
            from src.utils.pak_extractor import robust_rmtree
            robust_rmtree(old_path)
            logger.info(f"Removed old DataForge cache at {old_path}")
        except Exception as e:
            logger.warning(
                f"Could not remove old DataForge cache at {old_path}: {e}. "
                "Delete it manually if you want to reclaim the disk space."
            )

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
            entry_info = tr("status_bar.entry_count", count=f"{len(self.entries):,}")
            if modified_count:
                entry_info += tr("status_bar.override_count_suffix", count=modified_count)
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
            parts.append(tr("status_bar.manifest_missing", channel=active_channel))

        if parts:
            self.statusBar().showMessage("  |  ".join(parts))
        elif not self._has_long_running_worker():
            # Don't overwrite a progress message with "Ready" while a worker
            # is still running — the user reads the empty state as "done".
            self.statusBar().showMessage(tr("progress.ready"))

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

        self.statusBar().showMessage(tr("status_bar.starting_up"))
        self._startup_progress = AnimatedProgressDialog(
            tr("progress.syncing_sources"), parent=self, title=tr("progress.starting_up_title")
        )
        self._startup_sync_worker = StartupSyncWorker()
        self._startup_sync_worker.source_starting.connect(self._on_startup_source_starting)
        self._startup_sync_worker.source_synced.connect(self._on_startup_source_synced)
        self._startup_sync_worker.source_error.connect(self._on_startup_source_error)
        self._startup_sync_worker.finished.connect(self._on_startup_sync_finished)
        self._startup_sync_worker.start()

    @pyqtSlot(str)
    def _on_startup_source_starting(self, source_name: str):
        self.statusBar().showMessage(tr("status_bar.syncing_source", source_name=source_name))
        if self._startup_progress is not None:
            self._startup_progress.setLabelText(tr("status_bar.syncing_source", source_name=source_name))

    @pyqtSlot(str, bool)
    def _on_startup_source_synced(self, source_name: str, updated: bool):
        action = "updated" if updated else "up to date"
        logger.info(f"Startup sync: {source_name} {action}")
        label = tr("status_bar.source_updated") if updated else "✓"
        self._set_source_status(source_name, f"{source_name.title()}: {label}")

    @pyqtSlot(str, str)
    def _on_startup_source_error(self, source_name: str, message: str):
        logger.warning(f"Startup sync error ({source_name}): {message}")
        self._set_source_status(source_name, f"{source_name.title()}: ⚠ {tr('status_bar.source_offline')}")

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

        # If there's no SC path and no cached base.ini, guide the user
        # to the Config tab rather than loading (which would just error).
        base_ini = AppSettings.get_cache_dir() / "base.ini"
        if not base_ini.exists() and not AppSettings.get_sc_install_root():
            QMessageBox.information(
                self,
                tr("extract.path_required_title"),
                tr("extract.path_required_body"),
            )
            # Switch to Config tab so the user lands in the right place.
            config_idx = self.tabs.indexOf(self.config_tab)
            if config_idx >= 0:
                self.tabs.setCurrentIndex(config_idx)
            return

        # Prompt user to extract from p4k if base.ini is missing or outdated
        p4k_extraction_started = self._check_p4k_freshness()

        # If P4K extraction was started, don't load files yet.
        # The P4K extraction finished handler will do the loading.
        if p4k_extraction_started:
            return

        # User declined the extraction prompt (or it didn't fire, e.g. unp4k
        # missing) and there's still no cached base.ini. Loading sources now
        # would just fail with "file not found" — skip it instead of
        # surfacing error popups for a state the user just chose to leave.
        if not base_ini.exists():
            self.statusBar().showMessage(tr("status_bar.no_strings_loaded"))
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
            msg = tr("extract.p4k_prompt_base_missing")
        else:
            msg = tr("extract.p4k_prompt_p4k_newer")

        reply = QMessageBox.question(
            self, tr("extract.p4k_prompt_title"), msg,
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
        from src.utils.pak_extractor import P4K_MTIME_STAMP, dataforge_cache_is_fresh

        if self._forge_worker is not None or self._enhancements_worker is not None:
            return
        p4k_path = AppSettings.get_p4k_path()
        unp4k_exe = AppSettings.get_unp4k_exe_path()
        unforge_exe = AppSettings.get_unforge_exe_path()
        if not p4k_path.exists() or not unp4k_exe.exists() or not unforge_exe.exists():
            return
        forge_dir = AppSettings.get_dataforge_cache_dir()
        if not (forge_dir / P4K_MTIME_STAMP).exists():
            # Never extracted — handled later by _check_enhancements_freshness,
            # which shows a richer category-selection dialog.
            return
        if dataforge_cache_is_fresh(p4k_path, forge_dir):
            return

        reply = QMessageBox.question(
            self, tr("extract.dataforge_outdated_title"),
            tr("extract.dataforge_outdated_body"),
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
        dialog.setWindowTitle(tr("extract.generate_dialog_title"))
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)

        n = len(missing_checkbox_keys)
        noun = tr("extract.category_singular") if n == 1 else tr("extract.category_plural")
        layout.addWidget(QLabel(tr("extract.missing_categories_body", count=n, noun=noun)))

        layout.addSpacing(8)

        checkboxes: dict[str, QCheckBox] = {}
        for key, label in AppSettings.ENHANCEMENT_LABELS.items():
            cb = QCheckBox(label)
            if key in missing_checkbox_keys:
                cb.setChecked(True)
                cb.setText(tr("extract.missing_category_label", label=label))
            else:
                cb.setChecked(False)
            checkboxes[key] = cb
            layout.addWidget(cb)

        layout.addSpacing(8)

        info = QLabel(tr("extract.dataforge_auto_extract_note"))
        info.setProperty("role", "secondary")
        info.setStyleSheet("font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addSpacing(8)

        button_row = QHBoxLayout()
        generate_btn = QPushButton(tr("extract.generate_btn"))
        generate_btn.setDefault(True)
        generate_btn.setToolTip(tr("dialogs.generate_now_tooltip"))
        skip_btn = QPushButton(tr("extract.skip_btn"))
        skip_btn.setToolTip(tr("dialogs.skip_generate_tooltip"))

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

        # Preserve in-memory edits the user hasn't Applied yet — Generate
        # Enhancements (and other reload paths) hit this slot with freshly
        # loaded entries whose custom_value comes only from user.ini, so
        # any un-saved edits would be silently dropped without this.
        pending_edits = self._snapshot_pending_user_edits()
        restored = self._restore_pending_user_edits(entries, pending_edits)
        if restored:
            logger.info(f"Restored {restored} in-memory user edits not yet persisted to user.ini")

        self.default_values = default_values
        self.entries = entries
        if not entries and default_values is not None:
            # Sources were configured but produced no entries — most likely the
            # base.ini hasn't been extracted yet (fresh install) or source files
            # are missing on disk. Surface this so the user isn't left with a
            # silently blank table and no indication of why.
            logger.warning("Load completed with 0 entries — source files may be missing; try extracting from Data.p4k")
            self.statusBar().showMessage(tr("status_bar.no_strings_loaded"))
        self.update_category_combo()

        # Push data into the model — the view renders only visible rows, so this is instant
        self._model.set_data_source(
            self.entries,
            self.default_values,
            AppSettings.get_favorite_prefix(),
            sort_keys=sort_keys,
        )
        self.apply_filters()
        self._rebuild_blueprint_metadata()  # #157 follow-up: filter data
        self._recompute_owned()  # #157: weave [Owned] tags + populate Owned stars

        # Update status bar with entry counts and per-source status
        self._update_status_bar()

        # If enhancements check was deferred during startup, do it now (after file loading completes)
        # This avoids concurrent I/O contention between file loader and enhancements generator
        if self._check_enhancements_after_loading:
            self._check_enhancements_after_loading = False
            self._check_enhancements_freshness()

        # From here on, dirty-marking reflects a real in-session change —
        # see _mark_apply_dirty / _session_has_unapplied_edit.
        self._initial_load_done = True

    @pyqtSlot(str)
    def _on_loading_error(self, error_msg: str):
        """Handle file loading error."""
        self._loading_progress.close()
        self._loading_progress = None
        QMessageBox.critical(self, tr("dialogs.error_title"), tr("dialogs.failed_to_load_sources", error=error_msg))
        if self._loader_worker:
            self._loader_worker.quit()
            self._loader_worker.wait()
            self._loader_worker = None

    def _run_simple_apply(self):
        """Simple-mode one-button flow (#180): generate enhancements, then apply.

        Reuses the existing async pipeline (extract → generate) and the
        existing ``apply_to_game`` (backup / validate / rollback). Sets a flag
        so ``_on_enhancements_generation_finished`` continues into the apply
        once generation completes; this adds one continuation, not a parallel
        pipeline.
        """
        if self._enhancements_worker is not None or self._forge_worker is not None:
            return  # already running

        # Applying needs the game folder, but Config (where it's set) is hidden
        # in Simple mode — so guide the user to Advanced rather than no-op.
        if not AppSettings.get_game_install_path():
            QMessageBox.information(
                self, tr("simple_mode.set_game_folder_title"),
                tr("simple_mode.set_game_folder_body"),
            )
            self._apply_ui_mode(AppSettings.UI_MODE_ADVANCED)
            self.tabs.setCurrentIndex(self._config_tab_index)
            return

        reply = QMessageBox.question(
            self, tr("simple_mode.apply_enhancements_confirm_title"),
            tr("simple_mode.apply_enhancements_confirm_body"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._simple_run_active = True
        self.simple_page.set_busy(True)
        self._run_enhancements_pipeline()

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

    def _run_enhancements_generation(self, categories: set[str] | None = None,
                                     language: str | None = None):
        """Launch EnhancementsGeneratorWorker in the background with animated progress dialog.

        *language* selects which language's base.ini to generate against
        (None = the currently selected language). Resolved here on the main
        thread and handed to the worker as a concrete value so a mid-run
        language switch can't change what the worker is generating.
        """
        if self._enhancements_worker is not None:
            # Defensive: if extraction handed off but a stale enhancements
            # worker is somehow still around, don't orphan the forge dialog.
            stale = getattr(self, "_forge_progress_dialog", None)
            if stale is not None:
                stale.close()
                self._forge_progress_dialog = None
            return  # already running

        # Use enabled categories from settings if none specified
        if categories is None:
            categories = AppSettings.get_enabled_enhancement_categories()
        if language is None:
            language = AppSettings.get_selected_language()

        # Tag-builder config (issue #31): read once here on the main thread
        # and hand the worker a plain dict, so the generator's worker
        # thread/subprocess never touches a live QSettings handle. Same
        # rule for the mission-desc annotation toggle.
        tag_configs = AppSettings.get_all_tag_configs()
        annotate_mission_descs = AppSettings.get_tag_annotate_mission_descs()

        self._enhancements_worker = EnhancementsGeneratorWorker(
            categories=categories, tag_configs=tag_configs,
            annotate_mission_descs=annotate_mission_descs,
            rep_xp_label=AppSettings.get_rep_xp_label(),
            mission_headers=AppSettings.get_mission_headers(),
            mission_header_em_tag=AppSettings.get_mission_header_em_tag(),
            mission_detail_fields=AppSettings.get_mission_detail_fields(),
            mission_title_tags=AppSettings.get_mission_title_tags(),
            stats_prepend=AppSettings.get_stats_prepend(),
            standardize_earnable_ship_names=AppSettings.get_standardize_earnable_ship_names(),
            language=language,
        )
        self.enhancements_tab.set_operation_running(tr("enhancements.generating_enhancements_tooltip"))
        self.statusBar().showMessage(tr("status_bar.generating_enhancements_background"))

        enhancements_label = tr("progress.enhancements_label")

        # Reuse the DataForge extraction dialog if it's still open — keeps
        # the progress UI continuous through the extraction → enhancements
        # chain so the user doesn't see a "where did the progress bar go?"
        # gap between the snapshot completing and a fresh dialog opening.
        # Falls back to a new dialog when called standalone (e.g. from
        # the Enhancements tab's Generate button).
        existing = getattr(self, "_forge_progress_dialog", None)
        if existing is not None:
            self._enhancements_progress_dialog = existing
            self._forge_progress_dialog = None
            existing.setWindowTitle(tr("progress.generating_enhancements_title"))
            # Reset bar to indeterminate (0,0) with the new label so the
            # stale "Snapshotting cache (28000/28000)" 100% bar from the
            # extraction phase doesn't sit on screen until the first
            # enhancement progress emit lands.
            existing.set_progress(0, 0, enhancements_label)
        else:
            self._enhancements_progress_dialog = AnimatedProgressDialog(
                enhancements_label,
                parent=self,
                title=tr("progress.generating_enhancements_title"),
            )

        self._enhancements_worker.progress.connect(self.statusBar().showMessage)
        self._enhancements_worker.progress.connect(self._enhancements_progress_dialog.setLabelText)
        self._enhancements_worker.progress_pct.connect(self._enhancements_progress_dialog.set_progress)
        self._enhancements_worker.error.connect(self._on_enhancements_generation_error)
        self._enhancements_worker.finished.connect(self._on_enhancements_generation_finished)
        self._enhancements_worker.start()

    def _end_simple_run(self):
        """End the Simple-mode one-button flow: clear the active flag and let
        the Simple page leave its busy state. Idempotent — safe to call when no
        Simple run is in progress (both are already idle)."""
        self._simple_run_active = False
        self.simple_page.set_busy(False)

    def _on_enhancements_generation_error(self, message: str):
        logger.error(f"Enhancements generation error: {message}")
        # #180: abandon any in-flight Simple-mode flow so it doesn't apply.
        self._end_simple_run()
        # Close progress dialog on error
        if self._enhancements_progress_dialog is not None:
            self._enhancements_progress_dialog.close()
            self._enhancements_progress_dialog = None

    def _on_enhancements_generation_finished(self, success: bool):
        # Close progress dialog
        if self._enhancements_progress_dialog is not None:
            self._enhancements_progress_dialog.close()
            self._enhancements_progress_dialog = None

        self._enhancements_worker.quit()
        self._enhancements_worker.wait()
        self._enhancements_worker = None
        self.enhancements_tab.set_operation_idle(success)
        self.enhancements_tab.refresh_enhancements_status()

        if success:
            # #180: Simple-mode one-button flow continues into apply here.
            # apply_to_game is synchronous and re-loads sources from disk, so
            # the just-written enhancement INIs are picked up; the table reload
            # below keeps the (hidden) Advanced view consistent afterward.
            if self._simple_run_active:
                self._end_simple_run()
                self.statusBar().showMessage(tr("status_bar.enhancements_generated_applying"))
                self.apply_to_game()
            else:
                self.statusBar().showMessage(tr("status_bar.enhancements_generated_reloading"))
            self._show_loading_progress(tr("progress.reloading_with_enhancements"))
        else:
            self._end_simple_run()
            self.statusBar().showMessage(tr("status_bar.enhancement_generation_failed"))

    def _run_dataforge_extraction(self):
        """Launch DataForgeExtractWorker in the background (non-blocking)."""
        if self._forge_worker is not None:
            return

        p4k_path    = AppSettings.get_p4k_path()
        unp4k_exe   = AppSettings.get_unp4k_exe_path()
        unforge_exe = AppSettings.get_unforge_exe_path()
        forge_dir   = AppSettings.get_dataforge_cache_dir()

        self._forge_worker = DataForgeExtractWorker(p4k_path, unp4k_exe, unforge_exe, forge_dir)
        self.enhancements_tab.set_operation_running(tr("enhancements.extracting_dataforge_tooltip"))
        self.statusBar().showMessage(tr("extract.dataforge_extracting_background"))

        self._forge_progress_dialog = AnimatedProgressDialog(
            tr("extract.dataforge_extracting_label"),
            parent=self,
            title=tr("extract.dataforge_extraction_title"),
        )

        self._forge_worker.progress.connect(self.statusBar().showMessage)
        self._forge_worker.progress.connect(self._forge_progress_dialog.setLabelText)
        self._forge_worker.progress_pct.connect(self._forge_progress_dialog.set_progress)
        self._forge_worker.error.connect(self._on_dataforge_extract_error)
        self._forge_worker.finished.connect(self._on_dataforge_extract_finished)
        self._forge_worker.start()

    def _on_dataforge_extract_error(self, message: str):
        logger.error(f"DataForge extraction error: {message}")
        # #180: abandon any in-flight Simple-mode flow so it doesn't apply.
        self._end_simple_run()
        if getattr(self, "_forge_progress_dialog", None) is not None:
            self._forge_progress_dialog.close()
            self._forge_progress_dialog = None
        QMessageBox.warning(
            self, tr("extract.dataforge_extraction_error_title"),
            tr("extract.dataforge_extraction_error_body", message=message),
        )

    def _on_dataforge_extract_finished(self, success: bool):
        self._forge_worker.quit()
        self._forge_worker.wait()
        self._forge_worker = None
        self.enhancements_tab.refresh_forge_status()

        if success:
            # Drain any cache-dir-change cleanup queued by the Config tab.
            # The user picked "Re-extract and delete old" earlier; now that
            # the new location has a populated cache, the orphan can go.
            self._cleanup_pending_old_cache()
            # Hand the progress dialog off to the enhancements phase rather
            # than closing it here. Closing + re-opening leaves a visible
            # gap between the snapshot completing and the new dialog
            # appearing — long enough for users to wonder what the app is
            # doing. _run_enhancements_generation reuses the existing
            # dialog window if one is present, so the title/label change
            # is the only thing the user sees.
            self.statusBar().showMessage(tr("extract.dataforge_extracted_generating"))
            self._run_enhancements_generation()
        else:
            # #180: extraction failed, so the Simple-mode flow can't continue.
            self._end_simple_run()
            if getattr(self, "_forge_progress_dialog", None) is not None:
                self._forge_progress_dialog.close()
                self._forge_progress_dialog = None
            self.enhancements_tab.set_operation_idle(success=False)
            self.statusBar().showMessage(tr("extract.dataforge_extraction_failed"))

    def _run_p4k_extraction(self):
        """Launch P4kExtractWorker with a progress dialog; reload sources on success."""
        p4k_path = AppSettings.get_p4k_path()
        output_path = AppSettings.get_cache_dir() / 'base.ini'
        unp4k_exe = AppSettings.get_unp4k_exe_path()

        self._p4k_worker = P4kExtractWorker(p4k_path, output_path, unp4k_exe)
        self._p4k_progress = AnimatedProgressDialog(
            tr("extract.p4k_extracting_label"),
            parent=self,
            title=tr("extract.p4k_extraction_title")
        )

        self._p4k_worker.progress.connect(self._p4k_progress.setLabelText)
        self._p4k_worker.progress_pct.connect(self._p4k_progress.set_progress)
        self._p4k_worker.error.connect(lambda err: QMessageBox.warning(self, tr("extract.extraction_error_title"), err))
        self._p4k_worker.finished.connect(self._on_p4k_extract_finished)
        self._p4k_worker.start()

    def _on_p4k_extract_finished(self, success: bool):
        """Handle P4K extraction completion."""
        self._p4k_progress.close()
        self._p4k_worker.quit()
        self._p4k_worker.wait()
        self._p4k_worker = None

        if success:
            # Lock Global source to the local cache path with auto-update off,
            # so future startups don't overwrite the extracted file from a remote URL.
            local_path = str(AppSettings.get_cache_dir() / 'base.ini')
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, local_path)
            AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)
            # Refresh the config tab P4K status
            self.config_tab._refresh_p4k_status()

            # A fresh base.ini can change item names/descriptions (e.g. CIG
            # adding flavor text in a patch) without touching the DataForge
            # XML cache our dirty-check keys off — so a stale cached
            # enhancement entry for a changed item would otherwise never
            # prompt a re-run even after re-extracting global.ini.
            self.enhancements_tab.mark_enhancements_dirty()

            # Defer enhancements check until after file loading completes (avoid I/O contention)
            self._check_enhancements_after_loading = True

            # Show progress dialog while reloading with extracted data
            self._show_loading_progress("Reloading with extracted base.ini...")

    def closeEvent(self, event):
        """Save state and overrides before closing."""
        # Warn if something changed this session that Apply Enhancements
        # hasn't picked up yet (the button is still showing red) — e.g. the
        # user clicked Apply Tag Changes but never followed up with Apply
        # Enhancements. Gated on _session_has_unapplied_edit rather than
        # _apply_dirty directly since the latter also starts True at launch
        # (see its comment) — that boot-time uncertainty shouldn't nag a user
        # who hasn't touched anything this session.
        if self._session_has_unapplied_edit:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle(tr("dialogs.unapplied_changes_title"))
            box.setText(tr("dialogs.unapplied_changes_body"))
            apply_btn = box.addButton(
                tr("dialogs.unapplied_changes_apply_now"), QMessageBox.ButtonRole.AcceptRole
            )
            exit_btn = box.addButton(
                tr("dialogs.unapplied_changes_exit"), QMessageBox.ButtonRole.DestructiveRole
            )
            cancel_btn = box.addButton(QMessageBox.StandardButton.Cancel)
            box.setDefaultButton(apply_btn)
            box.exec()
            clicked = box.clickedButton()

            if clicked is cancel_btn:
                event.ignore()
                return
            if clicked is apply_btn:
                # Apply, then stay open — Apply to Game only updates
                # _apply_dirty in memory for this run; closing immediately
                # after would still start the *next* launch red regardless
                # (that boot-time default can't cheaply verify the game file
                # already matches — see _apply_dirty's comment), which read
                # as "my apply didn't work." Leaving the window open lets the
                # user see the button turn green and close normally whenever
                # they're ready.
                self.apply_to_game()
                event.ignore()
                return
            # exit_btn: fall through to the normal close sequence below,
            # exiting without applying.

        # Auto-save overrides if there are unsaved edits
        if self.entries and not (self._loader_worker and self._loader_worker.isRunning()):
            try:
                from src.utils.user_ini_manager import save_user_ini, should_autosave_user_ini
                user_ini_path = AppSettings.get_user_ini_path()
                if should_autosave_user_ini(self.entries, user_ini_path):
                    save_user_ini(self.entries, user_ini_path)
            except Exception as e:
                logger.error(f"Failed to auto-save overrides on exit: {e}")

        # Detach log handler before widgets are destroyed
        self.log_tab.remove_handler()

        # Clean up workers
        if self._loader_worker:
            self._loader_worker.quit()
            self._loader_worker.wait()

        # Persist only the dock/toolbar layout; window size is mode-driven and
        # recomputed on next launch (see _size_window_for_mode).
        AppSettings.set_window_state(self.saveState())

        event.accept()

    @timed
    def _filtered_entry_indices(self) -> list[int]:
        """Return indices into self.entries for entries passing the current filters.

        Reads UI state and delegates the actual filter loop to
        src.utils.entry_filter — kept Qt-aware here so the table can stay
        unaware of the extracted module's signature.
        """
        return _filter_entry_indices_impl(
            self.entries,
            self.default_values,
            self.filter_header.get_filter_texts(),
            self.category_combo.currentData() or self.category_combo.currentText(),
            self.status_combo.currentData() or "All",
            self.hide_unmodified_check.isChecked(),
            self.favorites_only_check.isChecked(),
            AppSettings.get_favorite_prefix(),
            bp_titles_only=self.bp_titles_check.isChecked(),
            bp_descs_only=self.bp_descs_check.isChecked(),
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
        self.category_combo.addItem(tr("filters.status_all"), userData="All")
        self.category_combo.addItems(categories)
        self.category_combo.blockSignals(False)

    def _entry_index_for_row(self, row: int) -> int:
        """Map a visual table row to an index into self.entries."""
        return self._model.entry_index_for_row(row)

    def _on_model_data_changed(self, top_left, bottom_right, _roles=None) -> None:
        """Keep the preview pane and editor dock in sync with model edits.

        Fires for every entry mutation routed through StringTableModel —
        inline cell edits, favorite-toggle, editor-dock typing, reset-to-
        original. Refreshes the preview if the changed range covers the
        currently-selected row, and refreshes the dock if it covers the
        entry the dock is currently tracking. Idempotent on both sides:
        when the change *originated* from the dock or the preview, the
        new value already matches what's on screen, so the refresh is a
        cheap no-op.
        """
        if not self.entries or not top_left.isValid():
            return

        self._mark_apply_dirty()

        # Preview: refresh if the selected row falls inside the changed range.
        sel_model = self.table.selectionModel() if hasattr(self, "table") else None
        if sel_model is not None:
            sel = sel_model.currentIndex()
            if sel.isValid() and top_left.row() <= sel.row() <= bottom_right.row():
                try:
                    entry = self.entries[self._entry_index_for_row(sel.row())]
                    raw = entry.custom_value or entry.original_value or ""
                    self.preview_pane.setHtml(
                        _render_preview_html(entry.key, raw, stamp=_journal_stamp_for_entry(entry))
                    )
                except (IndexError, AttributeError):
                    pass

        # Editor dock: refresh if the dock is tracking an entry whose row
        # falls inside the changed range. The dock's row is derived from
        # its entry index via the model's reverse lookup; if the entry
        # isn't currently visible in the filtered view there's no row to
        # check against, so fall back to a direct entry-index match.
        if (
            getattr(self, "editor_dock", None) is not None
            and self._editor_dock_entry_idx is not None
            and self._editor_dock_entry_idx < len(self.entries)
        ):
            dock_row = self._model.source_row_for_entry_index(self._editor_dock_entry_idx)
            if dock_row is None or top_left.row() <= dock_row <= bottom_right.row():
                entry = self.entries[self._editor_dock_entry_idx]
                raw = entry.custom_value if entry.custom_value else entry.original_value
                visual = (raw or "").replace("\\n", "\n")
                if visual != self.editor_dock_text.toPlainText():
                    self._editor_dock_loading = True
                    try:
                        self.editor_dock_text.setPlainText(visual)
                    finally:
                        self._editor_dock_loading = False
                self.editor_dock_status_label.setText(entry.status)

    def _on_preview_row_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        """Refresh the preview pane and editor dock when the selected row changes."""
        if not current.isValid() or not self.entries:
            self.preview_pane.clear()
            self._clear_editor_dock()
            return
        try:
            entry = self.entries[self._entry_index_for_row(current.row())]
        except (IndexError, AttributeError):
            self.preview_pane.clear()
            self._clear_editor_dock()
            return
        raw = entry.custom_value or entry.original_value or ""
        self.preview_pane.setHtml(
            _render_preview_html(entry.key, raw, stamp=_journal_stamp_for_entry(entry))
        )
        self._load_editor_dock_from_row(current.row())

    @pyqtSlot()
    def apply_filters(self):
        """Apply filters by updating the model's filtered index list."""
        if not self.entries:
            return
        indices = self._filtered_entry_indices()
        self._model.set_filtered_indices(indices)
        self.table_status_label.setText(tr("strings_tab.showing_count", shown=len(indices), total=len(self.entries)))

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
        self.bp_titles_check.blockSignals(True)
        self.bp_descs_check.blockSignals(True)

        self.filter_header.clear_all()
        self.category_combo.setCurrentIndex(0)
        self.status_combo.setCurrentIndex(0)
        self.hide_unmodified_check.setChecked(False)
        self.favorites_only_check.setChecked(False)
        self.bp_titles_check.setChecked(False)
        self.bp_descs_check.setChecked(False)

        self.category_combo.blockSignals(False)
        self.status_combo.blockSignals(False)
        self.hide_unmodified_check.blockSignals(False)
        self.favorites_only_check.blockSignals(False)
        self.bp_titles_check.blockSignals(False)
        self.bp_descs_check.blockSignals(False)

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
            QMessageBox.information(self, tr("dialogs.copy_filtered_title"), tr("dialogs.copy_filtered_empty"))
            return

        text_to_copy = "\n".join(lines)
        try:
            import pyperclip
            pyperclip.copy(text_to_copy)
            QMessageBox.information(self, tr("dialogs.copy_filtered_title"), tr("dialogs.copy_filtered_done", count=len(lines) - 1))
        except Exception as e:
            QMessageBox.warning(self, tr("dialogs.copy_error_title"), tr("dialogs.copy_error_body", error=e))

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
        menu.addAction(tr("strings_tab.context_copy_cell"), lambda: self.copy_cell(proxy_index))
        menu.addAction(tr("strings_tab.context_copy_key"), lambda: self.copy_key(proxy_row))
        menu.addSeparator()
        menu.addAction(tr("strings_tab.context_edit"), lambda: self.edit_cell(proxy_row))
        menu.addAction(tr("strings_tab.context_reset_to_original"), lambda: self.reset_to_original(proxy_row))
        menu.addSeparator()
        menu.addAction(tr("strings_tab.context_copy_all_filtered"), lambda: self.copy_filtered_to_clipboard())

        if entry.category == "Ships":
            menu.addSeparator()
            if is_favorite:
                menu.addAction(tr("strings_tab.context_remove_favorite"), lambda: self.toggle_favorite(proxy_row))
            else:
                menu.addAction(tr("strings_tab.context_add_favorite"), lambda: self.toggle_favorite(proxy_row))

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
            import pyperclip
            try:
                pyperclip.copy(text)
            except Exception:
                pass

    def copy_key(self, proxy_row: int):
        """Copy key to clipboard."""
        entry_idx = self._entry_index_for_row(proxy_row)
        if entry_idx < len(self.entries):
            import pyperclip
            try:
                pyperclip.copy(self.entries[entry_idx].key)
                self.statusBar().showMessage(tr("strings_tab.copied_key", key=self.entries[entry_idx].key))
            except ImportError:
                self.statusBar().showMessage(tr("strings_tab.pyperclip_missing"))

    @pyqtSlot(QModelIndex)
    def _on_cell_clicked(self, proxy_index: QModelIndex):
        """Handle cell clicks — COL_STAR toggles favorite (Ships).

        The Owned column (COL_OWNED) is a read-only indicator: ownership is now
        managed by the Blueprint Tracker tab, not by clicking the star here.
        """
        col = proxy_index.column()
        if col == COL_STAR:
            entry_idx = self._entry_index_for_row(proxy_index.row())
            if entry_idx < len(self.entries) and self.entries[entry_idx].category == "Ships":
                self.toggle_favorite(proxy_index.row())

    @pyqtSlot(QModelIndex)
    def _on_cell_double_clicked(self, proxy_index: QModelIndex):
        """Double-click on Current Value copies it to Custom Value and opens
        the Custom Value cell for editing with the cursor at the start."""
        if proxy_index.column() != COL_CURRENT:
            return
        entry_idx = self._entry_index_for_row(proxy_index.row())
        if entry_idx >= len(self.entries):
            return
        entry = self.entries[entry_idx]
        current_value = entry.original_value or ""
        if not current_value:
            return
        entry.custom_value = current_value
        entry.status = "Modified"
        self._model.notify_entry_changed(entry_idx)
        # Open the Custom Value editor with cursor at the beginning
        self._custom_value_delegate.set_cursor_at_start(True)
        custom_index = self._model.index(proxy_index.row(), COL_CUSTOM)
        self.table.setCurrentIndex(custom_index)
        self.table.edit(custom_index)

    def _rebuild_blueprint_metadata(self):
        """#157 follow-up: scan loaded strings once to build the blueprint-item
        metadata (eligible names + per-item mission/type/class/size/grade) the
        Blueprints shuttle filters on. Pure function of the loaded strings, so
        it runs on load — not on every owned-toggle (that path re-partitions
        the cached result)."""
        from src.utils.blueprint_meta import build_blueprint_metadata
        self._blueprint_meta = build_blueprint_metadata(self.entries)
        self._bp_item_names = set(self._blueprint_meta)

    def _recompute_owned(self):
        """#157: weave/strip [Owned] tags on blueprint-list bullets to match the
        owned set and refresh the table. Called after every load and on every
        Owned change; the transform is idempotent so repeated runs never double
        the tag. The eligible-name set + filter metadata are built separately by
        `_rebuild_blueprint_metadata` (cached, not rescanned here)."""
        from src.utils.owned_items import apply_owned_to_value
        owned = AppSettings.get_owned_items()
        for e in self.entries:
            new_val = apply_owned_to_value(e.original_value, owned)
            if new_val != e.original_value:
                e.original_value = new_val
        self._model.set_owned_state(self._bp_item_names, owned)
        # Feed the blueprint metadata to the Blueprint Tracker tab (it can't
        # see the loaded strings the data is derived from).
        if hasattr(self, "blueprint_tracker_tab"):
            self.blueprint_tracker_tab.set_blueprint_items(self._blueprint_meta)
        # Called after every reload (category/tag/enhancements apply, channel
        # and language switches, import, restore) and every Owned-set change
        # — in every case Apply to Game's output could now differ.
        self._mark_apply_dirty()

    def _on_apply_owned_tags_clicked(self):
        """Manual "Apply Owned Tags" button: force a re-weave on demand
        instead of relying on it happening as a side effect of moving an
        item between the Available/Owned lists or a log scan."""
        self._recompute_owned()
        self.statusBar().showMessage(tr("blueprint_tracker.owned_tags_refreshed"))

    def _run_blueprint_log_scan(self):
        """Scan the active channel's SC logs for received-blueprint events and
        fold them into the owned set. Launched by the Blueprint Tracker tab's
        "BP Scan" button; runs in a background worker with a progress dialog.

        Reads Game.log + logbackups/*.log from the active channel's install
        dir for "Received Blueprint" reward notifications — the game's own
        record of every blueprint the player has actually earned, independent
        of whether it's shown up in a loaded mission's reward text yet. Only
        events newer than the last scan's watermark are imported (#222), so
        re-running the scan against a still-growing Game.log doesn't re-walk
        the player's whole history every time.
        """
        if self._bp_log_scan_worker is not None:
            return  # already scanning

        channel_path = AppSettings.get_channel_install_path()
        if not channel_path or not Path(channel_path).is_dir():
            QMessageBox.warning(
                self,
                tr("enhancements.bp_scan_title"),
                tr("enhancements.bp_scan_no_path"),
            )
            return

        since = AppSettings.get_blueprint_log_watermark()
        self._bp_log_scan_worker = BlueprintLogScanWorker(channel_path, since)
        self._bp_log_scan_progress = AnimatedProgressDialog(
            tr("enhancements.bp_scan_starting"),
            parent=self,
            title=tr("enhancements.bp_scan_title"),
        )
        self._bp_log_scan_worker.progress.connect(self.statusBar().showMessage)
        self._bp_log_scan_worker.progress.connect(self._bp_log_scan_progress.setLabelText)
        self._bp_log_scan_worker.progress_pct.connect(self._bp_log_scan_progress.set_progress)
        self._bp_log_scan_worker.error.connect(self._on_blueprint_log_scan_error)
        self._bp_log_scan_worker.finished.connect(self._on_blueprint_log_scan_finished)
        self._bp_log_scan_worker.start()

    def _on_blueprint_log_scan_error(self, message: str):
        logger.error(f"BP Scan failed: {message}")
        if self._bp_log_scan_progress is not None:
            self._bp_log_scan_progress.close()
            self._bp_log_scan_progress = None

    def _on_blueprint_log_scan_finished(self, result):
        """Fold a completed scan's names into the owned set and report.

        Owns all owned-set / watermark mutation (the worker stays read-only),
        so every settings write happens on the main thread. ``result`` is a
        ``ScanResult`` or ``None`` when the scan errored (already surfaced via
        ``_on_blueprint_log_scan_error``)."""
        if self._bp_log_scan_progress is not None:
            self._bp_log_scan_progress.close()
            self._bp_log_scan_progress = None
        self._reap_worker(self._bp_log_scan_worker)
        self._bp_log_scan_worker = None

        if result is None:
            return

        from src.utils.owned_items import normalize_item_name

        # Normalize raw log names to the shared owned-set identity; drop blanks.
        scanned = {normalize_item_name(n) for n in result.names}
        scanned.discard("")

        owned = AppSettings.get_owned_items()
        new_names = sorted(scanned - owned)

        # Advance the watermark even when nothing new was imported, so a
        # growing Game.log's already-seen events aren't reparsed next time.
        if result.latest_timestamp is not None:
            prev = AppSettings.get_blueprint_log_watermark()
            newest = result.latest_timestamp if prev is None else max(prev, result.latest_timestamp)
            AppSettings.set_blueprint_log_watermark(newest)

        if not new_names:
            QMessageBox.information(
                self,
                tr("enhancements.bp_scan_title"),
                tr("enhancements.bp_scan_none"),
            )
            return

        AppSettings.set_owned_items(owned | set(new_names))
        self._recompute_owned()
        self.blueprint_tracker_tab.mark_owned_dirty()

        # How many of the newly-added names are visible right now (i.e. appear
        # as a blueprint bullet in the currently-loaded data). The rest light up
        # automatically whenever their item next appears in a blueprint list.
        visible_now = len(set(new_names) & getattr(self, "_bp_item_names", set()))
        summary = tr(
            "enhancements.bp_scan_summary",
            count=len(new_names),
            visible=visible_now,
        )
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(tr("enhancements.bp_scan_title"))
        box.setText(summary)
        box.setDetailedText("\n".join(new_names))
        box.exec()

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
        """Restore the dock / toolbar layout.

        Window *size* is mode-driven (Simple opens compact, Advanced opens
        maximized — see _size_window_for_mode), so geometry is intentionally
        neither persisted nor restored; only the dock/toolbar arrangement is.
        """
        state = AppSettings.get_window_state()
        if state:
            self.restoreState(state)

    def markdown_to_html(self, markdown_text: str) -> str:
        """Convert markdown to HTML with theme-aware styling.

        Pulls colors from the application palette (stable even when called
        synchronously right after QApplication.setPalette — widget-local
        palettes can lag one event-loop tick behind the app palette) and
        delegates the conversion to src.gui.markdown_renderer.
        """
        from PyQt6.QtWidgets import QApplication
        palette = QApplication.palette()
        return _md_to_html(
            markdown_text,
            text_color=palette.color(QPalette.ColorRole.Text).name(),
            base_color=palette.color(QPalette.ColorRole.Base).name(),
            link_color=palette.color(QPalette.ColorRole.Link).name(),
        )
