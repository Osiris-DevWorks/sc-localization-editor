"""Star Citizen log scanning for "Received Blueprint" reward notifications.

Regex/parsing verified against real Game.log / logbackups output (2026-07).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils.blueprint_log_scanner import (  # noqa: E402
    extract_blueprint_names,
    find_log_files,
    scan_log_files,
)

pytestmark = [pytest.mark.unit]


def _notification_line(name: str, notif_id: int = 15) -> str:
    """Build a realistic SHUDEvent_OnNotification log line for *name*."""
    return (
        f'<2026-07-09T07:54:03.720Z> [Notice] <SHUDEvent_OnNotification> '
        f'Added notification "Received Blueprint: {name}: " [{notif_id}] to queue. '
        f'New queue size: 4, MissionId: [00000000-0000-0000-0000-000000000000], '
        f'ObjectiveId: [] [Team_CoreGameplayFeatures][Missions][Comms]'
    )


class TestExtractBlueprintNames:
    def test_bare_name(self):
        text = _notification_line("Balandin")
        assert extract_blueprint_names(text) == {"Balandin"}

    def test_strips_component_tag(self):
        text = _notification_line("Agni [Industrial-S3-B-Quantum]")
        assert extract_blueprint_names(text) == {"Agni"}

    def test_strips_short_component_tag(self):
        text = _notification_line("Barbican [IND-S3-B]")
        assert extract_blueprint_names(text) == {"Barbican"}

    def test_name_with_embedded_quotes_not_truncated(self):
        # Paint/skin variant names carry their own literal quotes — a naive
        # capture-to-next-quote would truncate at "Demeco.
        text = _notification_line('Demeco "Purgatory Camo" LMG')
        assert extract_blueprint_names(text) == {'Demeco "Purgatory Camo" LMG'}

    def test_distinguishes_size_variants(self):
        text = "\n".join([
            _notification_line("QuadraCell [Military-S1-A-Power]", 1),
            _notification_line("QuadraCell MT [Military-S2-A-Power]", 2),
        ])
        assert extract_blueprint_names(text) == {"QuadraCell", "QuadraCell MT"}

    def test_repeated_notification_events_dedupe(self):
        # A single earned blueprint fires 4 log lines (queued + Next/
        # StartFade/Remove), all with identical notification text.
        text = "\n".join([
            _notification_line("Torrez", 5),
            f'<2026-07-09T07:54:18.830Z> [Notice] <UpdateNotificationItem> '
            f'Notification "Received Blueprint: Torrez: " [5], Action: Next '
            f'[Team_CoreGameplayFeatures][Missions][Comms]',
            f'<2026-07-09T07:54:23.847Z> [Notice] <UpdateNotificationItem> '
            f'Notification "Received Blueprint: Torrez: " [5], Action: StartFade '
            f'[Team_CoreGameplayFeatures][Missions][Comms]',
        ])
        assert extract_blueprint_names(text) == {"Torrez"}

    def test_unrelated_blueprint_mentions_ignored(self):
        text = (
            '<2026-06-07T04:27:45.846Z> [Notice] <ReuseChannel> Reusing channel '
            "for 'sc.external.services.blueprint_library.v1.BlueprintLibraryService' "
            "to endpoint pub-sc-alpha.example.com:443 (transport security: 1) "
            "[Team_OnlineTech][gRPC]"
        )
        assert extract_blueprint_names(text) == set()

    def test_empty_text(self):
        assert extract_blueprint_names("") == set()


class TestFindLogFiles:
    def test_finds_logbackups_and_live_log(self, tmp_path):
        (tmp_path / "logbackups").mkdir()
        a = tmp_path / "logbackups" / "Game Build(1) 01 Jan 26 (00 00 00).log"
        a.write_text("a")
        b = tmp_path / "logbackups" / "Game Build(1) 02 Jan 26 (00 00 00).log"
        b.write_text("b")
        live = tmp_path / "Game.log"
        live.write_text("c")

        files = find_log_files(tmp_path)
        assert set(files) == {a, b, live}

    def test_no_live_log_present(self, tmp_path):
        (tmp_path / "logbackups").mkdir()
        a = tmp_path / "logbackups" / "x.log"
        a.write_text("a")

        assert find_log_files(tmp_path) == [a]

    def test_missing_directory_yields_empty(self, tmp_path):
        assert find_log_files(tmp_path / "nonexistent") == []


class TestScanLogFiles:
    def test_scans_multiple_files_and_unions(self, tmp_path):
        f1 = tmp_path / "a.log"
        f1.write_text(_notification_line("Balandin"))
        f2 = tmp_path / "b.log"
        f2.write_text(_notification_line("Torrez"))

        found = scan_log_files([f1, f2])
        assert found == {"Balandin", "Torrez"}

    def test_progress_callback_invoked_per_file(self, tmp_path):
        f1 = tmp_path / "a.log"
        f1.write_text(_notification_line("Balandin"))
        f2 = tmp_path / "b.log"
        f2.write_text(_notification_line("Torrez"))

        calls = []
        scan_log_files([f1, f2], progress_callback=lambda c, t, m: calls.append((c, t, m)))
        # One call per file (0, 1) plus a final (total, total) completion call.
        assert calls[0] == (0, 2, "a.log")
        assert calls[1] == (1, 2, "b.log")
        assert calls[2] == (2, 2, "")

    def test_unreadable_file_skipped_not_fatal(self, tmp_path):
        f1 = tmp_path / "a.log"
        f1.write_text(_notification_line("Balandin"))
        missing = tmp_path / "does_not_exist.log"

        found = scan_log_files([f1, missing])
        assert found == {"Balandin"}

    def test_empty_paths_yields_empty_set(self):
        assert scan_log_files([]) == set()
