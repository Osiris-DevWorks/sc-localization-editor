"""Tests for ensure_default_settings() — seeds default source settings on first launch."""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSettings
from src.utils.settings import AppSettings

pytestmark = pytest.mark.unit

# ─────────────────────────────────────────────────────────────────────────────
# Fixtures (mirror the pattern from test_channel_layout.py)
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_qsettings(tmp_path, monkeypatch):
    """Point QSettings at a temp file so tests don't stomp on the real
    Windows Registry."""
    settings_file = tmp_path / "test_registry.ini"

    def _isolated():
        return QSettings(str(settings_file), QSettings.Format.IniFormat)

    monkeypatch.setattr(AppSettings, "settings", staticmethod(_isolated))
    yield


@pytest.fixture
def fake_user_data_dir(tmp_path, monkeypatch):
    """Redirect get_user_data_dir() so the migrators that touch path-helpers
    don't try to mkdir under a real Documents folder."""
    user_dir = tmp_path / "Open Strings"
    user_dir.mkdir(parents=True)
    monkeypatch.setattr(AppSettings, "get_user_data_dir", staticmethod(lambda: user_dir))
    return user_dir


# ─────────────────────────────────────────────────────────────────────────────
# ensure_default_settings — fresh-install defaults
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.critical
class TestFreshInstallDefaults:
    """A fresh install (empty registry) gets only global + user."""

    def test_seeds_global_and_user_only(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.ensure_default_settings()

        assert AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)
        assert AppSettings.get_source_path(AppSettings.SOURCE_USER)
        assert AppSettings.get_merge_hierarchy() == [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]

    def test_default_hierarchy_is_global_user(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.ensure_default_settings()
        assert AppSettings.get_merge_hierarchy() == [
            AppSettings.SOURCE_GLOBAL,
            AppSettings.SOURCE_USER,
        ]

    def test_idempotent(self, isolated_qsettings, fake_user_data_dir):
        AppSettings.ensure_default_settings()
        first_hierarchy = AppSettings.get_merge_hierarchy()
        first_global_path = AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)

        # Re-run — should be a no-op
        AppSettings.ensure_default_settings()
        assert AppSettings.get_merge_hierarchy() == first_hierarchy
        assert AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL) == first_global_path
