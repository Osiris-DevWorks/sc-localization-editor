"""Enhancements tab for Smart Citizen."""
import logging

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QCheckBox, QComboBox, QMessageBox
)
from PyQt6.QtCore import pyqtSignal

from src.utils.settings import AppSettings

logger = logging.getLogger(__name__)


class EnhancementsTab(QWidget):
    """Tab for optional enhancements: localization enhancements and ship favorites."""

    merge_requested = pyqtSignal()
    enhancements_pipeline_requested = pyqtSignal()   # extract DataForge if needed, then generate enhancements

    def __init__(self):
        super().__init__()
        self._loaded_prefix = AppSettings.get_favorite_prefix()
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Enhancements")
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(title)

        desc = QLabel(
            "Optional features that extend the base localization data. "
            "Each can be enabled or disabled independently."
        )
        desc.setProperty("role", "secondary")
        desc.setStyleSheet("font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addWidget(self._build_enhancements_group())
        layout.addWidget(self._build_favorites_group())
        layout.addStretch()

    # ── Enhancements ─────────────────────────────────────────────────────────

    def _build_enhancements_group(self) -> QGroupBox:
        group = QGroupBox("Localization Enhancements")
        gl = QVBoxLayout(group)

        enhancements_desc = QLabel(
            "Select which enhancement categories to include. "
            "Click Apply to save changes. Enhancements are generated from your installed Data.p4k."
        )
        enhancements_desc.setProperty("role", "secondary")
        enhancements_desc.setStyleSheet("font-size: 11px;")
        enhancements_desc.setWordWrap(True)
        gl.addWidget(enhancements_desc)

        # Per-category checkbox + description + status dot
        _CATEGORY_DESCRIPTIONS = {
            "ships":       "Ship performance, loadout, and crew data",
            "ship_items":  "Component class/size/grade annotations and statistics",
            "gear":        "Combat stats for FPS weapons",
            "missions":    "XP rewards and blueprint drops for missions",
            "commodities": "Crafting recipes and material usage",
            "journal":     "Mining Compendium with crafting data per mineral",
        }

        self._enhancements_status_labels: dict = {}
        self._enhancements_checkboxes: dict = {}
        categories_layout = QVBoxLayout()

        for key, label in AppSettings.ENHANCEMENT_LABELS.items():
            row = QHBoxLayout()
            cb = QCheckBox(label)
            cb.setChecked(AppSettings.get_enhancement_category_enabled(key))
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._on_category_checkbox_changed)
            row.addWidget(cb)
            self._enhancements_checkboxes[key] = cb

            dot = QLabel("●")
            dot.setStyleSheet("color: #999; font-size: 12px;")
            row.addWidget(dot)
            self._enhancements_status_labels[key] = dot

            desc = QLabel(_CATEGORY_DESCRIPTIONS.get(key, ""))
            desc.setProperty("role", "secondary")
            desc.setStyleSheet("font-size: 10px;")
            row.addWidget(desc)

            row.addStretch()
            categories_layout.addLayout(row)

        gl.addLayout(categories_layout)

        btn_row = QHBoxLayout()

        self._apply_categories_btn = QPushButton("Apply")
        self._apply_categories_btn.setMaximumWidth(100)
        self._apply_categories_btn.setEnabled(False)
        self._apply_categories_btn.setToolTip(
            "Save category selection. Unchecked categories will be disabled."
        )
        self._apply_categories_btn.clicked.connect(self._apply_category_changes)
        btn_row.addWidget(self._apply_categories_btn)

        self._generate_enhancements_btn = QPushButton("Generate Enhancements")
        self._generate_enhancements_btn.setMaximumWidth(160)
        self._generate_enhancements_btn.setToolTip(
            "Generate enhanced localization files from your game's Data.p4k.\n"
            "DataForge data will be extracted automatically if not already cached\n"
            "(first run takes ~5–10 minutes; subsequent runs are fast)."
        )
        self._generate_enhancements_btn.clicked.connect(self.enhancements_pipeline_requested.emit)
        btn_row.addWidget(self._generate_enhancements_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)

        self._forge_status_label = QLabel()
        self._forge_status_label.setProperty("role", "secondary")
        self._forge_status_label.setStyleSheet("font-size: 10px;")
        gl.addWidget(self._forge_status_label)

        self._operation_label = QLabel()
        self._operation_label.setStyleSheet("font-size: 10px; color: #2196F3;")
        self._operation_label.setVisible(False)
        gl.addWidget(self._operation_label)

        self.refresh_enhancements_status()
        return group

    def _on_category_checkbox_changed(self):
        """Enable Apply button if any checkbox differs from saved settings."""
        has_changes = any(
            cb.isChecked() != AppSettings.get_enhancement_category_enabled(key)
            for key, cb in self._enhancements_checkboxes.items()
        )
        self._apply_categories_btn.setEnabled(has_changes)

    def _apply_category_changes(self):
        """Save checkbox states, disable/restore enhancement files, and trigger reload."""
        for key, cb in self._enhancements_checkboxes.items():
            now_enabled = cb.isChecked()
            AppSettings.set_enhancement_category_enabled(key, now_enabled)

            cache_dir = AppSettings.get_cache_dir()
            # Apply to all files mapped to this checkbox key
            for filename in self._files_for_category(key):
                active_file = cache_dir / filename
                disabled_file = cache_dir / (filename + ".disabled")

                if not now_enabled and active_file.exists():
                    try:
                        active_file.rename(disabled_file)
                        logger.info(f"Disabled enhancement file: {filename}")
                    except OSError as e:
                        logger.warning(f"Failed to disable {filename}: {e}")

                elif now_enabled and not active_file.exists() and disabled_file.exists():
                    try:
                        disabled_file.rename(active_file)
                        logger.info(f"Restored enhancement file: {filename}")
                    except OSError as e:
                        logger.warning(f"Failed to restore {filename}: {e}")

        self._apply_categories_btn.setEnabled(False)
        self.refresh_enhancements_status()
        self.merge_requested.emit()

    @staticmethod
    def _files_for_category(key: str) -> list[str]:
        """Return the enhancement filenames controlled by a checkbox key."""
        file_keys = AppSettings.ENHANCEMENT_CATEGORY_FILES.get(key, [key])
        return [AppSettings.ENHANCEMENTS_FILES[fk] for fk in file_keys]

    def revert_category_checkboxes(self):
        """Reset checkboxes to match the saved settings (called when leaving tab without applying)."""
        for key, cb in self._enhancements_checkboxes.items():
            cb.blockSignals(True)
            cb.setChecked(AppSettings.get_enhancement_category_enabled(key))
            cb.blockSignals(False)
        self._apply_categories_btn.setEnabled(False)

    # ── Favorites ─────────────────────────────────────────────────────────────

    def _build_favorites_group(self) -> QGroupBox:
        group = QGroupBox("Favorites")
        gl = QVBoxLayout(group)

        favorites_desc = QLabel(
            "Favorited ships have a prefix character prepended to their name so they "
            "sort to the top of the in-game ship list. Choose which character to use:"
        )
        favorites_desc.setProperty("role", "secondary")
        favorites_desc.setStyleSheet("font-size: 11px;")
        favorites_desc.setWordWrap(True)
        gl.addWidget(favorites_desc)

        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Sort prefix:"))

        self.favorite_prefix_combo = QComboBox()
        self.favorite_prefix_combo.setToolTip("Character prepended to favorited ship names so they sort to the top of the in-game ship list. Click Apply Prefix after changing to update all existing favorites.")
        self.favorite_prefix_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        self.favorite_prefix_combo.addItem("  (space)", userData=" ")
        for code in range(33, 65):
            self.favorite_prefix_combo.addItem(chr(code), userData=chr(code))

        for i in range(self.favorite_prefix_combo.count()):
            if self.favorite_prefix_combo.itemData(i) == self._loaded_prefix:
                self.favorite_prefix_combo.setCurrentIndex(i)
                break

        combo_view = self.favorite_prefix_combo.view()
        if combo_view is not None:
            combo_view.setMinimumWidth(self.favorite_prefix_combo.sizeHint().width() + 20)
        prefix_row.addWidget(self.favorite_prefix_combo)

        apply_prefix_btn = QPushButton("Apply")
        apply_prefix_btn.setToolTip(
            "Save the selected prefix and update all existing favorites to use it"
        )
        apply_prefix_btn.clicked.connect(self._apply_favorite_prefix)
        prefix_row.addWidget(apply_prefix_btn)

        prefix_row.addStretch()
        gl.addLayout(prefix_row)
        return group

    def _apply_favorite_prefix(self):
        new_prefix = self.favorite_prefix_combo.currentData()
        if not new_prefix:
            return

        old_prefix = self._loaded_prefix

        if new_prefix != old_prefix:
            overrides_path = AppSettings.get_user_ini_path()
            if overrides_path.exists():
                try:
                    lines = overrides_path.read_text(encoding="utf-8").splitlines()
                    updated = []
                    migrated = 0
                    for line in lines:
                        if "=" in line:
                            key, _, value = line.partition("=")
                            if value.startswith(old_prefix):
                                value = new_prefix + value[len(old_prefix):]
                                migrated += 1
                            updated.append(f"{key}={value}")
                        else:
                            updated.append(line)
                    overrides_path.write_text("\n".join(updated), encoding="utf-8")
                    logger.info(f"Migrated {migrated} favorites from '{old_prefix}' to '{new_prefix}'")
                except Exception as e:
                    logger.exception(f"Failed to migrate favorites: {e}")
                    QMessageBox.critical(self, "Error", f"Failed to update favorites: {e}")
                    return

        AppSettings.set_favorite_prefix(new_prefix)
        self._loaded_prefix = new_prefix
        self.merge_requested.emit()

    # ── Operation state ───────────────────────────────────────────────────────

    def set_operation_running(self, message: str):
        """Disable the enhancements button and show an inline progress message."""
        self._generate_enhancements_btn.setEnabled(False)
        self._operation_label.setText(message)
        self._operation_label.setVisible(True)

    def set_operation_progress(self, message: str):
        """Update the inline progress message without changing button state."""
        self._operation_label.setText(message)

    def set_operation_idle(self):
        """Re-enable the enhancements button and hide the progress message."""
        self._generate_enhancements_btn.setEnabled(True)
        self._operation_label.setVisible(False)
        self._operation_label.setText("")

    # ── Status refresh ────────────────────────────────────────────────────────

    def refresh_enhancements_status(self):
        """Update enhancement file status indicators and DataForge cache status."""
        cache_dir = AppSettings.get_cache_dir()
        for key, dot in self._enhancements_status_labels.items():
            # Check all files controlled by this checkbox
            filenames = self._files_for_category(key)
            all_present = all((cache_dir / fn).exists() for fn in filenames)
            dot.setStyleSheet(f"color: {'#4caf50' if all_present else '#f44336'}; font-size: 12px;")
        self.refresh_forge_status()

    def refresh_forge_status(self):
        """Update the DataForge cache status label."""
        from src.utils.pak_extractor import dataforge_cache_is_fresh
        forge_dir = AppSettings.get_dataforge_cache_dir()
        p4k_path = AppSettings.get_p4k_path()
        if not (forge_dir / ".p4k_mtime").exists():
            self._forge_status_label.setText(
                "DataForge: not yet extracted — click 'Generate Enhancements' to begin"
            )
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #f44336;")
        elif p4k_path.exists() and not dataforge_cache_is_fresh(p4k_path, forge_dir):
            self._forge_status_label.setText(
                "DataForge: cache outdated — click 'Generate Enhancements' to re-extract and update"
            )
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #ff9800;")
        else:
            self._forge_status_label.setText("DataForge: cache up to date ✓")
            self._forge_status_label.setStyleSheet("font-size: 10px; color: #4caf50;")
