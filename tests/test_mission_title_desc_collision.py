"""Regression guard for #151: mission titles showing the full detail body.

A few CIG contracts (e.g. ``eckhart_defendship_MRT_title_001`` — the
"Stop Attack" missions) point their Description ContractStringParam at the
*same* loc key as their Title. When such a mission also awards blueprints,
``_run_gen_missions`` used to write the MISSION DETAILS / POTENTIAL
BLUEPRINTS body onto that shared key — clobbering the enhanced title with
the full block in-game. The fix excludes a mission's own title key from the
description-key set, so the title keeps only its ``[BP]`` / XP tags.

The no-blueprint collision was already handled by the "skip shared desc_key"
guard; this test locks the blueprint path, which the old guard missed.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_collision_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_POOL_UUID = "11111111-1111-1111-1111-111111111111"
_BP_UUID = "22222222-2222-2222-2222-222222222222"
_ENTITY_UUID = "33333333-3333-3333-3333-333333333333"
_SHARED_KEY = "eckhart_defendship_MRT_title_001"

# Contract whose Title and Description both point at the same loc key, with a
# blueprint reward so contract_has_bp becomes True — the exact #151 trigger.
_CONTRACT_GEN_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<ContractGenerator>
  <ContractGeneratorHandler_List debugName="Stanton_DefendShip">
    <Contract debugName="Stanton_StopAttack" notForRelease="0" minStanding="">
      <ContractStringParam param="Title" value="@{_SHARED_KEY}" />
      <ContractStringParam param="Description" value="@{_SHARED_KEY}" />
      <BlueprintRewards blueprintPool="{_POOL_UUID}" chance="1" />
    </Contract>
  </ContractGeneratorHandler_List>
</ContractGenerator>
"""

_BP_RECORD_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<CraftingBlueprintRecord __ref="{_BP_UUID}">
  <CraftingProcess_Creation entityClass="{_ENTITY_UUID}" />
</CraftingBlueprintRecord>
"""

_POOL_RECORD_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<BlueprintPoolRecord __ref="{_POOL_UUID}">
  <BlueprintReward blueprintRecord="{_BP_UUID}" />
</BlueprintPoolRecord>
"""


def _build_records_tree(tmp_path: Path) -> Path:
    records = tmp_path / "records"
    contractgen = records / "contracts" / "contractgenerator"
    bp_dir = records / "crafting" / "blueprints" / "crafting"
    pool_dir = records / "crafting" / "blueprintrewards"
    for d in (contractgen, bp_dir, pool_dir):
        d.mkdir(parents=True)
    (contractgen / "gen.xml").write_text(_CONTRACT_GEN_XML, encoding="utf-8")
    (bp_dir / "bp_craft_test.xml").write_text(_BP_RECORD_XML, encoding="utf-8")
    (pool_dir / "bp_rewards_test.xml").write_text(_POOL_RECORD_XML, encoding="utf-8")
    return records


def _run(gen_module, tmp_path):
    records = _build_records_tree(tmp_path)
    ctx = {
        "records": records,
        "forge_dir": tmp_path / "forge",
        "loc": {_SHARED_KEY: "Stop Attack on High-Profile Client"},
        "entity_names": {_ENTITY_UUID: "Test Component"},
        "reputation_lookup": {},
    }
    return gen_module._run_gen_missions(ctx)


class TestTitleDescCollision:
    def test_blueprint_pool_resolves(self, gen_module, tmp_path):
        """Guard the fixture itself: the contract must actually award a
        blueprint, otherwise the no-BP path would mask the regression."""
        out = _run(gen_module, tmp_path)
        assert _SHARED_KEY in out
        assert "[BP]" in out[_SHARED_KEY], (
            "fixture must produce a [BP] mission — the #151 bug only fires on "
            "the blueprint path"
        )

    def test_title_keeps_tags(self, gen_module, tmp_path):
        out = _run(gen_module, tmp_path)
        assert out[_SHARED_KEY].startswith("Stop Attack on High-Profile Client")

    def test_title_not_clobbered_by_body(self, gen_module, tmp_path):
        out = _run(gen_module, tmp_path)
        value = out[_SHARED_KEY]
        assert "MISSION DETAILS" not in value, (
            "#151: the description body must never overwrite a colliding title"
        )
        assert "POTENTIAL BLUEPRINTS" not in value
