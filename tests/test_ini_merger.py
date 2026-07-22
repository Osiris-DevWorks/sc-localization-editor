"""Tests for src/merger/ini_merger.py — sync_key_variants and the
merge_sources_by_hierarchy pipeline that drives it.

sync_key_variants had no test coverage at all before this file, despite two
real bug reports against its variant-selection heuristic (a naive "first
variant wins" pass, then a "prefer non-_SCItem" pre-filter, both wrong in
opposite ways — see the docstring in ini_merger.py). These tests pin the
three real-data shapes that broke it, plus the guard added so a user's
override to a variant can't be silently outvoted by the longest-value rule.

TestSyncKeyVariantsDomainScope (#255) pins a third, more severe bug: the
canonical-key grouping used to run over EVERY key in the merged table, not
just item_Name*/item_Desc*. Two completely unrelated CIG loc keys —
Stanton2 (the Crusader planet) and Stanton_2 (the Stanton star) — collapsed
to the same canonical string purely because underscore-stripping ignores
what the underscore was actually separating, and the star's longer value
overwrote the planet's name on the in-game starmap. A real base.ini audit
found 14 total live corruptions of this shape. The fix scopes the sync to
item_Name*/item_Desc* keys only; these tests lock that boundary down so it
can never again silently expand to swallow unrelated content.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.merger.ini_merger import (  # noqa: E402
    merge_ini_files,
    merge_sources_by_hierarchy,
    sync_key_variants,
)

pytestmark = pytest.mark.unit


class TestSyncKeyVariantsRealDataShapes:
    """The two real bug reports this function's history is built from."""

    def test_short_untagged_sibling_loses_to_tagged(self):
        """The 7SA pair: item_Name_SHLD_BEHR_S01_7SA (tagged/enhanced) and
        item_NameSHLD_BEHR_S01_7sa (a distinct, never-enhanced sibling with
        just the bare stock name) canonicalize to the same key. The short,
        untagged one must not win."""
        merged = {
            "item_Name_SHLD_BEHR_S01_7SA": "[SHLD-S1-B] BEHR Shield",
            "item_NameSHLD_BEHR_S01_7sa": "BEHR Shield",
        }
        sync_key_variants(merged)
        assert merged["item_Name_SHLD_BEHR_S01_7SA"] == "[SHLD-S1-B] BEHR Shield"
        assert merged["item_NameSHLD_BEHR_S01_7sa"] == "[SHLD-S1-B] BEHR Shield"

    def test_scitem_suffixed_variant_can_hold_correct_value(self):
        """The Taiga pair: item_NameCOOL_WCPR_S02_Taiga_SCItem holds the
        correctly tagged value while its non-_SCItem sibling
        item_Name_COOL_WCPR_S02_Taiga is the never-enhanced bare one. A
        blanket "non-_SCItem always wins" pre-filter (tried and reverted)
        picked the bare one every time — length alone must decide."""
        merged = {
            "item_Name_COOL_WCPR_S02_Taiga": "Taiga Cooler",
            "item_NameCOOL_WCPR_S02_Taiga_SCItem": "[COOL-S2-B] Taiga Cooler",
        }
        sync_key_variants(merged)
        assert merged["item_Name_COOL_WCPR_S02_Taiga"] == "[COOL-S2-B] Taiga Cooler"
        assert merged["item_NameCOOL_WCPR_S02_Taiga_SCItem"] == "[COOL-S2-B] Taiga Cooler"

    def test_equal_length_variants_are_a_no_op(self):
        """Genuine same-entity variants (the generator's own sibling
        mirroring) already carry matching values, so a length tie is
        harmless either way."""
        merged = {
            "item_Name_QDRV_RSI_S02_Hemera": "Hemera Drive",
            "item_nameQDRV_RSI_S02_Hemera_SCItem": "Hemera Drive",
        }
        sync_key_variants(merged)
        assert merged["item_Name_QDRV_RSI_S02_Hemera"] == "Hemera Drive"
        assert merged["item_nameQDRV_RSI_S02_Hemera_SCItem"] == "Hemera Drive"

    def test_unrelated_keys_untouched(self):
        merged = {"some_unrelated_key": "value", "another_key": "other value"}
        sync_key_variants(merged)
        assert merged == {"some_unrelated_key": "value", "another_key": "other value"}


class TestSyncKeyVariantsUserEditGuard:
    """A user-edited variant must survive sync_key_variants even when it's
    shorter than an untouched sibling's value — otherwise the very next
    merge silently reverts the user's edit (root CLAUDE.md: user overrides
    "apply last and survive")."""

    def test_user_edited_short_variant_wins_over_longer_untouched_sibling(self):
        merged = {
            "item_Name_SHLD_BEHR_S01_7SA": "My Custom Name",
            "item_NameSHLD_BEHR_S01_7sa": "[SHLD-S1-B] BEHR Shield Original",
        }
        sync_key_variants(merged, user_edited_keys={"item_Name_SHLD_BEHR_S01_7SA"})
        assert merged["item_Name_SHLD_BEHR_S01_7SA"] == "My Custom Name"
        assert merged["item_NameSHLD_BEHR_S01_7sa"] == "My Custom Name"

    def test_no_user_edit_falls_back_to_longest(self):
        """Same data as above, but with no user_edited_keys passed — the
        pre-existing longest-value behavior is unchanged."""
        merged = {
            "item_Name_SHLD_BEHR_S01_7SA": "My Custom Name",
            "item_NameSHLD_BEHR_S01_7sa": "[SHLD-S1-B] BEHR Shield Original",
        }
        sync_key_variants(merged)
        assert merged["item_Name_SHLD_BEHR_S01_7SA"] == "[SHLD-S1-B] BEHR Shield Original"
        assert merged["item_NameSHLD_BEHR_S01_7sa"] == "[SHLD-S1-B] BEHR Shield Original"

    def test_multiple_user_edited_variants_longest_of_those_wins(self):
        """No ordering signal between two deliberate edits, so fall back to
        the same longest-wins tie-break, scoped to just the edited ones."""
        merged = {
            "item_Name_SHLD_BEHR_S01_7SA": "Short Edit",
            "item_NameSHLD_BEHR_S01_7sa": "A Longer Deliberate Edit",
        }
        sync_key_variants(
            merged,
            user_edited_keys={"item_Name_SHLD_BEHR_S01_7SA", "item_NameSHLD_BEHR_S01_7sa"},
        )
        assert merged["item_Name_SHLD_BEHR_S01_7SA"] == "A Longer Deliberate Edit"
        assert merged["item_NameSHLD_BEHR_S01_7sa"] == "A Longer Deliberate Edit"

    def test_user_edited_key_unrelated_to_variants_is_ignored(self):
        """user_edited_keys naming a key with no variant siblings at all
        must not error or affect anything."""
        merged = {
            "item_Name_SHLD_BEHR_S01_7SA": "[SHLD-S1-B] BEHR Shield",
            "item_NameSHLD_BEHR_S01_7sa": "BEHR Shield",
        }
        sync_key_variants(merged, user_edited_keys={"totally_unrelated_key"})
        assert merged["item_Name_SHLD_BEHR_S01_7SA"] == "[SHLD-S1-B] BEHR Shield"


class TestMergeSourcesByHierarchyUserOverrideSurvival:
    """Integration-level: merge_sources_by_hierarchy must wire the guard
    through automatically, not just the unit-level sync_key_variants."""

    def test_user_override_to_short_variant_survives_merge(self):
        sources = {
            "global": {
                "item_Name_SHLD_BEHR_S01_7SA": "[SHLD-S1-B] BEHR Shield",
                "item_NameSHLD_BEHR_S01_7sa": "BEHR Shield",
            },
        }
        user_overrides = {"item_Name_SHLD_BEHR_S01_7SA": "My Renamed Shield"}
        result = merge_sources_by_hierarchy(sources, ["global"], user_overrides)
        assert result["item_Name_SHLD_BEHR_S01_7SA"] == "My Renamed Shield"
        assert result["item_NameSHLD_BEHR_S01_7sa"] == "My Renamed Shield"

    def test_no_overrides_still_syncs_by_longest(self):
        sources = {
            "global": {
                "item_Name_COOL_WCPR_S02_Taiga": "Taiga Cooler",
                "item_NameCOOL_WCPR_S02_Taiga_SCItem": "[COOL-S2-B] Taiga Cooler",
            },
        }
        result = merge_sources_by_hierarchy(sources, ["global"])
        assert result["item_Name_COOL_WCPR_S02_Taiga"] == "[COOL-S2-B] Taiga Cooler"


class TestSyncKeyVariantsDomainScope:
    """#255: sync_key_variants must never touch a key outside item_Name*/
    item_Desc* — that's the one guarantee this whole test class exists to
    pin down. Real key/value pairs pulled straight from the bug's audit."""

    def test_crusader_planet_not_overwritten_by_stanton_star(self):
        """The reported bug, verbatim: Stanton2 (planet, "Crusader") and
        Stanton_2 (star, "Stanton (Star)") canonicalize to the same string
        after underscore-stripping. Pre-fix, the longer star value won and
        got written into both — the starmap showed "Stanton (Star)" where
        "Crusader" should be."""
        merged = {"Stanton2": "Crusader", "Stanton_2": "Stanton (Star)"}
        sync_key_variants(merged)
        assert merged["Stanton2"] == "Crusader"
        assert merged["Stanton_2"] == "Stanton (Star)"

    def test_comm_array_button_labels_not_merged(self):
        merged = {"CommArray_Deactivate": "Deactivate", "comm_Array_Deactivate": "Disconnect Uplink"}
        sync_key_variants(merged)
        assert merged["CommArray_Deactivate"] == "Deactivate"
        assert merged["comm_Array_Deactivate"] == "Disconnect Uplink"

    def test_mission_title_format_string_not_overwritten_by_body_text(self):
        merged = {
            "LocalDelivery_title": "~mission(Contractor|LocalDeliveryTitle) - ~mission(Reward)",
            "Local_Delivery_Title": "Courier\\nLocal Multi-Stop Delivery\\nReward",
        }
        sync_key_variants(merged)
        assert merged["LocalDelivery_title"] == "~mission(Contractor|LocalDeliveryTitle) - ~mission(Reward)"
        assert merged["Local_Delivery_Title"] == "Courier\\nLocal Multi-Stop Delivery\\nReward"

    def test_two_distinct_thruster_names_not_collapsed(self):
        """Mid Left and Mid Lower are different thrusters — collapsing them
        to one name would mislabel a ship component, not just cosmetic."""
        merged = {"port_NameThrusterMavML": "Thruster Mid Left", "port_NameThrusterMavML_": "Thruster Mid Lower"}
        sync_key_variants(merged)
        assert merged["port_NameThrusterMavML"] == "Thruster Mid Left"
        assert merged["port_NameThrusterMavML_"] == "Thruster Mid Lower"

    def test_hardpoint_slot_suffix_not_dropped(self):
        """Two power-plant loadout slots must stay distinguishable — losing
        the "- 02" suffix makes them look like the same slot in the UI."""
        merged = {
            "itemPort_hardpoint_power_plant_02": "Power Plant",
            "itemPort_hardpoint_powerplant_02": "Power Plant - 02",
        }
        sync_key_variants(merged)
        assert merged["itemPort_hardpoint_power_plant_02"] == "Power Plant"
        assert merged["itemPort_hardpoint_powerplant_02"] == "Power Plant - 02"

    def test_options_menu_turret_labels_not_merged(self):
        merged = {
            "pause_OptionsLookAhead_Turret_Forward": "Turrets - Look Ahead - Strength - Forward vector",
            "pause_options_look_ahead_turret_forward": "Turret - Look Ahead - Strength - Forward Vector",
        }
        sync_key_variants(merged)
        assert merged["pause_OptionsLookAhead_Turret_Forward"] == "Turrets - Look Ahead - Strength - Forward vector"
        assert merged["pause_options_look_ahead_turret_forward"] == "Turret - Look Ahead - Strength - Forward Vector"

    def test_kiosk_label_does_not_leak_literal_underscore(self):
        """Shop_Terminal (with a literal underscore) must never win and
        display in a user-facing kiosk prompt."""
        merged = {"kiosk_ShopTerminal": "Shop Terminal", "kiosk_Shop_Terminal": "Shop_Terminal"}
        sync_key_variants(merged)
        assert merged["kiosk_ShopTerminal"] == "Shop Terminal"
        assert merged["kiosk_Shop_Terminal"] == "Shop_Terminal"

    def test_item_desc_variants_still_sync(self):
        """The fix must not become so narrow it stops syncing real item
        variants — two item_Desc keys for the same entity (missing
        underscore after "item_Desc") must still reach each other, same
        as the item_Name case every other test in this file already pins."""
        merged = {
            "item_Desc_SHLD_BEHR_S01_7SA": "[SHLD-S1-B] BEHR Shield description",
            "item_DescSHLD_BEHR_S01_7sa": "BEHR Shield description",
        }
        sync_key_variants(merged)
        assert merged["item_Desc_SHLD_BEHR_S01_7SA"] == "[SHLD-S1-B] BEHR Shield description"
        assert merged["item_DescSHLD_BEHR_S01_7sa"] == "[SHLD-S1-B] BEHR Shield description"

    def test_full_merge_pipeline_preserves_crusader(self):
        """Integration-level: the bug reproduces through the full
        merge_sources_by_hierarchy pipeline used by the app, not just the
        unit-level sync_key_variants."""
        sources = {"global": {"Stanton2": "Crusader", "Stanton_2": "Stanton (Star)"}}
        result = merge_sources_by_hierarchy(sources, ["global"])
        assert result["Stanton2"] == "Crusader"
        assert result["Stanton_2"] == "Stanton (Star)"


class TestMergeIniFilesBom:
    """#261: applying wrote the game's global.ini as plain UTF-8 with no BOM.

    Data.p4k's own extracted global.ini ships with a UTF-8 BOM, and Star
    Citizen's own loc-string loader appears to need it to reliably detect
    the file's encoding — without it, the game can fail to resolve the
    ENTIRE loc table (every string shows its raw @KeyName placeholder)
    rather than degrading per-key. Confirmed on a real install: after
    Apply, the whole in-game UI showed raw loc keys; deleting the applied
    file restored correct text. merge_ini_files now writes utf-8-sig
    (BOM included), matching Data.p4k's own format byte-for-byte.
    """

    def test_output_starts_with_utf8_bom(self, tmp_path):
        src = tmp_path / "base.ini"
        src.write_text("a=1\n", encoding="utf-8")
        out = tmp_path / "out.ini"
        merge_ini_files(src, {}, out)
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_output_has_bom_even_when_source_lacks_one(self, tmp_path):
        """The output BOM must not depend on the source having one — a
        cached base.ini that was hand-edited or re-saved without a BOM
        must still produce a correctly-BOM'd applied file."""
        src = tmp_path / "base.ini"
        src.write_bytes(b"a=1\n")  # deliberately no BOM
        out = tmp_path / "out.ini"
        merge_ini_files(src, {}, out)
        assert out.read_bytes().startswith(b"\xef\xbb\xbf")

    def test_source_bom_does_not_leak_into_first_key_name(self, tmp_path):
        """A BOM'd source (Data.p4k's native extraction format) must not
        prepend the BOM character onto the first key's name — that would
        silently corrupt the first key in the output on every apply."""
        src = tmp_path / "base.ini"
        # BOM written as explicit bytes rather than the invisible U+FEFF
        # character inline in a string literal — the latter is easy to lose
        # or miscopy since it renders as nothing in an editor.
        src.write_bytes(b"\xef\xbb\xbf" + "FirstKey=first value\nSecondKey=second\n".encode("utf-8"))
        out = tmp_path / "out.ini"
        merge_ini_files(src, {"FirstKey": "overridden"}, out)
        # utf-8-sig strips the (correct, expected) leading BOM the output
        # itself carries; a *second*, stray BOM glued onto the key name
        # would mean the source's BOM leaked through unstripped.
        text = out.read_text(encoding="utf-8-sig")
        assert "FirstKey=overridden" in text
        assert (chr(0xFEFF) + "FirstKey") not in text

    def test_values_and_structure_preserved_alongside_bom(self, tmp_path):
        src = tmp_path / "base.ini"
        src.write_text("a=1\nb=2\n; a comment\nc=3\n", encoding="utf-8")
        out = tmp_path / "out.ini"
        merge_ini_files(src, {"b": "overridden"}, out)
        text = out.read_text(encoding="utf-8-sig")
        assert text == "a=1\nb=overridden\n; a comment\nc=3\n"
