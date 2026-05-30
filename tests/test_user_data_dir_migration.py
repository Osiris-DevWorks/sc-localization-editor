"""Tests for migrate_user_data_dir (issue #103).

When the user moves the Smart Citizen data folder, their existing overrides /
backups / cached strings should follow the move instead of being left behind.
The helper copies (merge, never overwrite) so data already in the new location
wins and the originals survive as a safety net.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.user_ini_manager import migrate_user_data_dir  # noqa: E402

pytestmark = pytest.mark.unit


def _seed(root: Path) -> None:
    (root / "LIVE").mkdir(parents=True)
    (root / "LIVE" / "user.ini").write_text("vehicle_NameX= My Ship\n", encoding="utf-8")
    (root / "LIVE" / "backups").mkdir()
    (root / "LIVE" / "backups" / "global.ini.bak").write_text("backup", encoding="utf-8")


def test_copies_all_files_to_new_location(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)

    copied = migrate_user_data_dir(old, new)

    assert copied == 2
    assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "vehicle_NameX= My Ship\n"
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()
    # originals are left in place (copy, not move)
    assert (old / "LIVE" / "user.ini").exists()


def test_never_overwrites_existing_destination_files(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _seed(old)
    # Pre-existing data in the new location must win.
    (new / "LIVE").mkdir(parents=True)
    (new / "LIVE" / "user.ini").write_text("KEEP ME", encoding="utf-8")

    copied = migrate_user_data_dir(old, new)

    assert (new / "LIVE" / "user.ini").read_text(encoding="utf-8") == "KEEP ME"
    assert (new / "LIVE" / "backups" / "global.ini.bak").exists()  # non-conflicting file still copied
    assert copied == 1


def test_noop_when_same_dir(tmp_path):
    old = tmp_path / "d"
    _seed(old)
    assert migrate_user_data_dir(old, old) == 0


def test_noop_when_old_missing(tmp_path):
    assert migrate_user_data_dir(tmp_path / "does_not_exist", tmp_path / "new") == 0
