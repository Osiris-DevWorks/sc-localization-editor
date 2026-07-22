"""Tests for _name_from_blueprint_filename's fuel-nozzle alias correction (#281).

Fuel nozzle blueprint rewards miss both the UUID and filename entity-name
resolution tiers in build_blueprint_pool_lookup, falling through to this
function's title-cased-slug fallback -- confirmed live in-game via an
"URGENT REFUEL REQUEST" mission listing all 8 variants as raw garbled text
(e.g. "Nozzle Fuelgiver Grin Nozzlefast") instead of their real names.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_bp_filename_fallback_test", script_path,
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestFuelNozzleFallbackAliases:
    @pytest.mark.regression
    @pytest.mark.parametrize("filename,expected", [
        ("bp_craft_nozzle_fuelgiver_grin_nozzlefast.xml", "Norfield"),
        ("bp_craft_nozzle_fuelgiver_grin_nozzlesecure.xml", "Marlin"),
        ("bp_craft_nozzle_fuelgiver_grin_nozzleveryfast.xml", "Lindstrom"),
        ("bp_craft_nozzle_fuelgiver_grin_nozzleverysecure.xml", "Harkin"),
        ("bp_craft_nozzle_fuelgiver_misc_nozzlestandard.xml", "RN-7s"),
        ("bp_craft_nozzle_fuelgiver_shin_nozzleexpensivefast.xml", "Bendix"),
        ("bp_craft_nozzle_fuelgiver_shin_nozzleexpensivesecure.xml", "Torrez"),
        ("bp_craft_nozzle_fuelgiver_shin_nozzlemostexpensive.xml", "Ezra"),
    ])
    def test_known_fuel_nozzle_fallback_resolves_to_real_name(self, gen_module, filename, expected):
        assert gen_module._name_from_blueprint_filename(Path(filename)) == expected


class TestUnrelatedFilenameFallbackUnaffected:
    def test_non_nozzle_fallback_still_title_cased(self, gen_module):
        """Regression guard: the alias correction must not touch any other
        blueprint's filename-derived fallback name."""
        assert (
            gen_module._name_from_blueprint_filename(
                Path("bp_craft_salvage_modifier_scraper_large.xml")
            )
            == "Salvage Modifier Scraper Large"
        )

    def test_bp_rewards_prefix_still_stripped(self, gen_module):
        assert (
            gen_module._name_from_blueprint_filename(
                Path("bp_rewards_eckhartsecuritykillnpcboss.xml")
            )
            == "Eckhartsecuritykillnpcboss"
        )
