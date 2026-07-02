"""Mission Titles Tag Builder feature (2.1): route formatting, placement,
config persistence, and the #166-toggle migration."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402
from src.utils.tag_builder import (  # noqa: E402
    SIZE_ABBREV_BY_WORD,
    SIZE_ABBREVIATIONS,
    TagConfig,
    abbreviate_title,
    apply_mission_title,
    default_config,
    render_route,
    route_enabled,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def json_backend(tmp_path):
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield AppSettings._backend
    AppSettings._backend = saved


class TestRouteFormatting:
    def test_render_route_both_single_and_arrow(self):
        assert render_route("A", "B", "gt") == "A > B"
        # "->" not U+2192: mobiGlas has no glyph for the real arrow (#200).
        assert render_route("A", "B", "arrow") == "A -> B"
        assert render_route("A", "B", "to") == "A to B"
        assert render_route("A", "", "gt") == "from A"
        assert render_route("", "B", "gt") == "to B"
        assert render_route("", "", "gt") == ""

    def test_shape_arrow_encodes_multiplicity(self):
        """#200 follow-up: "-" one endpoint, "=" several, per side."""
        assert render_route("A", "B", "shape") == "A ->- B"
        assert render_route("A", "B, C", "shape", to_many=True) == "A ->= B, C"
        assert render_route("A, B", "C", "shape", from_many=True) == "A, B =>- C"
        assert render_route("A, B", "C, D", "shape", True, True) == "A, B =>= C, D"
        # One-sided degenerates carry no arrow, so no shape glyph.
        assert render_route("A", "", "shape", to_many=True) == "from A"
        # Non-shape arrows ignore the multiplicity flags.
        assert render_route("A", "B, C", "gt", to_many=True) == "A > B, C"

    def test_apply_placements(self):
        cfg = default_config("mission_titles")  # dash separator, prepend
        cfg.placement = "prepend"
        assert apply_mission_title("Job", "A > B", cfg) == "A > B - Job"
        cfg.placement = "append"
        assert apply_mission_title("Job", "A > B", cfg) == "Job - A > B"
        cfg.placement = "replace"
        assert apply_mission_title("Job", "A > B", cfg) == "A > B"

    def test_empty_route_keeps_original_under_replace(self):
        cfg = default_config("mission_titles")
        cfg.placement = "replace"
        assert apply_mission_title("Job", "", cfg) == "Job"


class TestDefaultAndPersistence:
    def test_default_config_shape(self):
        cfg = default_config("mission_titles")
        assert route_enabled(cfg) is True
        # location_detail defaults to "address" since 2.1.1 (#200): |name
        # fails to resolve for some mission instances in-game.
        assert (cfg.placement, cfg.route_arrow, cfg.title_separator, cfg.location_detail) \
            == ("prepend", "gt", "dash", "address")

    def test_from_dict_missing_location_detail_defaults_to_address(self):
        """Pre-2.1 saved blobs have no location_detail key at all; they must
        land on the safe |Address default, not the 2.1.0 "name" (#200)."""
        cfg = TagConfig.from_dict({"elements": [{"kind": "route", "enabled": True}]})
        assert cfg.location_detail == "address"

    def test_route_fields_round_trip(self):
        cfg = default_config("mission_titles")
        cfg.placement = "replace"
        cfg.route_arrow = "arrow"
        cfg.location_detail = "address"
        cfg.title_separator = "pipe"
        back = TagConfig.from_json(cfg.to_json())
        assert (back.placement, back.route_arrow, back.location_detail, back.title_separator) \
            == ("replace", "arrow", "address", "pipe")


class TestAbbreviateTitle:
    """#200 follow-up: curated stock-title shortening for hauling titles."""

    def test_phrase_map_on_real_title_shapes(self):
        # "Haul" is dropped entirely from shortened titles, not abbreviated.
        assert abbreviate_title(
            "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul"
        ) == "~mission(ReputationRank) - ~mission(CargoGradeToken)"
        assert abbreviate_title(
            "~mission(ReputationRank) Rank - Direct ~mission(CargoGradeToken) Cargo Haul"
        ) == "~mission(ReputationRank) - Direct ~mission(CargoGradeToken)"
        assert abbreviate_title(
            "~mission(ReputationRank) Hauler Needed for ~mission(CargoGradeToken) Shipment"
        ) == "~mission(ReputationRank) - ~mission(CargoGradeToken) Shipment"
        assert abbreviate_title("Covalex Local Shipment Route") == "Covalex Route"
        assert abbreviate_title(
            "Opportunity for Independent Cargo Hauler"
        ) == "Intro"

    def test_removed_phrase_never_leaves_dangling_separator(self):
        assert abbreviate_title("Something - Cargo Haul") == "Something"

    def test_size_abbreviations_order_and_content(self):
        # Longest-first so a literal-text pass can't turn "Extra Small"
        # into "Extra S".
        words = [w for w, _ in SIZE_ABBREVIATIONS]
        assert words.index("Extra Small") < words.index("Small")
        assert words.index("Extra Large") < words.index("Large")
        assert SIZE_ABBREV_BY_WORD["Extra Small"] == "XS"
        assert SIZE_ABBREV_BY_WORD["Medium"] == "M"

    def test_unmapped_title_passes_through(self):
        assert abbreviate_title("Quantum Sensitive Delivery") == "Quantum Sensitive Delivery"

    def test_tokens_never_touched(self):
        # No phrase in the map may rewrite inside a ~mission(...) token.
        s = "~mission(CargoGradeToken) and ~mission(ReputationRank)"
        assert abbreviate_title(s) == s

    def test_config_default_off_and_round_trip(self):
        cfg = default_config("mission_titles")
        assert cfg.abbreviate_title is False
        cfg.abbreviate_title = True
        assert TagConfig.from_json(cfg.to_json()).abbreviate_title is True
        # Pre-2.1.1 blobs have no key at all: default off.
        assert TagConfig.from_dict({}).abbreviate_title is False


class TestLocationDetailMigration:
    """2.1.1 (#200): a 2.1.0-seeded location_detail "name" flips to "address"
    exactly once; a deliberate Name pick afterward survives."""
    _CFG_KEY = "tag_builder/mission_titles/config"
    _MARKER = "tag_builder/mission_titles/location_detail_migrated"

    def test_seeded_name_flips_to_address(self, json_backend):
        cfg = default_config("mission_titles")
        cfg.location_detail = "name"     # what every saved 2.1.0 config holds
        cfg.placement = "replace"        # other fields must survive the flip
        AppSettings.set_tag_config("mission_titles", cfg)
        AppSettings.migrate_mission_titles_location_detail()
        back = AppSettings.get_tag_config("mission_titles")
        assert back.location_detail == "address"
        assert back.placement == "replace"
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_no_saved_config_only_sets_marker(self, json_backend):
        # Fresh install: nothing to flip, defaults are already address.
        AppSettings.migrate_mission_titles_location_detail()
        assert not json_backend.value(self._CFG_KEY, "", type=str)
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_runs_once_so_deliberate_name_survives(self, json_backend):
        AppSettings.migrate_mission_titles_location_detail()
        cfg = default_config("mission_titles")
        cfg.location_detail = "name"     # deliberate post-2.1.1 choice
        AppSettings.set_tag_config("mission_titles", cfg)
        AppSettings.migrate_mission_titles_location_detail()
        assert AppSettings.get_tag_config("mission_titles").location_detail == "name"


class TestRouteToggleMigration:
    _CFG_KEY = "tag_builder/mission_titles/config"
    _MARKER = "mission_field/route_migrated"

    def test_old_route_off_disables_new_element(self, json_backend):
        json_backend.setValue("mission_field/route", "false")
        AppSettings.migrate_route_toggle_to_mission_titles()
        cfg = AppSettings.get_tag_config("mission_titles")
        assert route_enabled(cfg) is False
        assert json_backend.value(self._MARKER, False, type=bool) is True

    def test_old_route_on_or_unset_leaves_default_on(self, json_backend):
        # Unset (user never touched it) -> no config written, feature stays on.
        AppSettings.migrate_route_toggle_to_mission_titles()
        assert not json_backend.value(self._CFG_KEY, "", type=str)
        assert route_enabled(AppSettings.get_tag_config("mission_titles")) is True

    def test_migration_runs_once(self, json_backend):
        json_backend.setValue("mission_field/route", "false")
        AppSettings.migrate_route_toggle_to_mission_titles()
        # A later flip of the new config must survive a second migrate call.
        cfg = default_config("mission_titles")
        AppSettings.set_tag_config("mission_titles", cfg)  # re-enable
        AppSettings.migrate_route_toggle_to_mission_titles()
        assert route_enabled(AppSettings.get_tag_config("mission_titles")) is True
