"""Tests for _blueprint_scan_since (#308): "Rescan all logs" ignores the
saved watermark for one scan run, falling back to the scanner's own
March-2026 epoch floor (BLUEPRINT_EPOCH) via a None since value.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.gui.main_window import _blueprint_scan_since


class TestBlueprintScanSince:
    def test_unforced_passes_watermark_through(self):
        watermark = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert _blueprint_scan_since(False, watermark) == watermark

    def test_unforced_none_watermark_stays_none(self):
        assert _blueprint_scan_since(False, None) is None

    def test_forced_ignores_watermark(self):
        watermark = datetime(2026, 5, 1, tzinfo=timezone.utc)
        assert _blueprint_scan_since(True, watermark) is None

    def test_forced_with_no_watermark_is_still_none(self):
        assert _blueprint_scan_since(True, None) is None
