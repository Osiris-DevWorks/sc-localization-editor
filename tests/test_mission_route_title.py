"""Hauling/delivery route-in-title derivation (issue #166).

Two layers, mirroring test_mission_detail_fields.py:

* The pure route-derivation helpers in scripts/generate_enhancements_ini.py
  (`_derive_route_fragment`, `_route_token_role`, `_title_route_token`),
  driven with synthetic mission bodies. The stale `kraken_4.7.ini` fixture is
  deliberately NOT used as ground truth — the format target comes from the
  current MrKraken/StarStrings contracts.ini (`| from > to`, `| from X`,
  `| to Y`, with the short `|name` modifier).
* The AppSettings contract for the new "route" mission-detail toggle.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture(scope="module")
def gen_module():
    """Load scripts/generate_enhancements_ini.py as an importable module.

    Lives outside src/ and isn't on pythonpath, so load it via importlib
    (same pattern as test_mission_engagement.py). Cached at module scope.
    """
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


# ── Route shape (the StarStrings layout) ────────────────────────────────────

def test_atob_full_route(gen_module):
    """One source, one dest → ``| from > to`` with the short |name modifier."""
    body = "stash at <EM4>~mission(Location|Address)</EM4>, deliver to ~mission(Destination|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        " | ~mission(Location|name) > ~mission(Destination|name)"
    )


def test_multi_to_single_shows_dest_only(gen_module):
    """Many pickups, one dropoff → ``| to <dest>`` (don't comma-list pickups)."""
    body = (
        "grab from ~mission(Location1|Address) and ~mission(Location2|Address), "
        "bring to ~mission(Destination|Address)"
    )
    assert gen_module._derive_route_fragment([body]) == " | to ~mission(Destination|name)"


def test_single_to_multi_shows_source_only(gen_module):
    """One pickup, many dropoffs → ``| from <source>``."""
    body = (
        "collect at ~mission(Location|Address), deliver to "
        "~mission(Destination1|Address) and ~mission(Destination2|Address)"
    )
    assert gen_module._derive_route_fragment([body]) == " | from ~mission(Location|name)"


def test_pickup_dropoff_copied_verbatim(gen_module):
    """Non-canonical endpoint vars keep the body's exact token (proven to
    resolve), rather than an unverified |name swap."""
    body = "pick up ~mission(Pickup1|Address), drop at ~mission(Dropoff1|Address)"
    assert gen_module._derive_route_fragment([body]) == (
        " | ~mission(Pickup1|Address) > ~mission(Dropoff1|Address)"
    )


def test_source_only_when_no_dest(gen_module):
    body = "objective located at ~mission(Location|Address)"
    assert gen_module._derive_route_fragment([body]) == " | from ~mission(Location|name)"


def test_no_route_tokens_omitted(gen_module):
    """A non-haul body (bounty/escort tokens) yields no route."""
    body = "eliminate ~mission(TargetName) in the ~mission(System) system"
    assert gen_module._derive_route_fragment([body]) == ""


def test_ambiguous_multi_multi_omitted(gen_module):
    """Many sources AND many dests can't be one route — omit (the guard)."""
    body = (
        "~mission(Location1|Address) ~mission(Location2|Address) -> "
        "~mission(Destination1|Address) ~mission(Destination2|Address)"
    )
    assert gen_module._derive_route_fragment([body]) == ""


def test_empty_and_none_bodies_safe(gen_module):
    assert gen_module._derive_route_fragment([]) == ""
    assert gen_module._derive_route_fragment([None, "", "no tokens here"]) == ""


def test_shared_title_agreeing_descs_emit_route(gen_module):
    """Multiple A→B descs under one title share the same Location/Destination
    *variable* names (only the resolved values differ), so the route stands."""
    bodies = [
        "from ~mission(Location|Address) to ~mission(Destination|Address)",
        "outlaws at ~mission(Location|Address); return to ~mission(Destination|Address)",
    ]
    assert gen_module._derive_route_fragment(bodies) == (
        " | ~mission(Location|name) > ~mission(Destination|name)"
    )


# ── Haul/delivery scope + de-dup guards ─────────────────────────────────────

@pytest.mark.parametrize("key", [
    "Foxwell_HaulCargo_AToB_OLP_title_01",
    "Covalex_HaulCargo_SingleToMulti_title",
    "CFP_Delivery_Outpost_title_001",
    "Headhunters_Delivery_Outpost_Multi_title_001",
])
def test_haul_delivery_keys_are_eligible(gen_module, key):
    assert gen_module._is_haul_or_delivery_title(key) is True


@pytest.mark.parametrize("key", [
    "BountyHuntersGuild_Bounty_Stanton_Easy_title_001",
    "cfp_defend_cave_Generic_title_001",
    "vaughn_assassination_FPS_UGF_legal_title_001",
])
def test_non_haul_keys_are_not_eligible(gen_module, key):
    """Combat/bounty titles must never get a route, even though their bodies
    can contain a ~mission(Location) token."""
    assert gen_module._is_haul_or_delivery_title(key) is False


def test_title_already_showing_route_token_is_skipped(gen_module):
    """CIG delivery titles embed the destination themselves; we must not double
    it, so a base title that already has a route token reports True."""
    assert gen_module._title_has_route_token(
        "Inter-Outpost Delivery at ~mission(Destination)"
    ) is True


def test_title_with_only_non_route_tokens_is_not_flagged(gen_module):
    """Rank/grade tokens are not route tokens, so such a title is still
    eligible to receive an appended route."""
    assert gen_module._title_has_route_token(
        "~mission(ReputationRank) Rank - ~mission(CargoGradeToken) Cargo Haul"
    ) is False
    assert gen_module._title_has_route_token("Retrieve Cargo Haul") is False


# ── AppSettings contract for the toggle ─────────────────────────────────────

@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


def test_route_field_registered_and_defaults_on(isolated_settings):
    fields = AppSettings.get_mission_detail_fields()
    assert "route" in fields, "the route toggle must be a mission-detail field"
    assert fields["route"] is True, "route must default on"


def test_route_field_roundtrip(isolated_settings):
    AppSettings.set_mission_detail_field("route", False)
    assert AppSettings.get_mission_detail_fields()["route"] is False
    AppSettings.set_mission_detail_field("route", True)
    assert AppSettings.get_mission_detail_fields()["route"] is True
