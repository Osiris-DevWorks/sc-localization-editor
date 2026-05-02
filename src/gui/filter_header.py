"""Per-column filter header for the strings table."""

from PyQt6.QtCore import QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import QHeaderView, QLineEdit


class FilterHeaderView(QHeaderView):
    """QHeaderView subclass that adds a row of QLineEdit filters below the header labels."""

    filter_changed = pyqtSignal()

    FILTER_ROW_HEIGHT = 24

    def __init__(self, column_names: list[str], parent=None, skip_columns: set[int] | None = None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self.setSectionsClickable(True)
        self._column_names = column_names
        self._skip_columns = skip_columns or set()
        self._filters: list[QLineEdit | None] = []
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(300)
        self._debounce.timeout.connect(self.filter_changed.emit)

        for i, name in enumerate(column_names):
            if i in self._skip_columns:
                self._filters.append(None)
                continue
            editor = QLineEdit(self)
            editor.setPlaceholderText("Filter...")
            editor.setClearButtonEnabled(True)
            editor.textChanged.connect(self._on_text_changed)
            self._filters.append(editor)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_filter_texts(self) -> list[str]:
        """Return lowered text for each column filter (empty string for skipped columns)."""
        return [f.text().lower() if f else "" for f in self._filters]

    def clear_all(self):
        """Clear every filter input without triggering per-keystroke signals."""
        for f in self._filters:
            if f is None:
                continue
            f.blockSignals(True)
            f.clear()
            f.blockSignals(False)
        self.filter_changed.emit()

    # ------------------------------------------------------------------
    # Size / paint
    # ------------------------------------------------------------------

    def sizeHint(self) -> QSize:
        s = super().sizeHint()
        return QSize(s.width(), s.height() + self.FILTER_ROW_HEIGHT)

    def paintSection(self, painter, rect, logicalIndex):
        """Paint the header label in the top portion only, not centered over the full height."""
        # During transient layout passes (theme swap, dock toggle, splitter drag,
        # font load), rect.height() can momentarily collapse below base_h. The
        # previous min(rect.height(), base_h) clamp then painted the label into
        # a near-zero rect, and that paint stuck until a full re-layout — which
        # for users meant restarting the app to get header text back. Force the
        # full base_h here; Qt clips on its own if rect is genuinely smaller.
        base_h = super().sizeHint().height()
        top_rect = QRect(rect.x(), rect.y(), rect.width(), base_h)
        super().paintSection(painter, top_rect, logicalIndex)

    # ------------------------------------------------------------------
    # Geometry
    # ------------------------------------------------------------------

    def updateGeometries(self):
        super().updateGeometries()
        # Reserve space below the header labels for the filter row
        self.setViewportMargins(0, 0, 0, self.FILTER_ROW_HEIGHT)
        self._position_editors()

    def _position_editors(self):
        """Align each QLineEdit to its column's current geometry."""
        # Editors sit just below the painted header labels.
        # With viewport margins, the base sizeHint gives the label-only height.
        y = super().sizeHint().height()
        for i, editor in enumerate(self._filters):
            if editor is None:
                continue
            x = self.sectionPosition(i) - self.offset()
            w = self.sectionSize(i)
            editor.setGeometry(x, y, w, self.FILTER_ROW_HEIGHT)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        """Route clicks in the label area to sorting, let filter row clicks pass through."""
        label_height = self.sizeHint().height() - self.FILTER_ROW_HEIGHT
        if event.position().y() < label_height:
            # Check if a QLineEdit is stealing this click (shouldn't, but just in case)
            super().mousePressEvent(event)
        # Clicks in the filter row are handled by the QLineEdit widgets

    def mouseReleaseEvent(self, event):
        label_height = self.sizeHint().height() - self.FILTER_ROW_HEIGHT
        if event.position().y() < label_height:
            super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        label_height = self.sizeHint().height() - self.FILTER_ROW_HEIGHT
        if event.position().y() < label_height:
            super().mouseMoveEvent(event)

    def _on_text_changed(self):
        self._debounce.stop()
        self._debounce.start()
