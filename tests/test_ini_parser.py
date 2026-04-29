"""Tests for src/parser/ini_parser.py — covering the previously untested paths."""

import pytest
from src.parser.ini_parser import (
    _determine_status,
    _determine_status_from_source,
    load_overrides,
    load_source_files,
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
