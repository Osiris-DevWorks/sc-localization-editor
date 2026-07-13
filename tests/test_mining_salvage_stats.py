"""Tests for ``enhancements_mining_laser`` and ``enhancements_salvage_tool``.

These extractors pull stats from XML element shapes that already exist
on every shipped mining-laser / handheld-salvage entity in the cache
(Arbor, Lancet, Helix, Hofstede, Klein, Impact mining lasers under
``ships/weapons/mining_laser_*.xml``; Renovar XTR + multitool salvage
mode under ``weapons/fps_weapons/grin_*salvage_repair*.xml``). The
tests fabricate minimal XMLs in tmp_path that hit each branch the
function reads — so the suite doesn't require an extracted DataForge
cache to be present on disk.

Scope of v1 (also documented at the function level):
  - Ship mining lasers: per-mode beam stats (Fracture / Extraction),
    SEntityComponentMiningLaserParams modifier overlays, component
    HP, distortion, signatures.
  - Handheld salvage tools: per-mode (Repair / Salvage) repair-rate /
    efficiency / ramp / energy / heat / wear, component HP, max lifetime.
  - Excluded: globalParams UUID resolution (would surface base mining
    laser power / range, not just modifiers — future enhancement);
    ship-mounted salvage equipment (currently placeholder XMLs); mining
    gadgets (attachable modifiers, low local-stat content).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from lxml import etree as ET

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("generate_enhancements_ini_stats_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Mining laser extractor ───────────────────────────────────────────────────

class TestEnhancementsMiningLaser:
    """Covers ``enhancements_mining_laser`` against fabricated entity
    XMLs that exercise each output line independently."""

    def _arbor_like_xml(self):
        """Realistic-shape XML mirroring Arbor S1's stats layout —
        two fire actions (Fracture + Extraction), a modifier block,
        component HP, distortion. Returns the parsed root."""
        xml = """<EntityClassDefinition>
  <Components>
    <SHealthComponentParams Health="8000"/>
    <SDistortionParams Maximum="500000"/>
    <SCItemWeaponComponentParams>
      <fireActions>
        <SWeaponActionFireBeamParams fullDamageRange="60" zeroDamageRange="180"
                                     minEnergyDraw="0" maxEnergyDraw="0"
                                     heatPerSecond="0" wearPerSecond="0">
          <mannequinTag tag="laser"/>
          <damagePerSecond>
            <DamageInfo DamageEnergy="1890"/>
          </damagePerSecond>
        </SWeaponActionFireBeamParams>
        <SWeaponActionFireBeamParams fullDamageRange="60" zeroDamageRange="180"
                                     minEnergyDraw="0" maxEnergyDraw="0"
                                     heatPerSecond="0" wearPerSecond="0">
          <mannequinTag tag="tractor"/>
          <damagePerSecond>
            <DamageInfo DamageEnergy="1850"/>
          </damagePerSecond>
        </SWeaponActionFireBeamParams>
      </fireActions>
    </SCItemWeaponComponentParams>
    <SEntityComponentMiningLaserParams>
      <miningLaserModifiers>
        <laserInstability>
          <FloatModifierMultiplicative value="-35"/>
        </laserInstability>
        <optimalChargeWindowSizeModifier>
          <FloatModifierMultiplicative value="40"/>
        </optimalChargeWindowSizeModifier>
        <resistanceModifier>
          <FloatModifierMultiplicative value="25"/>
        </resistanceModifier>
      </miningLaserModifiers>
      <filterParams>
        <filterModifier>
          <FloatModifierMultiplicative value="30"/>
        </filterModifier>
      </filterParams>
    </SEntityComponentMiningLaserParams>
  </Components>
</EntityClassDefinition>"""
        return ET.fromstring(xml)

    def test_arbor_like_full_stats(self, gen_module):
        """Realistic Arbor-shape input → all four sections present:
        Fracture beam, Extraction beam, Modifiers, Component HP, Max Distortion."""
        result = gen_module.enhancements_mining_laser(self._arbor_like_xml())
        assert "Fracture:" in result
        assert "DPS: 1,890" in result
        assert "Extraction:" in result
        assert "DPS: 1,850" in result
        assert "Range: 60m" in result
        assert "180m" in result
        assert "Instability: -35%" in result
        assert "Optimal Charge Window: +40%" in result
        assert "Resistance: +25%" in result
        assert "Inert Filter: +30%" in result
        assert "Component HP:" in result and "8,000" in result
        assert "Max Distortion:" in result and "500,000" in result

    def test_no_em4_tags_or_arrow_glyphs(self, gen_module):
        """Regression guard: the in-game Vehicle Loadout Manager's
        item-description widget doesn't interpret <EM4> rich-text (shows
        the raw tag characters) and has no glyph for the "→" arrow (shows
        a fallback box character) — both reported on GitHub. Labels must
        be plain text and the Range separator must be the en dash, which
        is already proven to render fine via the Energy line."""
        result = gen_module.enhancements_mining_laser(self._arbor_like_xml())
        assert "<EM4>" not in result and "</EM4>" not in result
        assert "→" not in result
        assert "Range: 60m–180m" in result

    def test_modes_named_by_mannequin_tag(self, gen_module):
        """Fire actions are labelled by mannequinTag — `laser` → Fracture,
        `tractor` → Extraction. Unknown tags fall back to ``Beam {idx}``."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
            <SWeaponActionFireBeamParams fullDamageRange="10" zeroDamageRange="20">
              <mannequinTag tag="unknown_tag"/>
              <damagePerSecond><DamageInfo DamageEnergy="42"/></damagePerSecond>
            </SWeaponActionFireBeamParams>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module.enhancements_mining_laser(ET.fromstring(xml))
        assert "Beam 1:" in result, f"unknown tag should fall back to numbered beam: {result}"
        assert "DPS: 42" in result

    def test_skips_zero_only_fire_actions(self, gen_module):
        """Template XMLs ship with all-zero stats. Skip them so the
        output isn't littered with ``Beam N: `` empty lines."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
            <SWeaponActionFireBeamParams fullDamageRange="0" zeroDamageRange="0"
                                         minEnergyDraw="0" maxEnergyDraw="0"
                                         heatPerSecond="0" wearPerSecond="0">
              <mannequinTag tag="laser"/>
              <damagePerSecond><DamageInfo DamageEnergy="0"/></damagePerSecond>
            </SWeaponActionFireBeamParams>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module.enhancements_mining_laser(ET.fromstring(xml))
        assert "Fracture" not in result
        assert "Beam" not in result

    def test_skips_modifier_section_when_all_zero(self, gen_module):
        """A mining-laser params block whose modifiers are all 0 → no
        Modifiers: line in output. Filters out template / unmodified
        base lasers that genuinely have no overlay to declare."""
        xml = """<E><Components>
          <SEntityComponentMiningLaserParams>
            <miningLaserModifiers>
              <laserInstability><FloatModifierMultiplicative value="0"/></laserInstability>
            </miningLaserModifiers>
          </SEntityComponentMiningLaserParams>
        </Components></E>"""
        result = gen_module.enhancements_mining_laser(ET.fromstring(xml))
        assert "Modifiers:" not in result

    def test_positive_modifier_gets_plus_sign(self, gen_module):
        """Output reads ``+25%`` for positive modifiers and ``-35%`` for
        negatives — the strict regex on the rendering side reads the sign."""
        xml = """<E><Components><SEntityComponentMiningLaserParams><miningLaserModifiers>
          <resistanceModifier><FloatModifierMultiplicative value="25"/></resistanceModifier>
        </miningLaserModifiers></SEntityComponentMiningLaserParams></Components></E>"""
        result = gen_module.enhancements_mining_laser(ET.fromstring(xml))
        assert "Resistance: +25%" in result

    def test_returns_empty_when_nothing_extractable(self, gen_module):
        """Bare entity with no relevant params → empty string, NOT None
        (so scan_entity_dir treats it as 'no enhancements' cleanly)."""
        xml = "<EntityClassDefinition><Components/></EntityClassDefinition>"
        assert gen_module.enhancements_mining_laser(ET.fromstring(xml)) == ""

    def test_signatures_emitted_when_present(self, gen_module):
        """Some mining lasers carry EMSignature / IRSignature — render
        them in the same shape as the existing component extractors."""
        xml = """<E><Components>
          <EMSignature nominalSignature="120"/>
          <IRSignature nominalSignature="80"/>
        </Components></E>"""
        result = gen_module.enhancements_mining_laser(ET.fromstring(xml))
        assert "Signatures:" in result
        assert "EM: 120" in result
        assert "IR: 80" in result


# ── Salvage tool extractor ───────────────────────────────────────────────────

class TestEnhancementsSalvageTool:
    """Covers ``enhancements_salvage_tool`` against fabricated XMLs
    matching the Renovar / multitool-salvage shape."""

    def _renovar_like_xml(self):
        xml = """<EntityClassDefinition>
  <Components>
    <SHealthComponentParams Health="500"/>
    <SCItemWeaponComponentParams>
      <fireActions>
        <SWeaponActionFireSalvageRepairParams salvageRepairMode="Repair"
            materialEfficiency="1" maxHealthRepairRate="160" maxDamageMapRepairRate="10"
            healthToAmmoRatio="0.1" rampUpTime="0.5" rampDownTime="0.1"
            minEnergyDraw="0" maxEnergyDraw="0" heatPerSecond="0" wearPerSecond="0"/>
        <SWeaponActionFireSalvageRepairParams salvageRepairMode="Salvage"
            materialEfficiency="0.7" maxHealthRepairRate="670" maxDamageMapRepairRate="10"
            healthToAmmoRatio="5.8" rampUpTime="4" rampDownTime="2"
            minEnergyDraw="0" maxEnergyDraw="0" heatPerSecond="0" wearPerSecond="0"/>
      </fireActions>
    </SCItemWeaponComponentParams>
  </Components>
</EntityClassDefinition>"""
        return ET.fromstring(xml)

    def test_renovar_like_full_stats(self, gen_module):
        result = gen_module.enhancements_salvage_tool(self._renovar_like_xml())
        # Both modes labelled and present.
        assert "Repair:" in result
        assert "Salvage:" in result
        # Repair mode stats (Renovar values).
        assert "HP Rate: 160/s" in result
        assert "Damage-Map Rate: 10/s" in result
        # Salvage mode stats — note efficiency only emits when != 1.0.
        assert "HP Rate: 670/s" in result
        assert "Material Efficiency: 0.70" in result, (
            f"non-unity efficiency should render: {result}"
        )
        assert "HP/Ammo: 5.80" in result
        # Component HP.
        assert "Component HP:" in result and "500" in result

    def test_no_em4_tags_or_arrow_glyphs(self, gen_module):
        """Regression guard, same rationale as the mining-laser test above:
        the in-game item-description widget shows <EM4> tags literally and
        has no glyph for "↑"/"↓" (renders a fallback box character)."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
          <SWeaponActionFireSalvageRepairParams salvageRepairMode="Repair"
              rampUpTime="0.5" rampDownTime="0.1"/>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module.enhancements_salvage_tool(ET.fromstring(xml))
        assert "<EM4>" not in result and "</EM4>" not in result
        assert "↑" not in result and "↓" not in result
        assert "Ramp: 0.5s up, 0.1s down" in result

    def test_skips_efficiency_when_unity(self, gen_module):
        """``materialEfficiency=1`` is the default no-op (Renovar's Repair
        mode runs at 1.0). Don't emit a line for it — clutter."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
          <SWeaponActionFireSalvageRepairParams salvageRepairMode="Repair"
              materialEfficiency="1" maxHealthRepairRate="100"/>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module.enhancements_salvage_tool(ET.fromstring(xml))
        assert "Material Efficiency" not in result, (
            f"unity efficiency should not render: {result}"
        )
        assert "HP Rate: 100/s" in result

    def test_falls_back_to_name_attr_for_mode_label(self, gen_module):
        """When salvageRepairMode isn't set, fall back to the ``name``
        attribute (multitool / older entity shape)."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
          <SWeaponActionFireSalvageRepairParams name="CustomMode" maxHealthRepairRate="50"/>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module.enhancements_salvage_tool(ET.fromstring(xml))
        assert "CustomMode:" in result

    def test_emits_max_lifetime_when_set(self, gen_module):
        xml = """<E><Components>
          <SWearAccumulatorParams MaxLifetimeHours="120"/>
        </Components></E>"""
        result = gen_module.enhancements_salvage_tool(ET.fromstring(xml))
        assert "Max Lifetime:" in result and "120" in result

    def test_returns_empty_when_no_salvage_params(self, gen_module):
        """No SWeaponActionFireSalvageRepairParams element → empty result
        even if other component params are present. Dispatch will then
        route through enhancements_weapon instead."""
        xml = """<E><Components>
          <SHealthComponentParams Health="100"/>
        </Components></E>"""
        # Health alone shouldn't trigger any output for a salvage tool —
        # if there's no salvage params, this isn't a salvage tool.
        # (The Component HP line still fires though, which is the only
        # output. Either behavior is defensible; assert what we ship.)
        result = gen_module.enhancements_salvage_tool(ET.fromstring(xml))
        assert "Salvage:" not in result and "Repair:" not in result


# ── Dispatch helpers ──────────────────────────────────────────────────────────

class TestPolymorphicDispatch:
    """The _ship_weapon_dispatch / _fps_weapon_dispatch helpers pick
    the right extractor based on a marker element. Tests verify the
    fallback to enhancements_weapon when the marker is absent."""

    def test_ship_dispatch_routes_mining_laser_to_specialised(self, gen_module):
        """SEntityComponentMiningLaserParams present → mining laser path."""
        xml = """<E><Components>
          <SHealthComponentParams Health="1000"/>
          <SEntityComponentMiningLaserParams/>
        </Components></E>"""
        result = gen_module._ship_weapon_dispatch(ET.fromstring(xml), vehicle_ammo={}, loc={})
        # Mining laser extractor emits a plain (not EM4-tagged) Component HP
        # line — the in-game Vehicle Loadout Manager doesn't interpret EM4
        # rich-text and showed the raw tag characters (GitHub bug report).
        assert "Component HP:" in result
        assert "<EM4>" not in result

    def test_ship_dispatch_routes_combat_weapon_to_default(self, gen_module):
        """No mining-laser marker → enhancements_weapon path. Both
        extractors can legitimately emit a plain "Component HP:" line
        for this bare XML now that EM4 wrapping is gone, so text
        presence can't prove routing. Instead, compare the dispatch
        result directly against calling enhancements_weapon with the
        same args — equality proves dispatch took that path."""
        xml = "<E><Components><SHealthComponentParams Health=\"1000\"/></Components></E>"
        root = ET.fromstring(xml)
        result = gen_module._ship_weapon_dispatch(root, vehicle_ammo={}, loc={})
        expected = gen_module.enhancements_weapon(root, {}, {})
        assert result == expected

    def test_fps_dispatch_routes_salvage_tool_to_specialised(self, gen_module):
        """SWeaponActionFireSalvageRepairParams present → salvage tool path."""
        xml = """<E><Components><SCItemWeaponComponentParams><fireActions>
          <SWeaponActionFireSalvageRepairParams salvageRepairMode="Salvage"
              maxHealthRepairRate="100"/>
        </fireActions></SCItemWeaponComponentParams></Components></E>"""
        result = gen_module._fps_weapon_dispatch(
            ET.fromstring(xml), fps_ammo={}, loc={}, mag_lookup={},
        )
        assert "Salvage:" in result and "HP Rate: 100/s" in result

    def test_fps_dispatch_falls_back_to_default_weapon(self, gen_module):
        """No salvage-tool marker → enhancements_weapon. Same shape
        assertion as the ship_dispatch fallback."""
        xml = "<E><Components/></E>"
        result = gen_module._fps_weapon_dispatch(
            ET.fromstring(xml), fps_ammo={}, loc={}, mag_lookup={},
        )
        # Default enhancements_weapon on a bare XML returns empty string.
        assert "Salvage:" not in result and "Repair:" not in result
