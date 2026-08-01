"""Tests for _channels_to_scan (#268): which channels a "Scan Logs for Owned
Blueprints" run should cover.

LIVE and HOTFIX share the same account/blueprint progression (HOTFIX is a
same-account emergency-patch channel), so a blueprint earned on one shows up
in the other's logs too. PTU/EPTU/TECH-PREVIEW are separate test builds with
their own progression and must never be included, regardless of the "also
scan other channels" checkbox or which of them happen to be installed.
"""
from __future__ import annotations

from src.gui.main_window import _channels_to_scan


class TestChannelsToScan:
    def test_active_channel_always_included_alone_when_disabled(self):
        assert _channels_to_scan("LIVE", False, {"LIVE", "HOTFIX", "PTU"}) == ["LIVE"]

    def test_active_channel_alone_when_no_other_linked_channel_installed(self):
        assert _channels_to_scan("LIVE", True, {"LIVE", "PTU"}) == ["LIVE"]

    def test_adds_hotfix_when_active_is_live_and_installed(self):
        assert _channels_to_scan("LIVE", True, {"LIVE", "HOTFIX"}) == ["LIVE", "HOTFIX"]

    def test_adds_live_when_active_is_hotfix_and_installed(self):
        assert _channels_to_scan("HOTFIX", True, {"LIVE", "HOTFIX"}) == ["HOTFIX", "LIVE"]

    def test_never_includes_ptu_eptu_tech_preview_even_when_enabled(self):
        installed = {"LIVE", "HOTFIX", "PTU", "EPTU", "TECH-PREVIEW"}
        result = _channels_to_scan("LIVE", True, installed)
        assert result == ["LIVE", "HOTFIX"]
        assert "PTU" not in result
        assert "EPTU" not in result
        assert "TECH-PREVIEW" not in result

    def test_active_channel_is_ptu_never_adds_anything_even_when_enabled(self):
        """PTU/EPTU/TECH-PREVIEW as the ACTIVE channel must not pull in
        LIVE/HOTFIX either -- the linked pair is LIVE<->HOTFIX only."""
        assert _channels_to_scan("PTU", True, {"LIVE", "HOTFIX", "PTU"}) == ["PTU"]

    def test_disabled_ignores_installed_set_entirely(self):
        """Checkbox off means only the active channel, no matter what's
        actually installed."""
        assert _channels_to_scan("LIVE", False, {"LIVE", "HOTFIX"}) == ["LIVE"]

    def test_empty_installed_set_is_safe(self):
        assert _channels_to_scan("LIVE", True, set()) == ["LIVE"]
