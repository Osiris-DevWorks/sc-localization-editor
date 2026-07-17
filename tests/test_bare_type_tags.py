"""Tests for ``enhancements_bare_type_tags`` (#266).

Some component-adjacent items (fuel nozzles so far) carry no Size:/Grade:/
Class: of their own -- there's nothing to hang the usual "[MIL-S1-A]" shape
off of, so a Type-only tag is their only option. Gated by the same
Components > Type element toggle as every other DEFAULT_COMPONENT_TYPE_
MAPPING entry (Shield Generator, Cooler, ...) -- users opt in or out, they
aren't force-shown just because they'd otherwise have no other tag.
Identified purely by loc-key prefix, no DataForge XML dependency -- same
"base.ini is the only input" shape as enhancements_medical_consumables.
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


class TestEnhancementsBareTypeTags:
    def test_no_tag_when_type_disabled_by_default(self, gen_module):
        """Type is disabled by default for "components" -- with no explicit
        config, fuel nozzles get no tag at all, same as any other
        DEFAULT_COMPONENT_TYPE_MAPPING entry the user hasn't opted into."""
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}})
        assert out == {}

    def test_tags_fuel_nozzle_when_type_enabled(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[FN] RN-7s"}

    def test_respects_users_configured_type_style(self, gen_module):
        """A user who's enabled Type gets their chosen abbreviation length
        (short/medium/long) applied here too."""
        cfg = _components_cfg_with_type(gen_module, style="long")
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[Fuel Nozzle] RN-7s"}

    def test_respects_append_placement(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short", placement="append")
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "RN-7s [FN]"}

    def test_tags_short_name_variant_too(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Name_short": "RN-7s",
        }
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out["item_fuelnozzle_MISC_Standard_Name"] == "[FN] RN-7s"
        assert out["item_fuelnozzle_MISC_Standard_Name_short"] == "[FN] RN-7s"

    def test_unrelated_keys_untouched(self, gen_module):
        cfg = _components_cfg_with_type(gen_module, style="short")
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": "Manufacturer: MISC\\nItem Type: Fuel Nozzle",
            "item_NameSHLD_ASAS_S01_Shimmer": "Shimmer",
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
        loc = {"item_fuelnozzle_MISC_Standard_Name": ""}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": cfg}}
        )
        assert out == {}
