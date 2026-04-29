"""Tests for src.utils.user_cfg.ensure_user_cfg_language."""

from pathlib import Path
from unittest.mock import patch

import pytest
from src.utils.user_cfg import ensure_user_cfg_language

pytestmark = pytest.mark.unit


def test_returns_false_when_no_channel_path():
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=""):
        assert ensure_user_cfg_language() is False


def test_returns_false_when_channel_dir_missing(tmp_path):
    missing = str(tmp_path / "LIVE")
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=missing):
        assert ensure_user_cfg_language() is False


def test_creates_user_cfg_when_absent(tmp_path):
    game_dir = tmp_path / "LIVE"
    game_dir.mkdir()
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=str(game_dir)):
        result = ensure_user_cfg_language()
    assert result is True
    assert (game_dir / "user.cfg").read_text(encoding="utf-8") == "g_language = english\n"


def test_appends_language_when_absent_from_existing_file(tmp_path):
    game_dir = tmp_path / "LIVE"
    game_dir.mkdir()
    (game_dir / "user.cfg").write_text("r_fullscreen = 1\n", encoding="utf-8")
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=str(game_dir)):
        result = ensure_user_cfg_language()
    assert result is True
    content = (game_dir / "user.cfg").read_text(encoding="utf-8")
    assert "g_language = english" in content
    assert "r_fullscreen = 1" in content


def test_noop_when_language_already_present(tmp_path):
    game_dir = tmp_path / "LIVE"
    game_dir.mkdir()
    (game_dir / "user.cfg").write_text("g_language = english\n", encoding="utf-8")
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=str(game_dir)):
        result = ensure_user_cfg_language()
    assert result is True
    content = (game_dir / "user.cfg").read_text(encoding="utf-8")
    assert content.count("g_language = english") == 1


def test_returns_false_on_write_exception(tmp_path):
    game_dir = tmp_path / "LIVE"
    game_dir.mkdir()
    with patch("src.utils.user_cfg.AppSettings.get_game_install_path", return_value=str(game_dir)):
        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            result = ensure_user_cfg_language()
    assert result is False
