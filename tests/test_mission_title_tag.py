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
    TagConfig,
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
        assert render_route("A", "B", "arrow") == "A → B"
        assert render_route("A", "B", "to") == "A to B"
        assert render_route("A", "", "gt") == "from A"
        assert render_route("", "B", "gt") == "to B"
        assert render_route("", "", "gt") == ""

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
        assert (cfg.placement, cfg.route_arrow, cfg.title_separator, cfg.location_detail) \
            == ("prepend", "gt", "dash", "name")

    def test_route_fields_round_trip(self):
        cfg = default_config("mission_titles")
        cfg.placement = "replace"
        cfg.route_arrow = "arrow"
        cfg.location_detail = "address"
        cfg.title_separator = "pipe"
        back = TagConfig.from_json(cfg.to_json())
        assert (back.placement, back.route_arrow, back.location_detail, back.title_separator) \
            == ("replace", "arrow", "address", "pipe")


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
