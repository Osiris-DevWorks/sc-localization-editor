"""Enhancements tab for Smart Citizen."""
import logging
from dataclasses import replace as dc_replace

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QTabWidget, QVBoxLayout, QWidget,
)

from src.gui.tag_mapping_dialog import TagMappingDialog
from src.utils.i18n import tr
from src.utils.settings import AppSettings
from src.utils.tag_builder import (
    CATEGORIES, ELEMENT_LABELS, ENCLOSINGS, LOCATION_DETAILS,
    MAPPED_KIND_NAMES, MISSION_TITLE_PLACEMENTS, PLACEMENTS, ROUTE_ARROWS,
    SEPARATORS, SIZE_ABBREVIATIONS, STYLES_BY_KIND, TITLE_SEPARATORS, TagConfig,
    USAGE_INPUT_SEP, abbreviate_title, apply_mission_title, default_config,
    render_route, render_tag, route_enabled,
)

logger = logging.getLogger(__name__)


class _NoScrollComboBox(QComboBox):
    """A combo box that ignores the mouse wheel unless it has focus (#197).

    The Enhancements tab lives in a scroll area with many dropdowns; by default
    a wheel scroll over an unfocused combo changes its selection instead of
    scrolling the page. StrongFocus stops the wheel from focusing the combo, and
    wheelEvent passes the scroll through to the page when the combo isn't focused.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event):  # noqa: N802 (Qt override)
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


# Sample values used by the live preview so the user can see what their
# config will produce without re-running the generator.
_PREVIEW_VALUES: dict[str, dict[str, str]] = {
    "components":   {"class": "Military", "size": "2", "grade": "A", "type": "Shield Generator"},
    "missiles":     {"ordinance": "Infrared", "size": "1"},
    "ship_weapons": {"damage": "Energy",   "size": "2"},
    "commodities":  {"label": "Crafting",
                     "usage": USAGE_INPUT_SEP.join(["Quantum Drive", "Shield"]),
                     "collection": "Collection"},
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
    "mission_titles": "Mission Titles",
}


class EnhancementsTab(QWidget):
    """Tab for optional enhancements: localization enhancements and ship favorites."""

    merge_requested = pyqtSignal()
    enhancements_pipeline_requested = pyqtSignal()   # extract DataForge if needed, then generate enhancements
    # The owned-blueprint set changed via the Blueprints shuttle (#157 follow-up).
    # MainWindow re-weaves [Owned] tags into the strings table and refreshes it.
    owned_items_changed = pyqtSignal()
    # (old_prefix, new_prefix) — the favourite sort prefix changed. MainWindow
    # re-prefixes in-memory favourites to match the migrated user.ini before
    # reloading, so the reload's pending-edit snapshot doesn't clobber the new
    # prefix back to the old one (#140).
    favorite_prefix_changed = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self._loaded_prefix = AppSettings.get_favorite_prefix()
        self.setup_ui()

    def setup_ui(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self._title_label = QLabel(tr("enhancements.title"))
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        layout.addWidget(self._title_label)

        self._desc_label = QLabel(tr("enhancements.desc"))
        self._desc_label.setProperty("role", "secondary")
        self._desc_label.setStyleSheet("font-size: 11px;")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)

        self._enhancements_group = self._build_enhancements_group()
        layout.addWidget(self._enhancements_group)

        mid_row = QHBoxLayout()
        self._favorites_group = self._build_favorites_group()
        mid_row.addWidget(self._favorites_group)
        mid_row.addWidget(self._build_mission_labels_group(), 1)
        layout.addLayout(mid_row)

        self._tag_builder_group = self._build_tag_builder_group()
        layout.addWidget(self._tag_builder_group, 1)

        self._blueprints_group = self._build_blueprints_group()
        layout.addWidget(self._blueprints_group)
        layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.viewport().setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    # ── Enhancements ─────────────────────────────────────────────────────────

    def _build_enhancements_group(self) -> QGroupBox:
        group = QGroupBox(tr("enhancements.enhancements_group"))
        self._enhancements_group_box = group
        gl = QVBoxLayout(group)

        self._enhancements_desc_label = QLabel(tr("enhancements.enhancements_desc"))
        self._enhancements_desc_label.setProperty("role", "secondary")
        self._enhancements_desc_label.setStyleSheet("font-size: 11px;")
        self._enhancements_desc_label.setWordWrap(True)
        gl.addWidget(self._enhancements_desc_label)

        # Per-category checkbox + description + status dot
        _CATEGORY_DESCRIPTIONS = {
            "ships":       tr("enhancements.cat_desc_ships"),
            "ship_items":  tr("enhancements.cat_desc_ship_items"),
            "gear":        tr("enhancements.cat_desc_gear"),
            "missions":    tr("enhancements.cat_desc_missions"),
            "commodities": tr("enhancements.cat_desc_commodities"),
            "journal":     tr("enhancements.cat_desc_journal"),
        }

        self._enhancements_status_labels: dict = {}
        self._enhancements_checkboxes: dict = {}
        self._cat_desc_labels: dict = {}
        # Two-column grid: column-major fill so the first three categories
        # stack down the left column and the next three down the right —
        # reads top-to-bottom-then-right rather than left-to-right.
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
            self._cat_desc_labels[key] = desc

            cell = QWidget()
            cell.setLayout(row)
            cell.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
            categories_layout.addWidget(cell, cell_row, cell_col)

        categories_layout.setColumnStretch(0, 0)
        categories_layout.setColumnStretch(1, 0)
        categories_layout.setColumnStretch(2, 0)
        categories_layout.setColumnStretch(3, 1)
        gl.addLayout(categories_layout)

        # ── Mission detail fields (#121) ───────────────────────────────────
        # Granular show/hide for each line the generator adds to a mission
        # DETAILS body. Persisted on toggle; baked at generation time, so a
        # change takes effect on the next Generate Enhancements run. Labels are
        # hardcoded English to match the sibling Mission Labels group.
        mf_heading = QLabel("Mission detail fields:")
        mf_heading.setStyleSheet("font-size: 11px; font-weight: bold;")
        gl.addWidget(mf_heading)

        _MISSION_FIELD_LABELS = [
            ("mission_type",  "Mission Type"),
            ("difficulty",    "Difficulty"),
            ("spawns",        "Hostiles"),
            ("reputation",    "Reputation"),
            ("blueprints",    "Blueprints"),
            ("blueprint_tag", "Blueprint Tag"),
            ("ace",           "Ace Pilot Tag"),
        ]
        # The blueprint_tag field controls the [BP]/[BP?] marker on the mission
        # TITLE, not a body line — it gets its own tooltip. Turning the body
        # section off while leaving the title tag on is intentional (compact
        # at-a-glance signal); the two are independent so the user picks.
        _MISSION_FIELD_TOOLTIPS = {
            "blueprint_tag": (
                "Show the [BP] / [BP?] marker on the mission title. "
                "Independent of the Blueprints body section. "
                "Takes effect on the next Generate Enhancements."
            ),
            "ace": (
                "Flag missions that spawn an ace pilot with an [ACE] title tag "
                "([ACE?] when only some variants of that mission do). "
                "Takes effect on the next Generate Enhancements."
            ),
        }
        self._mission_field_checkboxes: dict = {}
        _mf_saved = AppSettings.get_mission_detail_fields()
        mf_row = QHBoxLayout()
        mf_row.setContentsMargins(0, 0, 0, 0)
        for _field, _label in _MISSION_FIELD_LABELS:
            cb = QCheckBox(_label)
            cb.setChecked(_mf_saved.get(_field, True))
            cb.setStyleSheet("font-size: 11px;")
            cb.setToolTip(
                _MISSION_FIELD_TOOLTIPS.get(
                    _field,
                    f"Show the {_label} line in generated mission bodies. "
                    "Takes effect on the next Generate Enhancements.",
                )
            )
            cb.toggled.connect(
                lambda checked, f=_field: self._on_mission_field_toggled(f, checked)
            )
            mf_row.addWidget(cb)
            self._mission_field_checkboxes[_field] = cb
        mf_row.addStretch()
        gl.addLayout(mf_row)

        mf_note = QLabel(
            "Unchecked fields are left out of mission descriptions. "
            "Applies on the next Generate Enhancements."
        )
        mf_note.setProperty("role", "secondary")
        mf_note.setStyleSheet("font-size: 10px;")
        mf_note.setWordWrap(True)
        gl.addWidget(mf_note)

        # #153: place the stats block above the prose description (for ship and
        # component/weapon entries), so the useful numbers sit at the top when
        # comparing modules in the Hologlass. Baked at generation time.
        self._stats_prepend_check = QCheckBox("Show stats above description")
        self._stats_prepend_check.setChecked(AppSettings.get_stats_prepend())
        self._stats_prepend_check.setStyleSheet("font-size: 11px;")
        self._stats_prepend_check.setToolTip(
            "Put the generated stats block above the manufacturer/PR description "
            "instead of below it (ships, components, weapons). Takes effect on "
            "the next Generate Enhancements."
        )
        self._stats_prepend_check.toggled.connect(
            lambda checked: AppSettings.set_stats_prepend(checked)
        )
        gl.addWidget(self._stats_prepend_check)

        self._standardize_ship_names_check = QCheckBox("Standardize earnable ship names")
        self._standardize_ship_names_check.setChecked(
            AppSettings.get_standardize_earnable_ship_names()
        )
        self._standardize_ship_names_check.setStyleSheet("font-size: 11px;")
        self._standardize_ship_names_check.setToolTip(
            "Rename exec-hangar (PYX) and Wikelo (WIK) ship variants to include "
            "a suffix that distinguishes them from the standard pledge-store version "
            "(e.g. \"Anvil F8C Lightning PYX\"). Takes effect on the next Generate Enhancements."
        )
        self._standardize_ship_names_check.toggled.connect(
            lambda checked: AppSettings.set_standardize_earnable_ship_names(checked)
        )
        gl.addWidget(self._standardize_ship_names_check)

        btn_row = QHBoxLayout()

        self._apply_categories_btn = QPushButton(tr("enhancements.apply_btn"))
        self._apply_categories_btn.setMaximumWidth(100)
        self._apply_categories_btn.setEnabled(False)
        self._apply_categories_btn.setToolTip(
            "Save category selection. Unchecked categories will be disabled."
        )
        self._apply_categories_btn.clicked.connect(self._apply_category_changes)
        btn_row.addWidget(self._apply_categories_btn)

        self._generate_enhancements_btn = QPushButton(tr("enhancements.generate_btn"))
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

    def _on_mission_field_toggled(self, field: str, checked: bool) -> None:
        """Persist a mission-detail field toggle (#121). Baked at generation
        time, so the change shows up after the next Generate Enhancements."""
        AppSettings.set_mission_detail_field(field, checked)

    # ── Favorites ─────────────────────────────────────────────────────────────

    def _build_favorites_group(self) -> QGroupBox:
        group = QGroupBox(tr("enhancements.favorites_group"))
        self._favorites_group_box = group
        gl = QVBoxLayout(group)

        self._favorites_desc_label = QLabel(tr("enhancements.favorites_desc"))
        self._favorites_desc_label.setProperty("role", "secondary")
        self._favorites_desc_label.setStyleSheet("font-size: 11px;")
        self._favorites_desc_label.setWordWrap(True)
        gl.addWidget(self._favorites_desc_label)


        prefix_row = QHBoxLayout()
        self._sort_prefix_label = QLabel(tr("enhancements.sort_prefix_label"))
        prefix_row.addWidget(self._sort_prefix_label)

        self.favorite_prefix_combo = _NoScrollComboBox()
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

        self._apply_prefix_btn = QPushButton(tr("enhancements.apply_btn"))
        self._apply_prefix_btn.setToolTip(
            "Save the selected prefix and update all existing favorites to use it"
        )
        self._apply_prefix_btn.clicked.connect(self._apply_favorite_prefix)
        prefix_row.addWidget(self._apply_prefix_btn)

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

        grid.addWidget(QLabel("Header style:"), 1, 4)
        self._header_em_combo = _NoScrollComboBox()
        # #164: show what the tags actually do in-game (EM3 underlines, EM4
        # renders blue) instead of the opaque EM3/EM4 names. The stored value
        # stays the EM tag, so the generator output is unchanged.
        _EM_LABELS = {"EM3": "Underline", "EM4": "Blue text"}
        for tag in AppSettings.MISSION_HEADER_EM_TAGS:
            self._header_em_combo.addItem(_EM_LABELS.get(tag, tag), userData=tag)
        current_em = AppSettings.get_mission_header_em_tag()
        for i in range(self._header_em_combo.count()):
            if self._header_em_combo.itemData(i) == current_em:
                self._header_em_combo.setCurrentIndex(i)
                break
        self._header_em_combo.setToolTip("Style for section headers: Underline (EM3) or Blue text (EM4)")
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
                    QMessageBox.critical(self, tr("dialogs.error_title"), f"Failed to update favorites: {e}")
                    return

        AppSettings.set_favorite_prefix(new_prefix)
        self._loaded_prefix = new_prefix
        # Hand the old/new prefix to MainWindow so it can re-prefix in-memory
        # favourites before the reload (see signal doc). Emitting merge_requested
        # alone would let the pending-edit snapshot restore the old prefix.
        self.favorite_prefix_changed.emit(old_prefix, new_prefix)

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
        group = QGroupBox(tr("enhancements.tag_builder_group"))
        self._tag_builder_group_box = group
        gl = QVBoxLayout(group)

        self._tag_builder_desc_label = QLabel(tr("enhancements.tag_builder_desc"))
        self._tag_builder_desc_label.setProperty("role", "secondary")
        self._tag_builder_desc_label.setStyleSheet("font-size: 11px;")
        self._tag_builder_desc_label.setWordWrap(True)
        gl.addWidget(self._tag_builder_desc_label)

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
            tr("enhancements.annotate_mission_descs_cb")
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
        self._apply_tag_btn = QPushButton(tr("enhancements.apply_tag_changes_btn"))
        self._apply_tag_btn.setToolTip(
            "Save the Components / Missiles / Ship Weapons tag configs and "
            "re-run the enhancement generator. New tags appear in-game after "
            "the next Apply Enhancements."
        )
        self._apply_tag_btn.clicked.connect(self._apply_tag_builder)
        btn_row.addWidget(self._apply_tag_btn)

        self._reset_tag_btn = QPushButton(tr("enhancements.reset_defaults_btn"))
        self._reset_tag_btn.setToolTip(
            "Restore the default pattern, mapping, and ordering for every "
            "category (Components / Missiles / Ship Weapons). Does not save "
            "or regenerate until you click Apply Tag Changes."
        )
        self._reset_tag_btn.clicked.connect(self._reset_all_tag_builder_pages)
        btn_row.addWidget(self._reset_tag_btn)

        btn_row.addStretch()
        gl.addLayout(btn_row)
        return group

    # ── Retranslation ─────────────────────────────────────────────────────────

    def retranslate_ui(self) -> None:
        """Re-apply tr() to every text-bearing widget after a language switch."""
        self._title_label.setText(tr("enhancements.title"))
        self._desc_label.setText(tr("enhancements.desc"))
        self._enhancements_group_box.setTitle(tr("enhancements.enhancements_group"))
        self._enhancements_desc_label.setText(tr("enhancements.enhancements_desc"))
        self._apply_categories_btn.setText(tr("enhancements.apply_btn"))
        self._generate_enhancements_btn.setText(tr("enhancements.generate_btn"))
        _CAT_KEYS = {
            "ships":       "enhancements.cat_desc_ships",
            "ship_items":  "enhancements.cat_desc_ship_items",
            "gear":        "enhancements.cat_desc_gear",
            "missions":    "enhancements.cat_desc_missions",
            "commodities": "enhancements.cat_desc_commodities",
            "journal":     "enhancements.cat_desc_journal",
        }
        for key, lbl in self._cat_desc_labels.items():
            if key in _CAT_KEYS:
                lbl.setText(tr(_CAT_KEYS[key]))
        self._favorites_group_box.setTitle(tr("enhancements.favorites_group"))
        self._favorites_desc_label.setText(tr("enhancements.favorites_desc"))
        self._sort_prefix_label.setText(tr("enhancements.sort_prefix_label"))
        self._apply_prefix_btn.setText(tr("enhancements.apply_btn"))
        self._tag_builder_group_box.setTitle(tr("enhancements.tag_builder_group"))
        self._tag_builder_desc_label.setText(tr("enhancements.tag_builder_desc"))
        self._annotate_mission_descs_cb.setText(tr("enhancements.annotate_mission_descs_cb"))
        self._apply_tag_btn.setText(tr("enhancements.apply_tag_changes_btn"))
        self._reset_tag_btn.setText(tr("enhancements.reset_defaults_btn"))
        self._blueprints_group_box.setTitle(tr("enhancements.blueprints_group"))
        self._blueprints_desc_label.setText(tr("enhancements.blueprints_desc"))
        self._blueprints_empty_note.setText(tr("enhancements.blueprints_empty_note"))
        self._blueprints_search.setPlaceholderText(tr("enhancements.blueprints_search_placeholder"))
        self._blueprints_mission_label.setText(tr("enhancements.blueprints_mission_label"))
        self._blueprints_filter_note.setText(tr("enhancements.blueprints_filter_note"))
        self._blueprints_available_label.setText(tr("enhancements.blueprints_available_label"))
        self._blueprints_owned_label.setText(tr("enhancements.blueprints_owned_label"))
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        for label_key, lbl in self._blueprints_facet_labels.items():
            lbl.setText(tr(label_key))

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

    # ── Blueprints (#157 follow-up) ──────────────────────────────────────────

    def _build_blueprints_group(self) -> QGroupBox:
        """Construct the Blueprints shuttle shown below Tag Builder.

        A search-filtered list of every item that appears in a mission's
        POTENTIAL BLUEPRINTS reward on the left, the items the user owns on the
        right, and arrow buttons to move multi-selected items between them.
        This replaces toggling the Owned star in the strings table; the table's
        Owned column is now a read-only indicator. The available universe is
        fed in by MainWindow via ``set_blueprint_items`` (it is computed from
        the loaded mission strings, which this tab can't see).
        """
        group = QGroupBox(tr("enhancements.blueprints_group"))
        self._blueprints_group_box = group
        gl = QVBoxLayout(group)

        self._blueprints_desc_label = QLabel(tr("enhancements.blueprints_desc"))
        self._blueprints_desc_label.setProperty("role", "secondary")
        self._blueprints_desc_label.setStyleSheet("font-size: 11px;")
        self._blueprints_desc_label.setWordWrap(True)
        gl.addWidget(self._blueprints_desc_label)

        # Shown instead of the lists when no blueprint items exist yet (mission
        # enhancements not generated) — the same precondition the stars had.
        self._blueprints_empty_note = QLabel(tr("enhancements.blueprints_empty_note"))
        self._blueprints_empty_note.setProperty("role", "secondary")
        self._blueprints_empty_note.setStyleSheet("font-size: 11px; font-style: italic;")
        self._blueprints_empty_note.setWordWrap(True)
        gl.addWidget(self._blueprints_empty_note)

        self._blueprints_search = QLineEdit()
        self._blueprints_search.setPlaceholderText(
            tr("enhancements.blueprints_search_placeholder")
        )
        self._blueprints_search.setClearButtonEnabled(True)
        self._blueprints_search.textChanged.connect(self._refilter_blueprints_available)
        gl.addWidget(self._blueprints_search)

        mission_row = QHBoxLayout()
        self._blueprints_mission_label = QLabel(tr("enhancements.blueprints_mission_label"))
        self._blueprints_mission_label.setProperty("role", "secondary")
        mission_row.addWidget(self._blueprints_mission_label)
        self._blueprints_mission_combo = _NoScrollComboBox()
        self._blueprints_mission_combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        self._blueprints_mission_combo.currentIndexChanged.connect(
            self._refilter_blueprints_available
        )
        mission_row.addWidget(self._blueprints_mission_combo, 1)
        gl.addLayout(mission_row)

        # Component-attribute facets. Each combo's first row is "Any" (data
        # None); the rest are enumerated from the loaded metadata. Attributes
        # exist only for ship components, so the coverage note sets expectations.
        facet_row = QHBoxLayout()
        self._blueprints_facet_combos = {}
        for attr, label_key in (
            ("type", "enhancements.blueprints_facet_type"),
            ("cls", "enhancements.blueprints_facet_class"),
            ("size", "enhancements.blueprints_facet_size"),
            ("grade", "enhancements.blueprints_facet_grade"),
        ):
            lbl = QLabel(tr(label_key))
            lbl.setProperty("role", "secondary")
            combo = _NoScrollComboBox()
            combo.addItem(tr("enhancements.blueprints_facet_any"), None)
            combo.currentIndexChanged.connect(self._refilter_blueprints_available)
            self._blueprints_facet_combos[attr] = combo
            self._blueprints_facet_labels = getattr(self, "_blueprints_facet_labels", {})
            self._blueprints_facet_labels[label_key] = lbl
            facet_row.addWidget(lbl)
            facet_row.addWidget(combo, 1)
        gl.addLayout(facet_row)

        self._blueprints_filter_note = QLabel(tr("enhancements.blueprints_filter_note"))
        self._blueprints_filter_note.setProperty("role", "secondary")
        self._blueprints_filter_note.setStyleSheet("font-size: 10px;")
        self._blueprints_filter_note.setWordWrap(True)
        gl.addWidget(self._blueprints_filter_note)

        lists_row = QHBoxLayout()

        avail_col = QVBoxLayout()
        self._blueprints_available_label = QLabel(
            tr("enhancements.blueprints_available_label")
        )
        avail_col.addWidget(self._blueprints_available_label)
        self._blueprints_available_list = QListWidget()
        self._blueprints_available_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_available_list.itemDoubleClicked.connect(
            lambda _it: self._own_selected_blueprints()
        )
        avail_col.addWidget(self._blueprints_available_list)
        lists_row.addLayout(avail_col, 1)

        arrows = QVBoxLayout()
        arrows.addStretch()
        self._blueprints_add_btn = QPushButton("→")  # →
        self._blueprints_add_btn.setToolTip(tr("enhancements.blueprints_add_tooltip"))
        self._blueprints_add_btn.clicked.connect(self._own_selected_blueprints)
        arrows.addWidget(self._blueprints_add_btn)
        self._blueprints_remove_btn = QPushButton("←")  # ←
        self._blueprints_remove_btn.setToolTip(tr("enhancements.blueprints_remove_tooltip"))
        self._blueprints_remove_btn.clicked.connect(self._unown_selected_blueprints)
        arrows.addWidget(self._blueprints_remove_btn)
        arrows.addStretch()
        lists_row.addLayout(arrows)

        owned_col = QVBoxLayout()
        self._blueprints_owned_label = QLabel(
            tr("enhancements.blueprints_owned_label")
        )
        owned_col.addWidget(self._blueprints_owned_label)
        self._blueprints_owned_list = QListWidget()
        self._blueprints_owned_list.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self._blueprints_owned_list.itemDoubleClicked.connect(
            lambda _it: self._unown_selected_blueprints()
        )
        owned_col.addWidget(self._blueprints_owned_list)
        lists_row.addLayout(owned_col, 1)

        gl.addLayout(lists_row)

        # name -> BlueprintItem (or None for a bare name), set by MainWindow.
        # Owned state itself lives in AppSettings (single source of truth).
        self._blueprint_meta: dict = {}
        self._render_blueprint_lists()
        return group

    @staticmethod
    def _available_blueprints(all_names, owned) -> list:
        """Blueprint items not yet owned, sorted case-insensitively.

        Pure (Qt-free) so the available/owned split is unit-testable. Accepts a
        name iterable or a ``{name: meta}`` mapping (dict keys are the names).
        """
        return sorted(set(all_names) - set(owned), key=str.lower)

    def set_blueprint_items(self, meta) -> None:
        """Receive the blueprint-item metadata from MainWindow.

        *meta* is ``{name: BlueprintItem}`` (a bare name set/list is tolerated
        too — items then carry no filter attributes). Called after every load
        and every owned-set change, so the lists track the loaded strings.
        """
        if isinstance(meta, dict):
            self._blueprint_meta = dict(meta)
        else:
            self._blueprint_meta = {n: None for n in (meta or ())}
        self._populate_filter_combos()
        self._render_blueprint_lists()

    def _facet_value(self, name: str, attr: str):
        """The value of one facet attribute for *name*, or None if unknown."""
        item = self._blueprint_meta.get(name)
        return getattr(item, attr, None) if item is not None else None

    @staticmethod
    def _facet_sort_key(value: str):
        """Sort facet values alphabetically but keep "Other" pinned last."""
        return (value == "Other", value)

    def _populate_filter_combos(self) -> None:
        """Refill the mission and facet combos with the values present in the
        metadata, preserving each current selection where it still exists."""
        # Mission combo: the union of every item's mission names.
        missions = sorted({
            m for item in self._blueprint_meta.values()
            for m in getattr(item, "missions", ()) or ()
        }, key=str.lower)
        self._refill_combo(self._blueprints_mission_combo, missions)
        # Scalar facet combos.
        for attr, combo in self._blueprints_facet_combos.items():
            values = sorted({
                v for name in self._blueprint_meta
                if (v := self._facet_value(name, attr)) is not None
            }, key=self._facet_sort_key)
            self._refill_combo(combo, values)

    @staticmethod
    def _refill_combo(combo, values) -> None:
        """Rebuild *combo* as [Any, *values] preserving the prior selection."""
        prior = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(tr("enhancements.blueprints_facet_any"), None)
        for v in values:
            combo.addItem(v, v)
        idx = combo.findData(prior)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        combo.blockSignals(False)

    def _make_blueprint_item(self, name: str) -> QListWidgetItem:
        """A list row whose display text is the name, canonical name in
        UserRole (so filters/moves never depend on display text), and a tooltip
        summarizing the item's mission(s) and component attributes."""
        item = QListWidgetItem(name)
        item.setData(Qt.ItemDataRole.UserRole, name)
        meta = self._blueprint_meta.get(name)
        if meta is not None:
            bits = []
            attrs = " ".join(p for p in (meta.type, meta.cls, meta.size, meta.grade) if p)
            if attrs:
                bits.append(attrs)
            if meta.missions:
                bits.append(tr("enhancements.blueprints_tooltip_missions",
                               missions=", ".join(sorted(meta.missions))))
            if bits:
                item.setToolTip("\n".join(bits))
        return item

    def _render_blueprint_lists(self) -> None:
        """Repopulate both lists from the metadata + the persisted owned set,
        preserving the filters and not re-entering the move handlers."""
        owned = AppSettings.get_owned_items()
        available = self._available_blueprints(self._blueprint_meta, owned)
        owned_sorted = sorted(owned, key=str.lower)

        for lst, names in (
            (self._blueprints_available_list, available),
            (self._blueprints_owned_list, owned_sorted),
        ):
            lst.blockSignals(True)
            lst.clear()
            for name in names:
                lst.addItem(self._make_blueprint_item(name))
            lst.blockSignals(False)

        self._refilter_blueprints_available()

        # Empty state: no metadata and nothing owned -> guide the user to
        # generate mission enhancements first; hide the (useless) controls.
        has_content = bool(self._blueprint_meta) or bool(owned)
        self._blueprints_empty_note.setVisible(not has_content)
        for w in (
            self._blueprints_search,
            self._blueprints_mission_label, self._blueprints_mission_combo,
            self._blueprints_filter_note,
            self._blueprints_available_list, self._blueprints_owned_list,
            self._blueprints_add_btn, self._blueprints_remove_btn,
            self._blueprints_available_label, self._blueprints_owned_label,
            *self._blueprints_facet_combos.values(),
            *self._blueprints_facet_labels.values(),
        ):
            w.setVisible(has_content)

    def _blueprint_item_visible(self, name: str) -> bool:
        """True if *name* passes the keyword, mission, and facet filters.

        An item with no value for a facet is hidden only when that facet is set
        to a specific value (not "Any") — so untyped items stay visible until a
        component facet is actually chosen.
        """
        kw = self._blueprints_search.text().strip().lower()
        if kw and kw not in name.lower():
            return False
        mission = self._blueprints_mission_combo.currentData()
        if mission is not None:
            item = self._blueprint_meta.get(name)
            missions = getattr(item, "missions", ()) if item is not None else ()
            if mission not in missions:
                return False
        for attr, combo in self._blueprints_facet_combos.items():
            sel = combo.currentData()
            if sel is not None and self._facet_value(name, attr) != sel:
                return False
        return True

    def _refilter_blueprints_available(self, *_args) -> None:
        """Hide available rows that don't pass the current filters."""
        lst = self._blueprints_available_list
        for i in range(lst.count()):
            item = lst.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            item.setHidden(not self._blueprint_item_visible(name))

    def _selected_names(self, lst) -> list:
        return [it.data(Qt.ItemDataRole.UserRole) for it in lst.selectedItems()]

    def _own_selected_blueprints(self) -> None:
        """Move every selected available item into the owned set (one write)."""
        names = self._selected_names(self._blueprints_available_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()

    def _unown_selected_blueprints(self) -> None:
        """Move every selected owned item back to available (one write)."""
        names = self._selected_names(self._blueprints_owned_list)
        if not names:
            return
        owned = AppSettings.get_owned_items()
        owned.difference_update(names)
        AppSettings.set_owned_items(owned)
        self._render_blueprint_lists()
        self.owned_items_changed.emit()


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

        self.style_combo = _NoScrollComboBox()
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
        self.usage_sep_combo = None

        # Mission Titles is a purpose-built page (route controls, not element
        # rows + variant mappings), so it has its own layout branch.
        if category == "mission_titles":
            self._build_mission_titles_page()
            return

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
        self.sep_combo = _NoScrollComboBox()
        for key, label, _ in SEPARATORS:
            # "None" is offered for every category, commodities included: a
            # deliberate no-separator commodity tag renders "[CFCollection]".
            # A legacy leftover "none" is upgraded once to "pipe" by
            # AppSettings.get_tag_config so existing users don't regress (#97).
            self.sep_combo.addItem(label, userData=key)
        self._select_combo(self.sep_combo, config.separator)
        self.sep_combo.currentIndexChanged.connect(self._on_sep_changed)
        ctrl_grid.addWidget(self.sep_combo, 0, 1)

        ctrl_grid.addWidget(QLabel("Enclosing:"), 1, 0)
        self.enc_combo = _NoScrollComboBox()
        for key, label, _open, _close in ENCLOSINGS:
            self.enc_combo.addItem(label, userData=key)
        self._select_combo(self.enc_combo, config.enclosing)
        self.enc_combo.currentIndexChanged.connect(self._on_enc_changed)
        ctrl_grid.addWidget(self.enc_combo, 1, 1)

        ctrl_grid.addWidget(QLabel("Placement:"), 2, 0)
        self.placement_combo = _NoScrollComboBox()
        for key, label in PLACEMENTS:
            self.placement_combo.addItem(label, userData=key)
        self._select_combo(self.placement_combo, config.placement)
        self.placement_combo.currentIndexChanged.connect(self._on_placement_changed)
        ctrl_grid.addWidget(self.placement_combo, 2, 1)

        # Commodities get a second separator: the one used INSIDE the multi-value
        # "Used To Craft" element, independent of the element separator above.
        self.usage_sep_combo = None
        if self.category == "commodities":
            ctrl_grid.addWidget(QLabel("Craft-usage separator:"), 3, 0)
            self.usage_sep_combo = _NoScrollComboBox()
            for key, label, _ in SEPARATORS:
                self.usage_sep_combo.addItem(label, userData=key)
            self._select_combo(self.usage_sep_combo, config.usage_separator)
            self.usage_sep_combo.currentIndexChanged.connect(self._on_usage_sep_changed)
            ctrl_grid.addWidget(self.usage_sep_combo, 3, 1)

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

    def _on_usage_sep_changed(self, _idx: int):
        data = self.usage_sep_combo.currentData()
        if data is not None:
            self.config.usage_separator = data
            self._refresh_preview()

    # ── Mapping editor ───────────────────────────────────────────────────

    def _open_mapping_dialog(self, kind: str | None = None):
        """Open the variant-mapping editor for a specific element kind.

        Filters the shared class_mapping to only the keys belonging to
        *kind* so the user sees Class entries OR Type entries, not both.
        On accept, merges the edited subset back into the full mapping."""
        from src.utils.tag_builder import CATEGORY_ELEMENT_KINDS, DEFAULT_KIND_MAPPINGS
        kind_defaults = DEFAULT_KIND_MAPPINGS.get(kind, {})
        # Keys that belong to OTHER kinds *in this category* — exclude them from
        # this dialog. Scoped to the category (not all kinds globally) because
        # some keys collide across categories: component "type" and commodity
        # "usage" both map "Power Plant" / "Cooler" / "Quantum Drive" / "Radar"
        # with different codes, so a global exclusion would hide those rows when
        # editing commodity usage.
        category_kinds = set(CATEGORY_ELEMENT_KINDS.get(self.category, ()))
        other_keys = set()
        for other_kind in category_kinds:
            if other_kind != kind:
                other_keys.update(DEFAULT_KIND_MAPPINGS.get(other_kind, {}).keys())
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

    # ── Mission Titles page (route controls) ─────────────────────────────

    def _build_mission_titles_page(self) -> None:
        """Purpose-built page for the mission-title route: an enable toggle plus
        placement / arrow / separator / location-detail combos and a preview."""
        col = QVBoxLayout(self)
        col.setContentsMargins(10, 6, 10, 6)
        col.setSpacing(6)

        self._mt_enable = QCheckBox("Add route to hauling mission titles")
        route_el = next((e for e in self.config.elements if e.kind == "route"), None)
        self._mt_enable.setChecked(bool(route_el and route_el.enabled))
        self._mt_enable.toggled.connect(self._on_mt_enable)
        col.addWidget(self._mt_enable)

        hint = QLabel("The game fills in the real pickup and drop-off locations "
                      "when the mission is accepted.")
        hint.setProperty("role", "secondary")
        hint.setStyleSheet("font-size: 11px;")
        hint.setWordWrap(True)
        col.addWidget(hint)

        # #200 follow-up: shorten the stock title so the route + tags fit.
        self._mt_abbrev = QCheckBox("Shorten original titles (drops \"Rank\", \"Cargo Haul\", ...)")
        self._mt_abbrev.setChecked(bool(getattr(self.config, "abbreviate_title", False)))
        self._mt_abbrev.toggled.connect(self._on_mt_abbrev)
        col.addWidget(self._mt_abbrev)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(4)

        def _combo(items) -> QComboBox:
            c = _NoScrollComboBox()
            for entry in items:
                c.addItem(entry[1], userData=entry[0])
            return c

        self._mt_placement = _combo(MISSION_TITLE_PLACEMENTS)
        self._mt_arrow = _combo(ROUTE_ARROWS)
        self._mt_sep = _combo(TITLE_SEPARATORS)
        self._mt_detail = _combo(LOCATION_DETAILS)
        self._select_combo(self._mt_placement, self.config.placement)
        self._select_combo(self._mt_arrow, self.config.route_arrow)
        self._select_combo(self._mt_sep, self.config.title_separator)
        self._select_combo(self._mt_detail, self.config.location_detail)
        rows = [
            ("Placement:", self._mt_placement),
            ("Route arrow:", self._mt_arrow),
            ("Title separator:", self._mt_sep),
            ("Location detail:", self._mt_detail),
        ]
        for r, (lbl, combo) in enumerate(rows):
            grid.addWidget(QLabel(lbl), r, 0)
            combo.currentIndexChanged.connect(self._on_mt_changed)
            grid.addWidget(combo, r, 1)
        col.addLayout(grid)

        self.preview_label = QLabel()
        self.preview_label.setMinimumHeight(28)
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; padding: 4px; "
            "background: rgba(0, 0, 0, 30); border-radius: 3px;"
        )
        col.addWidget(self.preview_label)
        col.addStretch()
        self._set_mt_controls_enabled(self._mt_enable.isChecked())
        self._refresh_preview()

    def _set_mt_controls_enabled(self, on: bool) -> None:
        for c in (self._mt_placement, self._mt_arrow, self._mt_sep, self._mt_detail):
            c.setEnabled(on)

    def _on_mt_enable(self, checked: bool) -> None:
        for e in self.config.elements:
            if e.kind == "route":
                e.enabled = checked
        self._set_mt_controls_enabled(checked)
        self._refresh_preview()

    def _on_mt_abbrev(self, checked: bool) -> None:
        self.config.abbreviate_title = checked
        self._refresh_preview()

    def _on_mt_changed(self, _idx: int) -> None:
        self.config.placement = self._mt_placement.currentData() or self.config.placement
        self.config.route_arrow = self._mt_arrow.currentData() or self.config.route_arrow
        self.config.title_separator = self._mt_sep.currentData() or self.config.title_separator
        self.config.location_detail = self._mt_detail.currentData() or self.config.location_detail
        self._refresh_preview()

    def _refresh_mt_preview(self) -> None:
        sample_title = "Master Rank - Direct Medium Cargo Haul"
        if getattr(self.config, "abbreviate_title", False):
            sample_title = abbreviate_title(sample_title)
            # In-game the size comes from the CargoGradeToken loc keys the
            # generator overrides; mirror that on the literal sample here.
            for word, short in SIZE_ABBREVIATIONS:
                sample_title = sample_title.replace(word, short)
        if not route_enabled(self.config):
            self.preview_label.setText(f"Preview:  {sample_title} [50 REP]  (route off)")
            return
        if self.config.location_detail == "address":
            frm, to = "Area18, Crusader", "Lorville, Hurston"
        else:
            frm, to = "Area18", "Lorville"
        route = render_route(frm, to, self.config.route_arrow)
        title = apply_mission_title(sample_title, route, self.config)
        self.preview_label.setText(f"Preview:  {title} [50 REP]")

    # ── Preview ──────────────────────────────────────────────────────────

    def _refresh_preview(self):
        if self.category == "mission_titles":
            self._refresh_mt_preview()
            return
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
        if self.category == "mission_titles":
            route_el = next((e for e in fresh.elements if e.kind == "route"), None)
            self._mt_enable.setChecked(bool(route_el and route_el.enabled))
            self._mt_abbrev.setChecked(bool(fresh.abbreviate_title))
            self._select_combo(self._mt_placement, fresh.placement)
            self._select_combo(self._mt_arrow, fresh.route_arrow)
            self._select_combo(self._mt_sep, fresh.title_separator)
            self._select_combo(self._mt_detail, fresh.location_detail)
            self._set_mt_controls_enabled(self._mt_enable.isChecked())
            self._refresh_preview()
            return
        self._select_combo(self.sep_combo, fresh.separator)
        self._select_combo(self.enc_combo, fresh.enclosing)
        self._select_combo(self.placement_combo, fresh.placement)
        if self.usage_sep_combo is not None:
            self._select_combo(self.usage_sep_combo, fresh.usage_separator)
        self._repopulate_list()
        self._refresh_preview()

    @staticmethod
    def _select_combo(combo: QComboBox, key: str) -> None:
        for i in range(combo.count()):
            if combo.itemData(i) == key:
                combo.setCurrentIndex(i)
                return
