"""#161: reputation TRACK extraction. Some factions have multiple reputation
tracks (Foxwell Enforcement shows separate "Security" and "Standing" columns
in-game) and which track a mission's XP feeds isn't obvious from the mission
type or name alone. ``_REP_TRACK_PREFIX_RE`` pulls the track token out of a
standing rank's displayName loc key (``RepStanding_Security_Rank0`` ->
"Security", ``RepScope_Contractor_Rank3`` -> "Contractor"); the actual
``_build_standing_tracks`` file-walk (nested inside ``main()``) is exercised
end-to-end in ``test_mission_rep_label.py``'s ``_rep_reward_line`` tests and
verified separately against real DataForge data.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_rep_track_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestRepTrackPrefixRegex:
    def test_repstanding_rank_key(self, gen_module):
        m = gen_module._REP_TRACK_PREFIX_RE.match("RepStanding_Security_Rank0")
        assert m and m.group(1) == "Security"

    def test_repscope_rank_key(self, gen_module):
        m = gen_module._REP_TRACK_PREFIX_RE.match("RepScope_Contractor_Rank3")
        assert m and m.group(1) == "Contractor"

    def test_repstanding_named_rank_key(self, gen_module):
        """Some keys have a word (not just RankN) between the family and the
        trailing _Name, e.g. the Bounty track's special-named tiers."""
        m = gen_module._REP_TRACK_PREFIX_RE.match("RepStanding_Bounty_Applicant_Name")
        assert m and m.group(1) == "Bounty"

    def test_repstanding_rank_with_trailing_name_suffix(self, gen_module):
        m = gen_module._REP_TRACK_PREFIX_RE.match("RepStanding_Barter_Rank1_Name")
        assert m and m.group(1) == "Barter"

    def test_multi_word_family_only_captures_first_token(self, gen_module):
        """The regex captures letters only up to the next underscore —
        multi-word scope names (HiredMuscle) are a single CamelCase token,
        not underscore-separated, so this is still correct."""
        m = gen_module._REP_TRACK_PREFIX_RE.match("RepScope_HiredMuscle_Rank0")
        assert m and m.group(1) == "HiredMuscle"

    def test_unrelated_key_does_not_match(self, gen_module):
        assert gen_module._REP_TRACK_PREFIX_RE.match("mineabletype_primary_aluminium") is None

    def test_bare_prefix_with_no_family_does_not_match(self, gen_module):
        assert gen_module._REP_TRACK_PREFIX_RE.match("RepStanding_") is None
