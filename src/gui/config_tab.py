"""Configuration tab for Smart Citizen."""
import logging
import os
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
    QPushButton, QLabel, QFileDialog, QMessageBox, QComboBox,
    QCheckBox, QScrollArea, QFrame,
)
from PyQt6.QtCore import pyqtSignal, QTimer

from src.gui.theme import AVAILABLE_THEMES, THEME_LIGHT, THEME_DARK, THEME_SCLE, THEME_ODW
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


class ConfigTab(QWidget):
    """Configuration tab — game path, P4K extraction, and import tools."""

    merge_requested = pyqtSignal()
    p4k_extract_requested = pyqtSignal()
    import_ini_requested = pyqtSignal()
    # Emitted when the user clicks the "Reset user.ini" Tools button.
    # MainWindow runs the confirmation dialog and the actual file work so
    # this tab stays decoupled from filesystem state + reload orchestration.
    reset_user_ini_requested = pyqtSignal()
    # Emitted after the user picks a new channel in the combo AND the choice
    # has already been persisted via AppSettings.set_active_channel(). Main
    # window listens and triggers a reload against the new channel's data.
    channel_changed = pyqtSignal(str)
    # Emitted when the user clicks the "Check for Updates" button in Tools.
    # MainWindow owns the update-check worker and writes results back via
    # set_update_status() so this tab stays decoupled from the network path.
    check_updates_requested = pyqtSignal()
    # Emitted after the Smart Citizen data folder override has been saved.
    # MainWindow re-syncs source paths and reloads against the new location.
    data_dir_changed = pyqtSignal(str)
    # Emitted after the DataForge cache folder override has been saved AND
    # the user confirmed (in the re-extraction dialog) that the cache should
    # be rebuilt against the new location. MainWindow listens and triggers
    # P4K extraction. If the user picked "delete old cache after re-extract",
    # the old path is also stashed in AppSettings.PENDING_CACHE_CLEANUP for
    # the post-extract cleanup step.
    cache_dir_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        # Build into an inner content widget that a QScrollArea hosts, so the
        # tab degrades gracefully on short viewports (e.g. a 4K TV with
        # Windows display scaling, which gives the app a small logical height
        # and previously squished the Config tab — #98). The wrap is added at
        # the end of this method.
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Configuration")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        instructions = QLabel(
            "Configure your Star Citizen installation path, extract base localization "
            "from Data.p4k, and import external INI files to customize your strings."
        )
        instructions.setProperty("role", "secondary")
        instructions.setStyleSheet("font-size: 11px;")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        # ── Appearance ───────────────────────────────────────────────────────
        self.appearance_group = QGroupBox("Appearance")
        appearance_group = self.appearance_group
        appearance_layout = QHBoxLayout(appearance_group)

        theme_label = QLabel("Theme:")
        appearance_layout.addWidget(theme_label)

        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip("Switch the app theme. Takes effect immediately across the main window, toolbar, tabs, and Help panel.")
        self.theme_combo.addItem("Default", THEME_SCLE)
        self.theme_combo.addItem("Light", THEME_LIGHT)
        self.theme_combo.addItem("Dark", THEME_DARK)
        self.theme_combo.addItem("ODW", THEME_ODW)
        current = AppSettings.get_theme()
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.theme_combo.setMaximumWidth(150)
        appearance_layout.addWidget(self.theme_combo)

        appearance_layout.addSpacing(20)
        self.disable_tutorial_cb = QCheckBox("Disable Tutorial")
        self.disable_tutorial_cb.setToolTip(
            "When checked, the guided tour will not auto-launch on a new "
            "version. The Tutorial button in the toolbar still works."
        )
        self.disable_tutorial_cb.setChecked(AppSettings.get_tutorial_disabled())
        self.disable_tutorial_cb.toggled.connect(AppSettings.set_tutorial_disabled)
        appearance_layout.addWidget(self.disable_tutorial_cb)

        appearance_layout.addStretch()

        layout.addWidget(appearance_group)

        # ── Star Citizen Installation ────────────────────────────────────────
        self.game_group = QGroupBox("Star Citizen Installation")
        game_group = self.game_group
        game_layout = QVBoxLayout(game_group)

        game_desc = QLabel(
            "Path to your Star Citizen install root (the directory containing "
            "LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW)."
        )
        game_desc.setProperty("role", "secondary")
        game_desc.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        game_desc.setWordWrap(True)
        game_layout.addWidget(game_desc)

        game_input_layout = QHBoxLayout()
        self.game_path_input = QLineEdit()
        _initial_game_root = AppSettings.get_sc_install_root()
        self.game_path_input.setText(os.path.normpath(_initial_game_root) if _initial_game_root else "")
        self.game_path_input.setPlaceholderText(
            r"C:\Program Files\Roberts Space Industries\StarCitizen"
        )
        self.game_path_input.setToolTip(
            "Star Citizen install root — the directory that contains LIVE/, "
            "PTU/, EPTU/, HOTFIX/, and/or TECH-PREVIEW/. Auto-detected at "
            "install time; edit if your game lives elsewhere. The 'Channel' "
            "dropdown below picks which one the app reads and writes."
        )
        self.game_path_input.editingFinished.connect(self._save_game_path)
        game_input_layout.addWidget(self.game_path_input)

        game_browse_btn = QPushButton("Browse...")
        game_browse_btn.setMaximumWidth(100)
        game_browse_btn.setToolTip("Pick the Star Citizen install root in a folder browser.")
        game_browse_btn.clicked.connect(self._browse_game_path)
        game_input_layout.addWidget(game_browse_btn)
        game_layout.addLayout(game_input_layout)

        # ── Channel selector (LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW) ───
        channel_row = QHBoxLayout()
        channel_label = QLabel("Channel:")
        channel_label.setStyleSheet("font-size: 11px;")
        channel_row.addWidget(channel_label)

        self.channel_combo = QComboBox()
        self.channel_combo.setMaximumWidth(180)
        self.channel_combo.setToolTip(
            "Star Citizen channel to read Data.p4k from and write global.ini to. "
            "Channels with no Data.p4k under the install root are disabled. "
            "Switching channels immediately reloads strings against the new channel's data."
        )
        channel_row.addWidget(self.channel_combo)

        self._channel_hint_label = QLabel()
        self._channel_hint_label.setProperty("role", "secondary")
        self._channel_hint_label.setStyleSheet("font-size: 10px;")
        channel_row.addWidget(self._channel_hint_label)
        channel_row.addStretch()
        game_layout.addLayout(channel_row)

        self._populate_channel_combo()
        # Wire AFTER populate so the initial setCurrentIndex inside
        # _populate_channel_combo doesn't emit a phantom change signal.
        self.channel_combo.currentIndexChanged.connect(self._on_channel_changed)

        layout.addWidget(game_group)

        # ── Smart Citizen Data ───────────────────────────────────────────────
        self.data_group = QGroupBox("Smart Citizen Data")
        data_group = self.data_group
        data_layout = QVBoxLayout(data_group)

        data_desc = QLabel(
            "Folder for user.ini, source cache, enhancement INIs, and backups. "
            "Move this off OneDrive-synced Documents if cache cleanup fails. "
            "The DataForge XML cache has its own path below — it's ~1.4 GB so "
            "the default keeps it out of OneDrive automatically."
        )
        data_desc.setProperty("role", "secondary")
        data_desc.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        data_desc.setWordWrap(True)
        data_layout.addWidget(data_desc)

        # Sub-label for the user-data row.
        data_label = QLabel("App data folder:")
        data_label.setStyleSheet("font-size: 11px;")
        data_layout.addWidget(data_label)

        data_input_layout = QHBoxLayout()
        self.data_dir_input = QLineEdit()
        self.data_dir_input.setText(os.path.normpath(str(AppSettings.get_user_data_dir())))
        self.data_dir_input.setToolTip(
            "Smart Citizen's app data root. Each channel gets its own subfolder "
            "inside this directory. Leave blank or click Reset to use Documents\\Smart Citizen."
        )
        self.data_dir_input.editingFinished.connect(self._save_data_dir)
        data_input_layout.addWidget(self.data_dir_input)

        data_browse_btn = QPushButton("Browse...")
        data_browse_btn.setMaximumWidth(100)
        data_browse_btn.setToolTip("Pick the Smart Citizen data folder in a folder browser.")
        data_browse_btn.clicked.connect(self._browse_data_dir)
        data_input_layout.addWidget(data_browse_btn)

        data_reset_btn = QPushButton("Reset")
        data_reset_btn.setMaximumWidth(80)
        data_reset_btn.setToolTip("Clear the custom data folder and use Documents\\Smart Citizen.")
        data_reset_btn.clicked.connect(self._reset_data_dir)
        data_input_layout.addWidget(data_reset_btn)

        data_layout.addLayout(data_input_layout)

        # ── DataForge cache row ──────────────────────────────────────────
        # Independent from the app-data folder above so users can route the
        # ~1.4 GB / ~28k-file DataForge tree to a fast local SSD while
        # keeping their tiny user.ini / sources where they like. Default
        # base is %LOCALAPPDATA% (registry) or <exe-dir>/data/cache/
        # (portable) — both never OneDrive-synced.
        cache_label = QLabel("DataForge cache folder:")
        cache_label.setStyleSheet("font-size: 11px; margin-top: 8px;")
        data_layout.addWidget(cache_label)

        cache_input_layout = QHBoxLayout()
        self.cache_dir_input = QLineEdit()
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        self.cache_dir_input.setToolTip(
            "Base folder for the extracted DataForge XML tree (~1.4 GB). Each "
            "channel nests under this as {base}\\{channel}\\cache\\dataforge\\. "
            "Defaults to %LOCALAPPDATA%\\Smart Citizen so it stays out of "
            "OneDrive. Changing the path triggers a re-extraction."
        )
        self.cache_dir_input.editingFinished.connect(self._save_cache_dir)
        cache_input_layout.addWidget(self.cache_dir_input)

        cache_browse_btn = QPushButton("Browse...")
        cache_browse_btn.setMaximumWidth(100)
        cache_browse_btn.setToolTip("Pick the DataForge cache base folder in a folder browser.")
        cache_browse_btn.clicked.connect(self._browse_cache_dir)
        cache_input_layout.addWidget(cache_browse_btn)

        cache_reset_btn = QPushButton("Reset")
        cache_reset_btn.setMaximumWidth(80)
        cache_reset_btn.setToolTip("Clear the custom cache folder and use the platform default.")
        cache_reset_btn.clicked.connect(self._reset_cache_dir)
        cache_input_layout.addWidget(cache_reset_btn)

        data_layout.addLayout(cache_input_layout)
        layout.addWidget(data_group)

        # ── P4K Extraction ───────────────────────────────────────────────────
        self.p4k_group = QGroupBox("Base Localization (P4K Extraction)")
        p4k_group = self.p4k_group
        p4k_layout = QVBoxLayout(p4k_group)

        p4k_desc = QLabel(
            "Extract global.ini from your installed Data.p4k to get stock game strings "
            "that always match your installed version."
        )
        p4k_desc.setProperty("role", "secondary")
        p4k_desc.setStyleSheet("font-size: 11px;")
        p4k_desc.setWordWrap(True)
        p4k_layout.addWidget(p4k_desc)

        p4k_status_row = QHBoxLayout()
        self._p4k_status_dot = QLabel("●")
        self._p4k_status_dot.setStyleSheet("font-size: 14px;")
        p4k_status_row.addWidget(self._p4k_status_dot)

        self._p4k_status_label = QLabel()
        self._p4k_status_label.setProperty("role", "secondary")
        self._p4k_status_label.setStyleSheet("font-size: 11px;")
        p4k_status_row.addWidget(self._p4k_status_label)
        p4k_status_row.addStretch()

        self._extract_btn = QPushButton("Extract from Data.p4k")
        self._extract_btn.setMaximumWidth(180)
        self._extract_btn.setToolTip(
            "Unpack stock localization (base.ini) plus the DataForge entity XMLs "
            "from your installed Data.p4k. Run after every Star Citizen patch — "
            "the strings reload into the table automatically when extraction finishes."
        )
        self._extract_btn.clicked.connect(self.p4k_extract_requested.emit)
        p4k_status_row.addWidget(self._extract_btn)

        p4k_layout.addLayout(p4k_status_row)
        layout.addWidget(p4k_group)

        self._refresh_p4k_status()

        # ── Tools ────────────────────────────────────────────────────────────
        self.tools_group = QGroupBox("Tools")
        tools_group = self.tools_group
        tools_layout = QVBoxLayout(tools_group)

        tools_desc = QLabel(
            "Import an external INI file to merge custom strings into your user.ini. "
            "Keys are validated against base.ini, and conflicts are resolved interactively."
        )
        tools_desc.setProperty("role", "secondary")
        tools_desc.setStyleSheet("font-size: 11px;")
        tools_desc.setWordWrap(True)
        tools_layout.addWidget(tools_desc)

        self.include_new_cb = QCheckBox("Include discovered items")
        self.include_new_cb.setToolTip(
            "When checked, items discovered from DataForge XML (status 'New') "
            "that have non-empty text will be included in the applied global.ini."
        )
        self.include_new_cb.setChecked(AppSettings.get_include_new_lines())
        self.include_new_cb.toggled.connect(self._on_include_new_toggled)
        tools_layout.addWidget(self.include_new_cb)

        button_layout = QHBoxLayout()

        import_btn = QPushButton("Import INI...")
        import_btn.setMaximumWidth(150)
        import_btn.setToolTip(
            "Fold an external .ini into your overrides. A conflict-resolution "
            "dialog lets you decide per key: keep current, use imported, append, "
            "prepend, or provide a custom value."
        )
        import_btn.clicked.connect(self.import_ini_requested.emit)
        button_layout.addWidget(import_btn)

        reset_user_ini_btn = QPushButton("Reset user.ini...")
        reset_user_ini_btn.setMaximumWidth(150)
        reset_user_ini_btn.setToolTip(
            "Delete every custom string override for the active channel. "
            "A timestamped backup is saved next to the original so you can restore it."
        )
        reset_user_ini_btn.clicked.connect(self.reset_user_ini_requested.emit)
        button_layout.addWidget(reset_user_ini_btn)

        preview_btn = QPushButton("Preview Apply")
        preview_btn.setMaximumWidth(150)
        preview_btn.setToolTip(
            "Dry-run summary of what Apply to Game would write — per-source key "
            "counts (with Enhancements broken down by category) and a "
            "Modified / Enhanced / Unmodified / New status tally. Nothing is "
            "written to the game until you click Apply to Game."
        )
        preview_btn.clicked.connect(self.preview_merge)
        button_layout.addWidget(preview_btn)

        self._check_updates_btn = QPushButton("Check for Updates")
        self._check_updates_btn.setMaximumWidth(170)
        self._check_updates_btn.setToolTip(
            "Check GitHub for a newer Smart Citizen release."
        )
        self._check_updates_btn.clicked.connect(self.check_updates_requested.emit)
        button_layout.addWidget(self._check_updates_btn)

        self._update_status_label = QLabel("")
        self._update_status_label.setProperty("role", "secondary")
        self._update_status_label.setStyleSheet("font-size: 11px;")
        button_layout.addWidget(self._update_status_label)

        button_layout.addStretch()
        tools_layout.addLayout(button_layout)
        layout.addWidget(tools_group)

        layout.addStretch()

        # Host the content in a scroll area. MainWindow adds the tab widget
        # with stretch=1, so the scroll area fills the tab and this does NOT
        # reintroduce the tab-switch resize that got the 1.4.x Enhancements
        # scroll-area attempt reverted (#65). Keep the frame and viewport
        # background clear so the themed background shows through rather than
        # the scroll area painting its own Base colour.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Theme ────────────────────────────────────────────────────────────────

    def _on_theme_changed(self, _index: int):
        """Defer the actual swap to the next event-loop tick. Running
        app.setPalette() directly from a QComboBox.currentIndexChanged slot
        crashes Qt 6 because the combo's event chain hasn't finished unwinding.
        """
        theme = self.theme_combo.currentData()
        if theme not in AVAILABLE_THEMES:
            return
        QTimer.singleShot(0, lambda: self._apply_theme_change(theme))

    def _apply_theme_change(self, theme: str):
        """Persist and apply the theme. Runs via QTimer.singleShot so we're
        outside the combo's event handling — required for setPalette safety."""
        from PyQt6.QtWidgets import QApplication
        from src.gui.theme import apply_theme
        AppSettings.set_theme(theme)
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, theme)
        mw = self.window()
        if hasattr(mw, "refresh_action_buttons"):
            mw.refresh_action_buttons()

    def _on_include_new_toggled(self, checked: bool):
        AppSettings.set_include_new_lines(checked)

    # ── Game path ────────────────────────────────────────────────────────────

    def _save_game_path(self):
        """Save the SC install root when editing finishes, and refresh the
        channel combo so per-channel enable/disable reflects the new root."""
        game_path = self.game_path_input.text().strip()
        if game_path:
            # Normalize to native separators (backslashes on Windows). Qt's
            # QFileDialog returns POSIX-style forward slashes and Path.resolve()
            # also yields forward slashes in some flows; without this the field
            # toggles between styles depending on how the path arrived.
            game_path = os.path.normpath(game_path)
            self.game_path_input.setText(game_path)
        if game_path and not Path(game_path).exists():
            logger.warning(f"SC install root does not exist: {game_path}")
            return
        AppSettings.set_sc_install_root(game_path)
        # Keep the legacy GAME_INSTALL_PATH in sync for any caller that still
        # reads it — e.g. unsynchronized callers during an in-progress upgrade.
        AppSettings.set_game_install_path(
            AppSettings.get_channel_install_path() if game_path else ""
        )
        self._populate_channel_combo()
        self._refresh_p4k_status()

    def _browse_game_path(self):
        path = QFileDialog.getExistingDirectory(
            self, "Select Star Citizen Installation Root"
        )
        if path:
            self.game_path_input.setText(path)
            self._save_game_path()

    # ── Smart Citizen data folder ────────────────────────────────────────────

    def _save_data_dir(self):
        """Persist the Smart Citizen data folder override."""
        current_dir = AppSettings.get_user_data_dir()
        raw_path = self.data_dir_input.text().strip()
        if raw_path:
            raw_path = os.path.normpath(raw_path)

        try:
            if raw_path:
                target = Path(os.path.expandvars(raw_path)).expanduser().resolve()
                if target.exists() and not target.is_dir():
                    QMessageBox.warning(
                        self,
                        "Invalid Data Folder",
                        f"The selected data folder is a file, not a directory:\n{target}",
                    )
                    self.data_dir_input.setText(str(current_dir))
                    return
                target.mkdir(parents=True, exist_ok=True)
                AppSettings.set_user_data_dir(target)
            else:
                AppSettings.set_user_data_dir(None)

            new_dir = AppSettings.get_user_data_dir()
        except OSError as e:
            logger.warning(f"Could not use Smart Citizen data folder {raw_path!r}: {e}")
            QMessageBox.warning(
                self,
                "Invalid Data Folder",
                f"Smart Citizen could not use that data folder:\n{e}",
            )
            self.data_dir_input.setText(str(current_dir))
            return

        self.data_dir_input.setText(os.path.normpath(str(new_dir)))
        if new_dir != current_dir:
            logger.info(f"Smart Citizen data folder changed: {current_dir} → {new_dir}")
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

    def _browse_data_dir(self):
        start_dir = self.data_dir_input.text().strip() or str(AppSettings.get_user_data_dir())
        path = QFileDialog.getExistingDirectory(
            self, "Select Smart Citizen Data Folder", start_dir
        )
        if path:
            self.data_dir_input.setText(path)
            self._save_data_dir()

    def _reset_data_dir(self):
        current_dir = AppSettings.get_user_data_dir()
        AppSettings.set_user_data_dir(None)
        new_dir = AppSettings.get_user_data_dir()
        self.data_dir_input.setText(os.path.normpath(str(new_dir)))
        if new_dir != current_dir:
            logger.info(f"Smart Citizen data folder reset to default: {new_dir}")
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

    # ── DataForge cache folder ───────────────────────────────────────────────
    # The cache path is independent of the app-data path so users can target
    # a fast local SSD for the 1.4 GB DataForge tree without disturbing their
    # user.ini / sources. Changing the path requires a re-extraction (the
    # old cache contents aren't migrated — moving 28k tiny files is slower
    # than letting unforge rebuild from Data.p4k), so the user gets a
    # 3-button prompt: Re-extract + delete old / Re-extract + keep old /
    # Cancel. Cancel reverts the input to the previous value.

    def _maybe_apply_cache_change(self, new_override: "str | None") -> bool:
        """Common path for set/browse/reset.

        Returns ``True`` when the new override was accepted (the caller
        should refresh the input field) and ``False`` when the user
        cancelled the migration dialog (caller should revert the input).
        """
        old_base = AppSettings.get_dataforge_cache_base()
        old_leaf = AppSettings.get_dataforge_cache_dir()
        # Stash + temporarily apply the prospective override so the resolved
        # base picks up env-var expansion + resolve() in the same code path
        # production uses. Revert if the user cancels.
        prev_override = AppSettings.get_cache_dir_override()
        AppSettings.set_cache_dir(new_override)
        new_base = AppSettings.get_dataforge_cache_base()
        new_leaf = AppSettings.get_dataforge_cache_dir()

        if new_base == old_base:
            # No-op change (e.g. user typed the same path they had). The
            # mkdir inside get_dataforge_cache_dir is harmless.
            return True

        # Only prompt when the old cache actually has extracted content.
        # The ``.p4k_mtime`` stamp is written by pak_extractor.py once an
        # extraction succeeds, so its presence is the cheapest "is this a
        # populated cache" probe (avoids walking 28k files).
        old_has_content = (old_leaf / ".p4k_mtime").exists()
        if not old_has_content:
            logger.info(
                f"DataForge cache base changed: {old_base} → {new_base} "
                f"(old leaf empty; no migration prompt)"
            )
            self.cache_dir_changed.emit(str(new_leaf))
            return True

        # The shipped behavior is: never silently move ~1.4 GB. We ask the
        # user up-front whether to also clean up the orphan, and only the
        # cleanup is deferred (after re-extraction completes). The
        # re-extraction itself is triggered immediately via the signal so
        # the user can fire it off and walk away.
        prompt = QMessageBox(self)
        prompt.setWindowTitle("DataForge Cache Path Changed")
        prompt.setIcon(QMessageBox.Icon.Question)
        prompt.setText(
            "Changing the DataForge cache path requires re-extracting "
            "from Data.p4k.\n\nWhat should happen to the previous cache "
            "after re-extraction completes?"
        )
        prompt.setInformativeText(f"Old: {old_leaf}\nNew: {new_leaf}")
        delete_btn = prompt.addButton("Re-extract && delete old", QMessageBox.ButtonRole.AcceptRole)
        keep_btn = prompt.addButton("Re-extract && keep old", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = prompt.addButton(QMessageBox.StandardButton.Cancel)
        prompt.setDefaultButton(keep_btn)
        prompt.exec()
        clicked = prompt.clickedButton()

        if clicked is cancel_btn:
            AppSettings.set_cache_dir(prev_override or None)
            return False

        if clicked is delete_btn:
            # MainWindow drains this after the next successful re-extract.
            AppSettings.set_pending_cache_cleanup(old_leaf)
            logger.info(
                f"DataForge cache path changed; queued old cache for cleanup "
                f"after re-extraction: {old_leaf}"
            )
        else:
            # Re-extract + keep old: don't queue cleanup. The orphan stays
            # until the user removes it manually.
            AppSettings.set_pending_cache_cleanup(None)
            logger.info(
                f"DataForge cache path changed; old cache retained at {old_leaf}"
            )

        self.cache_dir_changed.emit(str(new_leaf))
        return True

    def _save_cache_dir(self):
        raw_path = self.cache_dir_input.text().strip()
        if raw_path:
            raw_path = os.path.normpath(raw_path)

        try:
            if raw_path:
                target = Path(os.path.expandvars(raw_path)).expanduser().resolve()
                if target.exists() and not target.is_dir():
                    QMessageBox.warning(
                        self,
                        "Invalid Cache Folder",
                        f"The selected cache folder is a file, not a directory:\n{target}",
                    )
                    self.cache_dir_input.setText(
                        os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
                    )
                    return
                target.mkdir(parents=True, exist_ok=True)
                accepted = self._maybe_apply_cache_change(str(target))
            else:
                accepted = self._maybe_apply_cache_change(None)
        except OSError as e:
            logger.warning(f"Could not use DataForge cache folder {raw_path!r}: {e}")
            QMessageBox.warning(
                self,
                "Invalid Cache Folder",
                f"Smart Citizen could not use that cache folder:\n{e}",
            )
            self.cache_dir_input.setText(
                os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
            )
            return

        # Always re-read AppSettings on exit — the user may have cancelled,
        # in which case the override is restored to its previous value.
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        if accepted:
            self._refresh_p4k_status()

    def _browse_cache_dir(self):
        start_dir = (
            self.cache_dir_input.text().strip()
            or str(AppSettings.get_dataforge_cache_base())
        )
        path = QFileDialog.getExistingDirectory(
            self, "Select DataForge Cache Folder", start_dir
        )
        if path:
            self.cache_dir_input.setText(path)
            self._save_cache_dir()

    def _reset_cache_dir(self):
        accepted = self._maybe_apply_cache_change(None)
        self.cache_dir_input.setText(
            os.path.normpath(str(AppSettings.get_dataforge_cache_base()))
        )
        if accepted:
            self._refresh_p4k_status()

    # ── Channel selector ─────────────────────────────────────────────────────

    def _populate_channel_combo(self):
        """Rebuild the channel combo, marking channels without a Data.p4k
        under the configured root as disabled.

        Signals are blocked while we mutate so an index change triggered by
        ``setCurrentIndex`` doesn't fire our ``currentIndexChanged`` slot,
        which would double-fire the channel-change reload logic.
        """
        if not hasattr(self, "channel_combo"):
            return
        blocker = self.channel_combo.blockSignals(True)
        try:
            self.channel_combo.clear()
            root = AppSettings.get_sc_install_root()
            active = AppSettings.get_active_channel()
            available_lookup = set(AppSettings.get_available_channels()) if root else set()
            active_index = 0
            for i, channel in enumerate(AppSettings.AVAILABLE_CHANNELS):
                self.channel_combo.addItem(channel, userData=channel)
                is_available = channel in available_lookup
                # Qt combo-item disable: set Qt.ItemFlag.NoItemFlags on the
                # item via the model, then a tooltip explains why.
                item = self.channel_combo.model().item(i)
                if item is not None and not is_available and root:
                    from PyQt6.QtCore import Qt
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setToolTip(
                        f"{channel} isn't installed — no Data.p4k at "
                        f"{Path(root) / channel / 'Data.p4k'}"
                    )
                if channel == active:
                    active_index = i
            self.channel_combo.setCurrentIndex(active_index)

            # If the stored active channel is unavailable, surface that with
            # a hint label so the user knows why things might not work.
            if root and active not in available_lookup:
                self._channel_hint_label.setText(
                    f"⚠ {active} isn't installed under this root — pick another channel"
                )
                self._channel_hint_label.setStyleSheet("font-size: 10px; color: #ff9800;")
            else:
                self._channel_hint_label.setText("")
        finally:
            self.channel_combo.blockSignals(blocker)

    def _on_channel_changed(self, index: int):
        """Persist the new active channel and notify the main window."""
        if index < 0:
            return
        channel = self.channel_combo.itemData(index)
        if not channel or channel == AppSettings.get_active_channel():
            return
        # Reject selection of disabled (not-installed) items defensively —
        # Qt normally prevents this, but some desktop environments can
        # still produce a currentIndexChanged here if the model's item
        # flags were bypassed.
        item = self.channel_combo.model().item(index)
        if item is not None:
            from PyQt6.QtCore import Qt
            if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
                QMessageBox.warning(
                    self, "Channel Not Installed",
                    f"{channel} isn't installed under the current root. "
                    "Install it via the RSI Launcher or pick a different channel."
                )
                # Revert the combo to the active channel.
                self._populate_channel_combo()
                return
        logger.info(f"Active channel switching: {AppSettings.get_active_channel()} → {channel}")
        AppSettings.set_active_channel(channel)
        # Keep the legacy key in sync for any pre-migration caller.
        AppSettings.set_game_install_path(AppSettings.get_channel_install_path())
        self._refresh_p4k_status()
        self.channel_changed.emit(channel)

    # ── P4K status ───────────────────────────────────────────────────────────

    def _refresh_p4k_status(self):
        p4k_path = AppSettings.get_p4k_path()
        base_ini = AppSettings.get_cache_dir() / 'base.ini'

        if p4k_path.exists():
            self._p4k_status_dot.setStyleSheet("color: #4caf50; font-size: 14px;")
            if base_ini.exists():
                try:
                    last_str = datetime.fromtimestamp(
                        base_ini.stat().st_mtime
                    ).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    last_str = "unknown"
                self._p4k_status_label.setText(
                    f"Data.p4k found  |  base.ini last updated: {last_str}"
                )
            else:
                self._p4k_status_label.setText("Data.p4k found  |  base.ini not yet extracted")
        else:
            self._p4k_status_dot.setStyleSheet("color: #f44336; font-size: 14px;")
            if AppSettings.get_game_install_path():
                self._p4k_status_label.setText(f"Data.p4k not found at: {p4k_path}")
            else:
                self._p4k_status_label.setText("Game install path not configured")

    # ── Updates ──────────────────────────────────────────────────────────────

    def set_update_status(self, text: str) -> None:
        """Write a short status string next to the 'Check for Updates' button.

        MainWindow calls this from its app-update signal handlers so the
        result ("Up to date", "v0.9.4 available", "Check failed") sits
        inline with the button without this tab needing to know about
        the worker.
        """
        self._update_status_label.setText(text)

    def set_check_updates_enabled(self, enabled: bool) -> None:
        """Toggle the 'Check for Updates' button — disable while a check runs."""
        self._check_updates_btn.setEnabled(enabled)

    # ── Preview ──────────────────────────────────────────────────────────────

    def preview_merge(self):
        """Show a dry-run summary of what Apply to Game would write.

        Mirrors the post-Apply success dialog so the preview reads as
        a "what will I get" forecast: per-source key counts, with the
        Smart Citizen Enhancements row broken down by category, plus
        a status (Modified / Enhanced / Unmodified / New) tally.
        """
        try:
            from collections import Counter
            from src.parser.ini_parser import load_sources_from_settings, load_source_files

            sources_dict, hierarchy, _enhancements_cats = load_sources_from_settings()

            if not sources_dict:
                QMessageBox.warning(self, "Warning", "No sources available to merge.")
                return

            entries = load_source_files(sources_dict, hierarchy)

            # Count contributions per source. The merge engine overlays later
            # sources on top of earlier ones, with user.ini always winning —
            # so a key the user has overridden is contributed by the user
            # source, even though entry.source_file still records its
            # original baseline source. Without this, the User row in the
            # preview always reads 0 unless the user added a brand-new key.
            from src.utils.settings import AppSettings as _AS
            source_counts: dict[str, int] = {}
            # Per-category counter for the enhancements source so we can
            # mirror the Apply-to-game dialog's breakdown. Other sources
            # don't get the category split — they're either "Global" (the
            # whole base) or "User" (always small enough to read at a
            # glance).
            enhancement_categories: Counter[str] = Counter()
            ENHANCEMENTS_SRC = "enhancements"
            for entry in entries:
                contributing = _AS.SOURCE_USER if entry.custom_value else entry.source_file
                source_counts[contributing] = source_counts.get(contributing, 0) + 1
                if contributing == ENHANCEMENTS_SRC:
                    enhancement_categories[entry.category] += 1

            # Filter out zero-key entries before displaying — leftover
            # `contracts` / `components` / `commodities` / `gear` source
            # entries from pre-0.7.0 registry state can linger in the
            # hierarchy even after `migrate_remove_retired_url_sources`
            # ran, because that migrator only prunes URL-backed paths.
            # Their content has been folded into the general
            # enhancements pipeline, so showing them as "X (0 keys)"
            # is just visual noise. Renumber remaining entries so the
            # list reads 1, 2, 3, ... without gaps.
            text = "Apply Preview\n\nMerge Order (top to bottom):\n"
            visible_index = 0
            for name in hierarchy:
                count = source_counts.get(name, 0)
                if count == 0:
                    continue
                visible_index += 1
                if name == ENHANCEMENTS_SRC:
                    text += f"  {visible_index}. Smart Citizen Enhancements ({count:,} keys total):\n"
                    if enhancement_categories:
                        for cat, ccount in enhancement_categories.most_common():
                            text += f"       {cat}: {ccount:,}\n"
                else:
                    text += f"  {visible_index}. {name.capitalize()} ({count:,} keys)\n"

            text += f"\nTotal Keys: {len(entries):,}\nStatus Breakdown:\n"
            status_counts: dict[str, int] = {}
            for entry in entries:
                status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
            # Sort descending by count so the largest bucket leads —
            # consistent with the Apply dialog's most_common() ordering.
            for status, count in sorted(status_counts.items(), key=lambda kv: -kv[1]):
                text += f"  {status}: {count:,}\n"

            QMessageBox.information(self, "Apply Preview", text)

        except Exception as e:
            logger.exception(f"Error previewing merge: {e}")
            QMessageBox.critical(self, "Error", f"Failed to preview merge: {e}")
