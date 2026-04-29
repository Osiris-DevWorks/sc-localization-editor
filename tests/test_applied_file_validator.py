"""Tests for src.utils.applied_file_validator.validate_applied_file."""

from unittest.mock import patch

import pytest
from src.utils.applied_file_validator import validate_applied_file

pytestmark = pytest.mark.unit


def test_missing_base_ini_returns_empty(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8")
    result = validate_applied_file(written, tmp_path)
    assert result == ""


def test_perfect_match_returns_empty(tmp_path):
    (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8")
    result = validate_applied_file(written, tmp_path)
    assert result == ""


def test_missing_keys_reported(tmp_path):
    (tmp_path / "base.ini").write_text("key1=a\nkey2=b\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key1=a\n", encoding="utf-8")
    result = validate_applied_file(written, tmp_path)
    assert "1 key(s) from base.ini" in result
    assert "key2" in result
    assert "restored" in result.lower()


def test_extra_keys_reported(tmp_path):
    (tmp_path / "base.ini").write_text("key1=a\n", encoding="utf-8")
    written = tmp_path / "written.ini"
    written.write_text("key1=a\nextra=b\n", encoding="utf-8")
    result = validate_applied_file(written, tmp_path)
    assert "1 unexpected key(s)" in result
    assert "extra" in result


def test_precomputed_stock_keys_skips_cache_dir(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key1=a\n", encoding="utf-8")
    result = validate_applied_file(written, tmp_path, stock_keys={"key1", "key2"})
    assert "key2" in result


def test_more_than_20_missing_shows_truncation(tmp_path):
    stock_keys = {f"key{i}" for i in range(25)}
    written = tmp_path / "written.ini"
    written.write_text("", encoding="utf-8")
    result = validate_applied_file(written, tmp_path, stock_keys=stock_keys)
    assert "... and" in result


def test_stock_parse_exception_returns_empty(tmp_path):
    (tmp_path / "base.ini").write_text("key=val\n", encoding="utf-8")
    (tmp_path / "written.ini").write_text("key=val\n", encoding="utf-8")
    with patch("src.utils.applied_file_validator.parse_ini_file", side_effect=Exception("boom")):
        result = validate_applied_file(tmp_path / "written.ini", tmp_path)
    assert result == ""


def test_written_parse_exception_returns_empty(tmp_path):
    written = tmp_path / "written.ini"
    written.write_text("key=val\n", encoding="utf-8")
    with patch("src.utils.applied_file_validator.parse_ini_file", side_effect=Exception("boom")):
        result = validate_applied_file(written, tmp_path, stock_keys={"key"})
    assert result == ""
