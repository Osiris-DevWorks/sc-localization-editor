"""Tests for ``enhancements_bare_type_tags`` (#266).

Some component-adjacent items (fuel nozzles so far) carry no Size:/Grade:/
Class: of their own -- there's nothing to hang the usual "[MIL-S1-A]" shape
off of, so a Type-only tag is their only option. Gated by the same
Components > Type element toggle as every other DEFAULT_COMPONENT_TYPE_
MAPPING entry (Shield Generator, Cooler, ...) -- users opt in or out, they
aren't force-shown just because they'd otherwise have no other tag.

Identified by the paired ``_Desc`` entry's own "Item Type: X" line, NOT by
loc-key naming -- fuel nozzles ship under at least two different key
conventions for different manufacturers (``item_fuelnozzle_MISC_Standard_*``
for MISC's RN-7s, but ``Nozzle_FuelGiver_GRIN_NozzleSecure_*`` for
Greycat's Marlin and ``Nozzle_FuelGiver_SHIN_*`` for Shubin's nozzles --
confirmed via tests/fixtures/kraken_global_latest.ini). An earlier
key-prefix-only version of this pass silently missed every
``Nozzle_FuelGiver_*`` entry (issue #266 follow-up report: "only some fuel
nozzles worked").
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
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_bare_type_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _components_cfg_with_type(gen_module, style="short", placement=None):
    """DEFAULT_TAG_CONFIGS["components"] with the Type element switched on
    (it's disabled by default) at the given style, same knob a real user
    flips via the Tag Builder's Components > Type checkbox."""
    comp_cfg = gen_module.DEFAULT_TAG_CONFIGS["components"]
    elements = [
        gen_module.ElementSpec(el.kind, el.enabled, el.style)
        for el in comp_cfg.elements
    ]
    for i, el in enumerate(elements):
        if el.kind == "type":
            elements[i] = gen_module.ElementSpec("type", True, style)
    return gen_module.TagConfig(
        elements=elements,
        separator=comp_cfg.separator,
        enclosing=comp_cfg.enclosing,
        placement=placement or comp_cfg.placement,
        class_mapping=comp_cfg.class_mapping,
    )


# Real stock text (tests/fixtures/kraken_global_latest.ini) -- the "\n"
# here is the literal two-character escape CIG ships in base.ini, not a
# real newline.
_RN7S_DESC = "Manufacturer: MISC\\nItem Type: Fuel Nozzle\\nHydrogen Flow Speed: 1.65 SCU/s\\n"
_MARLIN_DESC = "Manufacturer: Greycat Industrial\\nItem Type: Fuel Nozzle\\nHydrogen Flow Speed: 1.05 SCU/s\\n"


class TestEnhancementsBareTypeTags:
    def test_no_tag_when_type_disabled_by_default(self, gen_module):
        """Type is disabled by default for "components" -- with no explicit
        config, fuel nozzles get no tag at all, same as any other
        DEFAULT_COMPONENT_TYPE_MAPPING entry the user hasn't opted into."""
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}})
        assert out == {}

    def test_tags_fuel_nozzle_when_type_enabled(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[FN] RN-7s"}

    @pytest.mark.regression
    def test_tags_nozzle_fuelgiver_naming_convention_too(self, gen_module):
        """Regression guard: Greycat/Shubin fuel nozzles ship under the
        Nozzle_FuelGiver_* key convention, not item_fuelnozzle_* -- both
        must get tagged since detection keys off the Desc's Item Type
        text, not the Name key's prefix."""
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "Nozzle_FuelGiver_GRIN_NozzleSecure_Name": "Marlin",
            "Nozzle_FuelGiver_GRIN_NozzleSecure_Desc": _MARLIN_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"Nozzle_FuelGiver_GRIN_NozzleSecure_Name": "[FN] Marlin"}

    def test_respects_users_configured_type_style(self, gen_module):
        """A user who's enabled Type gets their chosen abbreviation length
        (short/medium/long) applied here too."""
        cfg = _components_cfg_with_type(gen_module, style="long")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[Fuel Nozzle] RN-7s"}

    def test_respects_append_placement(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short", placement="append")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "RN-7s [FN]"}

    def test_tags_short_name_variant_too(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Name_short": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out["item_fuelnozzle_MISC_Standard_Name"] == "[FN] RN-7s"
        assert out["item_fuelnozzle_MISC_Standard_Name_short"] == "[FN] RN-7s"

    def test_missing_desc_is_skipped(self, gen_module):
        """No paired _Desc entry at all -- can't determine Item Type, so
        no tag (rather than guessing from the key name)."""
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {}

    def test_unrelated_item_type_untouched(self, gen_module):
        """A component with a real Item Type that isn't in the small
        bare-type allow-list (e.g. Shield Generator, tagged elsewhere via
        the strict Class-based DataForge scan) must not get double-tagged
        here."""
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
            "item_NameSHLD_ASAS_S01_Shimmer": "Shimmer",
            "item_NameSHLD_ASAS_S01_Shimmer_Desc": "Item Type: Shield Generator\\nSize: 1\\nGrade: A\\n",
            "some_unrelated_key": "unrelated value",
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert set(out) == {"item_fuelnozzle_MISC_Standard_Name"}

    def test_empty_loc_is_empty(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        out = gen_module.enhancements_bare_type_tags(
            {"loc": {}, "tag_configs": {"components": cfg}}
        )
        assert out == {}

    def test_missing_name_value_is_skipped(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "",
            "item_fuelnozzle_MISC_Standard_Desc": _RN7S_DESC,
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {}
