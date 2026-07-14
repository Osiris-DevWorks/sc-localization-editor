"""Tests for the mission reputation-reward line formatter (issue #102).

`_rep_reward_line` renders the reputation line in a mission's MISSION DETAILS
body. Two rules it locks down:

  * The unit word is the user-configurable label (``rep_xp_label``, default
    "Rep"), never the literal "XP". Renaming the label on the Enhancements tab
    must flow through every mission body, combat and cargo alike.
  * The label is used as the field name when no rank/standing is known and as
    the trailing unit otherwise, but never both at once (no "Rep: +500 Rep").

This formatter drives the contract-generator combat bodies; the cargo / delivery
gap in #102 is closed separately by sparing those descriptions from the #31
orphan-drop, so all cargo hauls keep the contract-generator body the
ContractLegacy path already produces (verified against the LIVE cache and
in-game).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen():
    """Load scripts/generate_enhancements_ini.py (lives outside src/)."""
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location("gen_rep_label_test", script_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_rank_appends_label_as_unit(gen):
    assert gen._rep_reward_line("Neutral", "+500", "Rep") == "<EM4>Neutral:</EM4> +500 Rep"


def test_no_rank_uses_label_as_field_no_unit(gen):
    # field == label, so the unit is suppressed (no "Rep: +500 Rep" doubling).
    assert gen._rep_reward_line("", "+500", "Rep") == "<EM4>Rep:</EM4> +500"


def test_field_equal_label_suppresses_unit(gen):
    assert gen._rep_reward_line("Rep", "+500", "Rep") == "<EM4>Rep:</EM4> +500"


def test_failure_penalty(gen):
    assert gen._rep_reward_line("Failure Penalty", "-100", "Rep") == (
        "<EM4>Failure Penalty:</EM4> -100 Rep"
    )


def test_range_amount(gen):
    assert gen._rep_reward_line("", "+500–4,000", "Rep") == "<EM4>Rep:</EM4> +500–4,000"


def test_custom_label_never_says_xp(gen):
    line = gen._rep_reward_line("Tier 1", "+500", "Reputation")
    assert line == "<EM4>Tier 1:</EM4> +500 Reputation"
    assert "XP" not in line


def test_custom_label_no_rank_no_unit(gen):
    # custom label as field name, no rank: just the signed amount, no "XP".
    line = gen._rep_reward_line("", "+500", "Reputation")
    assert line == "<EM4>Reputation:</EM4> +500"
    assert "XP" not in line


class TestReputationTrackSuffix:
    """#161: some factions have multiple reputation tracks (e.g. Foxwell
    Enforcement shows separate "Security" and "Standing" columns in-game).
    ``_rep_reward_line``'s optional ``track`` param appends which track a
    rank belongs to, in parentheses after the unit."""

    def test_track_appended_after_unit(self, gen):
        assert gen._rep_reward_line("Applicant", "+500", "Rep", "Security") == (
            "<EM4>Applicant:</EM4> +500 Rep (Security)"
        )

    def test_no_track_unchanged(self, gen):
        assert gen._rep_reward_line("Applicant", "+500", "Rep", "") == (
            "<EM4>Applicant:</EM4> +500 Rep"
        )

    def test_track_default_omitted_when_not_passed(self, gen):
        """Backward compatible: existing 3-arg callers are unaffected."""
        assert gen._rep_reward_line("Applicant", "+500", "Rep") == (
            "<EM4>Applicant:</EM4> +500 Rep"
        )

    def test_track_suppressed_when_same_as_field_name(self, gen):
        """A rank literally named the same as its own track (e.g. Contractor
        rank 2 of the Contractor track) doesn't repeat itself."""
        assert gen._rep_reward_line("Contractor", "+200", "Rep", "Contractor") == (
            "<EM4>Contractor:</EM4> +200 Rep"
        )

    def test_track_with_no_rank_field(self, gen):
        assert gen._rep_reward_line("", "+500", "Rep", "Security") == (
            "<EM4>Rep:</EM4> +500 (Security)"
        )

    def test_track_with_failure_penalty_field(self, gen):
        assert gen._rep_reward_line("Failure Penalty", "-100", "Rep", "Security") == (
            "<EM4>Failure Penalty:</EM4> -100 Rep (Security)"
        )
