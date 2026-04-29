"""Tests for src.utils.version.get_version."""

import sys
from unittest.mock import patch

import pytest
from src.utils.version import get_version

pytestmark = pytest.mark.unit


def test_unfrozen_returns_non_empty_string():
    result = get_version()
    assert isinstance(result, str)
    assert result != ""


def test_frozen_reads_version_from_meipass(tmp_path):
    (tmp_path / "VERSION.TXT").write_text("9.8.7", encoding="utf-8")
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            result = get_version()
    assert result == "9.8.7"


def test_returns_fallback_when_version_txt_missing(tmp_path):
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            result = get_version()
    assert result == "0.1.0"


def test_frozen_strips_whitespace_from_version(tmp_path):
    (tmp_path / "VERSION.TXT").write_text("  2.0.0  \n", encoding="utf-8")
    with patch.object(sys, "frozen", True, create=True):
        with patch.object(sys, "_MEIPASS", str(tmp_path), create=True):
            result = get_version()
    assert result == "2.0.0"
