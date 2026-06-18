"""The side-docked Test Plan panel for testers (#144).

An interactive checklist of what changed in the release. Testers check items
off as they verify them; progress persists across launches, and the run can be
copied to the clipboard or posted to a Discord webhook. Modelled on the Help
dock (right-side `QDockWidget`); the plan content and report formatting live in
the Qt-free `src/utils/test_plan.py`.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.utils import test_plan
from src.utils.settings import AppSettings
from src.utils.version import get_version

logger = logging.getLogger(__name__)


class _ClickableLabel(QLabel):
    """A word-wrapping label that emits ``clicked`` when pressed.

    Paired with a text-less QCheckBox so a long checklist item wraps to the
    panel width (QCheckBox can't wrap its own label) while clicking the text
    still toggles the box.
    """

    clicked = pyqtSignal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)

    def mousePressEvent(self, event):
        self.clicked.emit()
        super().mousePressEvent(event)


class TestPlanPanel(QWidget):
    """Checklist widget shown inside the Test Plan dock."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._checked = AppSettings.get_test_plan_checks()
        self._checkboxes: dict[str, QCheckBox] = {}
        self._submit_worker = None
        self._build_ui()
        self._refresh_progress()

    # ── construction ─────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        intro = QLabel(
            "Work through each item on this build and check it off as you "
            "verify it. Your progress is saved automatically. When you're "
            "done, Copy Report or Submit to share what you found."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        # Tester name (persisted; used to label the submitted report).
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Tester:"))
        self.tester_edit = QLineEdit(AppSettings.get_tester_name())
        self.tester_edit.setPlaceholderText("Your name or handle")
        self.tester_edit.editingFinished.connect(
            lambda: AppSettings.set_tester_name(self.tester_edit.text())
        )
        name_row.addWidget(self.tester_edit, stretch=1)
        layout.addLayout(name_row)

        # Progress.
        prog_row = QHBoxLayout()
        self.progress_label = QLabel()
        prog_row.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, max(1, test_plan.total_items()))
        prog_row.addWidget(self.progress_bar, stretch=1)
        layout.addLayout(prog_row)

        # Checklist, in a scroll area so a long plan never squishes the buttons.
        # Items word-wrap to the panel width; the horizontal scrollbar is off so
        # long text never forces sideways scrolling.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        container = QWidget()
        clist = QVBoxLayout(container)
        for s, section in enumerate(test_plan.TEST_SECTIONS):
            group = QGroupBox(section["title"])
            gbox = QVBoxLayout(group)
            for i, text in enumerate(section["items"]):
                key = test_plan.item_key(s, i)
                gbox.addWidget(self._make_check_row(key, text))
            clist.addWidget(group)
        clist.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll, stretch=1)

        # Actions.
        btn_row = QHBoxLayout()
        self.submit_btn = QPushButton("Submit to Discord")
        self.submit_btn.clicked.connect(self._submit)
        webhook = AppSettings.get_test_webhook_url()
        if not webhook:
            self.submit_btn.setEnabled(False)
            self.submit_btn.setToolTip(
                "No Discord webhook configured. Set the "
                f"{AppSettings.TEST_WEBHOOK_ENV} environment variable (or the "
                "test_plan/webhook_url setting) to enable submitting. Use Copy "
                "Report in the meantime."
            )
        btn_row.addWidget(self.submit_btn)

        self.copy_btn = QPushButton("Copy Report")
        self.copy_btn.clicked.connect(self._copy_report)
        btn_row.addWidget(self.copy_btn)

        self.reset_btn = QPushButton("Reset")
        self.reset_btn.clicked.connect(self._reset)
        btn_row.addWidget(self.reset_btn)

        # Free-text feedback, included in the report (clipboard and Discord).
        layout.addWidget(QLabel("Additional feedback (optional):"))
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.setPlaceholderText(
            "Describe any bugs, surprises, or suggestions..."
        )
        self.notes_edit.setMaximumHeight(110)
        layout.addWidget(self.notes_edit)

        layout.addLayout(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

    def _make_check_row(self, key: str, text: str) -> QWidget:
        """A checklist row: a text-less checkbox plus a word-wrapping label.

        QCheckBox can't wrap its own label, so the wrapping text lives in a
        sibling label; clicking either the box or the text toggles the item.
        """
        row = QWidget()
        hb = QHBoxLayout(row)
        hb.setContentsMargins(0, 0, 0, 0)
        cb = QCheckBox()
        cb.setChecked(key in self._checked)
        cb.toggled.connect(lambda checked, k=key: self._on_toggle(k, checked))
        label = _ClickableLabel(text)
        label.clicked.connect(cb.toggle)
        hb.addWidget(cb, 0, Qt.AlignmentFlag.AlignTop)
        hb.addWidget(label, 1)
        self._checkboxes[key] = cb
        return row

    # ── state ─────────────────────────────────────────────────────────────────
    def _on_toggle(self, key: str, checked: bool) -> None:
        if checked:
            self._checked.add(key)
        else:
            self._checked.discard(key)
        AppSettings.set_test_plan_checks(self._checked)
        self._refresh_progress()

    def _refresh_progress(self) -> None:
        done, total, pct = test_plan.progress(self._checked)
        self.progress_label.setText(f"{done}/{total} ({pct}%)")
        self.progress_bar.setMaximum(max(1, total))
        self.progress_bar.setValue(done)

    def _build_report(self) -> str:
        return test_plan.build_report(
            self._checked,
            self.tester_edit.text(),
            get_version(),
            notes=self.notes_edit.toPlainText(),
        )

    # ── actions ─────────────────────────────────────────────────────────────
    def _copy_report(self) -> None:
        report = self._build_report()
        try:
            import pyperclip

            pyperclip.copy(report)
            self.status_label.setText("Report copied to clipboard.")
        except Exception as e:
            logger.error("Could not copy test-plan report: %s", e)
            self.status_label.setText("Could not copy report to clipboard.")

    def _reset(self) -> None:
        self._checked = set()
        AppSettings.set_test_plan_checks(self._checked)
        for cb in self._checkboxes.values():
            cb.blockSignals(True)
            cb.setChecked(False)
            cb.blockSignals(False)
        self._refresh_progress()
        self.status_label.setText("Checklist reset.")

    def _submit(self) -> None:
        webhook = AppSettings.get_test_webhook_url()
        if not webhook:
            self.status_label.setText("No Discord webhook configured.")
            return
        from src.gui.workers import TestPlanSubmitWorker

        chunks = test_plan.discord_chunks(self._build_report())
        self.submit_btn.setEnabled(False)
        self.status_label.setText("Sending report to Discord...")
        self._submit_worker = TestPlanSubmitWorker(webhook, chunks, self)
        self._submit_worker.finished.connect(self._on_submit_finished)
        self._submit_worker.start()

    def _on_submit_finished(self, ok: bool, message: str) -> None:
        self.status_label.setText(message)
        self.submit_btn.setEnabled(bool(AppSettings.get_test_webhook_url()))
        if self._submit_worker is not None:
            self._submit_worker.quit()
            self._submit_worker.wait()
            self._submit_worker = None
