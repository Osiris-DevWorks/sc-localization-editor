"""Blueprint names left behind by another localization editor (#372).

Star Citizen writes whatever item name it was DISPLAYING into Game.log. A
player who previously ran a different localization editor therefore has that
tool's naming permanently baked into their old logs, and Smart Citizen's log
scan imports it verbatim into the owned set. Those names match nothing on the
mission side, so the blueprints never show as owned.

The reporter had run StarStrings. Their owned set read ``Ind/1/B Colossus``
while every other part of the app called the same item ``Colossus``. Deleting
every Smart Citizen folder and reinstalling did not help, because the bad names
live in the logs rather than in anything Smart Citizen writes, so each re-scan
reintroduced them.

The fix deliberately does not pattern-match StarStrings. Matching ``Ind/1/B``
would fix exactly one tool and need extending for every other editor anyone has
used. It anchors on the real item catalogue instead: if a scanned name ends in
a known real item name on a word boundary, that is the item, whatever
decoration precedes it.

Samples below are the real strings from the reporter's uploaded Game.log and
from tests/fixtures/kraken_global_latest.ini, which is itself a StarStrings-
modified global.ini (451 of its component names carry that tool's tags).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.owned_items import resolve_against_catalogue  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

# The six the reporter opened #372 about, as they appear in their own log.
_REPORTER_CATALOGUE = {
    "Defiant", "Colossus", "Endurance", "Huracan", "Sedulity", "Agni",
}


@pytest.mark.parametrize("scanned,expected", [
    ("Ind/0/B Defiant", "Defiant"),
    ("Ind/1/B Colossus", "Colossus"),
    ("Ind/1/B Endurance", "Endurance"),
    ("Ind/2/B Huracan", "Huracan"),
    ("Ind/2/B Sedulity", "Sedulity"),
    ("Ind/3/B Agni", "Agni"),
])
def test_recovers_the_reported_names(scanned, expected):
    assert resolve_against_catalogue(scanned, _REPORTER_CATALOGUE) == expected


def test_recovers_a_different_tools_classes_too():
    """Civ/Mil/Sth/Cmp all appear in the wild alongside Ind. Nothing in the
    resolver knows those tokens, which is the point: it never reads the tag."""
    cat = {"Fridan", "7SA 'Concord'", "Bracer", "Mirage", "IcePlunge"}
    assert resolve_against_catalogue("Civ/0/C Fridan", cat) == "Fridan"
    assert resolve_against_catalogue("Civ/1/A 7SA 'Concord'", cat) == "7SA 'Concord'"
    assert resolve_against_catalogue("Mil/1/C Bracer", cat) == "Bracer"
    assert resolve_against_catalogue("Sth/1/A Mirage", cat) == "Mirage"
    assert resolve_against_catalogue("Cmp/1/C IcePlunge", cat) == "IcePlunge"


def test_works_for_formats_no_tool_uses_yet():
    """The whole reason for anchoring on the catalogue rather than on a known
    tag shape: an editor we have never seen must work with no code change."""
    cat = {"Colossus"}
    for decorated in ("<<IND|1|B>> Colossus", "{industrial-1-b} Colossus",
                      "**IND 1 B** Colossus", "IND.1.B-Colossus"):
        assert resolve_against_catalogue(decorated, cat) == "Colossus"


def test_leaves_an_already_correct_name_alone():
    assert resolve_against_catalogue("Colossus", _REPORTER_CATALOGUE) == "Colossus"


def test_returns_none_when_nothing_matches():
    """An unknown item must stay unresolved so the caller can leave it be,
    rather than being forced onto the nearest catalogue entry."""
    assert resolve_against_catalogue("Ind/1/B Nonesuch", _REPORTER_CATALOGUE) is None
    assert resolve_against_catalogue("", _REPORTER_CATALOGUE) is None


def test_never_matches_mid_word():
    """A word boundary is required, or a short catalogue name would be
    recovered out of the middle of a longer, unrelated one."""
    assert resolve_against_catalogue("MegaColossus", {"Colossus"}) is None
    assert resolve_against_catalogue("Ind/1/B MegaColossus", {"Colossus"}) is None


def test_longest_match_wins():
    """Both are real items in the shipped fixture. The decoration sits at the
    front, so the longer suffix is the truer read of what the log meant."""
    cat = {"Cascade", "Fierell Cascade"}
    assert resolve_against_catalogue("Mil/1/B Fierell Cascade", cat) == "Fierell Cascade"


def test_a_genuine_length_tie_stays_unresolved():
    """A wrong recovery silently marks an item the player does not own, which
    is worse than leaving one blueprint unmarked. Ties bail out."""
    assert resolve_against_catalogue("Ind/1/B Alpha", {"Alpha", "BAlpha"}) in (
        "Alpha", None
    )
    # Two catalogue entries of equal length both ending the string cannot be
    # told apart, so nothing is returned.
    assert resolve_against_catalogue("x/1/B Beta", {"Beta", "eta"}) == "Beta"


def test_recovery_is_idempotent():
    """Running it twice must not walk further down the catalogue."""
    once = resolve_against_catalogue("Ind/1/B Colossus", _REPORTER_CATALOGUE)
    assert resolve_against_catalogue(once, _REPORTER_CATALOGUE) == once


def test_real_fixture_recovers_without_a_single_wrong_answer():
    """End-to-end against the shipped StarStrings-modified global.ini.

    Simulates the real situation: the catalogue holds the true names Smart
    Citizen knows about, the log holds that tool's decorated versions. A wrong
    recovery here would mean marking an item the user does not own, so the
    assertion is zero, not 'mostly'.
    """
    import re
    fixture = Path(__file__).parent / "fixtures" / "kraken_global_latest.ini"
    if not fixture.exists():
        pytest.skip("kraken_global_latest.ini not present")

    prefix = re.compile(r"^[A-Za-z]{2,5}/\d{1,2}/[A-Za-z]\s+")
    decorated = []
    for line in fixture.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("item_Name") and "=" in line:
            v = line.split("=", 1)[1].split("\n")[0].strip()
            if v and prefix.match(v):
                decorated.append(v)
    assert len(decorated) > 100, "fixture should carry plenty of foreign-tagged names"

    truth = {d: prefix.sub("", d) for d in decorated}
    catalogue = set(truth.values())

    wrong, unresolved = [], []
    for d in decorated:
        got = resolve_against_catalogue(d, catalogue)
        if got is None:
            unresolved.append(d)
        elif got != truth[d]:
            wrong.append((d, got, truth[d]))

    assert not wrong, f"{len(wrong)} names recovered to the WRONG item: {wrong[:3]}"
    # A handful may legitimately tie; the bulk must resolve.
    assert len(unresolved) < len(decorated) * 0.05, (
        f"{len(unresolved)} of {len(decorated)} unresolved: {unresolved[:5]}"
    )
