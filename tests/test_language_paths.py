"""Per-language cache paths, enhancement stamps, and base.ini URL resolution
(src/utils/settings.py language layer, 2.0 #30).

These helpers decide where files land on disk and whether a language switch
regenerates enhancements, so the layout is locked here:

  * English base.ini stays at the channel cache root; every other language
    caches under ``cache/lang/{language}/`` (created on demand).
  * Enhancements always live next to the base.ini they were generated from
    (``get_enhancements_dir`` is just the base.ini's parent).
  * The ``.dataforge_stamp`` marker round-trips per language and is isolated
    between languages — French's stamp must not satisfy Portuguese's check.
  * ``get_language_base_url`` resolves user override first, then the bundled
    sources.json map, then ''.
  * ``get_sc_language_id`` maps app folder names to SC identifiers and falls
    back to the raw name for unknown languages.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from src.utils import settings as settings_module  # noqa: E402
from src.utils.json_settings import JsonSettings  # noqa: E402
from src.utils.settings import AppSettings  # noqa: E402

pytestmark = pytest.mark.unit


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Hermetic settings: tmp cache dir + tmp JsonSettings backend."""
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setattr(AppSettings, "get_cache_dir", staticmethod(lambda: cache))
    saved = AppSettings._backend
    AppSettings._backend = JsonSettings(tmp_path / "config.json")
    yield cache
    AppSettings._backend = saved


class TestBaseIniPath:
    def test_english_uses_cache_root(self, env):
        assert AppSettings.get_base_ini_path("english") == env / "base.ini"

    def test_english_does_not_create_lang_dir(self, env):
        AppSettings.get_base_ini_path("english")
        assert not (env / "lang").exists()

    def test_non_english_nests_under_lang(self, env):
        path = AppSettings.get_base_ini_path("french")
        assert path == env / "lang" / "french" / "base.ini"

    def test_non_english_creates_parent_dir(self, env):
        path = AppSettings.get_base_ini_path("french")
        assert path.parent.is_dir()

    def test_default_argument_uses_selected_language(self, env, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        assert AppSettings.get_base_ini_path() == env / "lang" / "french" / "base.ini"


class TestEnhancementsDir:
    def test_is_base_ini_parent_for_english(self, env):
        assert AppSettings.get_enhancements_dir("english") == env

    def test_is_base_ini_parent_for_non_english(self, env):
        assert (
            AppSettings.get_enhancements_dir("portuguese_br")
            == env / "lang" / "portuguese_br"
        )


class TestEnhancementsStamp:
    def test_absent_stamp_reads_empty(self, env):
        assert AppSettings.get_enhancements_stamp("french") == ""

    def test_round_trip(self, env):
        AppSettings.set_enhancements_stamp("p4k-2024-key", "french")
        assert AppSettings.get_enhancements_stamp("french") == "p4k-2024-key"

    def test_stamps_are_per_language(self, env):
        AppSettings.set_enhancements_stamp("french-key", "french")
        assert AppSettings.get_enhancements_stamp("portuguese_br") == ""

    def test_stamp_file_lives_in_enhancements_dir(self, env):
        AppSettings.set_enhancements_stamp("k", "french")
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.ENHANCEMENTS_STAMP_NAME
        )
        assert stamp.is_file()


class TestTagConfigStamp:
    """The .tag_config_stamp marker mirrors .dataforge_stamp: per-language,
    round-trips, isolated between languages, and a corrupt (non-UTF-8) stamp
    reads as missing rather than crashing (#251 bug class). Backs the Save Tag
    Changes button's per-channel freshness check on switch."""

    def test_absent_stamp_reads_empty(self, env):
        assert AppSettings.get_tag_config_stamp("french") == ""

    def test_round_trip(self, env):
        AppSettings.set_tag_config_stamp("abc123def456", "french")
        assert AppSettings.get_tag_config_stamp("french") == "abc123def456"

    def test_stamps_are_per_language(self, env):
        AppSettings.set_tag_config_stamp("french-fp", "french")
        assert AppSettings.get_tag_config_stamp("portuguese_br") == ""

    def test_independent_of_dataforge_stamp(self, env):
        # Both stamps live in the same dir but must not read each other.
        AppSettings.set_enhancements_stamp("p4k-key", "french")
        AppSettings.set_tag_config_stamp("tag-fp", "french")
        assert AppSettings.get_enhancements_stamp("french") == "p4k-key"
        assert AppSettings.get_tag_config_stamp("french") == "tag-fp"

    def test_stamp_file_lives_in_enhancements_dir(self, env):
        AppSettings.set_tag_config_stamp("fp", "french")
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.TAG_CONFIG_STAMP_NAME
        )
        assert stamp.is_file()

    def test_corrupt_stamp_reads_empty(self, env):
        # A non-UTF-8 stamp must be treated as missing, not raise (#251).
        stamp = (
            AppSettings.get_enhancements_dir("french")
            / AppSettings.TAG_CONFIG_STAMP_NAME
        )
        stamp.parent.mkdir(parents=True, exist_ok=True)
        stamp.write_bytes(b"stamp\xa0value")
        assert AppSettings.get_tag_config_stamp("french") == ""


class TestLanguageBaseUrl:
    def test_unset_and_unbundled_resolves_empty(self, env, monkeypatch):
        monkeypatch.setattr(settings_module, "_bundled_language_sources", lambda: {})
        assert AppSettings.get_language_base_url("french") == ""

    def test_bundled_map_is_the_fallback(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/bundled.ini"
        )

    def test_user_override_wins_over_bundled(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        AppSettings.set_language_source_override(
            "french", "https://example.test/override.ini"
        )
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/override.ini"
        )

    def test_clearing_override_restores_bundled(self, env, monkeypatch):
        monkeypatch.setattr(
            settings_module,
            "_bundled_language_sources",
            lambda: {"french": "https://example.test/bundled.ini"},
        )
        AppSettings.set_language_source_override("french", "https://x.test/o.ini")
        AppSettings.set_language_source_override("french", "")
        assert (
            AppSettings.get_language_base_url("french")
            == "https://example.test/bundled.ini"
        )

    def test_overrides_are_per_language(self, env, monkeypatch):
        monkeypatch.setattr(settings_module, "_bundled_language_sources", lambda: {})
        AppSettings.set_language_source_override("french", "https://x.test/fr.ini")
        assert AppSettings.get_language_base_url("portuguese_br") == ""


class TestLocalizedDocPath:
    @pytest.fixture
    def docs_env(self, tmp_path, monkeypatch):
        """Fake languages/ tree with a translated HELP.md for french only."""
        langs = tmp_path / "languages"
        (langs / "french").mkdir(parents=True)
        (langs / "french" / "HELP.md").write_text("# Aide", encoding="utf-8")
        monkeypatch.setattr(AppSettings, "get_languages_dir", staticmethod(lambda: langs))
        return langs

    def test_translated_doc_wins_for_non_english(self, docs_env):
        path = AppSettings.get_localized_doc_path("HELP.md", "french")
        assert path == docs_env / "french" / "HELP.md"

    def test_english_always_uses_bundled_docs(self, docs_env):
        path = AppSettings.get_localized_doc_path("HELP.md", "english")
        assert path.parts[-2:] == ("docs", "HELP.md")

    def test_missing_translation_falls_back_to_bundled_docs(self, docs_env):
        # french ships no LEGAL.md in this fixture → bundled English copy.
        path = AppSettings.get_localized_doc_path("LEGAL.md", "french")
        assert path.parts[-2:] == ("docs", "LEGAL.md")

    def test_default_argument_uses_selected_language(self, docs_env, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        path = AppSettings.get_localized_doc_path("HELP.md")
        assert path == docs_env / "french" / "HELP.md"


class TestScLanguageId:
    def test_known_mapping(self):
        assert AppSettings.get_sc_language_id("portuguese_br") == "portuguese_(brazil)"
        assert AppSettings.get_sc_language_id("english") == "english"

    def test_unknown_language_falls_back_to_raw_name(self):
        assert AppSettings.get_sc_language_id("klingon") == "klingon"

    def test_default_argument_uses_selected_language(self, monkeypatch):
        monkeypatch.setattr(
            AppSettings, "get_selected_language", staticmethod(lambda: "french")
        )
        assert AppSettings.get_sc_language_id() == "french_(france)"
