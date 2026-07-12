"""Mission-title tags ("General Tags", 2.2.0): independent show/hide for the
[BP]/[ACE]/rep-xp markers appended to the mission TITLE, split off from the
mission-detail-fields body toggles (issue #121) that used to share
"blueprint_tag"/"ace" with these. See test_mission_detail_fields.py for the
body-field contract.

Two layers are covered:

* The AppSettings contract: every field defaults to on (matching the prior,
  unsplit behaviour), set/get round-trips, unknown keys ignored.
* The generator's show/hide gating. ``_run_gen_missions`` isn't callable
  without a large synthetic ctx, so (as with test_mission_detail_fields.py)
  these tests drive a replica of the exact
  ``if _show_title_tag(field): augmented_title += ...`` structure. The
  replica is kept line-for-line faithful to the generator block it mirrors.
* The one-shot migration that carries a user's prior blueprint_tag/ace
  choice into the new independent keys.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PyQt6.QtCore import QSettings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils.settings import AppSettings  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Back AppSettings with one shared file-scoped QSettings instance (a single
    instance so set-then-get is consistent; see #123)."""
    shared = QSettings(str(tmp_path / "reg.ini"), QSettings.Format.IniFormat)
    monkeypatch.setattr(AppSettings, "settings", staticmethod(lambda: shared))


# ── Settings contract ──────────────────────────────────────────────────────

def test_defaults_all_on(isolated_settings):
    tags = AppSettings.get_mission_title_tags()
    assert set(tags) == set(AppSettings.MISSION_TITLE_TAG_KEYS)
    assert all(tags.values()), "every mission-title tag must default to on"


def test_set_get_roundtrip(isolated_settings):
    AppSettings.set_mission_title_tag("ace", False)
    AppSettings.set_mission_title_tag("rep", False)
    tags = AppSettings.get_mission_title_tags()
    assert tags["ace"] is False
    assert tags["rep"] is False
    # Untouched field stays on.
    assert tags["blueprint"] is True


def test_unknown_key_ignored(isolated_settings):
    AppSettings.set_mission_title_tag("not_a_field", False)
    tags = AppSettings.get_mission_title_tags()
    assert "not_a_field" not in tags
    assert all(tags.values())


# ── Generator gating (replica of the _run_gen_missions title-tag block) ─────

def _render_title_tags(tags: dict, *, has_bp=True, bp_partial=False,
                        all_ace=False, any_ace=False,
                        xps=(500,)) -> str:
    """Replica of the generator's title-tag gating. `tags` maps
    field -> bool; missing defaults to on, exactly like ``_show_title_tag``
    in _run_gen_missions. Returns just the appended tag suffix."""
    def _show_title_tag(f):
        return bool(tags.get(f, True))

    out = ""
    if _show_title_tag("blueprint"):
        if has_bp and not bp_partial:
            out += " [BP]"
        elif bp_partial:
            out += " [BP?]"
    if _show_title_tag("ace"):
        if all_ace:
            out += " [ACE]"
        elif any_ace:
            out += " [ACE?]"
    nonzero_xp = [x for x in xps if x > 0] if _show_title_tag("rep") else []
    if len(nonzero_xp) == 1:
        out += f" [{nonzero_xp[0]} REP]"
    elif len(nonzero_xp) > 1:
        out += f" [{min(nonzero_xp)}-{max(nonzero_xp)} REP]"
    return out


def test_all_on_shows_every_tag():
    tag = _render_title_tags({}, all_ace=True)
    assert "[BP]" in tag
    assert "[ACE]" in tag
    assert "[500 REP]" in tag


def test_blueprint_off_strips_bp_tag_only():
    tag = _render_title_tags({"blueprint": False}, all_ace=True)
    assert "[BP]" not in tag
    assert "[ACE]" in tag
    assert "REP]" in tag


def test_ace_off_strips_ace_tag_only():
    tag = _render_title_tags({"ace": False}, all_ace=True)
    assert "[BP]" in tag
    assert "[ACE]" not in tag
    assert "REP]" in tag


def test_rep_off_strips_rep_tag_only():
    tag = _render_title_tags({"rep": False}, all_ace=True)
    assert "[BP]" in tag
    assert "[ACE]" in tag
    assert "REP]" not in tag


def test_rep_off_with_no_other_tags_is_empty():
    # Regression: the old code's bare `else:` on the multi-xp range branch
    # would crash on an empty xp list once rep-gating could produce one.
    tag = _render_title_tags({"rep": False, "blueprint": False, "ace": False},
                              has_bp=False)
    assert tag == ""


def test_multi_xp_range_still_works_when_rep_on():
    tag = _render_title_tags({}, xps=(500, 900))
    assert "[500-900 REP]" in tag


def test_all_off_strips_everything():
    tag = _render_title_tags(
        {"blueprint": False, "ace": False, "rep": False}, all_ace=True
    )
    assert tag == ""


# ── Migration from the old shared blueprint_tag/ace toggle (2.2.0) ──────────

def test_migration_carries_prior_off_state(isolated_settings):
    # User had explicitly turned off the old shared toggles.
    AppSettings.settings().setValue("mission_field/blueprint_tag", False)
    AppSettings.settings().setValue("mission_field/ace", False)
    AppSettings.migrate_title_tag_settings()
    tags = AppSettings.get_mission_title_tags()
    assert tags["blueprint"] is False
    assert tags["ace"] is False
    # rep has no legacy source — defaults on.
    assert tags["rep"] is True


def test_migration_no_prior_settings_defaults_on(isolated_settings):
    AppSettings.migrate_title_tag_settings()
    tags = AppSettings.get_mission_title_tags()
    assert all(tags.values())


def test_migration_runs_once(isolated_settings):
    AppSettings.settings().setValue("mission_field/ace", False)
    AppSettings.migrate_title_tag_settings()
    assert AppSettings.get_mission_title_tags()["ace"] is False
    # A deliberate re-enable afterward must survive a second migration call.
    AppSettings.set_mission_title_tag("ace", True)
    AppSettings.migrate_title_tag_settings()
    assert AppSettings.get_mission_title_tags()["ace"] is True


def test_old_ace_body_field_untouched_by_migration(isolated_settings):
    # The body-only "ace" mission-detail field is a separate setting
    # ("mission_field/ace") from the new title-tag "ace" — migrating the
    # title tag must not disturb the body field's own value.
    AppSettings.set_mission_detail_field("ace", False)
    AppSettings.migrate_title_tag_settings()
    assert AppSettings.get_mission_detail_fields()["ace"] is False
