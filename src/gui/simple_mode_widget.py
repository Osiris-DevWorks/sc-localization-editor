"""Simple-mode landing page (#180).

A deliberately near-empty screen for users who just want the result: one big
**Apply Enhancements** button that runs the whole export with default
settings, plus a way back to the full **Advanced** UI. The orchestration lives
on ``MainWindow`` (`_run_simple_apply`, `_apply_ui_mode`); this widget only
emits intent.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from src.gui.theme import get_button_color, get_button_text_color
from src.utils.i18n import tr


class SimpleModeWidget(QWidget):
    """The Simple-mode page: a big generate-and-apply button and a mode switch."""

    generate_and_apply_requested = pyqtSignal()
    switch_to_advanced_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 24, 40, 24)
        layout.setSpacing(16)
        layout.addStretch(1)

        # Both buttons live in one centred, width-capped column and expand to
        # fill it, so they end up the same size. Apply Enhancements (primary)
        # sits on top; Switch to Advanced below it.
        self.generate_apply_btn = QPushButton(tr("simple_mode.generate_apply_btn"))
        self.generate_apply_btn.setToolTip(tr("simple_mode.generate_apply_tip"))
        self.generate_apply_btn.setMinimumHeight(44)
        self.generate_apply_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.generate_apply_btn.setStyleSheet(
            f"background-color: {get_button_color('apply')}; "
            f"color: {get_button_text_color()}; font-weight: bold; "
            f"font-size: 14px; padding: 10px 20px;"
        )
        self.generate_apply_btn.clicked.connect(self.generate_and_apply_requested)

        self.advanced_btn = QPushButton(tr("simple_mode.switch_to_advanced"))
        self.advanced_btn.setToolTip(tr("simple_mode.switch_to_advanced_tip"))
        self.advanced_btn.setMinimumHeight(44)
        self.advanced_btn.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.advanced_btn.setStyleSheet(
            f"background-color: {get_button_color('open')}; "
            f"color: {get_button_text_color()}; font-weight: bold; "
            f"font-size: 14px; padding: 10px 20px;"
        )
        self.advanced_btn.clicked.connect(self.switch_to_advanced_requested)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(12)
        btn_col.addWidget(self.generate_apply_btn)   # Apply Enhancements on top
        btn_col.addWidget(self.advanced_btn)         # Switch to Advanced below
        btn_wrap = QWidget()
        btn_wrap.setLayout(btn_col)
        btn_wrap.setMaximumWidth(320)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(btn_wrap)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        self.hint_label = QLabel(tr("simple_mode.defaults_hint"))
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hint_label.setWordWrap(True)
        self.hint_label.setProperty("role", "secondary")
        layout.addWidget(self.hint_label)

        layout.addStretch(2)

    def set_busy(self, busy: bool) -> None:
        """Disable the action button while a run is in progress."""
        self.generate_apply_btn.setEnabled(not busy)

    def retranslate_ui(self) -> None:
        """Re-pull strings after a language switch."""
        self.advanced_btn.setText(tr("simple_mode.switch_to_advanced"))
        self.advanced_btn.setToolTip(tr("simple_mode.switch_to_advanced_tip"))
        self.generate_apply_btn.setText(tr("simple_mode.generate_apply_btn"))
        self.generate_apply_btn.setToolTip(tr("simple_mode.generate_apply_tip"))
        self.hint_label.setText(tr("simple_mode.defaults_hint"))
