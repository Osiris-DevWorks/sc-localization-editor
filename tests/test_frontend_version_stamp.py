"""Tests for the Frontend_PU_Version watermark applied at apply-to-game time."""
from unittest.mock import patch

import pytest

from src.gui.main_window import (
    _FRONTEND_VERSION_KEY,
    _FRONTEND_VERSION_STAMP_RE,
    _stamp_frontend_version,
)


@pytest.fixture
def mock_version():
    with patch("src.utils.version.get_version", return_value="1.3.1"):
        yield "1.3.1"


class TestFrontendVersionStamp:
    def test_appends_watermark_to_stock_value(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen Alpha 4.8.0 PTU"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_skips_when_key_missing(self, mock_version):
        merged = {"SomeOtherKey": "value"}
        _stamp_frontend_version(merged)
        assert _FRONTEND_VERSION_KEY not in merged

    def test_idempotent_same_version(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen Alpha 4.8.0 PTU"}
        _stamp_frontend_version(merged)
        once = merged[_FRONTEND_VERSION_KEY]
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == once

    def test_rolls_forward_to_new_version(self):
        merged = {
            _FRONTEND_VERSION_KEY:
                "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.0"
        }
        with patch("src.utils.version.get_version", return_value="1.3.1"):
            _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_rolls_forward_from_old_pipe_format(self):
        # Pre-2.3.0 installs have the original " | "-separated watermark on
        # disk (#296-adjacent request: move the watermark to its own line) —
        # the next apply must replace it with the new "\n"-separated form,
        # not leave the old one dangling or double-stamp.
        merged = {
            _FRONTEND_VERSION_KEY:
                "Star Citizen Alpha 4.8.0 PTU | Localizations Enhanced with Smart Citizen v1.3.0"
        }
        with patch("src.utils.version.get_version", return_value="1.3.1"):
            _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    @pytest.mark.parametrize("legacy_suffix", [
        # First-cut watermark (heart emoji as text, "by") — pre-1.3.1 prereleases
        "| Enhanced with <3 by Smart Citizen v1.3.0",
        "| Enhanced with <3 by Smart Citizen 1.2.9",
        # Second-cut watermark ("Enhanced by", no v) — interim 1.3.1 build
        "| Localizations Enhanced by Smart Citizen 1.3.0",
        "| Localizations Enhanced by Smart Citizen v1.3.0",
        # Third-cut watermark (" | "-separated "Enhanced with") — pre-2.3.0
        "| Localizations Enhanced with Smart Citizen v1.3.0",
    ])
    def test_strips_legacy_phrasings(self, mock_version, legacy_suffix):
        # Every prior on-disk watermark wording must be stripped, not
        # left to accumulate, so users who applied with an earlier
        # build get the current phrasing on next Apply.
        merged = {
            _FRONTEND_VERSION_KEY: f"Star Citizen Alpha 4.8.0 PTU {legacy_suffix}"
        }
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen Alpha 4.8.0 PTU\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_preserves_user_edited_base_value(self, mock_version):
        merged = {_FRONTEND_VERSION_KEY: "My Custom Build"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "My Custom Build\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )

    def test_stamp_regex_matches_with_extra_whitespace(self):
        cases = [
            " | Localizations Enhanced with Smart Citizen v1.3.1",
            "  |  Localizations Enhanced with Smart Citizen v1.3.1",
            " | Localizations Enhanced with Smart Citizen 1.3.1",  # no-v tolerated
            " | Localizations Enhanced with Smart Citizen v1.3.1   ",
            "\\nLocalizations Enhanced with Smart Citizen v1.3.1",  # new form
            "\\nLocalizations Enhanced with Smart Citizen 1.3.1   ",  # no-v tolerated
        ]
        for suffix in cases:
            full = "Base value" + suffix
            assert _FRONTEND_VERSION_STAMP_RE.search(full), (
                f"regex did not match expected suffix: {suffix!r}"
            )

    def test_does_not_strip_pipe_in_base_value(self, mock_version):
        # Plain pipe in the middle isn't our watermark — leave it alone.
        merged = {_FRONTEND_VERSION_KEY: "Star Citizen | Build A"}
        _stamp_frontend_version(merged)
        assert merged[_FRONTEND_VERSION_KEY] == (
            "Star Citizen | Build A\\nLocalizations Enhanced with Smart Citizen v1.3.1"
        )
