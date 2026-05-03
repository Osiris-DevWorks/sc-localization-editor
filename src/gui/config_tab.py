"""Configuration tab for Open Strings."""

import logging
import os
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QStandardItemModel
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.gui.theme import AVAILABLE_THEMES, THEME_DARK, THEME_LIGHT, THEME_OS_DARK
from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


class ConfigTab(QWidget):
    """Configuration tab — game path, P4K extraction, and import tools."""

    merge_requested = pyqtSignal()
    p4k_extract_requested = pyqtSignal()
    import_ini_requested = pyqtSignal()
    # Emitted after the user picks a new channel in the combo AND the choice
    # has already been persisted via AppSettings.set_active_channel(). Main
    # window listens and triggers a reload against the new channel's data.
    channel_changed = pyqtSignal(str)
    # Emitted after the Open Strings data folder override has been saved.
    # MainWindow re-syncs source paths and reloads against the new location.
    data_dir_changed = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
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
        appearance_group = QGroupBox("Appearance")
        appearance_layout = QHBoxLayout(appearance_group)

        theme_label = QLabel("Theme:")
        appearance_layout.addWidget(theme_label)

        self.theme_combo = QComboBox()
        self.theme_combo.setToolTip(
            "Switch the app theme. Takes effect immediately across the main window, toolbar, tabs, and Help panel."
        )
        self.theme_combo.addItem("Default", THEME_OS_DARK)
        self.theme_combo.addItem("Light", THEME_LIGHT)
        self.theme_combo.addItem("Dark", THEME_DARK)
        current = AppSettings.get_theme()
        idx = self.theme_combo.findData(current)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        self.theme_combo.setMaximumWidth(150)
        appearance_layout.addWidget(self.theme_combo)
        appearance_layout.addStretch()
        layout.addWidget(appearance_group)

        # ── Star Citizen Installation ────────────────────────────────────────
        game_group = QGroupBox("Star Citizen Installation")
        game_layout = QVBoxLayout(game_group)

        game_desc = QLabel(
            "Path to your Star Citizen install root (the directory containing LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW)."
        )
        game_desc.setProperty("role", "secondary")
        game_desc.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        game_desc.setWordWrap(True)
        game_layout.addWidget(game_desc)

        game_input_layout = QHBoxLayout()
        self.game_path_input = QLineEdit()
        self.game_path_input.setText(AppSettings.get_sc_install_root())
        self.game_path_input.setPlaceholderText(r"C:\Program Files\Roberts Space Industries\StarCitizen")
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
        # ── Open Strings Data ───────────────────────────────────────────────────
        data_group = QGroupBox("Open Strings Data")
        data_layout = QVBoxLayout(data_group)

        data_desc = QLabel(
            "Folder for user.ini, source cache, DataForge extraction, enhancement INIs, "
            "and backups. Move this off OneDrive-synced Documents if extraction is slow "
            "or cache cleanup fails."
        )
        data_desc.setProperty("role", "secondary")
        data_desc.setStyleSheet("font-size: 11px; margin-bottom: 5px;")
        data_desc.setWordWrap(True)
        data_layout.addWidget(data_desc)

        data_input_layout = QHBoxLayout()
        self.data_dir_input = QLineEdit()
        self.data_dir_input.setText(str(AppSettings.get_user_data_dir()))
        self.data_dir_input.setToolTip(
            "Open Strings app data root. Each channel gets its own subfolder "
            r"inside this directory. Leave blank or click Reset to use Documents\Open Strings."
        )
        self.data_dir_input.editingFinished.connect(self._save_data_dir)
        data_input_layout.addWidget(self.data_dir_input)

        data_browse_btn = QPushButton("Browse...")
        data_browse_btn.setMaximumWidth(100)
        data_browse_btn.clicked.connect(self._browse_data_dir)
        data_input_layout.addWidget(data_browse_btn)

        data_reset_btn = QPushButton("Reset")
        data_reset_btn.setMaximumWidth(80)
        data_reset_btn.setToolTip(r"Clear the custom data folder and use Documents\Open Strings.")
        data_reset_btn.clicked.connect(self._reset_data_dir)
        data_input_layout.addWidget(data_reset_btn)

        data_layout.addLayout(data_input_layout)
        layout.addWidget(data_group)
        # ── P4K Extraction ───────────────────────────────────────────────────
        p4k_group = QGroupBox("Base Localization (P4K Extraction)")
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
        self._extract_btn.clicked.connect(self.p4k_extract_requested.emit)
        p4k_status_row.addWidget(self._extract_btn)

        p4k_layout.addLayout(p4k_status_row)
        layout.addWidget(p4k_group)

        self._refresh_p4k_status()

        # ── Tools ────────────────────────────────────────────────────────────
        tools_group = QGroupBox("Tools")
        tools_layout = QVBoxLayout(tools_group)

        tools_desc = QLabel(
            "Import an external INI file to merge custom strings into your user.ini. "
            "Keys are validated against base.ini, and conflicts are resolved interactively."
        )
        tools_desc.setProperty("role", "secondary")
        tools_desc.setStyleSheet("font-size: 11px;")
        tools_desc.setWordWrap(True)
        tools_layout.addWidget(tools_desc)

        button_layout = QHBoxLayout()

        import_btn = QPushButton("Import INI...")
        import_btn.setMaximumWidth(150)
        import_btn.clicked.connect(self.import_ini_requested.emit)
        button_layout.addWidget(import_btn)

        preview_btn = QPushButton("Preview Merge")
        preview_btn.setMaximumWidth(150)
        preview_btn.clicked.connect(self.preview_merge)
        button_layout.addWidget(preview_btn)

        button_layout.addStretch()
        tools_layout.addLayout(button_layout)
        layout.addWidget(tools_group)

        layout.addStretch()

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
        if isinstance(app, QApplication):
            apply_theme(app, theme)
        mw = self.window()
        refresh_action_buttons = getattr(mw, "refresh_action_buttons", None)
        if callable(refresh_action_buttons):
            refresh_action_buttons()

    # ── Game path ────────────────────────────────────────────────────────────

    def _save_game_path(self):
        """Save the SC install root when editing finishes, and refresh the
        channel combo so per-channel enable/disable reflects the new root."""
        game_path = self.game_path_input.text().strip()
        if game_path and not Path(game_path).exists():
            logger.warning(f"SC install root does not exist: {game_path}")
            return
        AppSettings.set_sc_install_root(game_path)
        # Keep the legacy GAME_INSTALL_PATH in sync for any caller that still
        # reads it — e.g. unsynchronized callers during an in-progress upgrade.
        AppSettings.set_game_install_path(AppSettings.get_channel_install_path() if game_path else "")
        self._populate_channel_combo()
        self._refresh_p4k_status()

    def _browse_game_path(self):
        path = QFileDialog.getExistingDirectory(self, "Select Star Citizen Installation Root")
        if path:
            self.game_path_input.setText(path)
            self._save_game_path()

    # ── Open Strings data folder ────────────────────────────────────────────────

    def _save_data_dir(self):
        """Persist the Open Strings data folder override."""
        current_dir = AppSettings.get_user_data_dir()
        raw_path = self.data_dir_input.text().strip()

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
            logger.warning(f"Could not use Open Strings data folder {raw_path!r}: {e}")
            QMessageBox.warning(
                self,
                "Invalid Data Folder",
                f"Open Strings could not use that data folder:\n{e}",
            )
            self.data_dir_input.setText(str(current_dir))
            return

        self.data_dir_input.setText(str(new_dir))
        if new_dir != current_dir:
            logger.info(f"Open Strings data folder changed: {current_dir} → {new_dir}")
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

    def _browse_data_dir(self):
        start_dir = self.data_dir_input.text().strip() or str(AppSettings.get_user_data_dir())
        path = QFileDialog.getExistingDirectory(self, "Select Open Strings Data Folder", start_dir)
        if path:
            self.data_dir_input.setText(path)
            self._save_data_dir()

    def _reset_data_dir(self):
        current_dir = AppSettings.get_user_data_dir()
        AppSettings.set_user_data_dir(None)
        new_dir = AppSettings.get_user_data_dir()
        self.data_dir_input.setText(str(new_dir))
        if new_dir != current_dir:
            logger.info(f"Open Strings data folder reset to default: {new_dir}")
            self._refresh_p4k_status()
            self.data_dir_changed.emit(str(new_dir))

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
                item = None
                model = self.channel_combo.model()
                if isinstance(model, QStandardItemModel):
                    item = model.item(i)
                if item is not None and not is_available and root:
                    from PyQt6.QtCore import Qt

                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                    item.setToolTip(f"{channel} isn't installed — no Data.p4k at {Path(root) / channel / 'Data.p4k'}")
                if channel == active:
                    active_index = i
            self.channel_combo.setCurrentIndex(active_index)

            # If the stored active channel is unavailable, surface that with
            # a hint label so the user knows why things might not work.
            if root and active not in available_lookup:
                self._channel_hint_label.setText(f"⚠ {active} isn't installed under this root — pick another channel")
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
        item = None
        model = self.channel_combo.model()
        if isinstance(model, QStandardItemModel):
            item = model.item(index)
        if item is not None:
            from PyQt6.QtCore import Qt

            if not (item.flags() & Qt.ItemFlag.ItemIsEnabled):
                QMessageBox.warning(
                    self,
                    "Channel Not Installed",
                    f"{channel} isn't installed under the current root. "
                    "Install it via the RSI Launcher or pick a different channel.",
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
        base_ini = AppSettings.get_cache_dir() / "base.ini"

        if p4k_path.exists():
            self._p4k_status_dot.setStyleSheet("color: #4caf50; font-size: 14px;")
            if base_ini.exists():
                try:
                    last_str = datetime.fromtimestamp(base_ini.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    last_str = "unknown"
                self._p4k_status_label.setText(f"Data.p4k found  |  base.ini last updated: {last_str}")
            else:
                self._p4k_status_label.setText("Data.p4k found  |  base.ini not yet extracted")
        else:
            self._p4k_status_dot.setStyleSheet("color: #f44336; font-size: 14px;")
            if AppSettings.get_game_install_path():
                self._p4k_status_label.setText(f"Data.p4k not found at: {p4k_path}")
            else:
                self._p4k_status_label.setText("Game install path not configured")

    # ── Preview ──────────────────────────────────────────────────────────────

    def preview_merge(self):
        """Show a dry-run summary of the current merge configuration."""
        try:
            from src.parser.ini_parser import load_source_files, load_sources_from_settings

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
            for entry in entries:
                contributing = _AS.SOURCE_USER if entry.custom_value else entry.source_file
                source_counts[contributing] = source_counts.get(contributing, 0) + 1

            text = "Merge Preview\n\nMerge Order (top to bottom):\n"
            for i, name in enumerate(hierarchy, 1):
                text += f"  {i}. {name.capitalize()} ({source_counts.get(name, 0)} keys)\n"

            text += f"\nTotal Keys: {len(entries)}\nStatus Breakdown:\n"
            status_counts: dict[str, int] = {}
            for entry in entries:
                status_counts[entry.status] = status_counts.get(entry.status, 0) + 1
            for status, count in status_counts.items():
                text += f"  {status}: {count}\n"

            QMessageBox.information(self, "Merge Preview", text)

        except Exception as e:
            logger.exception(f"Error previewing merge: {e}")
            QMessageBox.critical(self, "Error", f"Failed to preview merge: {e}")
