"""Tests for src.utils.applied_file_validator.validate_applied_file."""

from unittest.mock import patch

import pytest

from src.utils.applied_file_validator import validate_applied_file

pytestmark = pytest.mark.unit


def test_missing_base_ini_returns_empty(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path)
    assert result == ""


def test_perfect_match_returns_empty(tmp_path):
    (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path)
    assert result == ""


def test_missing_keys_reported(tmp_path):
    (tmp_path / "base.ini").write_text("key1=a\nkey2=b\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key1=a\n", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path)
    assert "1 key(s) from base.ini" in result
    assert "key2" in result
    assert "restored" in result.lower()


def test_extra_keys_reported(tmp_path):
    (tmp_path / "base.ini").write_text("key1=a\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key1=a\nextra=b\n", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path)
    assert "1 unexpected key(s)" in result
    assert "extra" in result


def test_precomputed_stock_keys_skips_cache_dir(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key1=a\n", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path, stock_keys={"key1", "key2"})
    assert "key2" in result


def test_more_than_20_missing_shows_truncation(tmp_path):
    stock_keys = {f"key{i}" for i in range(25)}
    written = tmp_path / "written.ini"
    written.write_text("", encoding="utf-8-sig")
    result = validate_applied_file(written, tmp_path, stock_keys=stock_keys)
    assert "... and" in result


def test_values_may_differ(tmp_path):
    """Validation passes when keys match even if values diverge."""
    written = tmp_path / "written.ini"
    written.write_text("k1=different_value\n", encoding="utf-8-sig")
    assert validate_applied_file(written, tmp_path, stock_keys={"k1"}) == ""


def test_stock_parse_exception_returns_empty(tmp_path):
    (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
    (tmp_path / "written.ini").write_text("key=val\n", encoding="utf-8-sig")
    with patch(
        "src.utils.applied_file_validator.parse_ini_file",
        side_effect=Exception("boom"),
    ):
        result = validate_applied_file(tmp_path / "written.ini", tmp_path)
    assert result == ""


def test_written_parse_exception_returns_empty(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8-sig")
    with patch(
        "src.utils.applied_file_validator.parse_ini_file",
        side_effect=Exception("boom"),
    ):
        result = validate_applied_file(written, tmp_path, stock_keys={"key"})
    assert result == ""


class TestBomCheck:
    """#261: the game's own loc-string loader needs the UTF-8 BOM Data.p4k's
    own extracted global.ini ships with to reliably detect encoding — without
    it the game can fail to resolve every key (shown as raw @KeyName
    placeholders) rather than degrading per-key. This was the actual
    mechanism behind a real "whole in-game UI shows raw loc keys" report:
    merge_ini_files wrote plain utf-8 (no BOM), and our own readers are
    utf-8-sig-aware so parse_ini_file accepted the BOM-less file fine —
    meaning the key-presence check alone reported success on a file the game
    itself couldn't parse. This class is the safety net: a missing BOM must
    fail validation and trigger the caller's rollback-to-backup path, even
    when every key is present and every value matches."""

    def test_missing_bom_fails_even_with_perfect_key_match(self, tmp_path):
        (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
        written = tmp_path / "written.ini"
        written.write_text("key=val\n", encoding="utf-8")  # no BOM — the bug
        result = validate_applied_file(written, tmp_path)
        assert result != ""
        assert "BOM" in result

    def test_present_bom_with_perfect_key_match_passes(self, tmp_path):
        (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
        written = tmp_path / "written.ini"
        written.write_text("key=val\n", encoding="utf-8-sig")
        assert validate_applied_file(written, tmp_path) == ""

    def test_missing_bom_reported_alongside_missing_keys(self, tmp_path):
        (tmp_path / "base.ini").write_text("key1=a\nkey2=b\n", encoding="utf-8")
        written = tmp_path / "written.ini"
        written.write_text("key1=a\n", encoding="utf-8")  # no BOM, and missing key2
        result = validate_applied_file(written, tmp_path)
        assert "BOM" in result
        assert "key2" in result

    def test_unreadable_file_for_bom_check_does_not_crash(self, tmp_path):
        """A file that vanishes between the caller's write and validation
        (or any other read error) must not blow up validation — same
        fail-open posture as the other exception guards in this module."""
        missing = tmp_path / "does_not_exist.ini"
        assert validate_applied_file(missing, tmp_path) == ""
