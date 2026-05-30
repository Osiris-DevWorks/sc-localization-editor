"""Settings management using QSettings."""
import logging
import os
from pathlib import Path

from PyQt6.QtCore import QSettings
import winreg

logger = logging.getLogger(__name__)


class AppSettings:
    """Wrapper around QSettings for application configuration."""

    ORG_NAME = "Osiris DevWorks"
    # QSettings registry node — 0.9.2+ uses "Smart Citizen" to match the
    # product rebrand. Legacy installs at "SC Localization Editor" are
    # migrated on first launch by migrate_registry_appname().
    APP_NAME = "Smart Citizen"
    # The old node name, preserved so the one-shot migration can find it.
    _LEGACY_APP_NAME = "SC Localization Editor"

    # Settings keys - Favorites
    FAVORITE_PREFIX = "favorite_prefix"

    # Settings keys - Mission labels
    REP_XP_LABEL = "rep_xp_label"
    MISSION_HEADER_DETAILS = "mission_header/details"
    MISSION_HEADER_BLUEPRINTS = "mission_header/blueprints"
    MISSION_HEADER_ITEMS = "mission_header/items"
    MISSION_HEADER_BLUEPRINT_DATA = "mission_header/blueprint_data"
    MISSION_HEADER_EM_TAG = "mission_header/em_tag"

    # Mission label defaults — source of truth for fallback values
    DEFAULT_REP_XP_LABEL = "Rep"
    DEFAULT_MISSION_HEADER_EM_TAG = "EM3"
    MISSION_HEADER_DEFAULTS = {
        "details": "MISSION DETAILS",
        "blueprints": "POTENTIAL BLUEPRINTS",
        "items": "ITEM REWARDS",
        "blueprint_data": "BLUEPRINT DATA",
    }

    # Settings keys - Appearance
    THEME = "theme"

    # Settings keys - Enhancements
    ENHANCEMENTS_ENABLED = "enhancements_enabled"
    INCLUDE_NEW_LINES = "include_new_lines"

    # Settings keys - Tutorial
    # Stores the app version string ("0.9.3") that last marked the guided tour
    # as completed, so a future release can re-trigger it if the tour gains
    # new steps worth showing again. Empty string means "never shown".
    TUTORIAL_COMPLETED_VERSION = "tutorial_completed_version"
    TUTORIAL_DISABLED = "tutorial_disabled"

    # Settings keys - App self-update check
    # Unix epoch of the last successful GitHub Releases check; the auto-check
    # on startup uses this to throttle itself to once per 6h (staying well
    # under GitHub's 60-req/hr unauthenticated rate limit). Manual checks
    # from the Config tab bypass the throttle.
    LAST_UPDATE_CHECK_EPOCH = "last_update_check_epoch"

    # Settings keys - Star Citizen channel selection
    # Star Citizen ships multiple channels (LIVE/PTU/EPTU/HOTFIX/TECH-PREVIEW)
    # under a common install root, each with its own Data.p4k. We store the
    # root directory + the active channel name separately so the rest of the
    # app can resolve channel-specific paths from a single source of truth.
    # Legacy installs with ``GAME_INSTALL_PATH = {root}\LIVE`` are migrated
    # by ``migrate_game_path_to_channel_layout`` on first launch.
    SC_INSTALL_ROOT = "sc_install_root"
    ACTIVE_CHANNEL = "active_channel"
    CHANNEL_LAYOUT_MIGRATED = "_channel_layout_migrated"  # one-shot marker

    # Channel names are the folder names Star Citizen uses under its install
    # root. Order here drives the combo box order in the Config tab.
    CHANNEL_LIVE = "LIVE"
    CHANNEL_PTU = "PTU"
    CHANNEL_EPTU = "EPTU"
    CHANNEL_HOTFIX = "HOTFIX"
    CHANNEL_TECH_PREVIEW = "TECH-PREVIEW"
    AVAILABLE_CHANNELS = (
        CHANNEL_LIVE,
        CHANNEL_PTU,
        CHANNEL_EPTU,
        CHANNEL_HOTFIX,
        CHANNEL_TECH_PREVIEW,
    )
    DEFAULT_CHANNEL = CHANNEL_LIVE

    # Enhancements cache filenames (written by generate_enhancements_ini.py into cache dir)
    ENHANCEMENTS_FILES = {
        "ship_descs":          "ships_desc_enhancements.ini",
        "component_descs":     "components_desc_enhancements.ini",
        "ship_weapon_descs":   "ship_weapons_desc_enhancements.ini",
        "fps_weapon_descs":    "fps_weapons_desc_enhancements.ini",
        "mission_rewards":     "mission_rewards_enhancements.ini",
        "commodity_crafting":  "commodity_crafting_enhancements.ini",
        "journal":            "journal_enhancements.ini",
        "missile_enhancements": "missile_enhancements.ini",
    }

    # User-facing category labels — match the filter categories on the main page
    ENHANCEMENT_LABELS = {
        "ships":       "Ships",
        "ship_items":  "Ship Items",
        "gear":        "Gear",
        "missions":    "Missions",
        "commodities": "Commodities",
        "journal":     "Journal",
    }

    # Maps each checkbox key to the enhancement file keys it controls
    ENHANCEMENT_CATEGORY_FILES = {
        "ships":       ["ship_descs"],
        "ship_items":  ["component_descs", "ship_weapon_descs", "missile_enhancements"],
        "gear":        ["fps_weapon_descs"],
        "missions":    ["mission_rewards"],
        "commodities": ["commodity_crafting"],
        "journal":     ["journal"],
    }

    # Settings keys - Legacy (kept for migration)
    BASE_GLOBAL_PATH = "base_global_path"
    VEHICLES_PATH = "vehicles_path"
    LAST_OVERRIDES_PATH = "last_overrides_path"
    GAME_INSTALL_PATH = "game_install_path"
    AUTO_WRITE_ENABLED = "auto_write_enabled"
    WINDOW_GEOMETRY = "window_geometry"
    WINDOW_STATE = "window_state"
    # Explicit override for the user-data directory. When set, takes
    # precedence over the Documents\Smart Citizen\ default. Users who have
    # Documents redirected to OneDrive can point this at a local path to
    # avoid slow extraction / rmtree races on OneDrive-synced folders.
    USER_DATA_DIR = "user_data_dir"
    # Compatibility alias for older docs/manual registry edits. The installer
    # and current app write ``user_data_dir``; read both so either spelling works.
    USER_DATA_DIR_ALIASES = ("UserDataDir",)
    # Explicit override for the DataForge XML cache root. Independent of
    # USER_DATA_DIR so a user can keep user.ini / source cache / backups in
    # Documents (or wherever) while sending the ~1.4 GB DataForge tree to a
    # fast local SSD (or to a folder excluded from OneDrive / Defender).
    # Pre-1.4.1 the cache was hard-pinned to %LOCALAPPDATA% with no way to
    # move it; this key is the configurable replacement.
    CACHE_DIR = "cache_dir"
    # Set by the Config tab when the user accepts a cache-path change with
    # "delete old cache after re-extraction". The path is removed after the
    # next successful P4K extraction so the 1.4 GB orphan doesn't linger.
    PENDING_CACHE_CLEANUP = "pending_cache_cleanup"
    # When True (default) the components Tag Builder annotation is woven
    # into the POTENTIAL BLUEPRINTS lists inside mission descriptions
    # (e.g. "[MIL-S1-A] Norfield"). Users who want clean mission body
    # text can turn it off here without affecting the inline tags on
    # the actual component names elsewhere. Issue #31 follow-up.
    TAG_ANNOTATE_MISSION_DESCS = "tag_builder/annotate_mission_descs"

    # Settings keys - Data sources (new)
    # Prefix: data_sources/{source_name}/
    DATA_SOURCES_PREFIX = "data_sources"
    MERGE_HIERARCHY = "merge_hierarchy"
    SOURCE_AUTO_UPDATE_PREFIX = "source_auto_update"

    # Available data sources
    SOURCE_GLOBAL = "global"
    SOURCE_CONTRACTS = "contracts"
    SOURCE_COMPONENTS = "components"
    SOURCE_SHIPS = "ships"
    SOURCE_COMMODITIES = "commodities"
    SOURCE_GEAR = "gear"
    SOURCE_USER = "user"
    AVAILABLE_SOURCES = [SOURCE_GLOBAL, SOURCE_USER]

    # Backend override hook — kept None by default so production stays on
    # QSettings (registry mode). PR-B in the standalone-build series sets
    # this to a JsonSettings instance during portable-mode startup. Tests
    # can also assign it to swap in a JsonSettings backed by a tmp_path
    # for hermetic settings testing without touching the real registry.
    _backend: object | None = None

    @staticmethod
    def settings():
        """Return the active settings backend.

        Defaults to a per-call QSettings(ORG_NAME, APP_NAME) — same
        behavior as before. When `_backend` is set (PR-B portable mode
        or test injection), returns that backend instead. Both paths
        expose the same minimal API: ``value(key, default, type=...)``,
        ``setValue(key, value)``, ``remove(key)``, ``sync()``.
        """
        if AppSettings._backend is not None:
            return AppSettings._backend
        return QSettings(AppSettings.ORG_NAME, AppSettings.APP_NAME)

    @staticmethod
    def get_enhancements_enabled() -> bool:
        """Check whether enhancements are enabled (default: True)."""
        return AppSettings.settings().value(AppSettings.ENHANCEMENTS_ENABLED, True, type=bool)

    @staticmethod
    def set_enhancements_enabled(enabled: bool) -> None:
        """Enable or disable enhancements."""
        AppSettings.settings().setValue(AppSettings.ENHANCEMENTS_ENABLED, enabled)

    @staticmethod
    def get_include_new_lines() -> bool:
        """Check whether discovered items (status 'New') are included in apply output."""
        return AppSettings.settings().value(AppSettings.INCLUDE_NEW_LINES, False, type=bool)

    @staticmethod
    def set_include_new_lines(enabled: bool) -> None:
        """Include or exclude discovered items from apply output."""
        AppSettings.settings().setValue(AppSettings.INCLUDE_NEW_LINES, enabled)

    @staticmethod
    def get_enhancement_category_enabled(key: str) -> bool:
        """Check if a specific enhancement category is enabled (default: True)."""
        return AppSettings.settings().value(
            f"enhancements/categories/{key}/enabled", True, type=bool)

    @staticmethod
    def set_enhancement_category_enabled(key: str, enabled: bool) -> None:
        """Enable or disable a specific enhancement category."""
        AppSettings.settings().setValue(
            f"enhancements/categories/{key}/enabled", enabled)

    @staticmethod
    def get_enabled_enhancement_categories() -> set[str]:
        """Return the set of enabled enhancement file keys (expanding grouped categories)."""
        result = set()
        for checkbox_key, file_keys in AppSettings.ENHANCEMENT_CATEGORY_FILES.items():
            if AppSettings.get_enhancement_category_enabled(checkbox_key):
                result.update(file_keys)
        return result

    @staticmethod
    def get_theme() -> str:
        """Get UI theme name ('light' or 'dark')."""
        from src.gui.theme import DEFAULT_THEME, AVAILABLE_THEMES
        value = AppSettings.settings().value(AppSettings.THEME, DEFAULT_THEME)
        return value if value in AVAILABLE_THEMES else DEFAULT_THEME

    @staticmethod
    def set_theme(theme: str) -> None:
        """Persist UI theme name."""
        AppSettings.settings().setValue(AppSettings.THEME, theme)
        AppSettings.settings().sync()

    @staticmethod
    def get_favorite_prefix() -> str:
        """Get the character prepended to favorited ship names (default '*')."""
        return AppSettings.settings().value(AppSettings.FAVORITE_PREFIX, "*")

    @staticmethod
    def set_favorite_prefix(prefix: str) -> None:
        """Set the character prepended to favorited ship names."""
        AppSettings.settings().setValue(AppSettings.FAVORITE_PREFIX, prefix)

    @staticmethod
    def get_rep_xp_label() -> str:
        """Label shown on single-tier mission XP lines (default 'Rep')."""
        return AppSettings.settings().value(AppSettings.REP_XP_LABEL, AppSettings.DEFAULT_REP_XP_LABEL)

    @staticmethod
    def set_rep_xp_label(label: str) -> None:
        AppSettings.settings().setValue(AppSettings.REP_XP_LABEL, label)

    @staticmethod
    def get_mission_headers() -> dict[str, str]:
        s = AppSettings.settings()
        d = AppSettings.MISSION_HEADER_DEFAULTS
        return {
            "details":        s.value(AppSettings.MISSION_HEADER_DETAILS, d["details"]),
            "blueprints":     s.value(AppSettings.MISSION_HEADER_BLUEPRINTS, d["blueprints"]),
            "items":          s.value(AppSettings.MISSION_HEADER_ITEMS, d["items"]),
            "blueprint_data": s.value(AppSettings.MISSION_HEADER_BLUEPRINT_DATA, d["blueprint_data"]),
        }

    @staticmethod
    def set_mission_header(key: str, value: str) -> None:
        key_map = {
            "details": AppSettings.MISSION_HEADER_DETAILS,
            "blueprints": AppSettings.MISSION_HEADER_BLUEPRINTS,
            "items": AppSettings.MISSION_HEADER_ITEMS,
            "blueprint_data": AppSettings.MISSION_HEADER_BLUEPRINT_DATA,
        }
        if key in key_map:
            AppSettings.settings().setValue(key_map[key], value)

    @staticmethod
    def get_mission_header_em_tag() -> str:
        return AppSettings.settings().value(AppSettings.MISSION_HEADER_EM_TAG, AppSettings.DEFAULT_MISSION_HEADER_EM_TAG)

    @staticmethod
    def set_mission_header_em_tag(tag: str) -> None:
        AppSettings.settings().setValue(AppSettings.MISSION_HEADER_EM_TAG, tag)

    @staticmethod
    def get_tag_config(category: str):
        """Return the user's TagConfig for *category*, or the default if absent/bad.

        Stored as one JSON blob per category under tag_builder/{category}/config
        so the slash-key contract honored by JsonSettings (see test_json_settings)
        doesn't have to round-trip a nested dict.
        """
        # Deferred import — tag_builder lives in src.utils too, and importing it
        # at module load time would create a circular import for callers that
        # do `from src.utils.settings import AppSettings` very early.
        from src.utils.tag_builder import TagConfig, default_config
        raw = AppSettings.settings().value(f"tag_builder/{category}/config", "", type=str)
        if not raw:
            return default_config(category)
        try:
            cfg = TagConfig.from_json(raw)
        except (ValueError, TypeError) as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Stored tag config for '{category}' is malformed ({e}); falling back to defaults."
            )
            return default_config(category)
        AppSettings._migrate_tag_config_mapping(category, cfg)
        AppSettings._backfill_new_elements(category, cfg)
        # 1.5.0: commodities gained a second flag (Collection). A stored
        # single-element config used separator "none", which would mash the
        # two flags together as "[CFCollection]". Pipe is the intended joiner,
        # and the separator was meaningless for the old single-element tag, so
        # upgrading it is safe (#97).
        if category == "commodities" and cfg.separator == "none":
            cfg.separator = "pipe"
        return cfg

    @staticmethod
    def _migrate_tag_config_mapping(category: str, cfg) -> None:
        """Upgrade the mapping dict in *cfg* to the current key vocabulary.

        Early ship-weapon configs stored damage entries under the compact
        generator labels ("Phys", "Distort", "Bio") and a brief experiment
        also kept the long-form duplicates ("Physical", "Distortion",
        "Biochemical") side-by-side. The current mapping keys on the long
        form so users see real English in the variant editor. Rename in
        place when an old key is present without its new counterpart;
        drop the old key if a new-key row already exists.
        """
        if category != "ship_weapons":
            return
        renames = {
            "Phys":    "Physical",
            "Distort": "Distortion",
            "Bio":     "Biochemical",
        }
        mapping = cfg.class_mapping
        for old, new in renames.items():
            if old not in mapping:
                continue
            if new in mapping:
                # Both present — keep the user-friendly new entry and drop
                # the orphan old one.
                del mapping[old]
            else:
                mapping[new] = mapping.pop(old)

    @staticmethod
    def _backfill_new_elements(category: str, cfg) -> None:
        """Append element kinds added in a newer version that the stored
        config doesn't have yet (e.g. ``type`` added to components in 1.4.2).
        New elements are appended disabled so existing output is unchanged."""
        from src.utils.tag_builder import (
            CATEGORY_ELEMENT_KINDS, DEFAULT_TAG_CONFIGS, DEFAULT_KIND_MAPPINGS,
            ElementSpec,
        )
        expected_kinds = CATEGORY_ELEMENT_KINDS.get(category, ())
        existing_kinds = {e.kind for e in cfg.elements}
        defaults = DEFAULT_TAG_CONFIGS.get(category)
        for kind in expected_kinds:
            if kind not in existing_kinds:
                default_spec = None
                if defaults:
                    default_spec = next((e for e in defaults.elements if e.kind == kind), None)
                cfg.elements.append(ElementSpec(
                    kind=kind,
                    enabled=default_spec.enabled if default_spec else False,
                    style=default_spec.style if default_spec else "",
                ))
            kind_mapping = DEFAULT_KIND_MAPPINGS.get(kind, {})
            for key, val in kind_mapping.items():
                if key not in cfg.class_mapping:
                    cfg.class_mapping[key] = val

    @staticmethod
    def set_tag_config(category: str, config) -> None:
        """Persist *config* (a TagConfig) for *category* as a JSON blob."""
        AppSettings.settings().setValue(
            f"tag_builder/{category}/config", config.to_json()
        )

    @staticmethod
    def get_all_tag_configs() -> dict:
        """Return TagConfigs for every supported category (defaults fill in)."""
        from src.utils.tag_builder import CATEGORIES
        return {cat: AppSettings.get_tag_config(cat) for cat in CATEGORIES}

    @staticmethod
    def get_tag_annotate_mission_descs() -> bool:
        """Whether component tags are woven into POTENTIAL BLUEPRINTS lists
        inside mission descriptions. Default True (annotation enabled),
        preserving the v1.4.0 behavior. Issue #31 follow-up — when False,
        the BP-pool resolver skips the tag weave entirely and mission
        bodies render with bare names."""
        raw = AppSettings.settings().value(
            AppSettings.TAG_ANNOTATE_MISSION_DESCS, True, type=bool
        )
        # QSettings on registry mode round-trips True via the bool type
        # arg; JsonSettings stores the raw value and we may get None
        # for "never set", which falls through to True by intent.
        if raw is None:
            return True
        return bool(raw)

    @staticmethod
    def set_tag_annotate_mission_descs(enabled: bool) -> None:
        """Persist the mission-desc annotation toggle."""
        AppSettings.settings().setValue(
            AppSettings.TAG_ANNOTATE_MISSION_DESCS, bool(enabled)
        )
        AppSettings.settings().sync()

    @staticmethod
    def get_tutorial_completed_version() -> str:
        """App version string that last completed the guided tour, or '' if never."""
        return AppSettings.settings().value(AppSettings.TUTORIAL_COMPLETED_VERSION, "")

    @staticmethod
    def set_tutorial_completed_version(version: str) -> None:
        """Record that the guided tour was completed for *version*."""
        AppSettings.settings().setValue(AppSettings.TUTORIAL_COMPLETED_VERSION, version)
        AppSettings.settings().sync()

    @staticmethod
    def get_tutorial_disabled() -> bool:
        """When True, the tutorial never auto-launches (Config tab opt-out)."""
        return AppSettings.settings().value(AppSettings.TUTORIAL_DISABLED, False, type=bool)

    @staticmethod
    def set_tutorial_disabled(disabled: bool) -> None:
        AppSettings.settings().setValue(AppSettings.TUTORIAL_DISABLED, bool(disabled))
        AppSettings.settings().sync()

    @staticmethod
    def get_last_update_check_epoch() -> int:
        """Unix epoch of the last successful app-update check (0 if never)."""
        raw = AppSettings.settings().value(AppSettings.LAST_UPDATE_CHECK_EPOCH, 0)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def set_last_update_check_epoch(epoch: int) -> None:
        """Persist the timestamp of the most recent app-update check."""
        AppSettings.settings().setValue(AppSettings.LAST_UPDATE_CHECK_EPOCH, int(epoch))
        AppSettings.settings().sync()

    @staticmethod
    def get_base_global_path() -> str:
        """Get legacy base global path (for backward compatibility).

        This is deprecated. Use get_source_path(SOURCE_GLOBAL) instead.
        """
        return AppSettings.settings().value(AppSettings.BASE_GLOBAL_PATH, "")

    @staticmethod
    def set_base_global_path(path: str) -> None:
        """Set legacy base global path (for backward compatibility).

        This is deprecated. Use set_source_path(SOURCE_GLOBAL, path) instead.
        """
        AppSettings.settings().setValue(AppSettings.BASE_GLOBAL_PATH, path)

    @staticmethod
    def get_vehicles_path() -> str:
        """Get path to vehicles.ini."""
        return AppSettings.settings().value(AppSettings.VEHICLES_PATH, "")

    @staticmethod
    def set_vehicles_path(path: str) -> None:
        """Set path to vehicles.ini."""
        AppSettings.settings().setValue(AppSettings.VEHICLES_PATH, path)

    @staticmethod
    def get_last_overrides_path() -> str:
        """Get last directory used for overrides."""
        return AppSettings.settings().value(AppSettings.LAST_OVERRIDES_PATH, "")

    @staticmethod
    def set_last_overrides_path(path: str) -> None:
        """Set last directory used for overrides."""
        AppSettings.settings().setValue(AppSettings.LAST_OVERRIDES_PATH, path)

    @staticmethod
    def get_game_install_path() -> str:
        """Return the install path of the **active channel**.

        Post 0.9.3 this resolves as ``{sc_install_root}\\{active_channel}``.
        Kept under the old name so existing callers (which assume "the"
        game install path means the active channel) still work; there's no
        semantic change for pre-channel-aware code paths that always
        operated on LIVE.

        Falls back to the legacy ``GAME_INSTALL_PATH`` stored value, and
        then to the installer-written registry key, for users whose
        settings haven't been through :meth:`migrate_game_path_to_channel_layout`
        yet (should be a vanishingly small window — the migrator runs at
        ``main()`` startup).
        """
        root = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")
        if root:
            return str(Path(root) / AppSettings.get_active_channel())

        # Legacy path stored under the old key.
        saved = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
        if saved:
            return saved

        # Installer-written registry key (older flow).
        try:
            reg_path = r'Software\Osiris DevWorks\SC Localization Editor'
            registry_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path)
            sc_directory, _ = winreg.QueryValueEx(registry_key, 'sc_directory')
            winreg.CloseKey(registry_key)
            if sc_directory:
                AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, sc_directory)
                return sc_directory
        except (WindowsError, OSError):
            pass

        for candidate in [
            r"C:\Program Files\Roberts Space Industries\StarCitizen\LIVE",
            r"C:\Program Files (x86)\Roberts Space Industries\StarCitizen\LIVE",
        ]:
            if Path(candidate).exists():
                return candidate

        return ""

    @staticmethod
    def get_game_version() -> str:
        """Get Star Citizen game version from build_manifest.id.

        Returns:
            Version string (e.g., "4.7.176.58286") or empty string if not found/invalid
        """
        import json
        game_path = AppSettings.get_game_install_path()
        if not game_path:
            return ""

        manifest_path = Path(game_path) / "build_manifest.id"
        if not manifest_path.exists():
            return ""

        try:
            with open(manifest_path, 'r') as f:
                data = json.load(f)
                version = data.get("Data", {}).get("Version", "")
                return version
        except Exception as e:
            logger.debug(f"Could not read game version from {manifest_path}: {e}")
            return ""

    @staticmethod
    def set_game_install_path(path: str) -> None:
        """Set Star Citizen install path."""
        AppSettings.settings().setValue(AppSettings.GAME_INSTALL_PATH, path)

    @staticmethod
    def get_auto_write_enabled() -> bool:
        """Get auto-write to game enabled flag."""
        return AppSettings.settings().value(AppSettings.AUTO_WRITE_ENABLED, False, type=bool)

    @staticmethod
    def set_auto_write_enabled(enabled: bool) -> None:
        """Set auto-write to game enabled flag."""
        AppSettings.settings().setValue(AppSettings.AUTO_WRITE_ENABLED, enabled)

    @staticmethod
    def get_window_geometry() -> bytes:
        """Get saved window geometry."""
        return AppSettings.settings().value(AppSettings.WINDOW_GEOMETRY, b"")

    @staticmethod
    def set_window_geometry(geometry: bytes) -> None:
        """Save window geometry."""
        AppSettings.settings().setValue(AppSettings.WINDOW_GEOMETRY, geometry)

    @staticmethod
    def get_window_state() -> bytes:
        """Get saved window state."""
        return AppSettings.settings().value(AppSettings.WINDOW_STATE, b"")

    @staticmethod
    def set_window_state(state: bytes) -> None:
        """Save window state."""
        AppSettings.settings().setValue(AppSettings.WINDOW_STATE, state)

    @staticmethod
    def get_source_path(source_name: str) -> str:
        """Get path/URL for a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER

        Returns:
            Path or URL string, empty string if not set
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        return AppSettings.settings().value(key, "")

    @staticmethod
    def set_source_path(source_name: str, path: str) -> None:
        """Set path/URL for a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER
            path: File path or URL
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        AppSettings.settings().setValue(key, path)

    @staticmethod
    def is_source_enabled(source_name: str) -> bool:
        """Check if a data source is enabled.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER

        Returns:
            True if enabled, False otherwise. Defaults to True for Global and User, False for others.
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        # Default: Global and User always enabled, others disabled
        default = source_name in [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        return AppSettings.settings().value(key, default, type=bool)

    @staticmethod
    def set_source_enabled(source_name: str, enabled: bool) -> None:
        """Enable or disable a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS, SOURCE_USER
            enabled: True to enable, False to disable
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        AppSettings.settings().setValue(key, enabled)

    @staticmethod
    def get_merge_hierarchy() -> list:
        """Get the merge hierarchy (ordered list of source names).

        Returns:
            List of source names in merge order, e.g. ["global", "user"]
        """
        default = [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        value = AppSettings.settings().value(AppSettings.MERGE_HIERARCHY, default)
        # Handle QVariant/list conversion
        if isinstance(value, str):
            # If stored as comma-separated string, split it
            return value.split(",") if value else default
        return value if value else default

    @staticmethod
    def set_merge_hierarchy(hierarchy: list) -> None:
        """Set the merge hierarchy (ordered list of source names).

        Args:
            hierarchy: List of source names in merge order
        """
        AppSettings.settings().setValue(AppSettings.MERGE_HIERARCHY, hierarchy)

    @staticmethod
    def get_source_auto_update(source_name: str) -> bool:
        """Check if auto-update is enabled for a source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS
            (SOURCE_USER does not support auto-update)

        Returns:
            True if auto-update enabled, False otherwise. Defaults to True.
        """
        if source_name == AppSettings.SOURCE_USER:
            return False  # User source never auto-updates
        key = f"{AppSettings.SOURCE_AUTO_UPDATE_PREFIX}/{source_name}"
        return AppSettings.settings().value(key, True, type=bool)

    @staticmethod
    def set_source_auto_update(source_name: str, enabled: bool) -> None:
        """Enable or disable auto-update for a source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_CONTRACTS, SOURCE_COMPONENTS, SOURCE_SHIPS
            enabled: True to auto-update, False to disable
        """
        if source_name == AppSettings.SOURCE_USER:
            return  # Cannot change auto-update for User source
        key = f"{AppSettings.SOURCE_AUTO_UPDATE_PREFIX}/{source_name}"
        AppSettings.settings().setValue(key, enabled)

    # One-shot marker for migrate_remove_retired_url_sources(). Versioned
    # so the migration can pick up new retired source names in later
    # releases without being blocked by an earlier run's marker. Always bump
    # the version when expanding RETIRED_URL_SOURCE_NAMES — the prior marker
    # stays in the registry but is ignored.
    #
    # v3 (1.3.1): re-runs to prune orphan hierarchy entries that v2 left
    # behind. v2 correctly handled URL-backed and orphan-no-path entries
    # in the same pass, but users who had a stored local path at v2-run
    # time (later cleared, leaving an orphan hierarchy slot with no path)
    # didn't get re-cleaned. v3 re-runs the (idempotent) prune so those
    # tail-end orphans surface and get removed. Local-path overrides are
    # still preserved — the URL-vs-local guard inside the migrator is
    # unchanged.
    RETIRED_URL_SOURCES_PRUNED = "_retired_url_sources_pruned_v3"

    # Sources that were retired in 0.7.0 when the app moved to local Data.p4k
    # extraction + locally-generated *_enhancements.ini files. New installs
    # don't get them; existing installs with these sources still in their
    # registry get them pruned by migrate_remove_retired_url_sources().
    RETIRED_URL_SOURCE_NAMES = (
        SOURCE_CONTRACTS,
        SOURCE_COMPONENTS,
        SOURCE_SHIPS,
        SOURCE_COMMODITIES,
        SOURCE_GEAR,
    )

    @staticmethod
    def migrate_legacy_settings() -> None:
        """Initialize default sources for a fresh install.

        Despite the name, this is the "set defaults if no settings exist"
        function — it short-circuits if the global source has already been
        registered. It seeds only the two sources the app actually uses:

          * ``global`` — locally-cached ``base.ini`` from Data.p4k extraction
          * ``user``   — per-channel ``user.ini`` (created lazily on first edit)

        The ``enhancements`` source is dynamically injected by
        :func:`load_sources_from_settings` based on which enhancement
        categories the user has enabled — it doesn't need a registry entry.

        The 0.x defaults registered four extra URL-based sources
        (contracts/components/ships/commodities) pointing at a ``data/``
        folder that was retired in 0.7.0. Those are no longer registered for
        new installs, and existing installs are cleaned up by
        :func:`migrate_remove_retired_url_sources`.
        """
        settings = AppSettings.settings()

        # Idempotence: check the global source registration as the marker.
        # (Pre-1.0 the marker was the contracts source — that key may still
        # exist on upgraders but the dedicated retired-source migrator below
        # will remove it on the same launch.)
        if settings.value(f"{AppSettings.DATA_SOURCES_PREFIX}/{AppSettings.SOURCE_GLOBAL}/path"):
            return

        # Global: locally-cached base.ini, populated by P4K extraction.
        global_local_path = str(AppSettings.get_cache_dir() / 'base.ini')
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, global_local_path)
        AppSettings.set_source_enabled(AppSettings.SOURCE_GLOBAL, True)
        AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)

        # User: per-channel user.ini.
        user_path = str(AppSettings.get_user_ini_path())
        AppSettings.set_source_path(AppSettings.SOURCE_USER, user_path)

        # Default hierarchy: global → user. The enhancements source is
        # auto-inserted between them at load time when its files exist.
        AppSettings.set_merge_hierarchy(
            [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        )

    @staticmethod
    def migrate_remove_retired_url_sources() -> bool:
        """One-shot prune of the four URL-based sources retired in 0.7.0.

        Pre-1.0 ``migrate_legacy_settings()`` registered ``contracts``,
        ``components``, ``ships``, and ``commodities`` pointing at a
        ``data/<name>.ini`` folder in the GitHub repo. That folder was
        retired in 0.7.0 when the app switched to local Data.p4k extraction
        + locally-generated ``*_enhancements.ini``, so those URLs have been
        404-ing silently for ~10 versions and produce zero-key rows in the
        Merge Preview.

        For each retired source name:
          * if its registered path is a URL (the original default state),
            delete the source's registry entries and remove it from the
            merge hierarchy;
          * if its path is a local file (rare — user manually re-pointed
            it at their own INI), leave it alone.

        Marker-gated via :data:`RETIRED_URL_SOURCES_PRUNED` so this runs
        exactly once per user.

        Returns:
            True if any source was actually removed, False if the migration
            had already run or there was nothing to clean up.
        """
        settings = AppSettings.settings()
        if settings.value(AppSettings.RETIRED_URL_SOURCES_PRUNED, False, type=bool):
            return False

        # First pass: figure out which retired sources to prune. A source is
        # eligible if EITHER its registry path is a URL (the original default
        # state) OR it's in the merge hierarchy with no path stored at all
        # (orphan hierarchy entry — happens when an even earlier version
        # added the name to the hierarchy without a per-source registration).
        # Sources with a local-file path are preserved (rare user override).
        prior_hierarchy = AppSettings.get_merge_hierarchy()
        in_hierarchy = set(prior_hierarchy)
        prune: list[str] = []
        for source_name in AppSettings.RETIRED_URL_SOURCE_NAMES:
            path = AppSettings.get_source_path(source_name)
            if path and not (path.startswith('http://') or path.startswith('https://')):
                logger.info(
                    f"Skipping retired-source prune for {source_name}: "
                    f"path is local ({path}), not a URL — preserving user override"
                )
                continue
            if not path and source_name not in in_hierarchy:
                # No path AND not in hierarchy — nothing to prune for this one.
                continue
            prune.append(source_name)

        for source_name in prune:
            # Nuke every key under data_sources/<name>/... (no-op if no path
            # was registered, which is fine — Qt's remove() on a missing key
            # is idempotent).
            settings.remove(f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}")

        if prune:
            new_hierarchy = [s for s in prior_hierarchy if s not in prune]
            if new_hierarchy != prior_hierarchy:
                AppSettings.set_merge_hierarchy(new_hierarchy)
            logger.info(
                f"Pruned retired URL-based sources: {prune} — "
                f"these defunct defaults from pre-0.7.0 produce no data and "
                f"have been removed from the merge hierarchy"
            )

        settings.setValue(AppSettings.RETIRED_URL_SOURCES_PRUNED, True)
        return bool(prune)

    @staticmethod
    def migrate_global_to_p4k_local() -> bool:
        """Migrate global source from any remote URL to local cached base.ini (v0.6.0+).

        For existing users whose Global source still points to MrKraken, BeltaKoda,
        or any other remote URL: switch to local cache path and disable auto-update
        so the file is managed by P4K extraction instead of remote download.

        Returns:
            True if migration was performed, False if already using local path.
        """
        current_path = AppSettings.get_source_path(AppSettings.SOURCE_GLOBAL)
        if current_path.startswith('http'):
            local_path = str(AppSettings.get_cache_dir() / 'base.ini')
            AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, local_path)
            AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)
            logger.info("Migrated global source from remote URL to local P4K cache path")
            return True
        return False





    @staticmethod
    def _resolve_docs_base() -> Path:
        """Resolve the real Documents root (honors OneDrive redirection)."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            )
            docs_path = Path(winreg.QueryValueEx(key, "Personal")[0])
            winreg.CloseKey(key)
        except (WindowsError, OSError):
            docs_path = Path.home() / "Documents"
        return docs_path

    # ── Registry appname migration (0.9.0 rebrand) ──────────────────────────
    # Rebrand moved the product name from "SC Localization Editor" to
    # "Smart Citizen" in 0.9.0. The Documents folder got renamed back then
    # (see migrate_docs_folder_rename). The registry node was left alone
    # to preserve existing users' settings, which meant fresh-eyes readers
    # kept seeing the old name under HKCU. The helpers below perform a
    # one-shot copy from the legacy node to the new node, then delete the
    # old subtree. A marker value (_MIGRATION_MARKER) short-circuits
    # subsequent runs so this is cheap on every startup.

    _MIGRATION_MARKER = "_migrated_from_legacy_appname"

    @staticmethod
    def migrate_registry_appname() -> None:
        r"""Copy HKCU\Software\<ORG>\SC Localization Editor → HKCU\Software\<ORG>\Smart Citizen.

        Must run **before** any ``AppSettings.settings()`` call — QSettings
        under the new APP_NAME would otherwise read from an empty node and
        silently lose every saved preference (themes, paths, favorites,
        window geometry, the USER_DATA_DIR override, etc.).

        Idempotent: a marker value written under the new node on first
        success prevents re-migration on every startup. Fresh installs
        (no legacy node present) stamp the marker directly so the check
        stays cheap.
        """
        org = AppSettings.ORG_NAME
        old_path = rf"SOFTWARE\{org}\{AppSettings._LEGACY_APP_NAME}"
        new_path = rf"SOFTWARE\{org}\{AppSettings.APP_NAME}"

        # Fast-path: marker already set → nothing to do.
        if AppSettings._reg_has_marker(new_path, AppSettings._MIGRATION_MARKER):
            return

        # No legacy node present — this is a fresh install (or an already-
        # cleaned-up migration where the marker was somehow lost). Stamp
        # the marker so future runs short-circuit.
        if not AppSettings._reg_key_exists(old_path):
            AppSettings._reg_write_marker(new_path, AppSettings._MIGRATION_MARKER)
            return

        logger.info(
            f"Migrating registry settings "
            f"HKCU\\{old_path}  →  HKCU\\{new_path}"
        )
        try:
            AppSettings._reg_copy_tree(old_path, new_path)
            AppSettings._reg_write_marker(new_path, AppSettings._MIGRATION_MARKER)
            AppSettings._reg_delete_tree(old_path)
            logger.info("Registry migration complete — legacy node removed")
        except OSError as e:
            # Leave the marker unset so we retry next launch. Log loudly
            # so any partial migration is visible in the Log tab.
            logger.error(f"Registry migration failed: {e}", exc_info=True)

    @staticmethod
    def _reg_key_exists(path: str) -> bool:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
            winreg.CloseKey(k)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _reg_has_marker(path: str, marker: str) -> bool:
        try:
            k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ)
        except FileNotFoundError:
            return False
        try:
            winreg.QueryValueEx(k, marker)
            return True
        except FileNotFoundError:
            return False
        finally:
            winreg.CloseKey(k)

    @staticmethod
    def _reg_write_marker(path: str, marker: str) -> None:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, path)
        try:
            winreg.SetValueEx(k, marker, 0, winreg.REG_SZ, "1")
        finally:
            winreg.CloseKey(k)

    @staticmethod
    def _reg_copy_tree(src_path: str, dst_path: str) -> None:
        """Recursive copy of every value and subkey from src to dst under HKCU.

        Preserves value types (REG_SZ / REG_DWORD / REG_BINARY / REG_MULTI_SZ
        / REG_EXPAND_SZ) by passing EnumValue's returned type directly to
        SetValueEx. Creates dst and its subtree as needed.
        """
        src = winreg.OpenKey(winreg.HKEY_CURRENT_USER, src_path, 0, winreg.KEY_READ)
        dst = winreg.CreateKey(winreg.HKEY_CURRENT_USER, dst_path)
        try:
            # Values at this level
            i = 0
            while True:
                try:
                    name, data, vtype = winreg.EnumValue(src, i)
                except OSError:
                    break
                # Skip the marker if it happens to exist on the source side
                # (shouldn't, but defensive against manual registry edits).
                if name != AppSettings._MIGRATION_MARKER:
                    winreg.SetValueEx(dst, name, 0, vtype, data)
                i += 1
            # Recurse into subkeys
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(src, i)
                except OSError:
                    break
                AppSettings._reg_copy_tree(
                    f"{src_path}\\{sub}", f"{dst_path}\\{sub}"
                )
                i += 1
        finally:
            winreg.CloseKey(src)
            winreg.CloseKey(dst)

    @staticmethod
    def _reg_delete_tree(path: str) -> None:
        """Depth-first delete of an HKCU subtree (winreg.DeleteKey refuses
        to remove a key that still has children, so we strip leaves first)."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS
            )
        except FileNotFoundError:
            return
        try:
            while True:
                try:
                    sub = winreg.EnumKey(key, 0)
                except OSError:
                    break
                AppSettings._reg_delete_tree(f"{path}\\{sub}")
        finally:
            winreg.CloseKey(key)
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except FileNotFoundError:
            pass

    @staticmethod
    def migrate_docs_folder_rename() -> None:
        r"""Rename legacy Documents\SC Localization Editor\ → Documents\Smart Citizen\.

        Safe to call on every startup — only acts when the old folder exists
        and the new one does not. The installer handles this on upgrade; this
        path covers dev runs and anyone who bypassed the installer.
        """
        docs = AppSettings._resolve_docs_base()
        old_dir = docs / "SC Localization Editor"
        new_dir = docs / "Smart Citizen"
        if old_dir.exists() and not new_dir.exists():
            try:
                old_dir.rename(new_dir)
                logger.info(f"Renamed data folder: {old_dir} → {new_dir}")
            except OSError as e:
                logger.warning(f"Could not rename data folder {old_dir}: {e}")

    @staticmethod
    def migrate_game_path_to_channel_layout() -> None:
        r"""One-shot migration to the 0.9.3 channel-aware layout.

        Two orthogonal bits of migration happen here; both are idempotent
        and short-circuited by a single marker (:data:`CHANNEL_LAYOUT_MIGRATED`)
        so every subsequent launch no-ops cheaply.

        **Registry side:** if ``GAME_INSTALL_PATH`` is set but ``SC_INSTALL_ROOT``
        isn't, split the stored path on a trailing ``\{CHANNEL}`` suffix and
        record the parent as ``SC_INSTALL_ROOT``. ``ACTIVE_CHANNEL`` is set
        to the stripped channel name (``LIVE`` when the stored path has no
        recognizable channel suffix — matches pre-0.9.3 behavior).

        **Filesystem side:** if ``Documents\Smart Citizen\`` contains the
        old flat layout (``base.ini`` / ``cache\`` / ``backups\`` / ``user.ini``)
        and no ``LIVE\`` (or other channel) subfolder exists, move those
        entries into a new ``LIVE\`` subfolder so every path helper starts
        resolving channel-scoped. Skips anything that looks like a channel
        directory, the migration marker, and the registry mirror files,
        leaving unrelated files untouched.

        Failures during the filesystem move are logged but not raised — the
        app degrades to "user re-runs Extract" at worst rather than
        crashing at startup.
        """
        settings = AppSettings.settings()
        if settings.value(AppSettings.CHANNEL_LAYOUT_MIGRATED, False, type=bool):
            return

        # --- Registry: split GAME_INSTALL_PATH into SC_INSTALL_ROOT + ACTIVE_CHANNEL
        if not settings.value(AppSettings.SC_INSTALL_ROOT, ""):
            legacy = settings.value(AppSettings.GAME_INSTALL_PATH, "")
            if legacy:
                legacy_path = Path(legacy)
                tail = legacy_path.name.upper()
                channels_upper = {c.upper(): c for c in AppSettings.AVAILABLE_CHANNELS}
                if tail in channels_upper:
                    settings.setValue(AppSettings.SC_INSTALL_ROOT, str(legacy_path.parent))
                    settings.setValue(AppSettings.ACTIVE_CHANNEL, channels_upper[tail])
                    logger.info(
                        f"Migrated GAME_INSTALL_PATH {legacy!r} → "
                        f"SC_INSTALL_ROOT={legacy_path.parent}, "
                        f"ACTIVE_CHANNEL={channels_upper[tail]}"
                    )
                else:
                    settings.setValue(AppSettings.SC_INSTALL_ROOT, legacy)
                    settings.setValue(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
                    logger.info(
                        f"Migrated GAME_INSTALL_PATH {legacy!r} (no channel suffix) → "
                        f"SC_INSTALL_ROOT={legacy}, ACTIVE_CHANNEL={AppSettings.DEFAULT_CHANNEL}"
                    )

        if not settings.value(AppSettings.ACTIVE_CHANNEL, ""):
            settings.setValue(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)

        # --- Filesystem: move flat layout into a {active_channel}/ subfolder
        root = AppSettings.get_user_data_dir()
        channels_upper = {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}

        # Whether a channel subfolder has any *real* content (files or nested
        # dirs) vs. just being an empty shell auto-created by a path helper's
        # ``mkdir(exist_ok=True)`` — the latter shouldn't block migration.
        def _has_content(p: Path) -> bool:
            try:
                for sub in p.rglob("*"):
                    if sub.is_file():
                        return True
            except OSError:
                return False
            return False

        populated_channel_dirs = [
            p for p in (root.iterdir() if root.exists() else [])
            if p.is_dir() and p.name.upper() in channels_upper and _has_content(p)
        ]

        if populated_channel_dirs:
            logger.info(
                f"Populated channel subfolders already present under {root}: "
                f"{[p.name for p in populated_channel_dirs]}; skipping filesystem migration"
            )
        else:
            target_channel = settings.value(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
            target_dir = root / target_channel
            moved = []
            skipped = []
            try:
                target_dir.mkdir(parents=True, exist_ok=True)
                for entry in list(root.iterdir()):
                    if entry == target_dir:
                        continue
                    # Skip anything that matches another channel name — either
                    # a populated sibling channel dir (bail above caught that)
                    # or an empty shell for a different channel (we leave
                    # alone; the current active channel is the only migration
                    # target).
                    if entry.is_dir() and entry.name.upper() in channels_upper:
                        skipped.append(entry.name)
                        continue
                    try:
                        # If the target already has an entry of the same name
                        # (e.g. empty ``LIVE\cache\`` auto-created by a path
                        # helper before the migrator ran), merge by moving
                        # the flat entry's contents into the existing target
                        # and then removing the now-empty flat dir.
                        dest = target_dir / entry.name
                        if dest.exists():
                            if entry.is_dir() and dest.is_dir():
                                for child in list(entry.iterdir()):
                                    try:
                                        child.rename(dest / child.name)
                                    except OSError as move_err:
                                        logger.warning(
                                            f"Could not merge {child} into {dest}: {move_err}"
                                        )
                                try:
                                    entry.rmdir()  # now empty
                                except OSError:
                                    pass
                                moved.append(f"{entry.name}/* → {dest}")
                                continue
                            # File-vs-file or mismatched-type collision —
                            # skip with a warning; user keeps both copies.
                            logger.warning(
                                f"Migration skipped {entry} — target {dest} already exists"
                            )
                            skipped.append(entry.name)
                            continue
                        entry.rename(dest)
                        moved.append(entry.name)
                    except OSError as move_err:
                        logger.warning(
                            f"Could not move {entry} into {target_dir}: {move_err}"
                        )
                if moved:
                    logger.info(
                        f"Migrated flat user-data layout into {target_dir}: "
                        f"moved {moved}"
                    )
                if skipped:
                    logger.debug(f"Skipped (already channel dirs or collisions): {skipped}")
            except OSError as e:
                logger.warning(f"Channel-layout filesystem migration failed: {e}")

        settings.setValue(AppSettings.CHANNEL_LAYOUT_MIGRATED, True)
        settings.sync()

    @staticmethod
    def _get_user_data_dir_override() -> str:
        """Return the configured user-data directory override, if any.

        Current builds store this as ``user_data_dir``. Some docs and manual
        support notes referred to ``UserDataDir``; migrate that alias lazily
        so users who followed those instructions don't fall back to Documents.
        """
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.USER_DATA_DIR, "", type=str)
        if raw and str(raw).strip():
            return str(raw).strip()

        for alias in AppSettings.USER_DATA_DIR_ALIASES:
            raw_alias = settings.value(alias, "", type=str)
            if raw_alias and str(raw_alias).strip():
                value = str(raw_alias).strip()
                settings.setValue(AppSettings.USER_DATA_DIR, value)
                settings.sync()
                logger.info(
                    f"Migrated user data directory setting {alias} → "
                    f"{AppSettings.USER_DATA_DIR}: {value}"
                )
                return value

        return ""

    @staticmethod
    def get_user_data_dir_override() -> str:
        """Return the explicit user-data directory override, or ``""`` when unset."""
        return AppSettings._get_user_data_dir_override()

    @staticmethod
    def _get_cache_dir_override() -> str:
        """Return the configured DataForge cache-directory override, if any."""
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.CACHE_DIR, "", type=str)
        return str(raw).strip() if raw and str(raw).strip() else ""

    @staticmethod
    def get_cache_dir_override() -> str:
        """Return the explicit DataForge cache directory override, or ``""`` when unset."""
        return AppSettings._get_cache_dir_override()

    @staticmethod
    def set_cache_dir(path: "str | Path | None") -> None:
        """Persist (or clear) the DataForge cache directory override.

        ``None`` or an empty string clears the override; subsequent
        :meth:`get_dataforge_cache_dir` calls fall back to the platform
        default (%LOCALAPPDATA% in registry mode, ``<exe-dir>/data/cache/``
        in portable mode).
        """
        settings = AppSettings.settings()
        if path is None or (isinstance(path, str) and not path.strip()):
            settings.remove(AppSettings.CACHE_DIR)
        else:
            settings.setValue(AppSettings.CACHE_DIR, str(path))
        settings.sync()

    @staticmethod
    def get_pending_cache_cleanup() -> str:
        """Return the path queued for deletion after the next successful P4K
        re-extraction, or ``""`` when no cleanup is pending."""
        settings = AppSettings.settings()
        raw = settings.value(AppSettings.PENDING_CACHE_CLEANUP, "", type=str)
        return str(raw).strip() if raw and str(raw).strip() else ""

    @staticmethod
    def set_pending_cache_cleanup(path: "str | Path | None") -> None:
        """Mark (or clear) a directory for deletion after re-extraction."""
        settings = AppSettings.settings()
        if path is None or (isinstance(path, str) and not path.strip()):
            settings.remove(AppSettings.PENDING_CACHE_CLEANUP)
        else:
            settings.setValue(AppSettings.PENDING_CACHE_CLEANUP, str(path))
        settings.sync()

    @staticmethod
    def get_user_data_dir() -> Path:
        r"""Get the user data directory.

        Portable mode (build_mode.IS_PORTABLE = True): always returns
        the ``data/`` directory next to the running binary. Registry
        override and Documents fallback are skipped — portability is
        the whole point. ``<exe-dir>/data/`` when frozen,
        ``<repo-root>/portable_data/`` when running from source.

        Registry mode (default) resolution order:
          1. Registry override ``USER_DATA_DIR`` — set by users who want the
             cache/user.ini off a OneDrive-synced Documents folder (extraction
             and rmtree are much slower under OneDrive's sync hooks).
          2. ``Documents\Smart Citizen\`` via the ``Personal`` shell-folder
             key, which honors OneDrive/folder redirection.
          3. ``~/Documents/Smart Citizen\`` as a last-ditch fallback.

        Returns:
            Path to the resolved directory (created if needed).
        """
        # Portable build: always next to the binary, no overrides.
        from src.utils import build_mode
        if build_mode.IS_PORTABLE:
            data_dir = AppSettings._portable_data_dir()
            data_dir.mkdir(parents=True, exist_ok=True)
            return data_dir

        override = AppSettings._get_user_data_dir_override()
        if override:
            override_path = Path(os.path.expandvars(override)).expanduser().resolve()
            try:
                override_path.mkdir(parents=True, exist_ok=True)
                return override_path
            except OSError as e:
                logger.warning(
                    f"USER_DATA_DIR override {override!r} not usable ({e}); "
                    f"falling back to Documents default"
                )
        data_dir = AppSettings._resolve_docs_base() / "Smart Citizen"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @staticmethod
    def _portable_data_dir() -> Path:
        """Resolve the portable-mode data root.

        Frozen (PyInstaller): ``<exe-dir>/data/`` — true portable, no
        machine state outside the .exe's folder. ``sys.executable``
        points at the bundled .exe, not the Python interpreter.

        Unfrozen (dev / tests): ``<repo-root>/portable_data/`` so a
        developer running ``python src/main.py`` with a monkeypatched
        IS_PORTABLE = True can exercise the portable code path without
        accidentally polluting Documents\\Smart Citizen.
        """
        import sys
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "data"
        # src/utils/settings.py → src/utils → src → repo root
        repo_root = Path(__file__).resolve().parent.parent.parent
        return repo_root / "portable_data"

    @staticmethod
    def setup_portable_backend_if_needed() -> None:
        """Wire the JSON settings backend on portable startup.

        Called from main.py once at startup, BEFORE any AppSettings
        accessor that depends on get_user_data_dir() (which the JSON
        backend file path is derived from). No-op in registry mode —
        the existing QSettings default keeps working.

        Idempotent: safe to call multiple times. Subsequent calls are
        a no-op once `_backend` is set.
        """
        from src.utils import build_mode
        if not build_mode.IS_PORTABLE:
            return
        if AppSettings._backend is not None:
            return
        from src.utils.json_settings import JsonSettings
        # Lives next to all the other portable data so the whole
        # standalone install is one folder the user can copy/move.
        config_path = AppSettings._portable_data_dir() / "config.json"
        AppSettings._backend = JsonSettings(config_path)
        logger.info("Portable mode active — settings backend: %s", config_path)

    @staticmethod
    def set_user_data_dir(path: "str | Path | None") -> None:
        r"""Override the user data directory. Pass ``None`` or an empty
        string to clear the override and revert to the Documents default.

        Writes to the Osiris DevWorks\Smart Citizen registry key (same scope
        as every other AppSettings value), so it survives reinstalls and is
        per-user.
        """
        settings = AppSettings.settings()
        if not path:
            settings.remove(AppSettings.USER_DATA_DIR)
            for alias in AppSettings.USER_DATA_DIR_ALIASES:
                settings.remove(alias)
        else:
            expanded = Path(os.path.expandvars(str(path))).expanduser().resolve()
            settings.setValue(AppSettings.USER_DATA_DIR, str(expanded))
            for alias in AppSettings.USER_DATA_DIR_ALIASES:
                settings.remove(alias)
        settings.sync()

    # ── Channel selection API ────────────────────────────────────────────────

    @staticmethod
    def get_active_channel() -> str:
        r"""Return the active Star Citizen channel (LIVE/PTU/EPTU/HOTFIX/TECH-PREVIEW).

        Falls back to :data:`DEFAULT_CHANNEL` when unset or unrecognized —
        safer than raising, since path helpers downstream depend on this and
        a bad value would break every subsequent call.
        """
        value = AppSettings.settings().value(AppSettings.ACTIVE_CHANNEL, AppSettings.DEFAULT_CHANNEL)
        if value in AppSettings.AVAILABLE_CHANNELS:
            return value
        logger.warning(
            f"Unknown active_channel {value!r}; defaulting to {AppSettings.DEFAULT_CHANNEL}"
        )
        return AppSettings.DEFAULT_CHANNEL

    @staticmethod
    def set_active_channel(channel: str) -> None:
        """Persist the active channel name. Must be a member of AVAILABLE_CHANNELS."""
        if channel not in AppSettings.AVAILABLE_CHANNELS:
            raise ValueError(
                f"Unknown channel {channel!r}; expected one of {AppSettings.AVAILABLE_CHANNELS}"
            )
        AppSettings.settings().setValue(AppSettings.ACTIVE_CHANNEL, channel)
        AppSettings.settings().sync()

    @staticmethod
    def get_sc_install_root() -> str:
        r"""Return the Star Citizen install root (parent of the channel folders).

        This is the directory containing ``LIVE\``, ``PTU\``, etc. Resolution
        order mirrors :meth:`get_game_install_path`:
          1. QSettings value for :data:`SC_INSTALL_ROOT`
          2. Derived from legacy ``GAME_INSTALL_PATH`` (strip trailing
             ``\LIVE`` if present)
          3. Auto-detected from the common RSI install locations

        Returns an empty string when nothing resolves — the Config tab shows
        a placeholder in that case.
        """
        saved = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")

        # Cross-check: the installer writes both game_install_path and
        # sc_install_root.  If the user reinstalled with a different SC
        # path, game_install_path is fresh but a stale sc_install_root
        # from a prior migration could survive (pre-1.4.2 installers
        # didn't write sc_install_root).  When the two disagree, derive
        # from game_install_path — it was written more recently.
        legacy = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
        if saved and legacy:
            legacy_path = Path(legacy)
            if legacy_path.name.upper() in (c.upper() for c in AppSettings.AVAILABLE_CHANNELS):
                derived_root = str(legacy_path.parent)
                if os.path.normcase(derived_root) != os.path.normcase(saved):
                    logger.info(
                        f"SC_INSTALL_ROOT {saved!r} disagrees with "
                        f"GAME_INSTALL_PATH {legacy!r} — using derived root {derived_root!r}"
                    )
                    AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, derived_root)
                    return derived_root

        if saved:
            return saved

        # Derive from the legacy per-channel path if it's set.
        if legacy:
            legacy_path = Path(legacy)
            if legacy_path.name.upper() in (c.upper() for c in AppSettings.AVAILABLE_CHANNELS):
                return str(legacy_path.parent)
            return legacy  # assume it was already a root

        for candidate in [
            r"C:\Program Files\Roberts Space Industries\StarCitizen",
            r"C:\Program Files (x86)\Roberts Space Industries\StarCitizen",
        ]:
            if Path(candidate).exists():
                return candidate
        return ""

    @staticmethod
    def set_sc_install_root(path: str) -> None:
        """Persist the SC install root. Callers should pass the directory
        that contains ``LIVE\\``, ``PTU\\``, etc., not a specific channel."""
        AppSettings.settings().setValue(AppSettings.SC_INSTALL_ROOT, path)

    @staticmethod
    def get_available_channels() -> list[str]:
        """Return channels for which ``{root}\\{channel}\\Data.p4k`` exists.

        Used by the Config tab to grey-out channel combo entries the user
        can't actually switch to. When the root isn't configured yet we
        return all channels so the combo isn't empty — the user can still
        pick one before the path is set.
        """
        root = AppSettings.get_sc_install_root()
        if not root:
            return list(AppSettings.AVAILABLE_CHANNELS)
        root_path = Path(root)
        return [
            channel for channel in AppSettings.AVAILABLE_CHANNELS
            if (root_path / channel / "Data.p4k").exists()
        ]

    @staticmethod
    def get_channel_install_path() -> str:
        r"""Return ``{sc_install_root}\{active_channel}``.

        This is the "game install path" for whichever channel is currently
        active — equivalent to what :meth:`get_game_install_path` returned
        before the channel layout landed.
        """
        root = AppSettings.get_sc_install_root()
        if not root:
            return ""
        return str(Path(root) / AppSettings.get_active_channel())

    @staticmethod
    def get_channel_data_dir() -> Path:
        r"""Return ``{user_data_dir}\{active_channel}\`` (created if needed).

        All per-channel user data (cache, backups, user.ini, DataForge
        extraction) lives under this. :meth:`get_user_data_dir` stays the
        root holding every channel's subfolder.
        """
        channel_dir = AppSettings.get_user_data_dir() / AppSettings.get_active_channel()
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir

    # ── Channel-scoped cache/backup/user.ini paths ──────────────────────────
    # These all used to nest directly under get_user_data_dir(); now they
    # nest under the active channel's subfolder. That makes every downstream
    # caller channel-aware automatically.

    @staticmethod
    def get_cache_dir() -> Path:
        r"""Get the active channel's cache directory (``…\{channel}\cache\``)."""
        cache_dir = AppSettings.get_channel_data_dir() / "cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def get_user_ini_path() -> Path:
        r"""Get the active channel's ``user.ini`` path.

        Each channel has its own user.ini — PTU and LIVE can have entirely
        different loc-key sets, so sharing edits across channels would
        require merging logic we don't want to maintain.

        Migrates from ``overrides.ini`` → ``user.ini`` on first call if
        needed, within the active channel's folder.
        """
        data_dir = AppSettings.get_channel_data_dir()
        user_ini = data_dir / "user.ini"
        old_overrides = data_dir / "overrides.ini"

        if old_overrides.exists() and not user_ini.exists():
            try:
                old_overrides.rename(user_ini)
                logger.info(f"Migrated {old_overrides} → {user_ini}")
            except OSError as e:
                logger.warning(f"Failed to migrate overrides.ini → user.ini: {e}")
                return old_overrides

        return user_ini

    @staticmethod
    def get_backups_dir() -> Path:
        r"""Get the active channel's backups directory (``…\{channel}\backups\``).

        Backups are per-channel because each channel's global.ini has its
        own stock baseline — restoring a LIVE backup into PTU would mix
        stock strings from different game builds.
        """
        backups_dir = AppSettings.get_channel_data_dir() / "backups"
        backups_dir.mkdir(parents=True, exist_ok=True)
        return backups_dir

    @staticmethod
    def get_logs_dir() -> Path:
        r"""Get the logs directory (``{user_data_dir}\logs\``).

        Crash dumps and manual log exports both land here. NOT per-channel:
        a crash can fire before the channel context is established (e.g.
        during startup migrators), so the path is rooted at the
        user-data dir directly. Created lazily so a fresh install doesn't
        carry an empty ``logs/`` until the first crash or export.
        """
        logs_dir = AppSettings.get_user_data_dir() / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        return logs_dir

    @staticmethod
    def migrate_dataforge_cache_to_local() -> None:
        r"""One-shot move of the DataForge XML cache from Documents → AppData\Local.

        Pre-1.0 the DataForge cache lived inside get_cache_dir() (Documents\…),
        putting ~1.4 GB of extracted XMLs into the OneDrive sync tree. Moving it
        to AppData\Local eliminates per-file OneDrive / Defender / Indexer hooks
        during extraction and keeps large build-artefact files out of cloud sync.

        Idempotent: no-ops when the old path is already absent. If the new
        location already has a valid stamp the old directory is cleaned up and
        the migration is considered complete.
        """
        import shutil

        old_dir = AppSettings.get_cache_dir() / "dataforge"
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        new_dir = (
            local_appdata / "Smart Citizen"
            / AppSettings.get_active_channel()
            / "cache" / "dataforge"
        )

        if not old_dir.exists():
            return

        if (new_dir / ".p4k_mtime").exists():
            logger.info(
                f"DataForge cache already at new location; removing old copy at {old_dir}"
            )
            try:
                shutil.rmtree(old_dir, ignore_errors=True)
            except Exception as e:
                logger.warning(f"Could not remove old DataForge cache at {old_dir}: {e}")
            return

        logger.info(f"Migrating DataForge cache: {old_dir} → {new_dir}")
        try:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
            logger.info("DataForge cache migration complete")
        except Exception as e:
            logger.warning(
                f"DataForge cache migration failed ({e}); "
                "cache will be re-extracted on next use"
            )

    @staticmethod
    def migrate_data_to_documents() -> None:
        """Copy user data files from old AppData location to new Documents location.

        Safe to call on every startup — skips files that already exist at the
        destination. Handles the upgrade path for users on previous versions.
        """
        import shutil

        old_base = Path(
            os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        ) / "Osiris DevWorks" / "SC Localization Editor"
        old_cache = old_base / "cache"

        new_base  = AppSettings.get_user_data_dir()
        new_cache = AppSettings.get_cache_dir()

        # Migrate overrides.ini
        old_overrides = old_base / "overrides.ini"
        new_overrides = new_base / "overrides.ini"
        if old_overrides.exists() and not new_overrides.exists():
            try:
                shutil.copy2(old_overrides, new_overrides)
                logger.info(f"Migrated overrides.ini to Documents")
            except Exception as e:
                logger.warning(f"Could not migrate overrides.ini: {e}")

        # Migrate cache files
        if old_cache.exists():
            for ini_file in old_cache.glob("*.ini"):
                dest = new_cache / ini_file.name
                if not dest.exists():
                    try:
                        shutil.copy2(ini_file, dest)
                        logger.info(f"Migrated {ini_file.name} to Documents cache")
                    except Exception as e:
                        logger.warning(f"Could not migrate {ini_file.name}: {e}")

        # Migrate backup files from old AppData location
        old_backups = old_base / "backups"
        if old_backups.exists():
            new_backups = AppSettings.get_backups_dir()
            for bak_file in old_backups.glob("global.ini.bak_*"):
                dest = new_backups / bak_file.name
                if not dest.exists():
                    try:
                        shutil.copy2(bak_file, dest)
                        logger.info(f"Migrated {bak_file.name} to Documents backups")
                    except Exception as e:
                        logger.warning(f"Could not migrate {bak_file.name}: {e}")

    @staticmethod
    def get_unp4k_exe_path() -> Path:
        """Resolve bundled unp4k.exe — works both frozen (PyInstaller) and in dev."""
        import sys
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            # src/utils/settings.py → src/utils → src → project root
            base = Path(__file__).parent.parent.parent
        return base / 'assets' / 'unp4k' / 'unp4k.exe'

    @staticmethod
    def get_unforge_exe_path() -> Path:
        """Resolve bundled unforge.exe — works both frozen (PyInstaller) and in dev."""
        import sys
        if getattr(sys, 'frozen', False):
            base = Path(sys._MEIPASS)
        else:
            base = Path(__file__).parent.parent.parent
        return base / 'assets' / 'unp4k' / 'unforge.exe'

    @staticmethod
    def get_dataforge_cache_base() -> Path:
        """Return the *base* directory for DataForge caches (without the
        active-channel suffix). The full per-channel cache path lives at
        ``{base}/{channel}/cache/dataforge/`` — see
        :meth:`get_dataforge_cache_dir` for the resolved leaf.

        Resolution order (registry mode):
          1. ``CACHE_DIR`` registry override — set by users splitting the
             DataForge cache off the user-data dir (e.g. fast SSD for the
             cache, OneDrive Documents for user.ini).
          2. ``%LOCALAPPDATA%\\Smart Citizen\\`` — the pre-1.4.1 default,
             preserved so unchanged installs see no path movement.

        Portable mode:
          1. ``CACHE_DIR`` override if set (portable users may want the
             1.4 GB cache off a slow USB stick).
          2. ``<exe-dir>/data/cache/`` — sits next to all other portable
             data so a USB-stick install is one fully self-contained folder.
        """
        from src.utils import build_mode
        override = AppSettings._get_cache_dir_override()
        if override:
            return Path(os.path.expandvars(override)).expanduser().resolve()
        if build_mode.IS_PORTABLE:
            return AppSettings._portable_data_dir() / "cache"
        return Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        ) / "Smart Citizen"

    @staticmethod
    def get_dataforge_cache_dir() -> Path:
        """Return the directory where DataForge entity XMLs are cached after unforge.

        Defaults to ``%LOCALAPPDATA%\\Smart Citizen\\{channel}\\cache\\dataforge\\``
        — never OneDrive-synced, eliminating per-file sync hooks during
        extraction of the ~1.4 GB / ~28k-file XML tree. A user can override
        the base via the Config tab (Smart Citizen Data → DataForge Cache
        Folder); see :meth:`get_dataforge_cache_base` for the resolution
        order. Channel nesting is preserved across all variants so each
        SC channel stays isolated.
        """
        cache_dir = (
            AppSettings.get_dataforge_cache_base()
            / AppSettings.get_active_channel()
            / "cache" / "dataforge"
        )
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def get_p4k_path() -> Path:
        """Return path to Data.p4k for the active channel.

        Resolves via :meth:`get_channel_install_path` which already nests the
        channel under the SC install root. Falls back to the legacy
        single-channel logic (where ``get_game_install_path()`` may have
        returned either the root or the channel dir) for users whose
        migration hasn't run yet — harmless on migrated installs since the
        active-channel branch wins above.
        """
        channel_path = AppSettings.get_channel_install_path()
        if channel_path:
            return Path(channel_path) / "Data.p4k"

        game_path = Path(AppSettings.get_game_install_path())
        if game_path.name.upper() in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}:
            return game_path / "Data.p4k"
        return game_path / AppSettings.get_active_channel() / "Data.p4k"

    @staticmethod
    def get_global_ini_path() -> Path:
        r"""Return the active channel's applied ``global.ini`` location.

        Equivalent to ``{sc_install_root}\{active_channel}\data\Localization\english\global.ini``
        — the file "Apply to Game" writes and "Clear Localization" deletes.
        Callers should use this instead of reconstructing the path from
        :meth:`get_game_install_path`, which the pre-0.9.3 code did with
        scattered ``if name == "LIVE"`` branches that don't cover the new
        channels.
        """
        channel_path = AppSettings.get_channel_install_path()
        if channel_path:
            return Path(channel_path) / "data" / "Localization" / "english" / "global.ini"

        game_path = Path(AppSettings.get_game_install_path())
        if game_path.name.upper() in {c.upper() for c in AppSettings.AVAILABLE_CHANNELS}:
            return game_path / "data" / "Localization" / "english" / "global.ini"
        return (
            game_path / AppSettings.get_active_channel()
            / "data" / "Localization" / "english" / "global.ini"
        )

    @staticmethod
    def ensure_user_ini_file() -> None:
        """Ensure user.ini exists, creating empty file if needed."""
        user_ini_path = AppSettings.get_user_ini_path()

        user_ini_path.parent.mkdir(parents=True, exist_ok=True)

        if not user_ini_path.exists():
            try:
                user_ini_path.touch()
                logger.info(f"Created empty user.ini: {user_ini_path}")
            except Exception as e:
                logger.error(f"Failed to create user.ini: {e}")
