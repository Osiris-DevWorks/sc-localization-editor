"""Tests for AppSettings getter/setter pairs and edge-case branches.

Focuses on the roughly 30% of settings.py that was previously uncovered:
- All simple setter methods
- get_last_update_check_epoch with non-integer stored value
- get_game_install_path resolution order
- get_game_version manifest parsing and error paths
- get_active_channel unknown-value fallback
- set_active_channel invalid-channel raises ValueError
- get_sc_install_root derivation from legacy path
- get_available_channels with and without a root
- get_user_data_dir with valid/invalid override
- set_user_data_dir with None clears the key
- get_user_ini_path overrides.ini → user.ini migration
- get_merge_hierarchy string-value branch
- get_merge_hierarchy other-type fallback
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings
from src.utils.settings import AppSettings

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path, monkeypatch):
    settings_file = tmp_path / "test_settings.ini"

    def _isolated():
        return QSettings(str(settings_file), QSettings.Format.IniFormat)

    monkeypatch.setattr(AppSettings, "settings", staticmethod(_isolated))
    yield


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    user_dir = tmp_path / "OpenStrings"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: user_dir))
    return user_dir


# ─────────────────────────────────────────────────────────────────────────────
# Enhancement settings
# ─────────────────────────────────────────────────────────────────────────────


class TestEnhancementSettings:
    def test_enhancements_enabled_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_enhancements_enabled() is True
        AppSettings.set_enhancements_enabled(False)
        assert AppSettings.get_enhancements_enabled() is False
        AppSettings.set_enhancements_enabled(True)
        assert AppSettings.get_enhancements_enabled() is True

    def test_enhancement_category_enabled_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_enhancement_category_enabled("ships") is True
        AppSettings.set_enhancement_category_enabled("ships", False)
        assert AppSettings.get_enhancement_category_enabled("ships") is False

    def test_enabled_enhancement_categories_all_on(self, isolated_qsettings):
        cats = AppSettings.get_enabled_enhancement_categories()
        assert "ship_descs" in cats
        assert "mission_rewards" in cats

    def test_enabled_enhancement_categories_one_off(self, isolated_qsettings):
        AppSettings.set_enhancement_category_enabled("missions", False)
        cats = AppSettings.get_enabled_enhancement_categories()
        assert "mission_rewards" not in cats
        assert "ship_descs" in cats


# ─────────────────────────────────────────────────────────────────────────────
# Theme, favorite prefix, tutorial, epoch
# ─────────────────────────────────────────────────────────────────────────────


class TestSimpleGetterSetters:
    def test_favorite_prefix_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_favorite_prefix() == "*"
        AppSettings.set_favorite_prefix("!")
        assert AppSettings.get_favorite_prefix() == "!"

    def test_tutorial_completed_version_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_tutorial_completed_version() == ""
        AppSettings.set_tutorial_completed_version("1.1.0")
        assert AppSettings.get_tutorial_completed_version() == "1.1.0"

    def test_last_update_check_epoch_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_last_update_check_epoch() == 0
        AppSettings.set_last_update_check_epoch(1700000000)
        assert AppSettings.get_last_update_check_epoch() == 1700000000

    def test_last_update_check_epoch_bad_value_returns_zero(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.LAST_UPDATE_CHECK_EPOCH, "not-a-number")
        assert AppSettings.get_last_update_check_epoch() == 0

    def test_base_global_path_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_base_global_path() == ""
        AppSettings.set_base_global_path(r"C:\some\path\base.ini")
        assert AppSettings.get_base_global_path() == r"C:\some\path\base.ini"

    def test_vehicles_path_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_vehicles_path() == ""
        AppSettings.set_vehicles_path(r"C:\vehicles.ini")
        assert AppSettings.get_vehicles_path() == r"C:\vehicles.ini"

    def test_last_overrides_path_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_last_overrides_path() == ""
        AppSettings.set_last_overrides_path(r"C:\overrides")
        assert AppSettings.get_last_overrides_path() == r"C:\overrides"

    def test_auto_write_enabled_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_auto_write_enabled() is False
        AppSettings.set_auto_write_enabled(True)
        assert AppSettings.get_auto_write_enabled() is True

    def test_window_geometry_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_window_geometry() == b""
        AppSettings.set_window_geometry(b"\x01\x02\x03")
        assert AppSettings.get_window_geometry() == b"\x01\x02\x03"

    def test_window_state_roundtrip(self, isolated_qsettings):
        assert AppSettings.get_window_state() == b""
        AppSettings.set_window_state(b"\xaa\xbb")
        assert AppSettings.get_window_state() == b"\xaa\xbb"


# ─────────────────────────────────────────────────────────────────────────────
# Game install path resolution
# ─────────────────────────────────────────────────────────────────────────────


class TestGameInstallPath:
    def test_returns_sc_root_plus_active_channel(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, r"C:\RSI\StarCitizen")
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "LIVE")
        result = AppSettings.get_game_install_path()
        assert result == str(Path(r"C:\RSI\StarCitizen") / "LIVE")

    def test_falls_back_to_legacy_game_install_path(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, r"C:\RSI\SC\LIVE")
        result = AppSettings.get_game_install_path()
        assert result == r"C:\RSI\SC\LIVE"

    def test_returns_empty_when_nothing_set(self, isolated_qsettings, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "exists", lambda self: False)
        result = AppSettings.get_game_install_path()
        assert result == ""


# ─────────────────────────────────────────────────────────────────────────────
# Game version from manifest
# ─────────────────────────────────────────────────────────────────────────────


class TestGameVersion:
    def test_returns_version_from_valid_manifest(self, isolated_qsettings, tmp_path, monkeypatch):
        game_dir = tmp_path / "SC" / "LIVE"
        game_dir.mkdir(parents=True)
        manifest = game_dir / "build_manifest.id"
        manifest.write_text(json.dumps({"Data": {"Version": "4.7.176.58286"}}), encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: str(game_dir)))
        assert AppSettings.get_game_version() == "4.7.176.58286"

    def test_returns_empty_when_no_game_path(self, isolated_qsettings, monkeypatch):
        monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: ""))
        assert AppSettings.get_game_version() == ""

    def test_returns_empty_when_manifest_missing(self, isolated_qsettings, tmp_path, monkeypatch):
        game_dir = tmp_path / "SC" / "LIVE"
        game_dir.mkdir(parents=True)
        monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: str(game_dir)))
        assert AppSettings.get_game_version() == ""

    def test_returns_empty_on_bad_json(self, isolated_qsettings, tmp_path, monkeypatch):
        game_dir = tmp_path / "SC" / "LIVE"
        game_dir.mkdir(parents=True)
        (game_dir / "build_manifest.id").write_text("not json", encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_game_install_path", staticmethod(lambda: str(game_dir)))
        assert AppSettings.get_game_version() == ""


# ─────────────────────────────────────────────────────────────────────────────
# Active channel
# ─────────────────────────────────────────────────────────────────────────────


class TestActiveChannel:
    def test_defaults_to_live(self, isolated_qsettings):
        assert AppSettings.get_active_channel() == "LIVE"

    def test_roundtrip(self, isolated_qsettings):
        AppSettings.set_active_channel("PTU")
        assert AppSettings.get_active_channel() == "PTU"

    def test_unknown_value_returns_default(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "BOGUS")
        assert AppSettings.get_active_channel() == AppSettings.DEFAULT_CHANNEL

    def test_set_invalid_channel_raises(self, isolated_qsettings):
        with pytest.raises(ValueError, match="Unknown channel"):
            AppSettings.set_active_channel("BOGUS")


# ─────────────────────────────────────────────────────────────────────────────
# SC install root
# ─────────────────────────────────────────────────────────────────────────────


class TestScInstallRoot:
    def test_returns_saved_value(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, r"C:\RSI\StarCitizen")
        assert AppSettings.get_sc_install_root() == r"C:\RSI\StarCitizen"

    def test_derives_from_legacy_path_with_channel_suffix(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, r"C:\RSI\StarCitizen\LIVE")
        result = AppSettings.get_sc_install_root()
        assert result == r"C:\RSI\StarCitizen"

    def test_derives_from_legacy_path_without_channel_suffix(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, r"C:\RSI\StarCitizen")
        result = AppSettings.get_sc_install_root()
        assert result == r"C:\RSI\StarCitizen"

    def test_set_sc_install_root_persists(self, isolated_qsettings):
        AppSettings.set_sc_install_root(r"C:\Games\SC")
        assert AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT) == r"C:\Games\SC"

    def test_returns_empty_when_nothing_set(self, isolated_qsettings, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "exists", lambda self: False)
        assert AppSettings.get_sc_install_root() == ""


# ─────────────────────────────────────────────────────────────────────────────
# Available channels
# ─────────────────────────────────────────────────────────────────────────────


class TestAvailableChannels:
    def test_returns_all_when_root_not_set(self, isolated_qsettings):
        result = AppSettings.get_available_channels()
        assert set(result) == set(AppSettings.AVAILABLE_CHANNELS)

    def test_returns_only_channels_with_p4k(self, isolated_qsettings, tmp_path):
        root = tmp_path / "StarCitizen"
        (root / "LIVE").mkdir(parents=True)
        (root / "LIVE" / "Data.p4k").write_bytes(b"dummy")
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, str(root))
        result = AppSettings.get_available_channels()
        assert result == ["LIVE"]


# ─────────────────────────────────────────────────────────────────────────────
# User data directory override
# ─────────────────────────────────────────────────────────────────────────────


class TestUserDataDir:
    def test_valid_override_is_used(self, isolated_qsettings, tmp_path):
        override = tmp_path / "my_data"
        AppSettings.settings().setValue(AppSettings.USER_DATA_DIR, str(override))
        result = AppSettings.get_user_data_dir()
        assert result == override
        assert override.exists()

    def test_bad_override_falls_back(self, isolated_qsettings, tmp_path, monkeypatch):
        # Point override to a path we make un-creatable by monkeypatching mkdir
        override = tmp_path / "bad_override"
        AppSettings.settings().setValue(AppSettings.USER_DATA_DIR, str(override))

        original_mkdir = Path.mkdir

        def _fail_mkdir(self, *args, **kwargs):
            if self == override:
                raise OSError("simulated failure")
            return original_mkdir(self, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", _fail_mkdir)
        docs_base = tmp_path / "Documents"
        docs_base.mkdir()
        monkeypatch.setattr(AppSettings, "_resolve_docs_base", staticmethod(lambda: docs_base))
        result = AppSettings.get_user_data_dir()
        assert "Open Strings" in str(result)

    def test_set_user_data_dir_persists(self, isolated_qsettings, tmp_path):
        override = tmp_path / "custom"
        AppSettings.set_user_data_dir(str(override))
        assert AppSettings.settings().value(AppSettings.USER_DATA_DIR) == str(override)

    def test_set_user_data_dir_none_clears_key(self, isolated_qsettings, tmp_path):
        AppSettings.settings().setValue(AppSettings.USER_DATA_DIR, r"C:\something")
        AppSettings.set_user_data_dir(None)
        assert AppSettings.settings().value(AppSettings.USER_DATA_DIR) is None

    def test_set_user_data_dir_empty_string_clears_key(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.USER_DATA_DIR, r"C:\something")
        AppSettings.set_user_data_dir("")
        assert not AppSettings.settings().value(AppSettings.USER_DATA_DIR)


# ─────────────────────────────────────────────────────────────────────────────
# Channel-scoped path helpers
# ─────────────────────────────────────────────────────────────────────────────


class TestChannelPaths:
    def test_get_channel_install_path_empty_when_no_root(self, isolated_qsettings):
        assert AppSettings.get_channel_install_path() == ""

    def test_get_channel_install_path_with_root(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, r"C:\RSI\StarCitizen")
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "LIVE")
        result = AppSettings.get_channel_install_path()
        assert result == str(Path(r"C:\RSI\StarCitizen") / "LIVE")

    def test_get_channel_data_dir_nested_under_channel(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "PTU")
        result = AppSettings.get_channel_data_dir()
        assert result.name == "PTU"
        assert result.exists()

    def test_get_cache_dir_created(self, isolated_qsettings, fake_user_data_dir):
        result = AppSettings.get_cache_dir()
        assert result.name == "cache"
        assert result.exists()

    def test_get_backups_dir_created(self, isolated_qsettings, fake_user_data_dir):
        result = AppSettings.get_backups_dir()
        assert result.name == "backups"
        assert result.exists()

    def test_get_global_ini_path_with_root(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, r"C:\RSI\StarCitizen")
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "LIVE")
        result = AppSettings.get_global_ini_path()
        assert result == Path(r"C:\RSI\StarCitizen\LIVE\data\Localization\english\global.ini")

    def test_get_p4k_path_with_root(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, r"C:\RSI\StarCitizen")
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, "LIVE")
        result = AppSettings.get_p4k_path()
        assert result == Path(r"C:\RSI\StarCitizen\LIVE\Data.p4k")


# ─────────────────────────────────────────────────────────────────────────────
# user.ini path migration (overrides.ini → user.ini)
# ─────────────────────────────────────────────────────────────────────────────


class TestUserIniPath:
    def test_returns_user_ini_when_no_migration_needed(self, isolated_qsettings, fake_user_data_dir):
        result = AppSettings.get_user_ini_path()
        assert result.name == "user.ini"

    def test_migrates_overrides_ini_to_user_ini(self, isolated_qsettings, fake_user_data_dir):
        channel_dir = fake_user_data_dir / AppSettings.get_active_channel()
        channel_dir.mkdir(parents=True, exist_ok=True)
        overrides = channel_dir / "overrides.ini"
        overrides.write_text("[section]\nkey=val\n", encoding="utf-8")

        result = AppSettings.get_user_ini_path()
        assert result.name == "user.ini"
        assert result.exists()
        assert not overrides.exists()


# ─────────────────────────────────────────────────────────────────────────────
# Merge hierarchy type coercion
# ─────────────────────────────────────────────────────────────────────────────


class TestMergeHierarchy:
    def test_list_value_returned_as_is(self, isolated_qsettings):
        AppSettings.set_merge_hierarchy(["global", "user"])
        result = AppSettings.get_merge_hierarchy()
        assert result == ["global", "user"]

    def test_string_value_is_split(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.MERGE_HIERARCHY, "global,user")
        result = AppSettings.get_merge_hierarchy()
        assert result == ["global", "user"]

    def test_empty_string_returns_default(self, isolated_qsettings):
        AppSettings.settings().setValue(AppSettings.MERGE_HIERARCHY, "")
        result = AppSettings.get_merge_hierarchy()
        assert result == [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]


# ─────────────────────────────────────────────────────────────────────────────
# Source auto-update
# ─────────────────────────────────────────────────────────────────────────────


class TestSourceAutoUpdate:
    def test_user_source_always_returns_false(self, isolated_qsettings):
        assert AppSettings.get_source_auto_update(AppSettings.SOURCE_USER) is False

    def test_set_auto_update_for_user_is_no_op(self, isolated_qsettings):
        AppSettings.set_source_auto_update(AppSettings.SOURCE_USER, True)
        assert AppSettings.get_source_auto_update(AppSettings.SOURCE_USER) is False

    def test_non_user_source_roundtrip(self, isolated_qsettings):
        AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)
        assert AppSettings.get_source_auto_update(AppSettings.SOURCE_GLOBAL) is False

    def test_non_user_source_default_is_true(self, isolated_qsettings):
        assert AppSettings.get_source_auto_update(AppSettings.SOURCE_GLOBAL) is True


# ─────────────────────────────────────────────────────────────────────────────
# ensure_user_ini_file
# ─────────────────────────────────────────────────────────────────────────────


class TestEnsureUserIni:
    def test_creates_empty_file_if_missing(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.ensure_user_ini_file()
        assert AppSettings.get_user_ini_path().exists()

    def test_is_idempotent_when_file_exists(self, isolated_qsettings, fake_user_data_dir):
        ini = AppSettings.get_user_ini_path()
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text("[section]\n", encoding="utf-8")
        AppSettings.ensure_user_ini_file()
        assert ini.read_text(encoding="utf-8") == "[section]\n"
