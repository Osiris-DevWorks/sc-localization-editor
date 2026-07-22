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
    expand_class_full_word,
    parse_component_tag,
    size_from_key,
    strip_size_prefix,
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


def test_parse_component_tag_trailing_placement():
    """A category configured to append (tag after the name) must still
    extract class/size/grade — pre-fix this lost the facets entirely for
    any append-placed category."""
    assert parse_component_tag("Balandin [MIL-S3-B]") == ("MIL", "S3", "B")
    assert parse_component_tag("Palisade [ind-s1-a]") == ("IND", "S1", "A")


def test_parse_component_tag_leading_wins_when_both_present():
    """Extremely unlikely in real data (a name can't legitimately carry two
    tags), but pins that a leading match short-circuits before the trailing
    regex ever runs."""
    assert parse_component_tag("[MIL-S3-B] Balandin [IND-S1-A]") == ("MIL", "S3", "B")


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


def test_expand_class_full_word():
    # Medium (default Tag Builder style) and Short both expand to the same
    # full word; already-full and unrecognized tokens pass through.
    assert expand_class_full_word("MIL") == "Military"
    assert expand_class_full_word("mil") == "Military"
    assert expand_class_full_word("M") == "Military"
    assert expand_class_full_word("IND") == "Industrial"
    assert expand_class_full_word("I") == "Industrial"
    assert expand_class_full_word("CIV") == "Civilian"
    assert expand_class_full_word("STH") == "Stealth"
    assert expand_class_full_word("CMP") == "Competition"
    assert expand_class_full_word("Military") == "Military"
    assert expand_class_full_word("CustomLabel") == "CustomLabel"
    assert expand_class_full_word(None) is None
    assert expand_class_full_word("") == ""


def test_strip_size_prefix():
    assert strip_size_prefix("S3") == "3"
    assert strip_size_prefix("s10") == "10"
    assert strip_size_prefix("S0") == "0"
    assert strip_size_prefix(None) is None
    assert strip_size_prefix("") == ""
    # Already bare — left alone.
    assert strip_size_prefix("3") == "3"


def test_blueprint_type_buckets():
    # Ship component type wins.
    assert blueprint_type_from_key("item_NameSHLD_Aspirum") == "Shield"
    # FPS weapon and armor by key tokens.
    assert blueprint_type_from_key("item_Name_rifle_behr_p4ar") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_pistol_gmni") == "FPS Weapon"
    assert blueprint_type_from_key("item_Nameutfl_crossbow_ballistic_01") == "FPS Weapon"
    assert blueprint_type_from_key("item_Name_armor_rsi_torso") == "Armor"
    assert blueprint_type_from_key("item_Name_helmet_xyz") == "Armor"
    # Ship weapons (#212): uppercase manufacturer + weapon size designator,
    # no recognized subsystem code. Size codes: _S2, _XL, _L-2, ...
    assert blueprint_type_from_key("item_NameKLWE_LaserCannon_S2") == "Ship Weapon"
    assert blueprint_type_from_key("item_NameBEHR_Gatling_S3") == "Ship Weapon"
    assert blueprint_type_from_key("item_NameAEGS_Bulldog_XL") == "Ship Weapon"
    # A recognized subsystem code still wins over the ship-weapon fallback
    # even though shields etc. also carry a _Sx size designator.
    assert blueprint_type_from_key("item_NameSHLD_ACOM_S01") == "Shield"
    # Lowercase (FPS gear) with a size-looking token is NOT a ship weapon.
    assert blueprint_type_from_key("item_Name_pistol_gmni") == "FPS Weapon"
    # Unrecognized / no match -> None (caller folds into "Other").
    # BombRack has no _Sx / _XL size designator, so it stays None.
    assert blueprint_type_from_key("item_NameAEGS_Eclipse_BombRack") is None
    assert blueprint_type_from_key(None) is None


def test_blueprint_type_mining_head_family_not_ship_weapon():
    """Reported: "S0 Helix" showed under Ship Weapon in the Blueprint
    Tracker's Type filter while other mining lasers showed under Other.

    Root cause: every real ship-mounted mining laser shares CIG's generic
    "Mining_Head" entity-model key (item_NameMining_Head_S00_<Name>[_SCItem])
    -- "Mining" starts with an uppercase letter like a manufacturer code, and
    "_S00" is the head's own size-0 designator, so EVERY variant (not just
    Helix) satisfies the #212 ship-weapon heuristic by coincidence. All four
    real variants must land in Other, consistently."""
    assert blueprint_type_from_key("item_NameMining_Head_S00_Arbor_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Helix_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Hofstede_SCItem") is None
    assert blueprint_type_from_key("item_NameMining_Head_S00_Klein_SCItem") is None
    # Real ship weapons must still classify correctly -- the carve-out is
    # scoped to the "mining_head" token, not a blanket size-designator skip.
    assert blueprint_type_from_key("item_NameKLWE_LaserCannon_S2") == "Ship Weapon"


def test_build_metadata_mining_head_family_lands_in_other():
    """End-to-end via build_blueprint_metadata, not just the key classifier
    in isolation -- confirms the fix actually reaches the Blueprint Tracker's
    Type filter for a real mission bullet + item_Name pair."""
    desc = ("x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- S0 Helix\\n- S0 Arbor")
    entries = [
        _Entry("M_Desc_001", desc, "Missions"),
        _Entry("item_NameMining_Head_S00_Helix_SCItem", "S0 Helix", "Ship Items"),
        _Entry("item_NameMining_Head_S00_Arbor_SCItem", "S0 Arbor", "Ship Items"),
    ]
    meta = build_blueprint_metadata(entries)
    assert meta["S0 Helix"].type == "Other"
    assert meta["S0 Arbor"].type == "Other"


def test_blueprint_type_armor_core_pieces():
    """FPS armor torso-platform pieces ("Core") reported showing up in the
    Blueprint Tracker's "Other" bucket instead of "Armor". Newer
    manufacturer-prefixed armor lines carry no "armor" token in the key at
    all (unlike CIG's older sets, which do), only "core"."""
    assert blueprint_type_from_key("item_Name_qrt_specialist_heavy_core_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_kap_combat_light_core_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_GRIN_utility_medium_core_01_01_01") == "Armor"
    # Older sets that DO carry "armor" in the key still work (no regression).
    assert blueprint_type_from_key("item_Name_cds_armor_heavy_core_01_02_01") == "Armor"
    # Ship components sharing the bare "core" word must not be reclassified —
    # their component-type-code prefix (POWR_/COOL_) wins first.
    assert blueprint_type_from_key("item_NamePOWR_ACOM_S02_LuxCore_SCItem") == "Power Plant"
    assert blueprint_type_from_key("item_NameCOOL_JUST_S02_CoolCore") == "Cooler"
    # The word is "_core" (underscore-prefixed), not bare "core" — a bare
    # substring match would misclassify anything with "score"/"scoreboard" in
    # the key ("score" contains "core"), and no armor set actually needs the
    # bare form since every real armor "core" piece carries the underscore.
    assert blueprint_type_from_key("item_Name_gys_scoreboard_01_01_01") is None
    assert blueprint_type_from_key("item_Name_gys_highscore_01_01_01") is None


def test_blueprint_type_gys_jacket_and_pants():
    """Carnifex set torso/leg pieces reported showing up in "Other" — the
    "gys" manufacturer keys these as jacket/pants, not core/legs/armor."""
    assert blueprint_type_from_key("item_Name_gys_jacket_01_01_01") == "Armor"
    assert blueprint_type_from_key("item_Name_gys_pants_01_01_01") == "Armor"
    # Scoped to "gys_" specifically — a bare "jacket"/"pants" match would also
    # catch unrelated civilian wardrobe items from other manufacturers.
    assert blueprint_type_from_key("item_Desc_987_Jacket_01_01_01") is None
    assert blueprint_type_from_key("item_Desc_DMC_Pants_01_01_01") is None


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
    assert (bal.type, bal.cls, bal.size, bal.grade) == ("Quantum Drive", "Military", "3", "B")
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
