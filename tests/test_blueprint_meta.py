"""Blueprint metadata builder for the shuttle filters (#157 follow-up).

Joins blueprint bullet names to component name entries (type / class / size /
grade) and to their mission titles, from the loaded strings. Qt-free.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.blueprint_meta import (  # noqa: E402
    blueprint_type_from_key,
    build_blueprint_metadata,
    clean_mission_title,
    component_type_from_key,
    parse_component_tag,
    size_from_key,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@dataclass
class _Entry:
    key: str
    original_value: str
    category: str = "Other"


def test_parse_component_tag():
    assert parse_component_tag("[MIL-S3-B] Balandin") == ("MIL", "S3", "B")
    assert parse_component_tag("[ind-s1-a] Palisade") == ("IND", "S1", "A")
    assert parse_component_tag("Balandin") == (None, None, None)
    assert parse_component_tag("") == (None, None, None)


def test_parse_component_tag_robust_to_config(gen_module=None):
    # #196: robust to the user's configurable separator / order / type element.
    assert parse_component_tag("[CMP.S1.B.PW] StarHeart") == ("CMP", "S1", "B")
    assert parse_component_tag("[MIL.S02.C] Foo") == ("MIL", "S2", "C")  # zero-pad stripped
    # A ship-weapon-style [E-S2] (no grade): class E is a lone letter -> grade,
    # class None. That's fine — the builder only keeps attrs for typed components.
    assert parse_component_tag("[E-S2] Gun")[1] == "S2"


def test_size_from_key():
    assert size_from_key("item_NamePOWR_ACOM_S01_StarHeart") == "S1"
    assert size_from_key("item_NameQDRV_RSI_S02_Hemera") == "S2"
    assert size_from_key("item_Name_no_size_here") is None


def test_component_type_from_key():
    assert component_type_from_key("item_NameQDRV_RSI_S02_Hemera") == "Quantum Drive"
    assert component_type_from_key("item_Name_SHLD_Aspirum") == "Shield"
    assert component_type_from_key("item_NameQRDV_typo") == "Quantum Drive"
    # Manufacturer-prefixed name (no recognized type code) -> no type.
    assert component_type_from_key("item_NameAEGS_Eclipse_BombRack_S03") is None


def test_blueprint_type_buckets():
    # Ship component type wins.
    assert blueprint_type_from_key("item_NameSHLD_Aspirum") == "Shield"
    # FPS weapon and armor by key tokens.
    assert blueprint_type_from_key("item_Name_rifle_behr_p4ar") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_pistol_gmni") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_armor_rsi_torso") == "Armor"
    assert blueprint_type_from_key("item_Name_helmet_xyz") == "Armor"
    # Unrecognized / no match -> None (caller folds into "Other").
    assert blueprint_type_from_key("item_NameAEGS_Eclipse_BombRack") is None
    assert blueprint_type_from_key(None) is None


def test_clean_mission_title_strips_reward_tags():
    raw = ("Salvager Needed (Lrg. Special Order) "
           "<EM4>[BP]</EM4> <EM4>[150 REP]</EM4>")
    assert clean_mission_title(raw) == "Salvager Needed (Lrg. Special Order)"


def _sample_entries():
    desc = (
        "Posting body.\\n\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
        "\\n- Balandin\\n- Abrade Scraper Module"
    )
    return [
        _Entry("Adagio_Run_Levski_H_Desc_001", desc, "Missions"),
        _Entry("Adagio_Run_Levski_H_Title_001",
               "Salvager Needed <EM4>[BP]</EM4> <EM4>[150 REP]</EM4>", "Missions"),
        _Entry("item_NameQDRV_WETK_S03_Balandin", "[MIL-S3-B] Balandin", "Ship Items"),
    ]


def test_build_joins_component_attributes():
    meta = build_blueprint_metadata(_sample_entries())
    assert set(meta) == {"Balandin", "Abrade Scraper Module"}
    bal = meta["Balandin"]
    assert (bal.type, bal.cls, bal.size, bal.grade) == ("Quantum Drive", "MIL", "S3", "B")
    # Plain item with no matching name entry -> "Other" type, no class/size/grade.
    scraper = meta["Abrade Scraper Module"]
    assert (scraper.type, scraper.cls, scraper.size, scraper.grade) == ("Other", None, None, None)


def test_build_type_buckets_fps_and_armor():
    desc = ("x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- P4-AR Rifle\\n- RSI Torso Armor\\n- Mystery Widget")
    entries = [
        _Entry("M_Desc_001", desc, "Missions"),
        _Entry("item_Name_rifle_behr_p4ar", "P4-AR Rifle", "Gear"),
        _Entry("item_Name_armor_rsi_torso", "RSI Torso Armor", "Gear"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["P4-AR Rifle"].type == "FPS Weapon"
    assert meta["RSI Torso Armor"].type == "Armor"
    # No matching name entry -> Other.
    assert meta["Mystery Widget"].type == "Other"


def test_build_attaches_mission_name():
    meta = build_blueprint_metadata(_sample_entries())
    assert meta["Balandin"].missions == frozenset({"Salvager Needed"})
    assert meta["Abrade Scraper Module"].missions == frozenset({"Salvager Needed"})


def test_item_in_multiple_missions_unions_titles():
    desc1 = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Balandin"
    desc2 = "y\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Balandin"
    entries = [
        _Entry("M_One_Desc_001", desc1, "Missions"),
        _Entry("M_One_Title_001", "First Job", "Missions"),
        _Entry("M_Two_Desc_001", desc2, "Missions"),
        _Entry("M_Two_Title_001", "Second Job", "Missions"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["Balandin"].missions == frozenset({"First Job", "Second Job"})


def test_desc_without_title_yields_no_mission_but_keeps_item():
    desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Orphan Part"
    meta = build_blueprint_metadata([_Entry("Loose_Desc_001", desc, "Missions")])
    assert "Orphan Part" in meta
    assert meta["Orphan Part"].missions == frozenset()


def test_no_blueprint_entries_is_empty():
    assert build_blueprint_metadata([_Entry("vehicle_NameRSI_Polaris", "Polaris", "Ships")]) == {}
