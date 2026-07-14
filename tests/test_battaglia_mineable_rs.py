"""Recco Battaglia's Scan/Mining contracts (4.9+): the "[RS ####]" mission-title
tag, gated by the "rs" General Tags checkbox (AppSettings.MISSION_TITLE_TAG_KEYS).

Each ``Battaglia_RPT_Scan_*`` / ``Battaglia_RPT_ScanMine_*`` contract targets 1-3
mineable ores via sibling ``MissionProperty`` overrides with
``extendedTextToken="ResourceType"``/``"ResourceType2"``/``"ResourceType3"``
pointing at a ``mineabletype_primary_<ore>`` loc key. CIG doesn't expose a
per-ore RS number anywhere in DataForge (confirmed against the full PTU 4.9
cache), so ``MINEABLE_RS_VALUES`` is a curated table covering just the 8 ores
this mission family uses.
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
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_battaglia_rs_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _resource_type_property(token: str, ore: str) -> str:
    return (
        f'<MissionProperty extendedTextToken="{token}">'
        '<value><MissionPropertyValue_StringHash><options>'
        f'<MissionPropertyValueOption_StringHash textId="@mineabletype_primary_{ore}" '
        'weighting="1" DEBUG_forceChooseThisOption="0" />'
        '</options></MissionPropertyValue_StringHash></value>'
        '</MissionProperty>'
    )


def _contract(title_key: str, *ore_tokens: tuple[str, str], tag: str = "CareerContract") -> str:
    props = "".join(_resource_type_property(token, ore) for token, ore in ore_tokens)
    return (
        f'<{tag} debugName="X">'
        '<paramOverrides><stringParamOverrides>'
        f'<ContractStringParam param="Title" value="@{title_key}" />'
        '</stringParamOverrides><propertyOverrides>'
        f'{props}'
        '</propertyOverrides></paramOverrides>'
        f'</{tag}>'
    )


class TestBattagliaContractMineableOres:
    def test_single_ore_resource_type(self, gen_module):
        root = ET.fromstring(_contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium")))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["aluminium"]

    def test_multi_ore_preserves_order(self, gen_module):
        root = ET.fromstring(_contract(
            "Battaglia_RPT_ScanMine_04_title",
            ("ResourceType", "bexalite"), ("ResourceType2", "ice"), ("ResourceType3", "torite"),
        ))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["bexalite", "ice", "torite"]

    def test_dedups_repeated_ore(self, gen_module):
        root = ET.fromstring(_contract(
            "Battaglia_RPT_Scan_01_title",
            ("ResourceType", "iron"), ("ResourceType2", "iron"),
        ))
        assert gen_module._battaglia_contract_mineable_ores(root) == ["iron"]

    def test_ignores_unrelated_mineabletype_tokens(self, gen_module):
        """``MineableType`` (deposit form, e.g. shipasteroid) is a different
        token family from ``ResourceType`` (the ore itself) and must not be
        picked up as an ore."""
        body = (
            '<CareerContract debugName="X">'
            '<paramOverrides><stringParamOverrides>'
            '<ContractStringParam param="Title" value="@Battaglia_RPT_Scan_01_title" />'
            '</stringParamOverrides><propertyOverrides>'
            + _resource_type_property("ResourceType", "aluminium") +
            '<MissionProperty extendedTextToken="MineableType">'
            '<value><MissionPropertyValue_StringHash><options>'
            '<MissionPropertyValueOption_StringHash textId="@mineabletype_type_shipasteroid" '
            'weighting="1" DEBUG_forceChooseThisOption="0" />'
            '</options></MissionPropertyValue_StringHash></value>'
            '</MissionProperty>'
            '</propertyOverrides></paramOverrides>'
            '</CareerContract>'
        )
        root = ET.fromstring(body)
        assert gen_module._battaglia_contract_mineable_ores(root) == ["aluminium"]

    def test_no_resource_type_yields_empty(self, gen_module):
        root = ET.fromstring('<CareerContract debugName="X"></CareerContract>')
        assert gen_module._battaglia_contract_mineable_ores(root) == []


class TestFormatRsTag:
    def test_single_ore(self, gen_module):
        assert gen_module._format_rs_tag(["aluminium"]) == "[RS 4285]"

    def test_multiple_ores_slash_joined_in_order(self, gen_module):
        assert gen_module._format_rs_tag(["bexalite", "ice", "torite"]) == "[RS 3600/4300/3900]"

    def test_unknown_ore_skipped_not_erroring(self, gen_module):
        """A future ore this table doesn't cover yet is silently dropped
        rather than crashing the whole tag."""
        assert gen_module._format_rs_tag(["aluminium", "unobtainium"]) == "[RS 4285]"

    def test_all_unknown_yields_empty_string(self, gen_module):
        assert gen_module._format_rs_tag(["unobtainium"]) == ""

    def test_empty_list_yields_empty_string(self, gen_module):
        assert gen_module._format_rs_tag([]) == ""


class TestBuildBattagliaMineableRsTags:
    def test_builds_tag_for_scan_and_scanmine_titles(self, gen_module, tmp_path):
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_04_title",
                        ("ResourceType", "bexalite"), ("ResourceType2", "ice"), ("ResourceType3", "torite"))
            + _contract("Battaglia_RPT_ScanMine_01_title",
                        ("ResourceType", "aluminium"), ("ResourceType2", "iron"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        tags = gen_module._build_battaglia_mineable_rs_tags(contractgen_dir)
        assert tags == {
            "Battaglia_RPT_Scan_04_title": "[RS 3600/4300/3900]",
            "Battaglia_RPT_ScanMine_01_title": "[RS 4285/4270]",
        }

    def test_ignores_non_battaglia_scan_titles(self, gen_module, tmp_path):
        """A mining-flavoured title from an unrelated contractor (or one of
        Battaglia's own non-scan mission types, e.g. Salvage) must not pick
        up an RS tag even if it happens to reference a mineabletype key."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        (contractgen_dir / "other.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Salvage_E_01_title", ("ResourceType", "aluminium"))
            + _contract("Shubin_ResourceGathering_title", ("ResourceType", "iron"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        tags = gen_module._build_battaglia_mineable_rs_tags(contractgen_dir)
        assert tags == {}

    def test_intro_contract_wrapper_also_covered(self, gen_module, tmp_path):
        """Battaglia wraps its intro mission in a plain <Contract> tag under
        introContracts, not <CareerContract> — must still be picked up."""
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        (contractgen_dir / "battaglia_generator.xml").write_text(
            '<ContractGeneratorHandler_Career><introContracts>'
            + _contract("Battaglia_RPT_Scan_01_title", ("ResourceType", "aluminium"), tag="Contract")
            + '</introContracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        tags = gen_module._build_battaglia_mineable_rs_tags(contractgen_dir)
        assert tags == {"Battaglia_RPT_Scan_01_title": "[RS 4285]"}

    def test_first_variant_wins_when_title_shared_across_files(self, gen_module, tmp_path):
        contractgen_dir = tmp_path / "contractgenerator"
        contractgen_dir.mkdir()
        (contractgen_dir / "a_stanton.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title", ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        (contractgen_dir / "b_pyro.xml").write_text(
            '<ContractGeneratorHandler_Career><contracts>'
            + _contract("Battaglia_RPT_Scan_06_title", ("ResourceType", "lindinium"), ("ResourceType2", "savrillium"))
            + '</contracts></ContractGeneratorHandler_Career>',
            encoding="utf-8",
        )
        tags = gen_module._build_battaglia_mineable_rs_tags(contractgen_dir)
        assert tags == {"Battaglia_RPT_Scan_06_title": "[RS 3400/3200]"}

    def test_missing_dir_returns_empty(self, gen_module, tmp_path):
        tags = gen_module._build_battaglia_mineable_rs_tags(tmp_path / "does_not_exist")
        assert tags == {}
