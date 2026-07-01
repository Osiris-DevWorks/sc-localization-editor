"""Hauling/delivery/courier route-in-title derivation (#166 → 2.1 Mission Titles).

The pure route helpers in scripts/generate_enhancements_ini.py
(`_derive_route_fragment`, `_route_token_role`, `_title_route_token`,
`_is_route_title`) driven with synthetic bodies. In 2.1 the route became a
Tag Builder feature: `_derive_route_fragment` returns the route CORE (no ` | `
separator, no placement — the caller places it via tag_builder.apply_mission_title),
the arrow and Location/Destination modifier come from the mission_titles config,
and courier titles are eligible. The stale `kraken_4.7.ini` fixture is deliberately
not used as ground truth.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils.tag_builder import default_config  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    repo_root = Path(__file__).resolve().parent.parent
    script_path = repo_root / "scripts" / "generate_enhancements_ini.py"
    spec = importlib.util.spec_from_file_location(
        "generate_enhancements_ini_route_test", script_path
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── Endpoint classification ─────────────────────────────────────────────────

@pytest.mark.parametrize("var", ["Location", "location", "Location1", "Pickup1", "pickup2"])
def test_role_from(gen_module, var):
    assert gen_module._route_token_role(var) == "from"


@pytest.mark.parametrize("var", ["Destination", "destination", "Destination2", "Dropoff1"])
def test_role_to(gen_module, var):
    assert gen_module._route_token_role(var) == "to"


@pytest.mark.parametrize("var", ["TargetName", "System", "Item", "Client", "MissionMaxSCUSize"])
def test_role_none(gen_module, var):
    assert gen_module._route_token_role(var) is None


# ── Route CORE shape (no separator; caller places it) ───────────────────────

def test_atob_full_route(gen_module):
    """One source, one dest → ``from > to`` with the short |name modifier."""
    body = "stash at <EM4>~mission(Location|Address)</EM4>, deliver to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Location|name) > ~mission(Destination|name)"
    )


def test_multi_to_single_shows_dest_only(gen_module):
    body = ("grab from ~mission(Location1|Address) and ~mission(Location2|Address), "
            "bring to ~mission(Destination|Address)")
    assert gen_module._derive_route_fragment([body]) == "to ~mission(Destination|name)"


def test_single_to_multi_shows_source_only(gen_module):
    body = ("collect at ~mission(Location|Address), deliver to "
            "~mission(Destination1|Address) and ~mission(Destination2|Address)")
    assert gen_module._derive_route_fragment([body]) == "from ~mission(Location|name)"


def test_pickup_dropoff_copied_verbatim(gen_module):
    """Non-canonical endpoints keep the body's exact token (which resolves)."""
    body = "pick up ~mission(Pickup1|Address), drop at ~mission(Dropoff1|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        "~mission(Pickup1|Address) > ~mission(Dropoff1|Address)"
    )


def test_source_only_when_no_dest(gen_module):
    body = "objective located at ~mission(Location|Address)"
    assert gen_module._derive_route_fragment([body]) == "from ~mission(Location|name)"


def test_no_route_tokens_omitted(gen_module):
    body = "eliminate ~mission(TargetName) in the ~mission(System) system"
    assert gen_module._derive_route_fragment([body]) == ""


def test_ambiguous_multi_multi_omitted(gen_module):
    body = ("~mission(Location1|Address) ~mission(Location2|Address) -> "
            "~mission(Destination1|Address) ~mission(Destination2|Address)")
    assert gen_module._derive_route_fragment([body]) == ""


def test_empty_and_none_bodies_safe(gen_module):
    assert gen_module._derive_route_fragment([]) == ""
    assert gen_module._derive_route_fragment([None, "", "no tokens here"]) == ""


# ── Config-driven arrow + location detail ───────────────────────────────────

def test_arrow_from_config(gen_module):
    cfg = default_config("mission_titles")
    cfg.route_arrow = "arrow"
    body = "at ~mission(Location|Address) to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body], cfg) == (
        "~mission(Location|name) → ~mission(Destination|name)"
    )


def test_location_detail_address_only_affects_canonical(gen_module):
    cfg = default_config("mission_titles")
    cfg.location_detail = "address"
    # Location/Destination honor the toggle...
    body = "at ~mission(Location|Address) to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body], cfg) == (
        "~mission(Location|Address) > ~mission(Destination|Address)"
    )
    # ...but Pickup/Dropoff keep the body's own modifier regardless.
    body2 = "pick up ~mission(Pickup1|Address), drop at ~mission(Dropoff1|Address)"
    assert gen_module._derive_route_fragment([body2], cfg) == (
        "~mission(Pickup1|Address) > ~mission(Dropoff1|Address)"
    )


# ── Eligibility (haul / delivery / courier) ─────────────────────────────────

@pytest.mark.parametrize("key", [
    "Foxwell_HaulCargo_AToB_OLP_title_01",
    "Covalex_HaulCargo_SingleToMulti_title",
    "CFP_Delivery_Outpost_title_001",
    "Headhunters_Delivery_Outpost_Multi_title_001",
    "FTL_Courier_Stanton_Easy_Title_001",
    "CleanAir_Courier_title",
])
def test_route_titles_eligible(gen_module, key):
    assert gen_module._is_route_title(key) is True


@pytest.mark.parametrize("key", [
    "BountyHuntersGuild_Bounty_Stanton_Easy_title_001",
    "cfp_defend_cave_Generic_title_001",
    "vaughn_assassination_FPS_UGF_legal_title_001",
])
def test_non_route_keys_not_eligible(gen_module, key):
    assert gen_module._is_route_title(key) is False


def test_title_already_showing_route_token_is_skipped(gen_module):
    assert gen_module._title_has_route_token(
        "Inter-Outpost Delivery at ~mission(Destination)"
    ) is True


def test_title_with_only_non_route_tokens_is_not_flagged(gen_module):
    assert gen_module._title_has_route_token(
        "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul"
    ) is False
    assert gen_module._title_has_route_token("Retrieve Cargo Haul") is False
