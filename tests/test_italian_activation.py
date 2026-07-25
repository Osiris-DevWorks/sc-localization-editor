"""Italian is shipped as an available, AI-translated language (#298).

Locks the activation:
  * the real ``languages/italian/ui.json`` parses and is in the ``{ht, at}``
    shape,
  * Italian appears in the language selector (it is no longer a stub),
  * the SC language id maps to ``italian_(italy)`` so apply-to-game writes the
    Localization folder and ``g_language`` the game actually loads,
  * ``languages/sources.json`` carries an Italian base.ini URL.

These guard against a key bump or a revert silently breaking the shipped
Italian language.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from utils.settings import AppSettings, SC_LANGUAGE_IDS  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.regression]

_IT_UI = REPO / "languages" / "italian" / "ui.json"


def _leaves(node, prefix=""):
    """Yield (dotpath, leaf) for every translation leaf in the tree."""
    for k, v in node.items():
        if k == "_comment":
            continue
        p = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict) and ("ht" in v or "at" in v):
            yield p, v
        elif isinstance(v, dict):
            yield from _leaves(v, p)


def test_italian_ui_json_is_valid_ht_at_shape():
    data = json.loads(_IT_UI.read_text(encoding="utf-8"))
    leaves = list(_leaves(data))
    assert leaves, "Italian ui.json has no translation leaves"
    for path, leaf in leaves:
        assert set(leaf) >= {"ht", "at"}, f"{path} is not an {{ht, at}} leaf: {leaf!r}"
        assert isinstance(leaf["ht"], str) and isinstance(leaf["at"], str)


def test_italian_has_ai_translations_for_every_english_key():
    en_data = json.loads((REPO / "languages" / "english" / "ui.json").read_text(encoding="utf-8"))
    it_data = json.loads(_IT_UI.read_text(encoding="utf-8"))
    en_paths = {p for p, _ in _leaves(en_data)}
    it_leaves = dict(_leaves(it_data))
    missing = en_paths - set(it_leaves)
    assert not missing, f"Italian is missing translations for: {sorted(missing)[:10]}"
    for path in en_paths:
        assert it_leaves[path]["at"].strip(), f"{path} has an empty `at` fallback"


def test_italian_tutorial_has_all_steps():
    it_data = json.loads(_IT_UI.read_text(encoding="utf-8"))
    tutorial = it_data.get("tutorial", {})
    expected_steps = {
        "welcome", "extract", "enhancements", "enh_categories", "enh_favorites",
        "enh_mission_labels", "enh_tag_builder", "blueprint_tracker", "edit",
        "filter_row", "editor", "preview", "apply", "cfg_appearance",
        "cfg_sc_install", "cfg_data_folder", "cfg_p4k_extraction", "cfg_tools", "help",
    }
    assert expected_steps <= set(tutorial), (
        f"Missing tutorial steps: {expected_steps - set(tutorial)}"
    )


def test_italian_is_available_in_selector():
    assert "italian" in AppSettings.get_available_languages()


def test_italian_maps_to_italy_localization_id():
    assert SC_LANGUAGE_IDS["italian"] == "italian_(italy)"
    assert AppSettings.get_sc_language_id("italian") == "italian_(italy)"


def test_sources_json_has_italian_url():
    sources = json.loads((REPO / "languages" / "sources.json").read_text(encoding="utf-8"))
    assert sources.get("italian", "").startswith("https://")
