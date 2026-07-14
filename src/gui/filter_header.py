"""Per-column filter header for the strings table."""

from PyQt6.QtCore import Qt, QTimer, QEvent, pyqtSignal, QSize, QRect, QPoint
from PyQt6.QtGui import QColor, QIcon, QPainter, QPalette, QPen, QPixmap
from PyQt6.QtWidgets import QHeaderView, QLineEdit, QStyleOptionHeader, QStyle

from src.utils.i18n import tr


# Resting-border alpha used to approximate a 1.5px-feeling stroke without
# leaving the 2px integer grid that QSS borders require. ~60% opacity reads
# as a softened 2px line rather than a hard one. Focus state stays fully
# opaque so the active editor still pops.
_REST_BORDER_ALPHA = 150


def _filter_input_qss(palette: QPalette) -> str:
    """Build the per-editor stylesheet from the current palette.

    Rebuilt on every PaletteChange (see :meth:`FilterHeaderView.changeEvent`)
    because QSS doesn't accept ``palette(link)`` inside an ``rgba()``
    expression — we have to bake the colour in at the call site.
    """
    link = palette.color(QPalette.ColorRole.Link)
    rest = (
        f"rgba({link.red()}, {link.green()}, {link.blue()}, {_REST_BORDER_ALPHA})"
    )
    return f"""
        QLineEdit#columnFilter {{
            background-color: palette(base);
            border: 2px solid {rest};
            border-radius: 4px;
            padding: 1px 3px;
        }}
        QLineEdit#columnFilter:focus {{
            border: 3px solid palette(highlight);
            padding: 0px 2px;
        }}
    """


def _make_search_icon(color: QColor, size: int = 14) -> QIcon:
    """Render a magnifier glyph to a QIcon at the given palette colour.

    A drawn pixmap (rather than an asset file) keeps the icon palette-aware
    on theme swap and avoids depending on a font that ships a search emoji.
    """
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(color, 1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.setBrush(Qt.GlobalColor.transparent)
    p.drawEllipse(2, 2, 7, 7)
    p.drawLine(8, 8, 12, 12)
    p.end()
    return QIcon(pix)


class FilterHeaderView(QHeaderView):
    """QHeaderView subclass that adds a row of QLineEdit filters below the header labels."""

    filter_changed = pyqtSignal()

    FILTER_ROW_HEIGHT = 26

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

        icon_color = self.palette().color(QPalette.ColorRole.Mid)
        self._search_icon = _make_search_icon(icon_color)

        for i, name in enumerate(column_names):
            if i in self._skip_columns:
                self._filters.append(None)
                continue
            editor = QLineEdit(self)
            editor.setObjectName("columnFilter")
            editor.setPlaceholderText(f"Filter {name.lower()}…")
            editor.setToolTip(tr("strings_tab.column_filter_tooltip", column=name))
            editor.setClearButtonEnabled(True)
            editor.addAction(self._search_icon, QLineEdit.ActionPosition.LeadingPosition)
            editor.textChanged.connect(self._on_text_changed)
            self._filters.append(editor)

        self._refresh_editor_styles()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_filter_texts(self) -> list[str]:
        """Return lowered text for each column filter (empty string for skipped columns)."""
        return [f.text().lower() if f else "" for f in self._filters]

    def update_column_names(self, names: list[str]) -> None:
        """Refresh column names and editor placeholder texts after a language change."""
        self._column_names = names
        for i, editor in enumerate(self._filters):
            if editor is None:
                continue
            name = names[i] if i < len(names) else ""
            editor.setPlaceholderText(f"Filter {name.lower()}…")
            editor.setToolTip(tr("strings_tab.column_filter_tooltip", column=name))

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

    def paintEvent(self, event):
        # Children (the QLineEdit filters) paint after their parent, so the tint
        # we draw here lands UNDER the editors. The result: the band reads as a
        # contiguous search strip with input boxes embedded in it, and the
        # skipped-column gaps (Category / ★ / Status) still get the tint so the
        # row is unmistakably a filter area.
        super().paintEvent(event)
        label_h = super().sizeHint().height()
        band = QRect(0, label_h, self.width(), self.FILTER_ROW_HEIGHT)
        painter = QPainter(self)
        tint = self.palette().color(QPalette.ColorRole.Highlight)
        tint.setAlpha(36)
        painter.fillRect(band, tint)
        painter.end()

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

    def _on_text_changed(self, text: str = "") -> None:
        self._debounce.stop()
        self._debounce.start()

    def _refresh_editor_styles(self) -> None:
        """Rebuild every filter editor's stylesheet from the current palette.

        Called from ``__init__`` and again on PaletteChange so the
        rgba-baked resting border tracks the active theme's Link colour.
        """
        qss = _filter_input_qss(self.palette())
        for editor in self._filters:
            if editor is not None:
                editor.setStyleSheet(qss)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            self._refresh_editor_styles()
