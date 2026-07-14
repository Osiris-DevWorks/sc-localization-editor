"""Conflict resolution dialog for importing INI files into user.ini."""

from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                              QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                              QComboBox, QDialogButtonBox, QHeaderView, QInputDialog)
from PyQt6.QtCore import Qt

from src.utils.i18n import tr


class ImportConflictDialog(QDialog):
    """Dialog for resolving conflicts when importing an INI file into user.ini."""

    RESOLUTION_OPTIONS = [
        "Keep Current",
        "Use Imported",
        "Append Imported",
        "Prepend Imported",
        "Custom...",
    ]

    def __init__(self, conflicts: dict[str, tuple[str, str]],
                 auto_add_count: int, excluded_count: int,
                 parent=None):
        super().__init__(parent)
        self._conflicts = conflicts
        self._auto_add_count = auto_add_count
        self._excluded_count = excluded_count

        self._keys: list[str] = list(conflicts.keys())
        self._combos: dict[str, QComboBox] = {}
        self._custom_values: dict[str, str] = {}
        self._previous_combo_index: dict[str, int] = {}

        self.setup_ui()

    def setup_ui(self):
        self.setWindowTitle(tr("import_dialog.title"))
        self.setMinimumSize(900, 500)

        layout = QVBoxLayout(self)

        # Summary label
        summary_parts = []
        if self._auto_add_count > 0:
            summary_parts.append(tr("import_dialog.auto_add_summary", count=self._auto_add_count))
        if self._excluded_count > 0:
            summary_parts.append(tr("import_dialog.excluded_summary", count=self._excluded_count))
        if summary_parts:
            summary_label = QLabel("  ".join(summary_parts))
            summary_label.setWordWrap(True)
            layout.addWidget(summary_label)

        # Conflicts group box
        conflict_count = len(self._conflicts)
        group = QGroupBox(tr("import_dialog.conflicts_group", count=conflict_count))
        group_layout = QVBoxLayout(group)

        # Bulk action buttons
        button_row = QHBoxLayout()
        keep_all_btn = QPushButton(tr("import_dialog.keep_all_btn"))
        keep_all_btn.setToolTip(tr("import_dialog.keep_all_tooltip"))
        keep_all_btn.clicked.connect(self._keep_all)
        button_row.addWidget(keep_all_btn)

        import_all_btn = QPushButton(tr("import_dialog.import_all_btn"))
        import_all_btn.setToolTip(tr("import_dialog.import_all_tooltip"))
        import_all_btn.clicked.connect(self._import_all)
        button_row.addWidget(import_all_btn)

        button_row.addStretch()
        group_layout.addLayout(button_row)

        # Conflict table
        self._table = QTableWidget(conflict_count, 4)
        self._table.setHorizontalHeaderLabels([
            tr("import_dialog.col_key"),
            tr("import_dialog.col_current_value"),
            tr("import_dialog.col_imported_value"),
            tr("import_dialog.col_resolution"),
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

        max_display_len = 120

        for row, key in enumerate(self._keys):
            current_value, imported_value = self._conflicts[key]

            # Key column (read-only)
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, key_item)

            # Current value column (read-only, truncated with tooltip)
            current_display = current_value
            if len(current_display) > max_display_len:
                current_display = current_display[:max_display_len] + "..."
            current_item = QTableWidgetItem(current_display)
            current_item.setFlags(
                current_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            current_item.setToolTip(current_value)
            self._table.setItem(row, 1, current_item)

            # Imported value column (read-only, truncated with tooltip)
            imported_display = imported_value
            if len(imported_display) > max_display_len:
                imported_display = imported_display[:max_display_len] + "..."
            imported_item = QTableWidgetItem(imported_display)
            imported_item.setFlags(
                imported_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            imported_item.setToolTip(imported_value)
            self._table.setItem(row, 2, imported_item)

            # Resolution combo box
            combo = QComboBox()
            combo.addItem(tr("import_dialog.resolution_keep"))
            combo.addItem(tr("import_dialog.resolution_use"))
            combo.addItem(tr("import_dialog.resolution_append"))
            combo.addItem(tr("import_dialog.resolution_prepend"))
            combo.addItem(tr("import_dialog.resolution_custom"))
            self._combos[key] = combo
            self._previous_combo_index[key] = 0
            combo.currentIndexChanged.connect(
                lambda index, k=key: self._on_resolution_changed(k, index))
            self._table.setCellWidget(row, 3, combo)

        group_layout.addWidget(self._table)
        layout.addWidget(group)

        # Dialog buttons
        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _on_resolution_changed(self, key: str, index: int):
        """Handle resolution combo change. Prompt for custom value if needed."""
        if index == 4:  # Custom...
            current_val, imported_val = self._conflicts[key]
            initial = self._custom_values.get(key, imported_val)
            text, ok = QInputDialog.getText(
                self, tr("import_dialog.custom_value_title"),
                tr("import_dialog.custom_value_prompt", key=key),
                text=initial)
            if ok:
                self._custom_values[key] = text
                self._previous_combo_index[key] = index
            else:
                # Revert to previous selection
                combo = self._combos[key]
                combo.blockSignals(True)
                combo.setCurrentIndex(self._previous_combo_index[key])
                combo.blockSignals(False)
        else:
            self._previous_combo_index[key] = index

    def _keep_all(self):
        """Set all resolution combos to Keep Current."""
        for key, combo in self._combos.items():
            combo.setCurrentIndex(0)

    def _import_all(self):
        """Set all resolution combos to Use Imported."""
        for key, combo in self._combos.items():
            combo.setCurrentIndex(1)

    def get_resolutions(self) -> dict[str, str]:
        """Return resolved values for all conflicting keys."""
        resolutions = {}
        for key in self._keys:
            combo = self._combos[key]
            index = combo.currentIndex()
            current_value, imported_value = self._conflicts[key]

            if index == 0:  # Keep Current
                resolutions[key] = current_value
            elif index == 1:  # Use Imported
                resolutions[key] = imported_value
            elif index == 2:  # Append Imported
                resolutions[key] = current_value + imported_value
            elif index == 3:  # Prepend Imported
                resolutions[key] = imported_value + current_value
            elif index == 4:  # Custom
                resolutions[key] = self._custom_values.get(key, current_value)

        return resolutions
