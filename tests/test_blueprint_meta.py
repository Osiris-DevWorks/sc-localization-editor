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


class TestBareTypeKeyConventions:
    """#266 follow-up: fuel nozzles and mining lasers don't follow the
    item_Name<code> / vehicle_Name prefix every other component uses, so
    Pass 1 never recognised their key as a Name entry -- tagged_name fell
    back to the untagged bare name in the Blueprint Tracker even though
    the enhancement generator's output (and the String Editor) showed the
    real tag correctly. ("Tags work right in string editor but not in
    blueprint tracker.")"""

    def test_fuel_nozzle_item_fuelnozzle_prefix_gets_tagged_name(self):
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- RN-7s"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_fuelnozzle_MISC_Standard_Name", "[FN] RN-7s", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["RN-7s"].tagged_name == "[FN] RN-7s"

    def test_fuel_nozzle_nozzle_fuelgiver_prefix_gets_tagged_name(self):
        """Regression guard: Greycat/Shubin nozzles ship under the
        Nozzle_FuelGiver_* convention, not item_fuelnozzle_*."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Marlin"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("Nozzle_FuelGiver_GRIN_NozzleSecure_Name", "[FN] Marlin", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Marlin"].tagged_name == "[FN] Marlin"

    def test_mining_laser_bare_key_gets_tagged_name(self):
        """Mining laser Name keys carry no "_Name" suffix at all -- the
        bare key (ending in the size code) IS the Name entry."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Lancet MH1 Mining Laser"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_Mining_MiningLaser_Greycat_1_S1",
                   "[ML-S1] Lancet MH1 Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Lancet MH1 Mining Laser"].tagged_name == "[ML-S1] Lancet MH1 Mining Laser"

    @pytest.mark.regression
    def test_scraper_module_joins_through_reputation_tier_and_category_annotation(self):
        """End-to-end regression for the two compounding bugs found while
        wiring up Scraper Module: the real Adagio Industrial mission body
        groups bullets under an "Awarded from X level variants" sub-header
        (previously mistaken for a section boundary, so the bullet was
        never even reached) AND appends a "(Salvage Mod)" category
        annotation the real item_Name never carries (so even once reached,
        the normalized names wouldn't have matched). Both must be fixed for
        this item to ever show up tagged in the Blueprint Tracker."""
        desc = (
            "Adagio Holdings...\\n\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n<EM4>Awarded from Contractor level variants</EM4>"
            "\\n- Trawler Scraper Module (Salvage Mod)"
            "\\n- Abrade Scraper Module (Salvage Mod)"
            "\\n- Cinch Scraper Module (Salvage Mod)"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_scraper_GRIN_Standard_Name", "[SCM] Abrade Scraper Module", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "Abrade Scraper Module" in meta
        assert meta["Abrade Scraper Module"].tagged_name == "[SCM] Abrade Scraper Module"


class TestBulletNameMismatches:
    """A live mission body ("Crew Hasn't Checked In") reported bullets that
    don't match any real item_Name value at all -- two different root
    causes, both fixed here (#266 follow-up)."""

    def test_key_slug_fallback_resolves_garbled_bullet_name(self):
        """CIG's own bug: the bullet lists the de-slugified loc KEY instead
        of the item's real localized name -- "Nozzle Fuelgiver Grin
        Nozzleveryfast" for a key whose real value is "Lindstrom". This is
        deterministic (title-case each underscore segment, drop a trailing
        "_Name" segment first), so it's resolved generically rather than
        via a hardcoded alias."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- Nozzle Fuelgiver Grin Nozzleveryfast"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("Nozzle_FuelGiver_GRIN_NozzleVeryFast_Name", "[FN] Lindstrom", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "Lindstrom" in meta
        assert meta["Lindstrom"].tagged_name == "[FN] Lindstrom"
        assert "Nozzle Fuelgiver Grin Nozzleveryfast" not in meta

    def test_known_alias_resolves_helix_mismatch(self):
        """Not every mismatch is the key-slug bug -- "Helix" bears no
        relation to its key's slug at all, just an informal short name a
        mission author typed. The real item is "S0 Helix"."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Helix"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Helix_SCItem", "[Mining Laser] S0 Helix", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "S0 Helix" in meta
        assert meta["S0 Helix"].tagged_name == "[Mining Laser] S0 Helix"
        assert "Helix" not in meta

    @pytest.mark.regression
    def test_known_alias_resolves_hofstede_mismatch(self):
        """Same "Mining Head" bare-name pattern as Helix, reported
        separately in a live mission body -- confirms this isn't a
        one-off, it's the whole item family."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Hofstede"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Hofstede_SCItem", "[Mining Laser] S00 Hofstede", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert "S00 Hofstede" in meta
        assert meta["S00 Hofstede"].tagged_name == "[Mining Laser] S00 Hofstede"
        assert "Hofstede" not in meta

    def test_known_aliases_cover_the_whole_mining_head_family(self):
        """Arbor and Klein share the same key convention as Helix/Hofstede
        (item_NameMining_Head_S00_<Name>_SCItem) -- added preemptively
        rather than waiting for each to be reported individually."""
        desc = (
            "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>"
            "\\n- Arbor\\n- Klein"
        )
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_NameMining_Head_S00_Arbor_SCItem", "[Mining Laser] S0 Arbor", "Ship Items"),
            _Entry("item_NameMining_Head_S00_Klein_SCItem", "Lawson Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["S0 Arbor"].tagged_name == "[Mining Laser] S0 Arbor"
        assert meta["Lawson Mining Laser"].tagged_name == "Lawson Mining Laser"
        assert "Arbor" not in meta
        assert "Klein" not in meta

    def test_direct_match_is_not_overridden_by_alias_or_keyslug(self):
        """A bullet name that already matches a real item directly must
        win outright -- the alias/keyslug fallback only kicks in when the
        direct match fails."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Pitman Mining Laser"
        entries = [
            _Entry("M_Desc_001", desc, "Missions"),
            _Entry("item_Mining_MiningLaser_Drake_Default_S0", "Pitman Mining Laser", "Ship Items"),
        ]
        meta = build_blueprint_metadata(entries)
        assert meta["Pitman Mining Laser"].tagged_name == "Pitman Mining Laser"

    def test_unresolvable_bullet_name_falls_back_to_other(self):
        """A bullet name matching neither a real item, a known alias, nor
        any key's slug still shows up (as an untagged "Other" entry)
        rather than being silently dropped."""
        desc = "x\\n<EM4>POTENTIAL BLUEPRINTS</EM4>\\n- Totally Unknown Widget"
        meta = build_blueprint_metadata([_Entry("M_Desc_001", desc, "Missions")])
        assert "Totally Unknown Widget" in meta
        assert meta["Totally Unknown Widget"].type == "Other"
