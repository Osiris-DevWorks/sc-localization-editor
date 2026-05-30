"""Enhancements tab for Smart Citizen."""
import logging
from dataclasses import replace as dc_replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QSizePolicy,
    QTabWidget, QVBoxLayout, QWidget,
)

from src.gui.tag_mapping_dialog import TagMappingDialog
from src.utils.settings import AppSettings
from src.utils.tag_builder import (
    CATEGORIES, ELEMENT_LABELS, ENCLOSINGS, MAPPED_KIND_NAMES,
    PLACEMENTS, SEPARATORS, STYLES_BY_KIND, TagConfig, default_config,
    render_tag,
)

logger = logging.getLogger(__name__)

# Sample values used by the live preview so the user can see what their
# config will produce without re-running the generator.
_PREVIEW_VALUES: dict[str, dict[str, str]] = {
    "components":   {"class": "Military", "size": "2", "grade": "A", "type": "Shield Generator"},
    "missiles":     {"ordinance": "Infrared", "size": "1"},
    "ship_weapons": {"damage": "Energy",   "size": "2"},
    "commodities":  {"label": "Crafting", "collection": "Collection"},
}
_PREVIEW_NAMES: dict[str, str] = {
    "components":   "FR-76",
    "missiles":     "Marksman I Missile",
    "ship_weapons": "MaxOx NN-14",
    "commodities":  "Agricium",
}
_CATEGORY_LABELS: dict[str, str] = {
    "components":   "Components",
    "missiles":     "Missiles",
    "ship_weapons": "Ship Weapons",
    "commodities":  "Commodities",
}


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
            "Optional features that extend the base localization data: "
            "category toggles for the enhancement generator, a favorites "
            "prefix for the in-game ship list, and a Tag Builder that "
            "customizes the bracketed name tags on components, missiles, "
            "ship weapons, and commodities."
        )
        desc.setProperty("role", "secondary")
        desc.setStyleSheet("font-size: 11px;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        layout.addWidget(self._build_enhancements_group())

        mid_row = QHBoxLayout()
        mid_row.addWidget(self._build_favorites_group())
        mid_row.addWidget(self._build_mission_labels_group(), 1)
        layout.addLayout(mid_row)

        layout.addWidget(self._build_tag_builder_group(), 1)

    # ── Enhancements ─────────────────────────────────────────────────────────

    def _build_enhancements_group(self) -> QGroupBox:
        self.localization_enhancements_group = QGroupBox("Localization Enhancements")
        group = self.localization_enhancements_group
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
        categories_layout = QGridLayout()
        categories_layout.setHorizontalSpacing(24)
        categories_layout.setVerticalSpacing(4)
        column_height = 2
        for idx, (key, label) in enumerate(AppSettings.ENHANCEMENT_LABELS.items()):
            cell_row = idx % column_height
            cell_col = idx // column_height

            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            description = _CATEGORY_DESCRIPTIONS.get(key, "")

            dot = QLabel("●")
            dot.setStyleSheet("color: #999; font-size: 12px;")
            row.addWidget(dot)
            self._enhancements_status_labels[key] = dot

            cb = QCheckBox(label)
            cb.setChecked(AppSettings.get_enhancement_category_enabled(key))
            cb.setStyleSheet("font-size: 11px;")
            cb.toggled.connect(self._on_category_checkbox_changed)
            row.addWidget(cb)
            self._enhancements_checkboxes[key] = cb

            desc = QLabel(description)
            desc.setProperty("role", "secondary")
            desc.setStyleSheet("font-size: 10px;")
            row.addWidget(desc)

            cell = QWidget()
            cell.setLayout(row)
            cell.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            categories_layout.addWidget(cell, cell_row, cell_col)

        categories_layout.setColumnStretch(0, 0)
        categories_layout.setColumnStretch(1, 0)
        categories_layout.setColumnStretch(2, 0)
        categories_layout.setColumnStretch(3, 1)
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
            "(first run takes a few minutes; subsequent runs are fast)."
        )
        self._generate_enhancements_btn.clicked.connect(self.enhancements_pipeline_requested.emit)
        btn_row.addWidget(self._generate_enhancements_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)

        self._forge_status_label = QLabel()
        self._forge_status_label.setProperty("role", "secondary")
        self._forge_status_label.setStyleSheet("font-size: 10px;")
        gl.addWidget(self._forge_status_label)

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
        self.favorites_group = QGroupBox("Favorites")
        group = self.favorites_group
        gl = QVBoxLayout(group)

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

        self.favorite_prefix_combo.view().setMinimumWidth(
            self.favorite_prefix_combo.sizeHint().width() + 20
        )
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

    # ── Mission Labels ──────────────────────────────────────────────────────

    def _build_mission_labels_group(self) -> QGroupBox:
        from PyQt6.QtWidgets import QLineEdit
        self.mission_labels_group = QGroupBox("Mission Labels")
        group = self.mission_labels_group
        gl = QVBoxLayout(group)

        headers = AppSettings.get_mission_headers()
        self._header_inputs: dict[str, QLineEdit] = {}

        # 6 fields in a 3-col × 2-row grid
        d = AppSettings.MISSION_HEADER_DEFAULTS
        fields = [
            ("details",        "Details:",        headers.get("details", d["details"])),
            ("blueprints",     "Blueprints:",     headers.get("blueprints", d["blueprints"])),
            ("items",          "Item rewards:",   headers.get("items", d["items"])),
            ("blueprint_data", "Blueprint data:", headers.get("blueprint_data", d["blueprint_data"])),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(4)
        col_height = 2
        for idx, (key, label_text, value) in enumerate(fields):
            row = idx % col_height
            col = (idx // col_height) * 2
            grid.addWidget(QLabel(label_text), row, col)
            inp = QLineEdit()
            inp.setText(value)
            inp.editingFinished.connect(lambda k=key: self._save_mission_header(k))
            self._header_inputs[key] = inp
            grid.addWidget(inp, row, col + 1)

        # XP label and header tag in the third column pair
        grid.addWidget(QLabel("XP label:"), 0, 4)
        self._rep_xp_label_input = QLineEdit()
        self._rep_xp_label_input.setText(AppSettings.get_rep_xp_label())
        self._rep_xp_label_input.setMaximumWidth(100)
        self._rep_xp_label_input.setToolTip("Label for missions without a rank name (e.g. 'Rep: +100 XP')")
        self._rep_xp_label_input.editingFinished.connect(self._save_rep_xp_label)
        grid.addWidget(self._rep_xp_label_input, 0, 5)

        grid.addWidget(QLabel("Header tag:"), 1, 4)
        self._header_em_combo = QComboBox()
        for tag in ("EM1", "EM2", "EM3", "EM4"):
            self._header_em_combo.addItem(tag, userData=tag)
        current_em = AppSettings.get_mission_header_em_tag()
        for i in range(self._header_em_combo.count()):
            if self._header_em_combo.itemData(i) == current_em:
                self._header_em_combo.setCurrentIndex(i)
                break
        self._header_em_combo.setToolTip("Emphasis tag for section headers (default EM3)")
        self._header_em_combo.currentIndexChanged.connect(self._save_header_em_tag)
        grid.addWidget(self._header_em_combo, 1, 5)

        gl.addLayout(grid)
        return group

    def _save_rep_xp_label(self):
        label = self._rep_xp_label_input.text().strip()
        if not label:
            label = AppSettings.DEFAULT_REP_XP_LABEL
            self._rep_xp_label_input.setText(label)
        AppSettings.set_rep_xp_label(label)

    def _save_mission_header(self, key: str):
        inp = self._header_inputs.get(key)
        if inp:
            val = inp.text().strip()
            if val:
                AppSettings.set_mission_header(key, val)

    def _save_header_em_tag(self):
        tag = self._header_em_combo.currentData()
        if tag:
            AppSettings.set_mission_header_em_tag(tag)

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
        self._generate_enhancements_btn.setEnabled(False)

    def set_operation_idle(self):
        self._generate_enhancements_btn.setEnabled(True)

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

    # ── Tag Builder (issue #31) ──────────────────────────────────────────────

    def _build_tag_builder_group(self) -> QGroupBox:
        """Construct the Tag Builder QGroupBox shown below Favorites.

        Each supported category (components, missiles, ship_weapons) gets a
        tab page with an element list (reorderable via the ▲/▼ buttons),
        per-element style dropdowns, separator/enclosing/placement
        dropdowns, and a live preview. The "Apply Tag Builder" button at
        the bottom persists every page's config and re-runs the enhancement
        generator so the new tags take effect immediately."""
        self.tag_builder_group = QGroupBox("Tag Builder")
        group = self.tag_builder_group
        gl = QVBoxLayout(group)

        desc = QLabel(
            "Customize bracketed name tags. Reorder with ▲/▼, untick to exclude, pick a style, then Apply."
        )
        desc.setProperty("role", "secondary")
        desc.setStyleSheet("font-size: 11px;")
        gl.addWidget(desc)

        self._tag_builder_tabs = QTabWidget()
        self._tag_builder_pages: dict[str, _TagBuilderPage] = {}
        for cat in CATEGORIES:
            cfg = AppSettings.get_tag_config(cat)
            page = _TagBuilderPage(cat, cfg)
            self._tag_builder_pages[cat] = page
            self._tag_builder_tabs.addTab(page, _CATEGORY_LABELS[cat])
        gl.addWidget(self._tag_builder_tabs)

        # Issue #31 follow-up: cross-surface toggle for the inline
        # component annotation inside mission POTENTIAL BLUEPRINTS lists.
        # Default ON preserves v1.4.0 behavior. When off, mission bodies
        # render bare names ("Norfield") even though the same component
        # on the strings tab still shows the configured tag. The toggle
        # is persisted alongside the per-category configs and applied
        # by the same "Apply Tag Changes" button below — no separate
        # save action so the user can't end up with the toggle and the
        # configs out of sync on disk.
        self._annotate_mission_descs_cb = QCheckBox(
            "Annotate components in mission descriptions"
        )
        self._annotate_mission_descs_cb.setChecked(
            AppSettings.get_tag_annotate_mission_descs()
        )
        self._annotate_mission_descs_cb.setToolTip(
            "When checked, the configured [CLASS-Sx-grade] tag is added "
            "to component names inside the POTENTIAL BLUEPRINTS list of "
            "mission descriptions. Uncheck for a cleaner mission body "
            "while keeping the tag on the actual component names elsewhere."
        )
        gl.addWidget(self._annotate_mission_descs_cb)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply Tag Changes")
        apply_btn.setToolTip(
            "Save the Components / Missiles / Ship Weapons tag configs and "
            "re-run the enhancement generator. New tags appear in-game after "
            "the next Apply to game."
        )
        apply_btn.clicked.connect(self._apply_tag_builder)
        btn_row.addWidget(apply_btn)

        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setToolTip(
            "Restore the default pattern, mapping, and ordering for every "
            "category (Components / Missiles / Ship Weapons). Does not save "
            "or regenerate until you click Apply Tag Changes."
        )
        reset_btn.clicked.connect(self._reset_all_tag_builder_pages)
        btn_row.addWidget(reset_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)
        return group

    def _apply_tag_builder(self):
        """Persist every page's TagConfig and kick off enhancement regen."""
        for cat, page in self._tag_builder_pages.items():
            AppSettings.set_tag_config(cat, page.config)
        AppSettings.set_tag_annotate_mission_descs(
            self._annotate_mission_descs_cb.isChecked()
        )
        logger.info("Tag Builder: saved configs for %s", ", ".join(self._tag_builder_pages))
        # Re-run the generator so the new tags show up in the output INIs;
        # MainWindow handles the worker lifecycle + progress UI.
        self.enhancements_pipeline_requested.emit()

    def _reset_all_tag_builder_pages(self):
        """Reset every category's tag config back to its built-in default.

        Resets in-memory only — the user still has to click Apply Tag
        Changes to persist + regenerate. That matches the per-page Edit
        mapping… flow where edits are tentative until Apply.
        """
        for page in self._tag_builder_pages.values():
            page._reset_to_defaults()


# ── Tag Builder helpers ──────────────────────────────────────────────────────
# Row + page widgets live alongside the tab so the live-preview wiring stays
# local. The mapping editor (TagMappingDialog) is in its own module because
# it's a modal dialog and gets reused by all three pages.


class _ElementRow(QWidget):
    """One element row inside a category's reorderable container.

    Holds the live ``ElementSpec`` from the parent's ``TagConfig`` so toggle
    + style-change events mutate the config in place. The page listens to
    ``changed`` to refresh its preview, to ``edit_mapping_requested`` to
    open the ``TagMappingDialog``, and to ``move_up`` / ``move_down`` to
    swap rows in the element list.
    """

    changed = pyqtSignal()
    edit_mapping_requested = pyqtSignal()
    move_up = pyqtSignal()
    move_down = pyqtSignal()

    # Sample raw value used to build dynamic style-dropdown labels for
    # mapped kinds. Picked to match the values in _PREVIEW_VALUES so the
    # dropdown's parenthetical hint matches what the user sees in the
    # preview row below. Unmapped kinds (size, grade) ignore this and use
    # the static STYLES_BY_KIND labels.
    _SAMPLE_MAPPED_RAW: dict[str, str] = {
        "class":      "Military",
        "ordinance":  "Infrared",
        "damage":     "Energy",
        "type":       "Shield Generator",
        "label":      "Crafting",
        "collection": "Collection",
    }

    def __init__(self, spec, mapping: dict | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.spec = spec  # ElementSpec from src.utils.tag_builder
        self._mapping = mapping or {}
        # Lock vertical size so the page's QVBoxLayout can't stretch a
        # single row to fill the tab — that's the symptom that produced
        # the overlapping-text bug.
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QHBoxLayout(self)
        row.setContentsMargins(4, 2, 4, 2)
        row.setSpacing(8)

        # Up/down reorder buttons, leading the row so users can't miss them.
        # QPushButton (not QToolButton) so they have visible chrome under
        # every theme; explicit width to keep them stacked tightly.
        self.up_btn = QPushButton("▲")
        self.up_btn.setToolTip("Move this element up")
        self.up_btn.setFixedSize(28, 26)
        self.up_btn.clicked.connect(self.move_up.emit)
        row.addWidget(self.up_btn)

        self.down_btn = QPushButton("▼")
        self.down_btn.setToolTip("Move this element down")
        self.down_btn.setFixedSize(28, 26)
        self.down_btn.clicked.connect(self.move_down.emit)
        row.addWidget(self.down_btn)

        self.enable_cb = QCheckBox()
        self.enable_cb.setChecked(spec.enabled)
        self.enable_cb.setToolTip("Untick to exclude this element from the tag")
        self.enable_cb.toggled.connect(self._on_enabled_toggled)
        row.addWidget(self.enable_cb)

        self.label = QLabel(ELEMENT_LABELS.get(spec.kind, spec.kind))
        self.label.setMinimumWidth(90)
        row.addWidget(self.label)

        self.style_combo = QComboBox()
        for style_key, style_label in STYLES_BY_KIND.get(spec.kind, ()):
            self.style_combo.addItem(
                self._build_style_label(spec.kind, style_key, style_label),
                userData=style_key,
            )
        target_idx = 0
        for i in range(self.style_combo.count()):
            if self.style_combo.itemData(i) == spec.style:
                target_idx = i
                break
        self.style_combo.setCurrentIndex(target_idx)
        if self.style_combo.currentData() is not None:
            self.spec.style = self.style_combo.currentData()
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        row.addWidget(self.style_combo)

        # Only kinds backed by the per-category variant mapping get the
        # mapping-edit button — size and grade are derived from raw values
        # and have nothing user-editable beyond style.
        if spec.kind in MAPPED_KIND_NAMES:
            edit_btn = QPushButton("Edit mapping…")
            _tips = {
                "ordinance": ("Edit the Short / Medium / Long text used for each tracking "
                              "type (e.g. Infrared → I / IR / Infrared)."),
                "damage":    ("Edit the Short / Medium / Long text used for each damage "
                              "type (e.g. Energy → E / EN / Energy)."),
                "type":      ("Edit the Short / Medium / Long text used for each component "
                              "type (e.g. Shield Generator → SH / SHLD / Shield)."),
                "label":     ("Edit the Short / Medium / Long text for the crafting label "
                              "(e.g. Crafting → CF / Craft / Crafting)."),
                "collection": ("Edit the Short / Medium / Long text for the collection label "
                               "(e.g. Collection → Col / Collect / Collection)."),
            }
            edit_btn.setToolTip(_tips.get(spec.kind,
                "Edit the Short / Medium / Long text used for each class "
                "(e.g. Military → M / MIL / Military)."))
            edit_btn.clicked.connect(self.edit_mapping_requested.emit)
            row.addWidget(edit_btn)

        row.addStretch()

    def _on_enabled_toggled(self, checked: bool):
        self.spec.enabled = bool(checked)
        # Dim the row so disabled state is visually obvious.
        self.label.setEnabled(checked)
        self.style_combo.setEnabled(checked)
        self.changed.emit()

    def _on_style_changed(self, _idx: int):
        data = self.style_combo.currentData()
        if data is not None:
            self.spec.style = data
            self.changed.emit()

    def set_move_enabled(self, can_up: bool, can_down: bool) -> None:
        self.up_btn.setEnabled(can_up)
        self.down_btn.setEnabled(can_down)

    def _build_style_label(self, kind: str, style_key: str, fallback: str) -> str:
        """Return the dropdown label for a style.

        For mapped kinds (class/ordinance/damage), build the label from the
        current user mapping so an edit like Military Short → "ML" shows up
        as "Short (ML)" instead of the baked-in "Short (M)". For unmapped
        kinds (size/grade) the static STYLES_BY_KIND label is the natural
        thing to show.
        """
        sample = self._SAMPLE_MAPPED_RAW.get(kind)
        if sample is None:
            return fallback
        variants = self._mapping.get(sample)
        if not variants:
            return fallback
        idx_by_style = {"short": 0, "med": 1, "long": 2}
        idx = idx_by_style.get(style_key, 1)
        try:
            variant_text = variants[idx]
        except IndexError:
            return fallback
        # Strip the parenthetical sample from the fallback label
        # ("Short (M)" → "Short") and re-attach with the live mapping value.
        base = fallback.split(" (")[0]
        return f"{base} ({variant_text})"


class _TagBuilderPage(QWidget):
    """One category's Tag Builder page (element list + separator/enclosing
    dropdowns + live preview + Reset button)."""

    def __init__(self, category: str, config: TagConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self.category = category
        self.config = config
        self._rows: list[_ElementRow] = []

        # Rows + separator/preview/reset go directly into the page's own
        # QVBoxLayout. An earlier iteration wrapped this in a QScrollArea
        # to avoid forcing a hard minimum height up the widget tree (which
        # was squeezing the main window's footer), but the scroll area
        # introduced its own dark "Base" palette background and made the
        # Apply Tag Builder button render against the group-box border.
        # With the Localization Enhancements section now using a two-column
        # grid (freeing ~84px of vertical space), the natural layout
        # comfortably fits without needing scroll/min-height tricks.
        top = QHBoxLayout(self)
        top.setContentsMargins(8, 4, 8, 4)
        top.setSpacing(12)

        # ── Left: element rows ────────────────────────────────────────
        self._rows_column = QVBoxLayout()
        self._rows_column.setSpacing(2)
        self._page_layout = self._rows_column
        self._rows_insert_at = 0
        self._repopulate_list()
        self._rows_column.addStretch()
        top.addLayout(self._rows_column, 0)

        # ── Right: controls + preview ─────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(4)

        ctrl_grid = QGridLayout()
        ctrl_grid.setVerticalSpacing(4)
        ctrl_grid.setHorizontalSpacing(6)

        ctrl_grid.addWidget(QLabel("Separator:"), 0, 0)
        self.sep_combo = QComboBox()
        for key, label, _ in SEPARATORS:
            # Commodities can't use "none": with two flags it would mash them
            # into "[CFCollection]", and get_tag_config force-upgrades a stored
            # "none" to "pipe", so don't offer it here (#97).
            if self.category == "commodities" and key == "none":
                continue
            self.sep_combo.addItem(label, userData=key)
        self._select_combo(self.sep_combo, config.separator)
        self.sep_combo.currentIndexChanged.connect(self._on_sep_changed)
        ctrl_grid.addWidget(self.sep_combo, 0, 1)

        ctrl_grid.addWidget(QLabel("Enclosing:"), 1, 0)
        self.enc_combo = QComboBox()
        for key, label, _open, _close in ENCLOSINGS:
            self.enc_combo.addItem(label, userData=key)
        self._select_combo(self.enc_combo, config.enclosing)
        self.enc_combo.currentIndexChanged.connect(self._on_enc_changed)
        ctrl_grid.addWidget(self.enc_combo, 1, 1)

        ctrl_grid.addWidget(QLabel("Placement:"), 2, 0)
        self.placement_combo = QComboBox()
        for key, label in PLACEMENTS:
            self.placement_combo.addItem(label, userData=key)
        self._select_combo(self.placement_combo, config.placement)
        self.placement_combo.currentIndexChanged.connect(self._on_placement_changed)
        ctrl_grid.addWidget(self.placement_combo, 2, 1)

        right.addLayout(ctrl_grid)

        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(28)
        self.preview_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; padding: 4px; "
            "background: rgba(0, 0, 0, 30); border-radius: 3px;"
        )
        right.addWidget(self.preview_label)
        right.addStretch()
        top.addLayout(right, 0)
        top.addStretch(1)

        self._refresh_preview()

    # ── Row population + reorder ─────────────────────────────────────────

    # Fixed pixel height for each row widget; pinned on the row itself
    # (setFixedHeight below) so the page's QVBoxLayout can't stretch it
    # on first show.
    _ROW_H = 32

    def _repopulate_list(self) -> None:
        """Rebuild the row widgets from ``self.config.elements`` in order.

        Rows live directly in ``self._page_layout`` between the hint label
        and the separator/enclosing/placement row — no nested container.
        Insertion index is tracked in ``self._rows_insert_at`` and stays
        valid because we remove every existing row before adding new ones.
        """
        # Remove every existing row from the layout + delete the widget.
        for row in self._rows:
            self._page_layout.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        insert_at = self._rows_insert_at
        for idx, spec in enumerate(self.config.elements):
            row_widget = _ElementRow(spec, mapping=self.config.class_mapping)
            row_widget.setFixedHeight(self._ROW_H)
            row_widget.changed.connect(self._refresh_preview)
            row_widget.edit_mapping_requested.connect(
                lambda _checked=False, k=spec.kind: self._open_mapping_dialog(k)
            )
            row_widget.move_up.connect(lambda i=idx: self._move_row(i, -1))
            row_widget.move_down.connect(lambda i=idx: self._move_row(i, +1))
            # Initial enabled-state visual sync — the row constructor sets
            # checkbox state but doesn't fire toggled, so dim styling is
            # applied here.
            row_widget.label.setEnabled(spec.enabled)
            row_widget.style_combo.setEnabled(spec.enabled)
            self._page_layout.insertWidget(insert_at + idx, row_widget)
            self._rows.append(row_widget)

        # Disable the up-arrow on the first row and down-arrow on the
        # last, so users can't move rows off the ends.
        n = max(len(self._rows), 1)
        for i, r in enumerate(self._rows):
            r.set_move_enabled(can_up=(i > 0), can_down=(i < n - 1))

        # Equalize style-combo and label widths across all rows so columns
        # line up visually.
        if self._rows:
            max_combo = max(r.style_combo.sizeHint().width() for r in self._rows)
            max_label = max(r.label.sizeHint().width() for r in self._rows)
            for r in self._rows:
                r.style_combo.setMinimumWidth(max_combo)
                r.label.setMinimumWidth(max_label)

    def _move_row(self, index: int, delta: int) -> None:
        """Swap ``self.config.elements[index]`` with its neighbor at
        ``index + delta`` (delta is -1 or +1) and rebuild the row list."""
        target = index + delta
        if target < 0 or target >= len(self.config.elements):
            return
        elems = self.config.elements
        elems[index], elems[target] = elems[target], elems[index]
        self._repopulate_list()
        self._refresh_preview()

    # ── Separator/Enclosing change handlers ──────────────────────────────

    def _on_sep_changed(self, _idx: int):
        data = self.sep_combo.currentData()
        if data is not None:
            self.config.separator = data
            self._refresh_preview()

    def _on_enc_changed(self, _idx: int):
        data = self.enc_combo.currentData()
        if data is not None:
            self.config.enclosing = data
            self._refresh_preview()

    def _on_placement_changed(self, _idx: int):
        data = self.placement_combo.currentData()
        if data is not None:
            self.config.placement = data
            self._refresh_preview()

    # ── Mapping editor ───────────────────────────────────────────────────

    def _open_mapping_dialog(self, kind: str | None = None):
        """Open the variant-mapping editor for a specific element kind.

        Filters the shared class_mapping to only the keys belonging to
        *kind* so the user sees Class entries OR Type entries, not both.
        On accept, merges the edited subset back into the full mapping."""
        from src.utils.tag_builder import DEFAULT_KIND_MAPPINGS
        kind_defaults = DEFAULT_KIND_MAPPINGS.get(kind, {})
        # Keys that belong to OTHER kinds — exclude them from this dialog.
        other_keys = set()
        for other_kind, other_map in DEFAULT_KIND_MAPPINGS.items():
            if other_kind != kind:
                other_keys.update(other_map.keys())
        kind_mapping = {k: v for k, v in self.config.class_mapping.items() if k not in other_keys}

        kind_label = ELEMENT_LABELS.get(kind, kind or self.category)
        title = f"Edit {kind_label} variants"
        dialog = TagMappingDialog(
            kind_mapping, kind_defaults, title, parent=self,
        )
        if dialog.exec():
            result = dialog.result_mapping()
            for k in list(self.config.class_mapping):
                if k not in other_keys:
                    del self.config.class_mapping[k]
            self.config.class_mapping.update(result)
            self._repopulate_list()
            self._refresh_preview()

    # ── Preview ──────────────────────────────────────────────────────────

    def _refresh_preview(self):
        tag = render_tag(self.config, _PREVIEW_VALUES.get(self.category, {}))
        name = _PREVIEW_NAMES.get(self.category, "Sample")
        if tag:
            if self.config.placement == "append":
                self.preview_label.setText(f"Preview:  {name} {tag}")
            else:
                self.preview_label.setText(f"Preview:  {tag} {name}")
        else:
            self.preview_label.setText(f"Preview:  {name}   (no tag — every element is empty or disabled)")

    # ── Reset ────────────────────────────────────────────────────────────

    def _reset_to_defaults(self):
        # Replace this page's config with a fresh default, rebuild the
        # row list, resync separator/enclosing/placement combos + preview.
        fresh = default_config(self.category)
        self.config = fresh
        self._select_combo(self.sep_combo, fresh.separator)
        self._select_combo(self.enc_combo, fresh.enclosing)
        self._select_combo(self.placement_combo, fresh.placement)
        self._repopulate_list()
        self._refresh_preview()

    @staticmethod
    def _select_combo(combo: QComboBox, key: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == key:
                combo.setCurrentIndex(i)
                return
