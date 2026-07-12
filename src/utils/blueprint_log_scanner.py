"""Scan Star Citizen's Game.log / logbackups for "Received Blueprint" reward
notifications, so the Blueprint Tracker's Owned list can be auto-populated
from a player's actual play history instead of manual marking one by one.

Qt-free and settings-free (mirrors owned_items.py) so it's unit-testable with
plain strings/paths; the caller (a QThread worker) resolves the actual log
directory via AppSettings and reports progress to the UI.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.utils.owned_items import normalize_item_name

# Star Citizen logs one line per notification-queue event, e.g.:
#   <2026-07-09T07:54:03.720Z> [Notice] <SHUDEvent_OnNotification> Added
#   notification "Received Blueprint: NDB-30 Repeater [Energy-S3]: " [15] to
#   queue. New queue size: 4, ...
#
# The item name can itself contain literal double quotes (paint/skin variant
# names, e.g. `Demeco "Purgatory Camo" LMG`), so a naive capture up to the
# next `"` truncates at the first embedded quote. The reliable terminator is
# the fixed `: " [<id>]` suffix the game always appends after the name —
# colon, space, quote, space, bracketed notification id — a sequence real
# item names never happen to contain.
_RECEIVED_BLUEPRINT_RE = re.compile(r'Received Blueprint: (.+?): "\s\[\d+\]')

ProgressCallback = Callable[[int, int, str], None]


def extract_blueprint_names(text: str) -> set[str]:
    """Return the normalized blueprint names in one log file's full text.

    Names are run through the same `normalize_item_name` used for blueprint
    bullet matching, so the game's own reward-notification tag (e.g.
    "Agni [Industrial-S3-B-Quantum]") reduces to the same identity ("Agni")
    the Blueprint Tracker keys its Available/Owned lists on. A notification
    fires 4 times per earned blueprint (queued + Next/StartFade/Remove), all
    with identical text, so duplicates collapse naturally via the set.
    """
    return {
        normalize_item_name(m.group(1))
        for m in _RECEIVED_BLUEPRINT_RE.finditer(text)
        if normalize_item_name(m.group(1))
    }


def find_log_files(channel_install_path) -> list[Path]:
    """Return every log file worth scanning for a channel install dir.

    Includes ``logbackups/*.log`` (rotated prior-session logs — where
    "Received Blueprint" notifications accumulate over a player's whole
    history) and the current session's live ``Game.log`` if present, so a
    scan run without restarting the game still picks up blueprints earned
    this session. Returns an empty list if neither exists (uninitialized or
    misconfigured install path).
    """
    channel_install_path = Path(channel_install_path)
    files = sorted((channel_install_path / "logbackups").glob("*.log"))
    live_log = channel_install_path / "Game.log"
    if live_log.exists():
        files.append(live_log)
    return files


def scan_log_files(
    paths: Iterable[Path],
    *,
    progress_callback: Optional[ProgressCallback] = None,
) -> set[str]:
    """Scan every file in *paths* for blueprint-reward notifications.

    Returns the union of normalized names across all files. Unreadable
    files (permission errors, a mid-write live Game.log) are skipped, not
    fatal — logbackups/ can hold hundreds of rotated session logs and one
    bad file shouldn't abort the whole scan.
    """
    paths = list(paths)
    total = len(paths)
    found: set[str] = set()
    for i, path in enumerate(paths):
        if progress_callback:
            progress_callback(i, total, path.name)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found.update(extract_blueprint_names(text))
    if progress_callback:
        progress_callback(total, total, "")
    return found
