"""Tests for ``enhancements_bare_type_tags`` (#266).

Some component-adjacent items (fuel nozzles so far) carry no Size:/Grade:/
Class: of their own -- there's nothing to hang the usual "[MIL-S1-A]" shape
off of, and the optional "Type" element is disabled by default, so without
this dedicated pass they'd never show any tag at all ("What is an R7?").
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


class TestEnhancementsBareTypeTags:
    def test_tags_fuel_nozzle_with_default_config(self, gen_module):
        """Default Tag Builder config: Type element is disabled but stored
        at "short" style -- this pass forces it on regardless, producing
        the short abbreviation ("FN"), prepended (the default placement)."""
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}})
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[FN] RN-7s"}

    def test_respects_users_configured_type_style(self, gen_module):
        """A user who has actually configured the Type element (even while
        leaving it disabled for their sized components) gets their chosen
        abbreviation length here instead of the built-in default."""
        comp_cfg = gen_module.DEFAULT_TAG_CONFIGS["components"]
        custom_cfg = gen_module.TagConfig(
            elements=[gen_module.ElementSpec("type", False, "long")],
            separator=comp_cfg.separator,
            enclosing=comp_cfg.enclosing,
            placement=comp_cfg.placement,
            class_mapping=comp_cfg.class_mapping,
        )
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": custom_cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "[Fuel Nozzle] RN-7s"}

    def test_respects_append_placement(self, gen_module):
        comp_cfg = gen_module.DEFAULT_TAG_CONFIGS["components"]
        append_cfg = gen_module.TagConfig(
            elements=list(comp_cfg.elements),
            separator=comp_cfg.separator,
            enclosing=comp_cfg.enclosing,
            placement="append",
            class_mapping=comp_cfg.class_mapping,
        )
        loc = {"item_fuelnozzle_MISC_Standard_Name": "RN-7s"}
        out = gen_module.enhancements_bare_type_tags(
            {"loc": loc, "tag_configs": {"components": append_cfg}}
        )
        assert out == {"item_fuelnozzle_MISC_Standard_Name": "RN-7s [FN]"}

    def test_tags_short_name_variant_too(self, gen_module):
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Name_short": "RN-7s",
        }
        out = gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}})
        assert out["item_fuelnozzle_MISC_Standard_Name"] == "[FN] RN-7s"
        assert out["item_fuelnozzle_MISC_Standard_Name_short"] == "[FN] RN-7s"

    def test_unrelated_keys_untouched(self, gen_module):
        loc = {
            "item_fuelnozzle_MISC_Standard_Name": "RN-7s",
            "item_fuelnozzle_MISC_Standard_Desc": "Manufacturer: MISC\\nItem Type: Fuel Nozzle",
            "item_NameSHLD_ASAS_S01_Shimmer": "Shimmer",
            "some_unrelated_key": "unrelated value",
        }
        out = gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}})
        assert set(out) == {"item_fuelnozzle_MISC_Standard_Name"}

    def test_empty_loc_is_empty(self, gen_module):
        assert gen_module.enhancements_bare_type_tags({"loc": {}, "tag_configs": {}}) == {}

    def test_missing_name_value_is_skipped(self, gen_module):
        loc = {"item_fuelnozzle_MISC_Standard_Name": ""}
        assert gen_module.enhancements_bare_type_tags({"loc": loc, "tag_configs": {}}) == {}
