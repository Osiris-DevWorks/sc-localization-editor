"""Tests for the channel-aware layout — path helpers and channel selection API."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from src.utils.settings import AppSettings

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at an in-memory / file-scoped store so tests don't
    stomp on the real Windows Registry. Uses IniFormat under tmp_path which
    QSettings will use when we force the format + path."""
    settings_file = tmp_path / "test_registry.ini"
    # Swap out AppSettings.settings() for a QSettings instance backed by our
    # temp file. Scoped per test.

    def _isolated():
        return QSettings(str(settings_file), QSettings.Format.IniFormat)

    monkeypatch.setattr(AppSettings, "settings", staticmethod(_isolated))
    # Clear any lru_cache or cached state on AppSettings if added later.
    yield
    # Explicit cleanup not needed — tmp_path handles file removal.


@pytest.fixture
def fake_sc_root(tmp_path):
    """Build a fake SC install root containing LIVE and PTU Data.p4k files."""
    root = tmp_path / "StarCitizen"
    for channel in ("LIVE", "PTU"):
        (root / channel).mkdir(parents=True)
        (root / channel / "Data.p4k").write_bytes(b"dummy")
    # TECH-PREVIEW intentionally absent to test the "disabled channel" path.
    return root


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    """Redirect AppSettings.get_user_data_dir() to a tmp_path so we don't
    touch the real ``Documents\\Open Strings\\``."""
    user_dir = tmp_path / "Open Strings"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: user_dir))
    return user_dir


# ─────────────────────────────────────────────────────────────────────────────
# Channel constants & API
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestChannelConstants:
    def test_channels_defined(self):
        assert set(AppSettings.AVAILABLE_CHANNELS) == {"LIVE", "PTU", "EPTU", "HOTFIX", "TECH-PREVIEW"}

    def test_default_is_live(self):
        assert AppSettings.DEFAULT_CHANNEL == "LIVE"


@pytest.mark.unit
class TestActiveChannel:
    def test_unset_returns_default(self, isolated_qsettings):
        assert AppSettings.get_active_channel() == AppSettings.DEFAULT_CHANNEL

    def test_set_and_get_roundtrip(self, isolated_qsettings):
        AppSettings.set_active_channel("PTU")
        assert AppSettings.get_active_channel() == "PTU"

    def test_unknown_stored_value_falls_back_to_default(self, isolated_qsettings):
        # Simulate a corrupt registry value.
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "NOT-A-CHANNEL")
        assert AppSettings.get_active_channel() == AppSettings.DEFAULT_CHANNEL

    def test_set_rejects_unknown_channel(self, isolated_qsettings):
        with pytest.raises(ValueError):
            AppSettings.set_active_channel("NOT-A-CHANNEL")


# ─────────────────────────────────────────────────────────────────────────────
# Path helpers nest under active channel
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestChannelScopedPaths:
    def test_cache_dir_nests_under_active_channel(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.set_active_channel("PTU")
        cache = AppSettings.get_cache_dir()
        assert cache == fake_user_data_dir / "PTU" / "cache"
        assert cache.exists()

    def test_backups_dir_nests_under_active_channel(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.set_active_channel("EPTU")
        backups = AppSettings.get_backups_dir()
        assert backups == fake_user_data_dir / "EPTU" / "backups"

    def test_user_ini_path_nests_under_active_channel(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.set_active_channel("LIVE")
        ini_path = AppSettings.get_user_ini_path()
        assert ini_path == fake_user_data_dir / "LIVE" / "user.ini"

    def test_dataforge_cache_dir_nests_under_active_channel(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.set_active_channel("TECH-PREVIEW")
        df = AppSettings.get_dataforge_cache_dir()
        assert df == fake_user_data_dir / "TECH-PREVIEW" / "cache" / "dataforge"

    def test_switching_channel_changes_all_paths(self, isolated_qsettings, fake_user_data_dir):
        """Critical contract: every path helper tracks get_active_channel()."""
        AppSettings.set_active_channel("LIVE")
        live_cache = AppSettings.get_cache_dir()
        live_user = AppSettings.get_user_ini_path()

        AppSettings.set_active_channel("PTU")
        ptu_cache = AppSettings.get_cache_dir()
        ptu_user = AppSettings.get_user_ini_path()

        assert live_cache != ptu_cache
        assert live_user != ptu_user
        assert live_cache.parent.name == "LIVE"
        assert ptu_cache.parent.name == "PTU"


# ─────────────────────────────────────────────────────────────────────────────
# SC install root + channel install path + p4k path
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestSCInstallRoot:
    def test_set_and_get(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        assert AppSettings.get_sc_install_root() == str(fake_sc_root)

    def test_channel_install_path_composes_root_and_channel(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("PTU")
        assert Path(AppSettings.get_channel_install_path()) == fake_sc_root / "PTU"

    def test_p4k_path_includes_channel(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("LIVE")
        assert AppSettings.get_p4k_path() == fake_sc_root / "LIVE" / "Data.p4k"

    def test_global_ini_path_under_channel(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        AppSettings.set_active_channel("LIVE")
        expected = fake_sc_root / "LIVE" / "data" / "Localization" / "english" / "global.ini"
        assert AppSettings.get_global_ini_path() == expected


# ─────────────────────────────────────────────────────────────────────────────
# Channel auto-detection
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAvailableChannels:
    def test_reports_only_channels_with_p4k(self, isolated_qsettings, fake_sc_root):
        AppSettings.set_sc_install_root(str(fake_sc_root))
        # fake_sc_root fixture ships LIVE + PTU Data.p4k; EPTU/TECH-PREVIEW are missing.
        available = AppSettings.get_available_channels()
        assert available == ["LIVE", "PTU"]

    def test_returns_all_when_root_unset(self, isolated_qsettings, monkeypatch):
        """Combo shouldn't be empty before the user configures the root —
        we return all channels so they can pick one as they set the path.
        Stub get_sc_install_root to avoid the auto-detect fallback that
        otherwise picks up the real machine's StarCitizen install."""
        monkeypatch.setattr(AppSettings, "get_sc_install_root", staticmethod(lambda: ""))
        assert AppSettings.get_available_channels() == list(AppSettings.AVAILABLE_CHANNELS)

    def test_empty_list_when_root_set_but_no_channels_installed(self, isolated_qsettings, tmp_path):
        empty_root = tmp_path / "empty_sc"
        empty_root.mkdir()
        AppSettings.set_sc_install_root(str(empty_root))
        assert AppSettings.get_available_channels() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
