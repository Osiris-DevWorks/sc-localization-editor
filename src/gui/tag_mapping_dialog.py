"""Modal editor for the class/ordinance/damage variant mapping used by
the Tag Builder. Rows are the raw values (Military, CrossSection,
Energy, …); columns are the Short / Medium / Long variants that the
pattern's element-style dropdown selects between."""
from __future__ import annotations

from typing import Dict, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from src.utils.i18n import tr


class TagMappingDialog(QDialog):
    """Edit the variant mapping for one element kind.

    The dialog shows three columns by default (Short / Medium / Long). The
    `medium_column_visible` flag hides Medium for kinds that only expose
    Short / Long styles in the renderer (i.e. missiles' ordinance), so the
    user doesn't see a column they can't actually select against.
    """

    def __init__(
        self,
        mapping: Dict[str, Tuple[str, str, str]],
        defaults: Dict[str, Tuple[str, str, str]],
        title: str,
        medium_column_visible: bool = True,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._defaults = defaults
        self._medium_column_visible = medium_column_visible

        layout = QVBoxLayout(self)

        hint = QLabel(tr("tag_mapping_dialog.hint"))
        hint.setWordWrap(True)
        hint.setProperty("role", "secondary")
        hint.setStyleSheet("font-size: 11px;")
        layout.addWidget(hint)

        self._table = QTableWidget(len(mapping), 4, self)
        self._table.setHorizontalHeaderLabels([
            tr("tag_mapping_dialog.col_value"),
            tr("tag_mapping_dialog.col_short"),
            tr("tag_mapping_dialog.col_medium"),
            tr("tag_mapping_dialog.col_long"),
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(
            QTableWidget.EditTrigger.DoubleClicked
            | QTableWidget.EditTrigger.SelectedClicked
            | QTableWidget.EditTrigger.AnyKeyPressed
        )
        # Row keys are read-only — only the variant columns are editable.
        for row, (key, variants) in enumerate(sorted(mapping.items())):
            key_item = QTableWidgetItem(key)
            key_item.setFlags(key_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._table.setItem(row, 0, key_item)
            short, med, long = variants
            self._table.setItem(row, 1, QTableWidgetItem(short))
            self._table.setItem(row, 2, QTableWidgetItem(med))
            self._table.setItem(row, 3, QTableWidgetItem(long))
        self._table.resizeColumnsToContents()
        if not medium_column_visible:
            self._table.setColumnHidden(2, True)
        layout.addWidget(self._table)

        button_row = QHBoxLayout()
        reset_btn = QPushButton(tr("tag_mapping_dialog.reset_btn"))
        reset_btn.setToolTip(tr("tag_mapping_dialog.reset_tooltip"))
        reset_btn.clicked.connect(self._reset_to_defaults)
        button_row.addWidget(reset_btn)
        button_row.addStretch()

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        button_row.addWidget(bb)
        layout.addLayout(button_row)

        self.resize(520, 320)

    def _reset_to_defaults(self) -> None:
        for row in range(self._table.rowCount()):
            key = self._table.item(row, 0).text()
            variants = self._defaults.get(key)
            if variants is None:
                continue
            short, med, long = variants
            self._table.item(row, 1).setText(short)
            self._table.item(row, 2).setText(med)
            self._table.item(row, 3).setText(long)

    def result_mapping(self) -> Dict[str, Tuple[str, str, str]]:
        """Read back the edited mapping. Hidden Medium column re-uses its
        stored value (we never clear it on hide), so a Short/Long-only
        dialog still round-trips a 3-tuple cleanly."""
        out: Dict[str, Tuple[str, str, str]] = {}
        for row in range(self._table.rowCount()):
            key = self._table.item(row, 0).text()
            short = self._table.item(row, 1).text()
            med   = self._table.item(row, 2).text()
            long  = self._table.item(row, 3).text()
            if not self._medium_column_visible:
                # Mirror short into medium so a missile mapping that only
                # exposes Short/Long doesn't introduce a stale Medium value.
                med = short
            out[key] = (short, med, long)
        return out
