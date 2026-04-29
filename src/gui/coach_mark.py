"""Interactive coach-mark tour (guided tutorial).

A :class:`CoachMarkOverlay` is a full-window translucent widget that:

* dims everything with a semi-opaque black layer
* cuts a "spotlight" rectangle around one target widget so it shows through
* floats a callout frame (title, description, step counter, Back / Next / Skip)
  positioned next to the spotlight

A :class:`TutorialTour` is the sequencer: given a list of :class:`CoachMarkStep`
records it steps the overlay through them, runs optional per-step pre-actions
(e.g. switch to the Config tab so the Extract button is visible), and emits a
``finished(completed: bool)`` signal when the user reaches the end or skips.

Kept as a self-contained module so the rest of the GUI doesn't need to know
anything about overlay painting — the main window just builds a list of steps
and calls ``tour.start()``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger(__name__)


# Tour authors build these; the tour sequencer resolves the target lazily on
# each show_step so widgets created after the tour starts (e.g. a panel that
# only exists after a tab is activated) still match.
@dataclass
class CoachMarkStep:
    target: Callable[[], QWidget | None]  # None → step paints dim only, no spotlight
    title: str
    description: str
    pre_action: Callable[[], None] | None = None  # e.g. switch to Config tab
    preferred_side: str = "auto"  # "right" | "below" | "above" | "left" | "auto"


# ── Visual constants ──────────────────────────────────────────────────────────
_DIM_OPACITY = 170  # 0..255 — how dark the overlay is outside the spotlight
_SPOTLIGHT_PADDING = 6  # px of empty space around target before the highlight border
_SPOTLIGHT_CORNER = 6  # rounded-rect radius for the spotlight cut-out
_SPOTLIGHT_BORDER_PX = 3
_SPOTLIGHT_BORDER_COLOR = QColor("#00d4ff")
_CALLOUT_MARGIN = 16  # px gap between spotlight and callout
_CALLOUT_MAX_WIDTH = 380
_WINDOW_EDGE_MARGIN = 16  # keep callout at least this far from the window edge


class CoachMarkOverlay(QWidget):
    """Translucent overlay with a spotlight cut-out and a callout frame."""

    next_clicked = pyqtSignal()
    back_clicked = pyqtSignal()
    skip_clicked = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        # Transparent background so the area we don't paint shows the parent
        # through. WA_NoSystemBackground stops Qt from auto-filling before
        # paintEvent; WA_TranslucentBackground marks the widget's pixmap as
        # alpha-aware on compositing backends.
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # We absorb all clicks that aren't on the callout's buttons, so users
        # can't accidentally click a widget behind the dim layer while the
        # tour is live.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self._spotlight: QRect = QRect()
        self._callout = self._build_callout()
        self.hide()

    # ---- construction ------------------------------------------------------

    def _build_callout(self) -> QFrame:
        frame = QFrame(self)
        frame.setObjectName("coachCallout")
        frame.setAutoFillBackground(True)
        frame.setStyleSheet(
            """
            QFrame#coachCallout {
                background-color: palette(window);
                color: palette(window-text);
                border: 2px solid #00d4ff;
                border-radius: 8px;
            }
            QFrame#coachCallout QLabel { background: transparent; }
            QFrame#coachCallout #coachTitle { font-size: 15px; font-weight: bold; }
            QFrame#coachCallout #coachDesc  { font-size: 13px; }
            QFrame#coachCallout #coachCounter {
                color: palette(mid); font-size: 11px;
            }
            """
        )
        frame.setMaximumWidth(_CALLOUT_MAX_WIDTH)

        v = QVBoxLayout(frame)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        self._title_label = QLabel(frame)
        self._title_label.setObjectName("coachTitle")
        self._title_label.setWordWrap(True)
        v.addWidget(self._title_label)

        self._desc_label = QLabel(frame)
        self._desc_label.setObjectName("coachDesc")
        self._desc_label.setWordWrap(True)
        v.addWidget(self._desc_label)

        footer = QHBoxLayout()
        footer.setSpacing(8)
        self._counter_label = QLabel(frame)
        self._counter_label.setObjectName("coachCounter")
        footer.addWidget(self._counter_label)
        footer.addStretch()

        self._skip_btn = QPushButton("Skip", frame)
        self._skip_btn.setFlat(True)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.clicked.connect(self.skip_clicked)
        footer.addWidget(self._skip_btn)

        self._back_btn = QPushButton("Back", frame)
        self._back_btn.clicked.connect(self.back_clicked)
        footer.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next", frame)
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self.next_clicked)
        footer.addWidget(self._next_btn)

        v.addLayout(footer)
        frame.adjustSize()
        return frame

    # ---- step rendering ----------------------------------------------------

    def show_step(
        self,
        step: CoachMarkStep,
        current_idx: int,
        total: int,
        has_back: bool,
        is_last: bool,
    ) -> None:
        """Render *step* over the parent window.

        If the step's target widget isn't available or isn't visible, the
        overlay still shows with a full dim and a centered callout — the
        caller can let the user Back/Skip past it rather than auto-advancing,
        so they can read the text.
        """
        target = self._resolve_visible_target(step.target)

        if target is None:
            self._spotlight = QRect()
        else:
            # Widget coordinates → overlay-local coordinates. The overlay is a
            # child of the same widget the tour was started against, which
            # means the target's ancestors share a coordinate space with us.
            top_left = target.mapTo(self.parentWidget(), QPoint(0, 0))
            self._spotlight = QRect(top_left, target.size()).adjusted(
                -_SPOTLIGHT_PADDING,
                -_SPOTLIGHT_PADDING,
                _SPOTLIGHT_PADDING,
                _SPOTLIGHT_PADDING,
            )

        self._title_label.setText(step.title)
        self._desc_label.setText(step.description)
        self._counter_label.setText(f"Step {current_idx + 1} of {total}")
        self._back_btn.setEnabled(has_back)
        self._next_btn.setText("Finish" if is_last else "Next")

        # Callout sizes itself to content, then we place it.
        self._callout.adjustSize()
        self._position_callout(step.preferred_side)

        if not self.isVisible():
            self.show()
        self.raise_()
        self.update()

    @staticmethod
    def _resolve_visible_target(resolver: Callable[[], QWidget | None]) -> QWidget | None:
        try:
            w = resolver()
        except Exception:
            logger.exception("Coach-mark target resolver raised")
            return None
        if w is None:
            return None
        # width/height of 0 means the widget hasn't been laid out yet (e.g.
        # on a tab that was never shown); treat as unavailable.
        if not w.isVisible() or w.width() == 0 or w.height() == 0:
            return None
        return w

    # ---- positioning -------------------------------------------------------

    def _position_callout(self, preferred: str) -> None:
        """Place the callout frame so it doesn't overlap the spotlight.

        Tries the preferred side first, then right / below / above / left,
        falling back to a window-centered placement if none fit.
        """
        spot = self._spotlight
        size = self._callout.size()
        bounds = self.rect()

        def clamp(rect: QRect) -> QRect:
            r = QRect(rect)
            if r.left() < bounds.left() + _WINDOW_EDGE_MARGIN:
                r.moveLeft(bounds.left() + _WINDOW_EDGE_MARGIN)
            if r.right() > bounds.right() - _WINDOW_EDGE_MARGIN:
                r.moveRight(bounds.right() - _WINDOW_EDGE_MARGIN)
            if r.top() < bounds.top() + _WINDOW_EDGE_MARGIN:
                r.moveTop(bounds.top() + _WINDOW_EDGE_MARGIN)
            if r.bottom() > bounds.bottom() - _WINDOW_EDGE_MARGIN:
                r.moveBottom(bounds.bottom() - _WINDOW_EDGE_MARGIN)
            return r

        candidates: dict[str, QRect] = {}
        if not spot.isEmpty():
            candidates["right"] = QRect(
                QPoint(spot.right() + _CALLOUT_MARGIN, spot.top()),
                size,
            )
            candidates["below"] = QRect(
                QPoint(spot.left(), spot.bottom() + _CALLOUT_MARGIN),
                size,
            )
            candidates["above"] = QRect(
                QPoint(spot.left(), spot.top() - _CALLOUT_MARGIN - size.height()),
                size,
            )
            candidates["left"] = QRect(
                QPoint(spot.left() - _CALLOUT_MARGIN - size.width(), spot.top()),
                size,
            )

        order = ["right", "below", "above", "left"]
        if preferred != "auto" and preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)

        for side in order:
            candidate = candidates.get(side)
            if candidate is None:
                continue
            clamped = clamp(candidate)
            # Accept the first placement that (a) fits inside the window, and
            # (b) doesn't overlap the spotlight after clamping.
            if bounds.contains(clamped) and not clamped.intersects(spot):
                self._callout.move(clamped.topLeft())
                return

        # No side placement worked — center in the window, below the spotlight
        # if the spotlight is in the upper half (so the callout stays below
        # the highlighted widget rather than covering it).
        center = QRect(
            bounds.center() - QPoint(size.width() // 2, size.height() // 2),
            size,
        )
        if not spot.isEmpty() and center.intersects(spot):
            if spot.center().y() < bounds.center().y():
                center.moveTop(spot.bottom() + _CALLOUT_MARGIN)
            else:
                center.moveBottom(spot.top() - _CALLOUT_MARGIN)
        self._callout.move(clamp(center).topLeft())

    # ---- painting ----------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Fill everything except the spotlight with the dim color. Using a
        # QPainterPath subtraction gives us a rounded spotlight hole without
        # relying on composition-mode tricks that don't always play nicely
        # with child widgets.
        path = QPainterPath()
        path.addRect(QRectF(self.rect()))
        spot = self._spotlight
        if not spot.isEmpty():
            hole = QPainterPath()
            hole.addRoundedRect(QRectF(spot), _SPOTLIGHT_CORNER, _SPOTLIGHT_CORNER)
            path = path.subtracted(hole)

        p.fillPath(path, QColor(0, 0, 0, _DIM_OPACITY))

        if not spot.isEmpty():
            pen = QPen(_SPOTLIGHT_BORDER_COLOR, _SPOTLIGHT_BORDER_PX)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(
                QRectF(spot),
                _SPOTLIGHT_CORNER,
                _SPOTLIGHT_CORNER,
            )


# ── Sequencer ─────────────────────────────────────────────────────────────────


class TutorialTour(QObject):
    """Sequences :class:`CoachMarkStep` entries over a root widget.

    Emits ``finished(True)`` when the user completes the tour via Finish, or
    ``finished(False)`` when they skip. The caller is expected to persist the
    completion state themselves (e.g. via AppSettings) on the True emission.
    """

    finished = pyqtSignal(bool)

    def __init__(self, root: QWidget, steps: list[CoachMarkStep]):
        super().__init__(root)
        self._root = root
        self._steps = steps
        self._idx = 0
        self._overlay = CoachMarkOverlay(root)
        self._overlay.next_clicked.connect(self._on_next)
        self._overlay.back_clicked.connect(self._on_back)
        self._overlay.skip_clicked.connect(self._on_skip)
        root.installEventFilter(self)

    # ---- public API --------------------------------------------------------

    def start(self) -> None:
        if not self._steps:
            self.finished.emit(True)
            return
        self._idx = 0
        self._overlay.setGeometry(self._root.rect())
        self._show_current()

    def is_running(self) -> bool:
        return self._overlay.isVisible()

    # ---- step transitions --------------------------------------------------

    def _show_current(self) -> None:
        step = self._steps[self._idx]
        if step.pre_action is not None:
            try:
                step.pre_action()
            except Exception:
                logger.exception(f"Coach-mark pre_action failed for step {self._idx}")
        # Let Qt finish any pending layout from pre_action (tab switch, etc.)
        # before we query the target widget's geometry.
        QApplication.processEvents()
        self._overlay.setGeometry(self._root.rect())
        self._overlay.show_step(
            step,
            self._idx,
            len(self._steps),
            has_back=self._idx > 0,
            is_last=self._idx == len(self._steps) - 1,
        )

    def _on_next(self) -> None:
        if self._idx + 1 >= len(self._steps):
            self._finish(completed=True)
            return
        self._idx += 1
        self._show_current()

    def _on_back(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self._show_current()

    def _on_skip(self) -> None:
        self._finish(completed=False)

    def _finish(self, completed: bool) -> None:
        self._overlay.hide()
        self._root.removeEventFilter(self)
        self._overlay.deleteLater()
        self.finished.emit(completed)

    # ---- keep overlay aligned when the window moves/resizes ---------------

    def eventFilter(self, obj, event):
        if obj is self._root and self._overlay.isVisible():
            t = event.type()
            if t in (QEvent.Type.Resize, QEvent.Type.Move):
                self._overlay.setGeometry(self._root.rect())
                # Re-show the current step so the spotlight tracks the target
                # at its new geometry.
                self._show_current()
        return False  # never swallow
