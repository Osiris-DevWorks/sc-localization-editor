"""Tests for ``enhancements_medical_consumables``.

Unlike every other enhancement category, this one has no DataForge XML
dependency — the stock item_Desc for every CureLife pen is lore-only prose
("From the Empire's most trusted medical company...") and never states what
the item actually does in gameplay terms, so there's no stat to extract.
MEDICAL_CONSUMABLE_EFFECTS is fixed, curated copy keyed directly off loc
keys already present in base.ini. Tests drive the function with a plain
``loc`` dict (no XML, no tmp_path DataForge cache needed).
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
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_medical_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestEnhancementsMedicalConsumables:
    def test_appends_effect_to_every_known_pen(self, gen_module):
        """All 7 known CureLife pens get an appended effect line under its
        own "--- EFFECT ---" header (not the shared "--- STATS ---" one,
        and no redundant "Effect:" prefix on the line itself), with the
        original lore text preserved (appended-to, not replaced)."""
        loc = {
            key: f"Manufacturer: CureLife\\nItem Type: Medical Consumable\\n\\nStock lore for {key}."
            for key in gen_module.MEDICAL_CONSUMABLE_EFFECTS
        }
        ctx = {"loc": loc}
        out = gen_module.enhancements_medical_consumables(ctx)

        assert set(out) == set(gen_module.MEDICAL_CONSUMABLE_EFFECTS)
        for key, effect in gen_module.MEDICAL_CONSUMABLE_EFFECTS.items():
            assert "--- EFFECT ---" in out[key]
            assert "--- STATS ---" not in out[key]
            assert effect in out[key]
            assert f"Effect: {effect}" not in out[key]
            assert f"Stock lore for {key}." in out[key]

    def test_skips_keys_missing_from_loc(self, gen_module):
        """A pen key absent from the loaded base.ini (e.g. a channel that
        hasn't shipped it yet) is silently skipped, not KeyError'd."""
        ctx = {"loc": {}}
        out = gen_module.enhancements_medical_consumables(ctx)
        assert out == {}

    def test_only_known_pens_touched(self, gen_module):
        """Unrelated loc keys in the same dict are left alone."""
        loc = {
            "item_Desccrlf_consumable_healing_01": "Stock MedPen lore.",
            "item_Namecrlf_consumable_healing_01": "MedPen (Hemozal)",
            "some_unrelated_key": "unrelated value",
        }
        ctx = {"loc": loc}
        out = gen_module.enhancements_medical_consumables(ctx)
        assert set(out) == {"item_Desccrlf_consumable_healing_01"}

    def test_prepend_option_puts_effect_before_lore(self, gen_module):
        loc = {"item_Desccrlf_consumable_oxygen_01": "Stock OxyPen lore."}
        ctx = {"loc": loc, "stats_prepend": True}
        out = gen_module.enhancements_medical_consumables(ctx)
        result = out["item_Desccrlf_consumable_oxygen_01"]
        effect = gen_module.MEDICAL_CONSUMABLE_EFFECTS["item_Desccrlf_consumable_oxygen_01"]
        assert result.index(effect) < result.index("Stock OxyPen lore.")

    def test_no_em4_tags(self, gen_module):
        """Plain text only — the in-game inventory tooltip doesn't render
        <EM4> any better than the Vehicle Loadout Manager did (see the
        mining-laser/salvage-tool EM4 fix)."""
        loc = {key: "lore" for key in gen_module.MEDICAL_CONSUMABLE_EFFECTS}
        ctx = {"loc": loc}
        out = gen_module.enhancements_medical_consumables(ctx)
        for value in out.values():
            assert "<EM4>" not in value

    def test_seven_known_pens_registered(self, gen_module):
        """Locks the exact set of pens this category covers — the base
        (non-Xtra) CureLife pens, matching the user-specified list. BoostPen,
        VitalityPen, and the Xtra variants are deliberately out of scope."""
        expected_names = {
            "item_Desccrlf_consumable_adrenaline_01",      # AdrenaPen (Demexatrine)
            "item_Desccrlf_consumable_steroids_01",        # CorticoPen (Sterogen)
            "item_Desccrlf_consumable_radiation_01",       # DeconPen (Canoiodide)
            "item_Desccrlf_consumable_overdoseRevival_01", # DetoxPen (Resurgera)
            "item_Desccrlf_consumable_healing_01",         # MedPen (Hemozal)
            "item_Desccrlf_consumable_painkiller_01",      # OpioPen (Roxaphen)
            "item_Desccrlf_consumable_oxygen_01",          # OxyPen
        }
        assert set(gen_module.MEDICAL_CONSUMABLE_EFFECTS) == expected_names
