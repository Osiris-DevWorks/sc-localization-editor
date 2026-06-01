"""Unit tests for AppSettings.get_sc_install_root cross-check logic.

When SC_INSTALL_ROOT and GAME_INSTALL_PATH disagree (stale root from a
pre-1.4.2 installer), GAME_INSTALL_PATH wins. The comparison uses
os.path.normcase so drive-letter casing differences on Windows don't
cause spurious mismatches.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def json_backend(tmp_path, monkeypatch):
    """Swap AppSettings._backend for a tmp JsonSettings so each test is hermetic."""
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestInstallRootCrossCheck:
    def test_matching_root_returns_unchanged(self, json_backend):
        """SC_INSTALL_ROOT matches GAME_INSTALL_PATH parent -- returns as-is."""
        root = r"D:\Games\StarCitizen"
        game_path = r"D:\Games\StarCitizen\LIVE"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        assert os.path.normcase(result) == os.path.normcase(root)

    def test_disagreeing_root_derives_from_game_path(self, json_backend):
        """SC_INSTALL_ROOT disagrees with GAME_INSTALL_PATH -- derives from game path."""
        stale_root = r"C:\OldLocation\StarCitizen"
        game_path = r"D:\NewLocation\StarCitizen\LIVE"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, stale_root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        expected = r"D:\NewLocation\StarCitizen"
        assert os.path.normcase(result) == os.path.normcase(expected)

    def test_only_sc_install_root_set(self, json_backend, monkeypatch):
        """Only SC_INSTALL_ROOT set (no GAME_INSTALL_PATH) -- returns SC_INSTALL_ROOT.

        Mocks _is_valid_sc_root to return True since this test exercises the
        cross-check logic, not path validation (which is tested separately).
        """
        root = r"E:\RSI\StarCitizen"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        # GAME_INSTALL_PATH not set (defaults to "")

        # Mock validation to return True -- test focuses on cross-check, not validation
        monkeypatch.setattr("src.utils.settings._is_valid_sc_root", lambda p: True)

        result = AppSettings.get_sc_install_root()
        assert result == root

    def test_neither_set_falls_through(self, json_backend, monkeypatch):
        """Neither setting set -- falls through to auto-detection.

        We monkeypatch Path.exists to return False for the standard
        install locations so the method returns empty string.
        """
        # Ensure neither key is set
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        # Block the filesystem auto-detection candidates
        original_exists = Path.exists
        def _fake_exists(self):
            s = str(self)
            if "Roberts Space Industries" in s:
                return False
            return original_exists(self)
        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = AppSettings.get_sc_install_root()
        assert result == ""

    def test_ptu_channel_recognized(self, json_backend):
        """GAME_INSTALL_PATH ending in PTU is recognized as a channel folder."""
        root = r"D:\Games\StarCitizen"
        game_path = r"D:\Games\StarCitizen\PTU"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        assert os.path.normcase(result) == os.path.normcase(root)

    def test_disagreeing_ptu_path_overrides(self, json_backend):
        """Stale root + fresh PTU game path -- derives from PTU path."""
        stale_root = r"C:\Old\StarCitizen"
        game_path = r"D:\New\StarCitizen\PTU"
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, stale_root)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, game_path)

        result = AppSettings.get_sc_install_root()
        expected = r"D:\New\StarCitizen"
        assert os.path.normcase(result) == os.path.normcase(expected)

    def test_game_path_without_channel_suffix_used_as_root(self, json_backend, monkeypatch):
        """GAME_INSTALL_PATH that doesn't end in a channel name is treated
        as the root itself when SC_INSTALL_ROOT is not set.

        Mocks _is_valid_sc_root to return True since this test exercises the
        cross-check logic, not path validation (which is tested separately).
        """
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, r"D:\Games\StarCitizen")

        # Mock validation to return True -- test focuses on cross-check, not validation
        monkeypatch.setattr("src.utils.settings._is_valid_sc_root", lambda p: True)

        # Block filesystem auto-detection
        original_exists = Path.exists
        def _fake_exists(self):
            s = str(self)
            if "Roberts Space Industries" in s:
                return False
            return original_exists(self)
        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = AppSettings.get_sc_install_root()
        assert result == r"D:\Games\StarCitizen"


class TestIsValidScRoot:
    """Tests for the _is_valid_sc_root path validation helper."""

    def test_nonexistent_path_returns_false(self):
        """A path that doesn't exist should return False."""
        from src.utils.settings import _is_valid_sc_root
        assert _is_valid_sc_root(r"C:\Nonexistent\Path") is False

    def test_path_without_channel_subdirs_returns_false(self):
        """A directory without LIVE/PTU/etc. subdirs should return False."""
        from src.utils.settings import _is_valid_sc_root
        # Use a directory that exists but has no channel subdirs
        assert _is_valid_sc_root(r"C:\Windows") is False

    def test_stale_registry_value_rejected(self, tmp_path):
        """A stale value like 'SmartCitizen 1.4.1' should be rejected."""
        from src.utils.settings import _is_valid_sc_root
        # Create a directory that looks like a stale app install
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        assert _is_valid_sc_root(str(stale_dir)) is False

    def test_valid_root_with_live_subdir(self, tmp_path):
        """A root with LIVE subdir should be accepted."""
        from src.utils.settings import _is_valid_sc_root
        root = tmp_path / "StarCitizen"
        root.mkdir()
        (root / "LIVE").mkdir()
        assert _is_valid_sc_root(str(root)) is True

    def test_valid_root_with_multiple_channels(self, tmp_path):
        """A root with multiple channel subdirs should be accepted."""
        from src.utils.settings import _is_valid_sc_root
        root = tmp_path / "StarCitizen"
        root.mkdir()
        (root / "LIVE").mkdir()
        (root / "PTU").mkdir()
        assert _is_valid_sc_root(str(root)) is True

    def test_channel_path_not_root(self, tmp_path):
        """A channel path (ending in LIVE) is not a valid root."""
        from src.utils.settings import _is_valid_sc_root
        # _is_valid_sc_root checks for channel SUBDIRS, so a channel
        # path itself is NOT a valid root (it has no subdirs named LIVE)
        channel = tmp_path / "StarCitizen" / "LIVE"
        channel.mkdir(parents=True)
        assert _is_valid_sc_root(str(channel)) is False

    def test_invalid_path_string_returns_false(self):
        """An invalid path string should return False without crashing."""
        from src.utils.settings import _is_valid_sc_root
        assert _is_valid_sc_root("") is False
        assert _is_valid_sc_root("not_a_path|with invalid chars") is False

    @pytest.mark.regression
    def test_stale_sc_install_root_dropped_by_getter(self, tmp_path, json_backend, monkeypatch):
        """End-to-end: SC_INSTALL_ROOT pointing at a directory with no channel
        subdirs is rejected by get_sc_install_root() and falls through.

        Regression for the 'SmartCitizen 1.4.1' stale-registry bug."""
        # Simulate the stale registry value: a dir that exists but has no
        # channel subdirectories
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        json_backend.setValue(AppSettings.SC_INSTALL_ROOT, str(stale_dir))
        json_backend.remove(AppSettings.GAME_INSTALL_PATH)

        # Block filesystem auto-detection so the test doesn't accidentally
        # find a real SC install on the test machine
        original_exists = Path.exists

        def _fake_exists(self):
            s = str(self)
            if "Roberts Space Industries" in s:
                return False
            return original_exists(self)

        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = AppSettings.get_sc_install_root()
        # The stale value must be rejected, falling through to '' (no auto-detect)
        assert result == ""

    @pytest.mark.regression
    def test_stale_game_install_path_dropped_by_getter(self, tmp_path, json_backend, monkeypatch):
        """End-to-end: GAME_INSTALL_PATH pointing at a stale dir (no channel subdirs)
        is rejected by get_sc_install_root() when SC_INSTALL_ROOT is unset."""
        stale_dir = tmp_path / "SmartCitizen 1.4.1"
        stale_dir.mkdir()
        json_backend.remove(AppSettings.SC_INSTALL_ROOT)
        json_backend.setValue(AppSettings.GAME_INSTALL_PATH, str(stale_dir))

        original_exists = Path.exists

        def _fake_exists(self):
            s = str(self)
            if "Roberts Space Industries" in s:
                return False
            return original_exists(self)

        monkeypatch.setattr(Path, "exists", _fake_exists)

        result = AppSettings.get_sc_install_root()
        # The stale value must be rejected, falling through to ''
        assert result == ""
