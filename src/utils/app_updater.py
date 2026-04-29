"""Check GitHub Releases for a newer Smart Citizen installer.

Hits the public ``/releases/latest`` endpoint (no auth), parses ``tag_name`` +
``html_url`` + ``body`` from the JSON payload, and compares the tag against
the locally-installed version from ``VERSION.TXT``. Runs on a ``QThread`` so
the UI never blocks on the network.

The GitHub unauthenticated rate limit is 60 req/hr per IP; callers (currently
``MainWindow``) cap auto-checks to once per 6 hours via a registry-backed
timestamp to stay well under that.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from PyQt6.QtCore import QThread, pyqtSignal

from src.utils.version import get_version

logger = logging.getLogger(__name__)

GITHUB_API_URL = (
    "https://api.github.com/repos/Osiris-DevWorks/smart-citizen/releases/latest"
)
REQUEST_TIMEOUT_SECONDS = 10


def parse_version(s: str) -> tuple[int, int, int] | None:
    """Parse a ``major.minor.patch`` (optionally ``v``-prefixed) into a tuple.

    Returns ``None`` if the input can't be parsed — callers should treat that
    as "can't compare" rather than "equal" so we never silently pester on
    malformed tags.
    """
    if not s:
        return None
    s = s.strip().lstrip("vV")
    parts = s.split(".")
    if len(parts) < 2:
        return None
    try:
        nums = [int(p) for p in parts[:3]]
    except ValueError:
        return None
    while len(nums) < 3:
        nums.append(0)
    return (nums[0], nums[1], nums[2])


def is_newer(latest: str, current: str) -> bool:
    """Return True iff *latest* is strictly newer than *current*.

    Unparseable input on either side returns False — fail safe so we don't
    prompt the user based on garbage.
    """
    lt = parse_version(latest)
    ct = parse_version(current)
    if lt is None or ct is None:
        return False
    return lt > ct


class AppUpdateCheckWorker(QThread):
    """Query GitHub Releases for the latest Smart Citizen version.

    Emits one of ``update_available`` / ``up_to_date`` / ``check_error`` and
    always emits ``finished`` so the owner can clean up. Mirrors the
    signal shape of ``StartupSyncWorker`` in ``main_window.py``.
    """

    update_available = pyqtSignal(str, str, str)  # (latest_version, url, body)
    up_to_date = pyqtSignal(str)                   # (current_version)
    check_error = pyqtSignal(str)                  # (error_message)
    finished = pyqtSignal()

    def run(self) -> None:
        current = get_version()
        try:
            req = urllib.request.Request(
                GITHUB_API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": f"SmartCitizen/{current}",
                },
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                payload = json.load(resp)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            logger.warning(f"App update check failed: {msg}")
            self.check_error.emit(msg)
            self.finished.emit()
            return

        tag = (payload.get("tag_name") or "").strip()
        url = (payload.get("html_url") or "").strip()
        body = (payload.get("body") or "").strip()
        latest = tag.lstrip("vV")

        if not tag:
            self.check_error.emit("Release payload missing tag_name")
            self.finished.emit()
            return

        if is_newer(tag, current):
            logger.info(f"App update available: {latest} (current {current})")
            self.update_available.emit(latest, url, body)
        else:
            logger.info(f"App is up to date at {current}")
            self.up_to_date.emit(current)

        self.finished.emit()
