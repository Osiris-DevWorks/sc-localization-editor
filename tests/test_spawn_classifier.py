"""Tests for the 1.4.1 spawn-group classifier in ``generate_enhancements_ini``.

The classifier (``classify_spawn_group``) and the bucket-aggregating
``_extract_spawn_counts`` are the replacement for the pre-1.4.1 binary
"Enemies vs Non-hostiles" tally. Key regressions guarded here:

* Civilians (``Civs`` / ``Civ`` / ``Civilian`` / CIG-typo ``Civillian``) all
  route to the Friendlies bucket. Pre-1.4.1, only the literal ``civilian``
  substring matched, so the 80+ shorthand occurrences in infiltrate missions
  silently defaulted to hostile.
* ``Allies`` ship-groups route to Hostiles. In mercenary/council contracts the
  player IS the attacker; ``Allies`` is reinforcements allied with the
  antagonist NPC, not the player. Pre-1.4.1, the ``defend``/``protect``-only
  friendly list missed this and ``Allies`` defaulted to hostile by accident.
  This locks the call so the routing is now intentional and labeled.
* ``Defenders`` ship-groups route to Hostiles (not Friendlies). They spawn
  under ``MissionTargets_BP`` alongside the bounty target — they defend the
  player's target. Pre-1.4.1 they wrongly classified as friendly via the
  ``defend`` substring.
* ``Probe N`` / ``Probe Civillian`` (destroy-satellite mission objectives)
  route to the new Objectives bucket — inanimate satellites, not enemies.
* Spawn groups with names CIG typo'd (``Reinforcments`` missing the 'e',
  ``Civillian`` extra 'l') still classify correctly.
* Unknown is now a real bucket — unrecognized names fall through here
  instead of silently defaulting to hostile.
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
        "generate_enhancements_ini_classifier_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_root(body: str) -> ET.Element:
    return ET.fromstring(f"<MissionBrokerEntry>{body}</MissionBrokerEntry>")


# ── classify_spawn_group: name → (bucket, label) ─────────────────────────────


class TestClassifyHostileShipNames:
    """Names CIG ships that the classifier must route to Hostiles."""

    @pytest.mark.parametrize(
        "name,label",
        [
            ("Target", "Targets"),
            ("Targets", "Targets"),
            ("Reinforcement", "Reinforcements"),
            ("Reinforcements", "Reinforcements"),
            ("Reinforcments", "Reinforcements"),  # CIG typo
            ("Enemy Ships", "Hostiles"),
            ("Hostile Ships", "Hostiles"),
            ("Hostiles", "Hostiles"),
            ("Pirates", "Pirates"),
            ("Bandits", "Bandits"),
            ("Prospectors", "Prospectors"),
            ("InterdictionShips_BP", "Interdiction Ships"),
            ("AcePilotShip", "Ace Pilots"),
            ("Heist Ship", "Heist Target"),
            ("Xeno Threat Vultures", "Xeno Threat"),
            ("Polaris", "Polaris"),
            ("Mauler", "Maulers"),
            ("Security Ships", "Security Forces"),
            # Wave naming — pre-1.4.1 fell through to default-hostile
            ("Wave1", "Hostile Wave"),
            ("Wave 1", "Hostile Wave"),
            ("First Wave", "Hostile Wave"),
            ("Second Wave", "Hostile Wave"),
            ("Starter Wave", "Hostile Wave"),
            ("InitialEnemies", "Hostile Wave"),
        ],
    )
    def test_routes_to_hostiles(self, gen_module, name, label):
        bucket, got_label = gen_module.classify_spawn_group(name, "ship")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert got_label == label


class TestClassifyFriendlyShipNames:
    """Ship-group names that route to Friendlies."""

    @pytest.mark.parametrize(
        "name,label",
        [
            ("ShipToDefend", "Ships to Defend"),
            ("1st ShipToDefend", "Ships to Defend"),
            ("EscortShip", "Escort Wings"),
            ("SalvageableShip", "Salvageable Ships"),
            ("RecipientShip", "Recipient"),
            ("FriendlyShip", "Friendlies"),
        ],
    )
    def test_routes_to_friendlies(self, gen_module, name, label):
        bucket, got_label = gen_module.classify_spawn_group(name, "ship")
        assert bucket == gen_module.SPAWN_FRIENDLY
        assert got_label == label


class TestAlliesIsHostile:
    """Per 1.4.1 redesign: ``Allies`` ship-groups are HOSTILE.

    The mission-data sweep showed ``Allies`` only appears in mercenary_guild
    and thecouncil_guild contract generators, where the player is the
    attacker. The Allies spawn-description sits under ``AlliedSpawnDescriptions_BP``
    — meaning allied with the antagonist NPC the player is hunting, not
    allied with the player.
    """

    def test_allies_routes_to_hostiles(self, gen_module):
        bucket, label = gen_module.classify_spawn_group("Allies", "ship")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert label == "Hostile Allies"


class TestDefendersAreHostile:
    """Per 1.4.1 redesign: ``Defenders`` are HOSTILE in both ship and NPC kinds.

    In mercenary bounty-kill contracts the ``Defenders`` ship-group spawns
    under ``MissionTargets_BP`` alongside the ``Target`` group — they defend
    the bounty target the player is hunting. Pre-1.4.1, ship-context Defenders
    were wrongly classified as friendly via the bare ``defend`` substring.
    """

    def test_ship_defenders_hostile(self, gen_module):
        bucket, label = gen_module.classify_spawn_group("Defenders", "ship")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert label == "Defenders"

    def test_npc_defenders_hostile(self, gen_module):
        bucket, label = gen_module.classify_spawn_group("Defenders", "npc")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert label == "Defenders"

    def test_shiptodefend_still_friendly(self, gen_module):
        """``ShipToDefend`` must still route to Friendlies despite sharing the
        ``defend`` substring with the now-hostile ``Defenders`` — the more
        specific compound-name keyword wins via priority ordering."""
        bucket, label = gen_module.classify_spawn_group("ShipToDefend", "ship")
        assert bucket == gen_module.SPAWN_FRIENDLY
        assert label == "Ships to Defend"

    def test_defendlocationwrapperenemyships_stays_hostile(self, gen_module):
        """``DefendLocationWrapperEnemyShips`` contains both ``defend`` and
        ``enemy`` substrings — the ``enemy`` hostile keyword must win, since
        it appears earlier in the keyword table priority order."""
        bucket, label = gen_module.classify_spawn_group(
            "DefendLocationWrapperEnemyShips", "ship"
        )
        assert bucket == gen_module.SPAWN_HOSTILE
        assert label == "Hostiles"


# ── NPC role keywords ────────────────────────────────────────────────────────


class TestClassifyHostileNpcNames:
    @pytest.mark.parametrize(
        "name,label",
        [
            ("Boss", "Boss"),
            ("Backup", "Backup"),
            ("Sniper x 2", "Snipers"),
            ("CQC x 3", "CQC"),
            ("Soldier x 3", "Soldiers"),
            ("Techie x10", "Technicians"),
            ("Techi x 2", "Technicians"),
            ("Tech x 2", "Technicians"),
            ("Captain x 1", "Captain"),
            ("Exterior Guards", "Guards"),
            ("Sentry", "Sentries"),
            ("Grunts", "Grunts"),
            ("Attackers", "Attackers"),
            ("Juggernaut x 1", "Juggernauts"),
            ("Ninetails_Heavy", "Nine Tails"),
            ("Kopions x 6 -Target", "Kopions"),  # specific keyword beats generic "target"
            ("PrivateSecurity_Armed_Light", "Private Security"),
            ("PrivSec - Sentry - 4", "Private Security"),
        ],
    )
    def test_routes_to_hostiles(self, gen_module, name, label):
        bucket, got_label = gen_module.classify_spawn_group(name, "npc")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert got_label == label


class TestCiviliansAreFriendly:
    """CIG uses several civilian shorthand variants — all must route to Friendlies.

    Pre-1.4.1, the friendly keyword list contained only the literal
    ``civilian`` substring, so the 80+ ``Civs`` / ``Civ`` occurrences in
    infiltrate missions defaulted to hostile.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "Civilians",
            "Civilian",
            "Civillian",  # CIG typo
            "Civs",
            "Civ",
            "Civ x 4",
        ],
    )
    def test_npc_civilian_variants_friendly(self, gen_module, name):
        bucket, label = gen_module.classify_spawn_group(name, "npc")
        assert bucket == gen_module.SPAWN_FRIENDLY
        assert label == "Civilians"

    def test_ship_probe_civillian_friendly(self, gen_module):
        """``Probe Civillian`` (CIG typo + civilian context) routes to Friendlies,
        NOT the Objectives bucket — the leading ``probe `` pattern requires a
        following digit, and civilian beats the generic probe match."""
        bucket, label = gen_module.classify_spawn_group("Probe Civillian", "ship")
        assert bucket == gen_module.SPAWN_FRIENDLY
        assert label == "Civilians"


class TestObjectives:
    """Probes are inanimate satellites — they belong in the Objectives bucket."""

    @pytest.mark.parametrize("name", ["Probe 1", "Probe 2", "Probe 3", "Probe 1 "])
    def test_probe_routes_to_objectives(self, gen_module, name):
        bucket, label = gen_module.classify_spawn_group(name, "ship")
        assert bucket == gen_module.SPAWN_OBJECTIVE
        assert label == "Probe"


class TestUnknownFallback:
    """Names that match no keyword must fall through to the Unknown bucket
    rather than silently defaulting to hostile (the pre-1.4.1 behavior)."""

    @pytest.mark.parametrize(
        "name,kind",
        [
            ("CompletelyMadeUpName", "ship"),
            ("Some Random Future Group", "ship"),
            ("Mystery Squad Z", "npc"),
            ("", "ship"),
        ],
    )
    def test_unknown_names_route_to_unknown(self, gen_module, name, kind):
        bucket, label = gen_module.classify_spawn_group(name, kind)
        assert bucket == gen_module.SPAWN_UNKNOWN
        assert label == "Unknown"


# ── _extract_spawn_counts: aggregation + bucketing ───────────────────────────


class TestExtractSpawnCountsBuckets:
    def test_empty_root_returns_empty_breakdown(self, gen_module):
        root = _make_root("")
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown == {
            gen_module.SPAWN_HOSTILE: {},
            gen_module.SPAWN_FRIENDLY: {},
            gen_module.SPAWN_OBJECTIVE: {},
            gen_module.SPAWN_UNKNOWN: {},
        }

    def test_mixed_ship_groups_bucket_by_label(self, gen_module):
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="Pirates">'
            '<ships><SpawnDescription_Ship concurrentAmount="4"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="Bandits">'
            '<ships><SpawnDescription_Ship concurrentAmount="2"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="EscortShip">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Pirates": 4, "Bandits": 2}
        assert breakdown[gen_module.SPAWN_FRIENDLY] == {"Escort Wings": 1}
        assert breakdown[gen_module.SPAWN_OBJECTIVE] == {}
        assert breakdown[gen_module.SPAWN_UNKNOWN] == {}

    def test_salvage_mission_with_only_salvageable_ship_has_no_hostiles(self, gen_module):
        """A plain salvage mission (SalvageableShip only) should emit zero
        Hostiles — the bug the user originally reported."""
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="SalvageableShip">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}
        assert breakdown[gen_module.SPAWN_FRIENDLY] == {"Salvageable Ships": 1}

    def test_destroy_satellite_mission_emits_objectives_not_hostiles(self, gen_module):
        """A destroy-satellite mission spawning Probe 1/2/3 must emit
        Objectives, not Hostiles. Pre-1.4.1 these inanimate satellites
        counted as enemies."""
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="Probe 1">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="Probe 2">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="Probe 3">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}
        assert breakdown[gen_module.SPAWN_OBJECTIVE] == {"Probe": 3}

    def test_infiltrate_mission_with_civs_doesnt_count_as_enemies(self, gen_module):
        """Infiltrate missions spawn ``Civs`` NPC groups (civilians the player
        must AVOID killing) — these must not show up as Hostiles. Pre-1.4.1,
        ``Civs`` defaulted to hostile because ``civ`` wasn't matched."""
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_NPC_Group Name="Soldier x 3"/>'
            # The "x N" suffix is parsed out by _extract_spawn_counts when no
            # autoSpawnSettings child gives an explicit maxSpawns.
            '<SpawnDescription_NPC_Group Name="Civs x 4"/>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Soldiers": 3}
        assert breakdown[gen_module.SPAWN_FRIENDLY] == {"Civilians": 4}

    def test_unknown_name_lands_in_unknown_bucket(self, gen_module):
        """Pre-1.4.1, an unrecognized spawn-group name silently inflated the
        Enemies tally. With the new classifier, it must land in Unknown so
        the player sees the data is uncertain rather than misleading."""
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="QuantumWidgetSquadron">'
            '<ships><SpawnDescription_Ship concurrentAmount="3"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}
        assert breakdown[gen_module.SPAWN_UNKNOWN] == {"Unknown": 3}

    def test_turret_ship_groups_still_excluded(self, gen_module):
        """Turret ship-groups continue to be skipped by
        ``_extract_spawn_counts`` so they don't double-count with
        ``_extract_turret_info`` in the MISSION DETAILS block."""
        root = _make_root(
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="Pirates">'
            '<ships><SpawnDescription_Ship concurrentAmount="4"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="Turrets">'
            '<ships><SpawnDescription_Ship concurrentAmount="3"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Pirates": 4}


# ── _format_spawn_lines: rendering ───────────────────────────────────────────


class TestFormatSpawnLines:
    def test_empty_breakdown_emits_nothing(self, gen_module):
        breakdown = gen_module._empty_spawn_breakdown()
        assert gen_module._format_spawn_lines(breakdown) == []

    def test_hostiles_line_renders_alphabetically(self, gen_module):
        breakdown = gen_module._empty_spawn_breakdown()
        breakdown[gen_module.SPAWN_HOSTILE] = {"Pirates": 4, "Bandits": 2}
        lines = gen_module._format_spawn_lines(breakdown)
        assert lines == ["<EM4>Hostiles:</EM4> Bandits x2, Pirates x4"]

    def test_unknown_bucket_is_not_rendered(self, gen_module):
        """#187: the Unknown bucket is never surfaced. It guards against
        miscounting unclassified spawns as hostiles, but a bare "Unknown: N"
        (e.g. the cargo ship recovered in a Ling delivery) reads as a bug, so
        it is suppressed in the MISSION DETAILS block."""
        breakdown = gen_module._empty_spawn_breakdown()
        breakdown[gen_module.SPAWN_UNKNOWN] = {"Unknown": 3}
        assert gen_module._format_spawn_lines(breakdown) == []

    def test_mixed_buckets_emit_in_canonical_order(self, gen_module):
        """Hostiles → Friendlies → Objectives — the order matches the visual
        hierarchy in the MISSION DETAILS block. The Unknown bucket, even when
        populated, is omitted (#187)."""
        breakdown = gen_module._empty_spawn_breakdown()
        breakdown[gen_module.SPAWN_HOSTILE] = {"Pirates": 4}
        breakdown[gen_module.SPAWN_FRIENDLY] = {"Escort Wings": 1}
        breakdown[gen_module.SPAWN_OBJECTIVE] = {"Probe": 3}
        breakdown[gen_module.SPAWN_UNKNOWN] = {"Unknown": 2}
        lines = gen_module._format_spawn_lines(breakdown)
        assert lines == [
            "<EM4>Hostiles:</EM4> Pirates x4",
            "<EM4>Friendlies:</EM4> Escort Wings x1",
            "<EM4>Objectives:</EM4> Probe x3",
        ]


# ── _merge_spawn_breakdowns_max: cross-variant aggregation ───────────────────


class TestWrapperHostileFallback:
    """When ``classify_spawn_group`` returns Unknown (typically because the
    spawn-group ``Name`` attribute is missing or empty), ``_extract_spawn_counts``
    walks up to the enclosing ``<MissionProperty missionVariableName="...">``
    and reclassifies as hostile if the wrapper is *player-relative* —
    Hostile, Target, Boss, Eliminate. Relational wrappers (Allied, Attacked,
    Reinforcements) are deliberately excluded because their hostility flips
    per mission template.

    Real-data motivation: 27 unnamed ship-groups in
    ``eckhartsecurity_shipambush.xml`` sit under ``TargetSpawnDescriptions_BP``.
    Pre-fallback they all landed in Unknown; with the fallback they correctly
    land in Hostiles labeled "Targets".
    """

    def _wrap(self, wrapper_name: str, group_xml: str) -> ET.Element:
        return _make_root(
            f'<MissionProperty missionVariableName="{wrapper_name}">'
            f'<value><MissionPropertyValue_ShipSpawnDescriptions>'
            f'<spawnDescriptions>{group_xml}</spawnDescriptions>'
            f'</MissionPropertyValue_ShipSpawnDescriptions></value>'
            f'</MissionProperty>'
        )

    @pytest.mark.parametrize(
        "wrapper_name,expected_label",
        [
            ("HostileShipSpawnDescriptions_BP", "Hostiles"),
            ("TargetSpawnDescriptions_BP", "Targets"),
            ("BossSpawnDescriptions_BP", "Boss"),
            ("BP_SpawnDescriptions_Boss", "Boss"),
            ("BP_SpawnDescriptions_EliminateSpecific_EliminateAll", "Hostiles"),
            ("EliminateSpecific_BP_SpawnDescriptions", "Hostiles"),
        ],
    )
    def test_player_relative_wrapper_recovers_unknown(
        self, gen_module, wrapper_name, expected_label
    ):
        root = self._wrap(
            wrapper_name,
            '<SpawnDescription_ShipGroup>'
            '<ships><SpawnDescription_Ship concurrentAmount="3"/></ships>'
            '</SpawnDescription_ShipGroup>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {expected_label: 3}
        assert breakdown[gen_module.SPAWN_UNKNOWN] == {}

    @pytest.mark.parametrize(
        "wrapper_name",
        [
            # Relational wrappers — meaning flips per template; do NOT recover.
            "AlliedSpawnDescriptions_BP",
            "AttackedShipSpawnDescriptions_BP",
            "ReinforcementsSpawnDescriptions_BP",
            # Generic wrappers — too underspecified to recover from.
            "BP_SpawnDescriptions",
            "NPCSpawnDescriptions_BP",
            "EntitySpawnDescriptions_BP",
            "SpawnDescriptions_BP",
        ],
    )
    def test_relational_or_generic_wrapper_stays_unknown(
        self, gen_module, wrapper_name
    ):
        root = self._wrap(
            wrapper_name,
            '<SpawnDescription_ShipGroup>'
            '<ships><SpawnDescription_Ship concurrentAmount="3"/></ships>'
            '</SpawnDescription_ShipGroup>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}
        assert breakdown[gen_module.SPAWN_UNKNOWN] == {"Unknown": 3}

    def test_name_keyword_match_wins_over_wrapper(self, gen_module):
        """When the Name itself classifies (i.e. NOT Unknown), the wrapper
        fallback never fires — Name-keyword always wins. Otherwise a
        ``Name="Civilians"`` group sitting inside ``TargetSpawnDescriptions_BP``
        would get flipped to hostile, which is wrong."""
        root = self._wrap(
            "TargetSpawnDescriptions_BP",
            '<SpawnDescription_ShipGroup Name="Civilians">'
            '<ships><SpawnDescription_Ship concurrentAmount="2"/></ships>'
            '</SpawnDescription_ShipGroup>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        assert breakdown[gen_module.SPAWN_FRIENDLY] == {"Civilians": 2}
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}

    def test_npc_group_fallback_works_too(self, gen_module):
        """The fallback applies to NPC groups as well — an unnamed NPC
        group inside ``BossSpawnDescriptions_BP`` lands in Hostiles."""
        root = self._wrap(
            "BossSpawnDescriptions_BP",
            '<SpawnDescription_NPC_Group Name="x 5"/>'
        )
        breakdown = gen_module._extract_spawn_counts(root)
        # The "x 5" Name has no keyword match so it classifies Unknown,
        # then the wrapper fallback promotes it to Hostiles/Boss with the
        # ``x N`` count parsed from the Name.
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Boss": 5}
        assert breakdown[gen_module.SPAWN_UNKNOWN] == {}


class TestHandlerScopeExclusion:
    """#186: the handler-level spawn fallback must inherit only spawns defined
    at handler scope, never the union of every sibling ``CareerContract``'s
    roster. A greedy ``.//`` scan over the whole handler leaked ground
    "Kopions"/"Soldiers" onto an easy 9-probe satellite mission whose own
    contract carried no spawns and so fell back to the handler breakdown.
    """

    def _handler(self) -> ET.Element:
        root = _make_root(
            '<ContractGeneratorHandler_Career>'
            # Handler-scope default: a ship group directly under the handler,
            # outside any CareerContract — the genuine shared default.
            '<SpawnDescription_ShipGroup Name="Defenders">'
            '<ships><SpawnDescription_Ship concurrentAmount="4"/></ships>'
            '</SpawnDescription_ShipGroup>'
            # Two sibling contracts, each with its own larger roster — including
            # a ground "Kopions" group that must never leak onto a sibling.
            '<CareerContract debugName="A">'
            '<SpawnDescription_ShipGroup Name="Pirates">'
            '<ships><SpawnDescription_Ship concurrentAmount="30"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</CareerContract>'
            '<CareerContract debugName="B">'
            '<SpawnDescription_ShipGroup Name="Kopions">'
            '<ships><SpawnDescription_Ship concurrentAmount="9"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</CareerContract>'
            '</ContractGeneratorHandler_Career>'
        )
        return root.find(".//ContractGeneratorHandler_Career")

    def test_excludes_sibling_contract_spawns(self, gen_module):
        handler = self._handler()
        breakdown = gen_module._extract_spawn_counts(
            handler, exclude_within="CareerContract"
        )
        # Only the handler-scope Defenders survive; the contracts' rosters drop.
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Defenders": 4}

    def test_without_exclusion_unions_everything(self, gen_module):
        # Documents the pre-fix behavior the exclusion guards against.
        handler = self._handler()
        breakdown = gen_module._extract_spawn_counts(handler)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {
            "Defenders": 4, "Pirates": 30, "Kopions": 9,
        }

    def test_contract_own_spawns_unchanged(self, gen_module):
        # The exclusion only matters at handler scope; a contract still reports
        # its own roster (this is what wins when a contract has its own spawns).
        contract = self._handler().find(".//CareerContract[@debugName='A']")
        breakdown = gen_module._extract_spawn_counts(contract)
        assert breakdown[gen_module.SPAWN_HOSTILE] == {"Pirates": 30}

    def test_no_handler_scope_spawns_yields_empty(self, gen_module):
        # The satellite case: every spawn lives inside a contract, so handler
        # scope is empty and an own-less contract inherits nothing (no inflated
        # roster) rather than the union.
        root = _make_root(
            '<ContractGeneratorHandler_Career>'
            '<CareerContract debugName="A">'
            '<SpawnDescription_ShipGroup Name="Pirates">'
            '<ships><SpawnDescription_Ship concurrentAmount="30"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</CareerContract>'
            '</ContractGeneratorHandler_Career>'
        )
        handler = root.find(".//ContractGeneratorHandler_Career")
        breakdown = gen_module._extract_spawn_counts(
            handler, exclude_within="CareerContract"
        )
        assert breakdown[gen_module.SPAWN_HOSTILE] == {}


class TestMergeSpawnBreakdownsMax:
    """The contract aggregator merges per-variant breakdowns by taking the
    MAX per label — preserving the pre-1.4.1 ``max(enemies, venemies)``
    semantics at finer granularity. A variant absent from one breakdown
    doesn't suppress the value from another."""

    def test_per_label_max_across_variants(self, gen_module):
        agg = gen_module._empty_spawn_breakdown()
        v1 = gen_module._empty_spawn_breakdown()
        v1[gen_module.SPAWN_HOSTILE] = {"Pirates": 4, "Bandits": 2}
        v2 = gen_module._empty_spawn_breakdown()
        v2[gen_module.SPAWN_HOSTILE] = {"Pirates": 6, "Soldiers": 3}

        gen_module._merge_spawn_breakdowns_max(agg, v1)
        gen_module._merge_spawn_breakdowns_max(agg, v2)

        assert agg[gen_module.SPAWN_HOSTILE] == {
            "Pirates": 6,  # max(4, 6) = 6
            "Bandits": 2,  # only in v1; preserved
            "Soldiers": 3,  # only in v2; preserved
        }

    def test_smaller_count_does_not_overwrite(self, gen_module):
        agg = gen_module._empty_spawn_breakdown()
        agg[gen_module.SPAWN_HOSTILE] = {"Pirates": 10}
        v = gen_module._empty_spawn_breakdown()
        v[gen_module.SPAWN_HOSTILE] = {"Pirates": 3}
        gen_module._merge_spawn_breakdowns_max(agg, v)
        assert agg[gen_module.SPAWN_HOSTILE] == {"Pirates": 10}


class TestSpawnGatingInEnhancementsMission:
    """#163 / #165: the Hostiles toggle and shared-desc ambiguity suppression
    are applied inside ``enhancements_mission`` (the pu_missions / entities
    path), not just the contractgen path."""

    @staticmethod
    def _mission():
        # A salvage-shaped mission: one friendly salvage target + a hostile
        # group, under a description key shared with other variants.
        return ET.fromstring(
            '<MissionBrokerEntry description="@Shared_desc">'
            '<spawnDescriptions>'
            '<SpawnDescription_ShipGroup Name="SalvageableShip">'
            '<ships><SpawnDescription_Ship concurrentAmount="1"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '<SpawnDescription_ShipGroup Name="Pirates">'
            '<ships><SpawnDescription_Ship concurrentAmount="4"/></ships>'
            '</SpawnDescription_ShipGroup>'
            '</spawnDescriptions>'
            '</MissionBrokerEntry>'
        )

    def test_show_spawns_true_emits_hostiles(self, gen_module):
        body = gen_module.enhancements_mission(self._mission(), show_fields={"spawns": True})
        assert "Hostiles:" in body and "Pirates" in body

    def test_show_spawns_false_drops_all_spawn_lines(self, gen_module):
        # #163: with the Hostiles toggle off, no spawn bucket is emitted.
        body = gen_module.enhancements_mission(self._mission(), show_fields={"spawns": False})
        assert "Hostiles:" not in body
        assert "Salvageable Ships" not in body

    def test_ambiguous_desc_drops_hostiles_keeps_friendlies(self, gen_module):
        # #165: a desc key shared by missions with conflicting hostiles drops
        # ONLY the Hostiles bucket; the consistent friendly line survives.
        root = self._mission()
        key = gen_module._mission_loc_key(root)
        body = gen_module.enhancements_mission(
            root, spawn_ambiguous_keys={key}
        )
        assert "Hostiles:" not in body
        assert "Salvageable Ships" in body


class TestAcePilotClassification:
    """#158: an AcePilotShip spawn group is the detection basis for the
    [ACE]/[ACE?] title tag — it must classify as the 'Ace Pilots' hostile
    label so the title loop can find it in a variant's spawn breakdown."""

    @pytest.mark.parametrize("name", ["AcePilotShip", "AcePilot", "Ace Pilot"])
    def test_ace_group_is_hostile_ace_pilots(self, gen_module, name):
        bucket, label = gen_module.classify_spawn_group(name, "ship")
        assert bucket == gen_module.SPAWN_HOSTILE
        assert label == "Ace Pilots"
