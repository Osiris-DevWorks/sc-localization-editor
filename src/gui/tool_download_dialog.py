"""Modal dialog that downloads unp4k / unforge on first use."""

import logging
import threading

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from src.utils.tools_manager import download_tools, get_tools_dir

logger = logging.getLogger(__name__)


class _DownloadWorker(QThread):
    """Background thread that calls :func:`~src.utils.tools_manager.download_tools`."""

    status = pyqtSignal(str)
    finished = pyqtSignal(bool)
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            download_tools(
                progress_callback=self.status.emit,
                cancel_event=self._cancel,
            )
            if self._cancel.is_set():
                self.finished.emit(False)
            else:
                self.finished.emit(True)
        except Exception as e:
            if self._cancel.is_set():
                self.finished.emit(False)
            else:
                logger.exception("Tool download failed")
                self.error.emit(str(e))
                self.finished.emit(False)


class ToolDownloadDialog(QDialog):
    """Modal dialog that downloads and extracts unp4k + unforge.

    Show with ``dialog.exec()``. Returns ``QDialog.DialogCode.Accepted``
    (truthy) when both tools have downloaded successfully, ``Rejected``
    if the user cancels or an error occurs.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Downloading Tools")
        self.setModal(True)
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(18, 16, 18, 14)

        self._info = QLabel(
            "Open Strings needs to download <b>unp4k</b> and <b>unforge</b> (~130 MB)\n"
            "to extract Star Citizen data files.\n"
            "This is a one-time download and will not happen again."
        )
        self._info.setWordWrap(True)
        layout.addWidget(self._info)

        self._status_label = QLabel("Starting…")
        layout.addWidget(self._status_label)

        self._bar = QProgressBar()
        self._bar.setRange(0, 0)  # indeterminate
        layout.addWidget(self._bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self._on_cancel)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self._worker = _DownloadWorker()
        self._worker.status.connect(self._status_label.setText)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_cancel(self) -> None:
        self._cancel_btn.setEnabled(False)
        self._status_label.setText("Cancelling…")
        self._worker.finished.disconnect(self._on_finished)
        self._worker.cancel()
        self._worker.wait()
        self.reject()

    def _on_finished(self, success: bool) -> None:
        self._worker.wait()
        if success:
            self.accept()
        else:
            self.reject()

    def _on_error(self, message: str) -> None:
        tools_dir = get_tools_dir()
        QMessageBox.warning(
            self,
            "Download Failed",
            f"Could not download tools:\n\n{message}\n\n"
            "Check your internet connection and try again.\n\n"
            "Alternatively, download unp4k and unforge manually from:\n"
            "https://github.com/dolkensp/unp4k/releases\n\n"
            f"Place unp4k.exe and unforge.exe (and their supporting files) in:\n{tools_dir}",
        )
