"""Tests for src/parser/ini_parser.py — covering the previously untested paths."""

from unittest.mock import MagicMock, patch

import pytest
from src.parser.ini_parser import (
    _determine_status,
    _determine_status_from_source,
    load_overrides,
    load_source_files,
    load_sources_from_settings,
    parse_ini_file,
)

# ---------------------------------------------------------------------------
# parse_ini_file
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseIniFile:
    def test_basic_key_value(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("key1=value1\nkey2=value2\n", encoding="utf-8")
        result = parse_ini_file(f)
        assert result == {"key1": "value1", "key2": "value2"}

    def test_missing_file_returns_empty(self, tmp_path):
        result = parse_ini_file(tmp_path / "nonexistent.ini")
        assert result == {}

    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.ini"
        f.write_text("", encoding="utf-8")
        assert parse_ini_file(f) == {}

    def test_comments_and_blank_lines_skipped(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("; comment\n\nkey=val\n", encoding="utf-8")
        assert parse_ini_file(f) == {"key": "val"}

    def test_lines_without_equals_skipped(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("no_equals_here\nkey=val\n", encoding="utf-8")
        assert parse_ini_file(f) == {"key": "val"}

    def test_value_can_contain_equals(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("key=a=b=c\n", encoding="utf-8")
        assert parse_ini_file(f) == {"key": "a=b=c"}

    def test_comma_suffix_stripped_from_key(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("vehicle_Name,P=Cutlass\n", encoding="utf-8")
        assert parse_ini_file(f) == {"vehicle_Name": "Cutlass"}

    def test_utf8_bom_handled(self, tmp_path):
        f = tmp_path / "test.ini"
        # utf-8-sig BOM
        f.write_bytes(b"\xef\xbb\xbfkey=value\n")
        assert parse_ini_file(f) == {"key": "value"}

    def test_whitespace_trimmed_from_key_and_value(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("  key  =  value  \n", encoding="utf-8")
        assert parse_ini_file(f) == {"key": "value"}

    def test_empty_key_after_comma_strip_skipped(self, tmp_path):
        # A line like ",P=value" would produce an empty key after strip — should be ignored
        f = tmp_path / "test.ini"
        f.write_text(",P=orphan\nreal=kept\n", encoding="utf-8")
        result = parse_ini_file(f)
        assert "real" in result
        assert "" not in result

    def test_accepts_string_path(self, tmp_path):
        f = tmp_path / "test.ini"
        f.write_text("k=v\n", encoding="utf-8")
        result = parse_ini_file(str(f))
        assert result == {"k": "v"}


# ---------------------------------------------------------------------------
# load_overrides (thin wrapper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadOverrides:
    def test_delegates_to_parse_ini_file(self, tmp_path):
        f = tmp_path / "overrides.ini"
        f.write_text("x=y\n", encoding="utf-8")
        assert load_overrides(f) == {"x": "y"}

    def test_missing_path_returns_empty(self, tmp_path):
        assert load_overrides(tmp_path / "gone.ini") == {}


# ---------------------------------------------------------------------------
# _determine_status (legacy helper)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetermineStatus:
    def test_no_custom_is_unmodified(self):
        assert _determine_status("orig", "") == "Unmodified"

    def test_custom_different_is_modified(self):
        assert _determine_status("orig", "custom") == "Modified"

    def test_custom_same_as_original_is_unmodified(self):
        assert _determine_status("orig", "orig") == "Unmodified"


# ---------------------------------------------------------------------------
# _determine_status_from_source
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDetermineStatusFromSource:
    def test_base_source_is_unmodified(self):
        assert _determine_status_from_source("global", "global") == "Unmodified"

    def test_user_source_is_modified(self):
        assert _determine_status_from_source("user", "global") == "Modified"

    def test_higher_priority_source_is_modified(self):
        assert _determine_status_from_source("contracts", "global") == "Modified"


# ---------------------------------------------------------------------------
# load_source_files
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLoadSourceFiles:
    def _make_sources(self):
        return {
            "global": {
                "vehicle_NameHawk": "Hawk",
                "item_NameSHLD_S01": "Shield S01",
            },
            "contracts": {
                "contract_001_name": "Delivery Run",
            },
        }

    def test_basic_merge_returns_entries(self):
        sources = self._make_sources()
        entries = load_source_files(sources, ["global", "contracts"])
        keys = {e.key for e in entries}
        assert "vehicle_NameHawk" in keys
        assert "contract_001_name" in keys

    def test_user_overrides_populate_custom_value(self):
        sources = self._make_sources()
        entries = load_source_files(
            sources,
            ["global"],
            user_overrides={"vehicle_NameHawk": "Custom Hawk"},
        )
        hawk = next(e for e in entries if e.key == "vehicle_NameHawk")
        assert hawk.custom_value == "Custom Hawk"
        assert hawk.status == "Modified"

    def test_unmodified_entry_has_empty_custom(self):
        sources = self._make_sources()
        entries = load_source_files(sources, ["global"])
        hawk = next(e for e in entries if e.key == "vehicle_NameHawk")
        assert hawk.custom_value == ""
        assert hawk.status == "Unmodified"

    def test_user_only_key_gets_new_status(self):
        sources = self._make_sources()
        entries = load_source_files(
            sources,
            ["global"],
            user_overrides={"brand_new_key": "brand new value"},
        )
        new_entry = next(e for e in entries if e.key == "brand_new_key")
        assert new_entry.status == "New"
        assert new_entry.custom_value == "brand new value"

    def test_vehicle_name_short_entries_skipped(self):
        sources = {
            "global": {
                "vehicle_NameHunter_short": "Cut",
                "vehicle_NameHunter": "Cutlass Black",
            }
        }
        entries = load_source_files(sources, ["global"])
        keys = {e.key for e in entries}
        assert "vehicle_NameHunter_short" not in keys
        assert "vehicle_NameHunter" in keys

    def test_contracts_source_assigns_missions_category(self):
        sources = self._make_sources()
        entries = load_source_files(sources, ["global", "contracts"])
        contract = next(e for e in entries if e.key == "contract_001_name")
        assert contract.category == "Missions"

    def test_empty_sources_returns_empty_list(self):
        assert load_source_files({}, []) == []

    def test_hierarchy_order_respected(self):
        # 'contracts' overrides 'global' for same key when contracts comes later in hierarchy
        sources = {
            "global": {"shared_key": "global_value"},
            "contracts": {"shared_key": "contracts_value"},
        }
        entries = load_source_files(sources, ["global", "contracts"])
        shared = next(e for e in entries if e.key == "shared_key")
        assert shared.original_value == "contracts_value"

    def test_legacy_custom_path_param(self, tmp_path):
        override_file = tmp_path / "user.ini"
        override_file.write_text("vehicle_NameHawk=Legacy Override\n", encoding="utf-8")
        sources = self._make_sources()
        entries = load_source_files(sources, ["global"], custom_path=override_file)
        hawk = next(e for e in entries if e.key == "vehicle_NameHawk")
        assert hawk.custom_value == "Legacy Override"

    def test_journal_key_gets_journal_category(self):
        sources = {"global": {"mission_journal_001": "Journal entry"}}
        entries = load_source_files(sources, ["global"])
        e = next(e for e in entries if e.key == "mission_journal_001")
        assert e.category == "Journal"

    def test_enhancements_key_categories_overrides_category(self):
        sources = {"global": {"vehicle_NameHunter": "Cutlass"}}
        enhancements = {"vehicle_NameHunter": "CustomCategory"}
        entries = load_source_files(sources, ["global"], enhancements_key_categories=enhancements)
        e = next(e for e in entries if e.key == "vehicle_NameHunter")
        assert e.category == "CustomCategory"

    def test_user_source_in_sources_dict_populates_custom_value(self):
        # User source passed via sources_dict (not user_overrides) should still
        # populate custom_value and be excluded from original_value baseline.
        sources = {
            "global": {"vehicle_NameHawk": "Hawk"},
            "user": {"vehicle_NameHawk": "My Hawk"},
        }
        entries = load_source_files(sources, ["global", "user"])
        hawk = next(e for e in entries if e.key == "vehicle_NameHawk")
        assert hawk.custom_value == "My Hawk"
        assert hawk.original_value == "Hawk"
        assert hawk.status == "Modified"

    def test_user_source_only_key_in_sources_dict_is_new(self):
        sources = {
            "global": {"vehicle_NameHawk": "Hawk"},
            "user": {"brand_new": "only in user"},
        }
        entries = load_source_files(sources, ["global", "user"])
        new_e = next(e for e in entries if e.key == "brand_new")
        assert new_e.status == "New"


# ---------------------------------------------------------------------------
# load_sources_from_settings
# ---------------------------------------------------------------------------


def _mock_settings(
    *,
    hierarchy=None,
    cache_dir=None,
    available_sources=None,
    enabled=True,
    global_path=None,
    user_path=None,
    enhancements=None,
):
    """Return a minimal AppSettings mock for load_sources_from_settings tests."""
    from pathlib import Path

    settings = MagicMock()
    settings.SOURCE_GLOBAL = "global"
    settings.SOURCE_USER = "user"
    settings.AVAILABLE_SOURCES = available_sources or ["global", "user"]
    settings.ENHANCEMENTS_FILES = {
        "ship_descs": "ships_desc_enhancements.ini",
        "mission_rewards": "mission_rewards_enhancements.ini",
    }
    settings.get_merge_hierarchy.return_value = hierarchy or ["global", "user"]
    settings.get_cache_dir.return_value = cache_dir or Path("/fake/cache")
    settings.is_source_enabled.return_value = enabled
    settings.get_source_path.side_effect = lambda name: {
        "global": global_path or "",
        "user": user_path or "",
    }.get(name, "")
    settings.get_enabled_enhancement_categories.return_value = enhancements or []
    return settings


@pytest.mark.unit
class TestLoadSourcesFromSettings:
    def test_no_path_configured_skips_source(self, tmp_path):
        mock_s = _mock_settings(global_path="", user_path="")
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, hierarchy, _ = load_sources_from_settings()
        assert "global" not in sources
        assert "user" not in sources

    def test_local_global_file_loaded(self, tmp_path):
        ini = tmp_path / "base.ini"
        ini.write_text("key1=val1\n", encoding="utf-8")
        mock_s = _mock_settings(global_path=str(ini), user_path="")
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, hierarchy, _ = load_sources_from_settings()
        assert sources.get("global") == {"key1": "val1"}

    def test_local_global_missing_silently_skipped(self, tmp_path):
        missing = str(tmp_path / "gone.ini")
        mock_s = _mock_settings(global_path=missing, user_path="")
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        # Missing local file is caught and logged — source is absent, no raise
        assert "global" not in sources

    def test_remote_url_with_cache_file_loaded(self, tmp_path):
        cache_ini = tmp_path / "base.ini"
        cache_ini.write_text("remote_key=remote_val\n", encoding="utf-8")
        mock_s = _mock_settings(
            global_path="https://example.com/global.ini",
            user_path="",
            cache_dir=tmp_path,
        )
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        assert sources.get("global") == {"remote_key": "remote_val"}

    def test_remote_url_missing_cache_silently_skipped(self, tmp_path):
        mock_s = _mock_settings(
            global_path="https://example.com/global.ini",
            user_path="",
            cache_dir=tmp_path,  # cache dir exists but base.ini does not
        )
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        # Missing remote cache is caught and logged — source absent, no raise
        assert "global" not in sources

    def test_user_source_loaded_when_exists(self, tmp_path):
        user_ini = tmp_path / "user.ini"
        user_ini.write_text("uk=uv\n", encoding="utf-8")
        mock_s = _mock_settings(global_path="", user_path=str(user_ini))
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        assert sources.get("user") == {"uk": "uv"}

    def test_user_source_missing_silently_skipped(self, tmp_path):
        mock_s = _mock_settings(global_path="", user_path=str(tmp_path / "no_user.ini"))
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        assert "user" not in sources

    def test_source_disabled_skipped(self, tmp_path):
        ini = tmp_path / "base.ini"
        ini.write_text("k=v\n", encoding="utf-8")
        mock_s = _mock_settings(global_path=str(ini), enabled=False)
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, _, _ = load_sources_from_settings()
        assert "global" not in sources

    def test_enhancements_loaded_and_added_to_hierarchy(self, tmp_path):
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("k=v\n", encoding="utf-8")
        enh_ini = tmp_path / "ships_desc_enhancements.ini"
        enh_ini.write_text("vehicle_NameCutlass=Cut\n", encoding="utf-8")
        mock_s = _mock_settings(
            global_path=str(base_ini),
            user_path="",
            cache_dir=tmp_path,
            enhancements={"ship_descs"},
        )
        with patch("src.utils.settings.AppSettings", mock_s):
            sources, hierarchy, key_cats = load_sources_from_settings()
        assert "enhancements" in sources
        assert "enhancements" in hierarchy
        assert key_cats.get("vehicle_NameCutlass") == "Ships"

    def test_enhancements_user_before_in_hierarchy(self, tmp_path):
        # When "user" is in hierarchy, enhancements should be inserted before it
        base_ini = tmp_path / "base.ini"
        base_ini.write_text("k=v\n", encoding="utf-8")
        user_ini = tmp_path / "user.ini"
        user_ini.write_text("uk=uv\n", encoding="utf-8")
        enh_ini = tmp_path / "ships_desc_enhancements.ini"
        enh_ini.write_text("vehicle_NameCutlass=Cut\n", encoding="utf-8")
        mock_s = _mock_settings(
            hierarchy=["global", "user"],
            global_path=str(base_ini),
            user_path=str(user_ini),
            cache_dir=tmp_path,
            enhancements={"ship_descs"},
        )
        with patch("src.utils.settings.AppSettings", mock_s):
            _, hierarchy, _ = load_sources_from_settings()
        enh_idx = hierarchy.index("enhancements")
        user_idx = hierarchy.index("user")
        assert enh_idx < user_idx


# ---------------------------------------------------------------------------
# parse_ini_file — exception path
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestParseIniFileExceptionPath:
    def test_read_error_returns_empty_dict(self, tmp_path):
        # File exists but open raises — exception is caught, empty dict returned
        f = tmp_path / "bad.ini"
        f.write_text("k=v\n", encoding="utf-8")
        with patch("builtins.open", side_effect=PermissionError("denied")):
            result = parse_ini_file(f)
        assert result == {}
