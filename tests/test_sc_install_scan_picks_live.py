"""The install scan must not pick an abandoned Star Citizen folder (#370).

A user's DataForge extraction hung for 30 minutes on every run. The chain of
symptoms pointed everywhere except the cause: unforge stalling, memory at 99%,
a 114 MB Game.dcb where healthy installs carry a 330 MB Game2.dcb. The build
manifest they sent matched two working installs byte for byte, so their game
looked fine. Verify Files in the RSI launcher changed nothing.

It changed nothing because the launcher was verifying the install it manages,
and Smart Citizen was reading a different one. A leftover
``D:\Program Files\Roberts Space Industries\StarCitizen`` still had a valid
channel folder, so the scan accepted it and returned, and their real install at
``E:\Roberts Space Industries\StarCitizen`` was never looked at.

Two things caused that, and both are the scan's fault rather than the user's:

* it returned its first hit instead of comparing candidates, and
* the iteration is drive-major over a subpath list whose first entry is
  ``Program Files\...``, so an orphan on an earlier drive beats the real
  install on a later one every time.

Newest Data.p4k now wins, because an abandoned install's archive is frozen at
whenever it stopped being patched while the live one moves with every update.
Every candidate is logged either way: the heuristic can still be wrong, and a
log naming the alternatives is what turns this into a one-line diagnosis
instead of the thread it took.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.settings import (  # noqa: E402
    _newest_p4k_mtime, _pick_live_sc_install,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _install(root: Path, channel: str = "LIVE", *, mtime: float | None = None) -> str:
    """Build a folder shaped like a real install: a channel dir with a p4k."""
    p4k = root / channel / "Data.p4k"
    p4k.parent.mkdir(parents=True, exist_ok=True)
    p4k.write_bytes(b"\0")
    if mtime is not None:
        import os
        os.utime(p4k, (mtime, mtime))
    return str(root)


def test_newest_p4k_wins_over_scan_order(tmp_path):
    """#370 reduced to its essentials: the orphan is found first, the live
    install is found later, and the live one has to win anyway."""
    orphan = _install(tmp_path / "D_ProgramFiles", mtime=1_000_000)
    live = _install(tmp_path / "E_RSI", mtime=2_000_000)
    # scan order puts the orphan first, exactly as the drive-major walk does
    assert _pick_live_sc_install([orphan, live]) == live


def test_single_candidate_is_returned_unchanged(tmp_path):
    """The overwhelmingly common case must not change behaviour at all."""
    only = _install(tmp_path / "solo")
    assert _pick_live_sc_install([only]) == only


def test_scan_order_breaks_ties(tmp_path):
    """Equal timestamps fall back to the order the scan produced, so a machine
    where the heuristic cannot discriminate behaves exactly as before."""
    a = _install(tmp_path / "a", mtime=5_000_000)
    b = _install(tmp_path / "b", mtime=5_000_000)
    assert _pick_live_sc_install([a, b]) == a


def test_candidate_without_a_readable_p4k_loses(tmp_path):
    """A folder with a channel dir but no usable Data.p4k scores zero, so a
    real install always outranks it rather than the walk order deciding."""
    empty = str(tmp_path / "empty")
    (tmp_path / "empty" / "LIVE").mkdir(parents=True)
    real = _install(tmp_path / "real", mtime=9_000_000)
    assert _pick_live_sc_install([empty, real]) == real


def test_newest_across_channels_not_just_live(tmp_path):
    """A PTU player keeps that channel current while LIVE goes stale. Ranking
    an install by its stalest channel would invert the comparison."""
    root = tmp_path / "multi"
    _install(root, "LIVE", mtime=1_000_000)
    _install(root, "PTU", mtime=8_000_000)
    assert _newest_p4k_mtime(str(root)) == 8_000_000


def test_multiple_candidates_are_all_logged(tmp_path, caplog):
    """The diagnostic half. Even a wrong pick is recoverable in minutes if the
    log names what else was on the machine."""
    orphan = _install(tmp_path / "orphan", mtime=1_000_000)
    live = _install(tmp_path / "live", mtime=2_000_000)
    with caplog.at_level(logging.WARNING):
        _pick_live_sc_install([orphan, live])
    logged = "\n".join(r.message for r in caplog.records)
    assert orphan in logged and live in logged
    assert "Config tab" in logged


def test_single_candidate_does_not_warn(tmp_path, caplog):
    """One install is not ambiguous, so it must not produce a warning a user
    would reasonably read as a problem."""
    with caplog.at_level(logging.WARNING):
        _pick_live_sc_install([_install(tmp_path / "solo")])
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_unreadable_root_scores_zero_rather_than_raising(tmp_path):
    """A disconnected network drive or a path that vanished mid-scan must not
    take the whole detection down with it."""
    assert _newest_p4k_mtime(str(tmp_path / "does-not-exist")) == 0.0
