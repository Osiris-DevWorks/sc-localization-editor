"""Settings management using QSettings."""

import logging
import sys
from pathlib import Path

from PyQt6.QtCore import QSettings

logger = logging.getLogger(__name__)


class AppSettings:
    """Wrapper around QSettings for application configuration."""

    ORG_NAME = "Joni Hayes"
    APP_NAME = "Open Strings"

    # Settings keys - Favorites
    FAVORITE_PREFIX = "favorite_prefix"

    # Settings keys - Appearance
    THEME = "theme"

    # Settings keys - Enhancements
    ENHANCEMENTS_ENABLED = "enhancements_enabled"

    # Settings keys - Tutorial
    # Stores the app version string ("0.9.3") that last marked the guided tour
    # as completed, so a future release can re-trigger it if the tour gains
    # new steps worth showing again. Empty string means "never shown".
    TUTORIAL_COMPLETED_VERSION = "tutorial_completed_version"

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
    SC_INSTALL_ROOT = "sc_install_root"
    ACTIVE_CHANNEL = "active_channel"

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
        "ship_descs": "ships_desc_enhancements.ini",
        "component_descs": "components_desc_enhancements.ini",
        "ship_weapon_descs": "ship_weapons_desc_enhancements.ini",
        "fps_weapon_descs": "fps_weapons_desc_enhancements.ini",
        "mission_rewards": "mission_rewards_enhancements.ini",
        "commodity_crafting": "commodity_crafting_enhancements.ini",
        "journal": "journal_enhancements.ini",
        "missile_enhancements": "missile_enhancements.ini",
    }

    # User-facing category labels — match the filter categories on the main page
    ENHANCEMENT_LABELS = {
        "ships": "Ships",
        "ship_items": "Ship Items",
        "gear": "Gear",
        "missions": "Missions",
        "commodities": "Commodities",
        "journal": "Journal",
    }

    # Maps each checkbox key to the enhancement file keys it controls
    ENHANCEMENT_CATEGORY_FILES = {
        "ships": ["ship_descs"],
        "ship_items": ["component_descs", "ship_weapon_descs", "missile_enhancements"],
        "gear": ["fps_weapon_descs"],
        "missions": ["mission_rewards"],
        "commodities": ["commodity_crafting"],
        "journal": ["journal"],
    }

    # Settings keys - Legacy
    GAME_INSTALL_PATH = "game_install_path"
    WINDOW_GEOMETRY = "window_geometry"
    WINDOW_STATE = "window_state"
    # Explicit override for the user-data directory. When set, takes
    # precedence over the Documents\Open Strings\ default. Users who have
    # Documents redirected to OneDrive can point this at a local path to
    # avoid slow extraction / rmtree races on OneDrive-synced folders.
    USER_DATA_DIR = "user_data_dir"

    # Settings keys - Data sources (new)
    # Prefix: data_sources/{source_name}/
    DATA_SOURCES_PREFIX = "data_sources"
    MERGE_HIERARCHY = "merge_hierarchy"
    SOURCE_AUTO_UPDATE_PREFIX = "source_auto_update"

    # Available data sources
    SOURCE_GLOBAL = "global"
    SOURCE_USER = "user"
    AVAILABLE_SOURCES = [SOURCE_GLOBAL, SOURCE_USER]

    @staticmethod
    def settings() -> QSettings:
        """Get QSettings instance."""
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
    def get_enhancement_category_enabled(key: str) -> bool:
        """Check if a specific enhancement category is enabled (default: True)."""
        return AppSettings.settings().value(f"enhancements/categories/{key}/enabled", True, type=bool)

    @staticmethod
    def set_enhancement_category_enabled(key: str, enabled: bool) -> None:
        """Enable or disable a specific enhancement category."""
        AppSettings.settings().setValue(f"enhancements/categories/{key}/enabled", enabled)

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
        from src.gui.theme import AVAILABLE_THEMES, DEFAULT_THEME

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
    def get_tutorial_completed_version() -> str:
        """App version string that last completed the guided tour, or '' if never."""
        return AppSettings.settings().value(AppSettings.TUTORIAL_COMPLETED_VERSION, "")

    @staticmethod
    def set_tutorial_completed_version(version: str) -> None:
        """Record that the guided tour was completed for *version*."""
        AppSettings.settings().setValue(AppSettings.TUTORIAL_COMPLETED_VERSION, version)
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
    def get_game_install_path() -> str:
        """Return the install path of the **active channel**.

        Post 0.9.3 this resolves as ``{sc_install_root}\\{active_channel}``.
        Kept under the old name so existing callers (which assume "the"
        game install path means the active channel) still work; there's no
        semantic change for pre-channel-aware code paths that always
        operated on LIVE.

        Falls back to the legacy ``GAME_INSTALL_PATH`` stored value, and
        then to the installer-written registry key, for users whose
        settings haven't yet been written (new install first-launch only).
        """
        root = AppSettings.settings().value(AppSettings.SC_INSTALL_ROOT, "")
        if root:
            return str(Path(root) / AppSettings.get_active_channel())

        # Legacy path stored under the old key.
        saved = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
        if saved:
            return saved

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
            with open(manifest_path, encoding="utf-8") as f:
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
            source_name: One of SOURCE_GLOBAL, SOURCE_USER

        Returns:
            Path or URL string, empty string if not set
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        return AppSettings.settings().value(key, "")

    @staticmethod
    def set_source_path(source_name: str, path: str) -> None:
        """Set path/URL for a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_USER
            path: File path or URL
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/path"
        AppSettings.settings().setValue(key, path)

    @staticmethod
    def is_source_enabled(source_name: str) -> bool:
        """Check if a data source is enabled.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_USER

        Returns:
            True if enabled, False otherwise. Defaults to True for both.
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        # Default: Global and User always enabled, others disabled
        default = source_name in [AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER]
        return AppSettings.settings().value(key, default, type=bool)

    @staticmethod
    def set_source_enabled(source_name: str, enabled: bool) -> None:
        """Enable or disable a data source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_USER
            enabled: True to enable, False to disable
        """
        key = f"{AppSettings.DATA_SOURCES_PREFIX}/{source_name}/enabled"
        AppSettings.settings().setValue(key, enabled)

    @staticmethod
    def get_merge_hierarchy() -> list[str]:
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
        if isinstance(value, list):
            return value
        return default

    @staticmethod
    def set_merge_hierarchy(hierarchy: list[str]) -> None:
        """Set the merge hierarchy (ordered list of source names).

        Args:
            hierarchy: List of source names in merge order
        """
        AppSettings.settings().setValue(AppSettings.MERGE_HIERARCHY, hierarchy)

    @staticmethod
    def get_source_auto_update(source_name: str) -> bool:
        """Check if auto-update is enabled for a source.

        Args:
            source_name: One of SOURCE_GLOBAL, SOURCE_USER
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
            source_name: One of SOURCE_GLOBAL, SOURCE_USER
            enabled: True to auto-update, False to disable
        """
        if source_name == AppSettings.SOURCE_USER:
            return  # Cannot change auto-update for User source
        key = f"{AppSettings.SOURCE_AUTO_UPDATE_PREFIX}/{source_name}"
        AppSettings.settings().setValue(key, enabled)

    @staticmethod
    def ensure_default_settings() -> None:
        """Seed default source settings on first launch if the registry is empty.

        Idempotent — short-circuits if the global source is already registered.
        Seeds only the two sources the app uses:

          * ``global`` — locally-cached ``base.ini`` from Data.p4k extraction
          * ``user``   — per-channel ``user.ini`` (created lazily on first edit)

        The ``enhancements`` source is dynamically injected by
        :func:`load_sources_from_settings` based on which enhancement
        categories the user has enabled — it doesn't need a registry entry.
        """
        settings = AppSettings.settings()

        # Auto-seed SC install root only if missing and SC is at a standard location.
        # Non-standard install paths must be set via Browse in the Config tab.
        if not settings.value(AppSettings.SC_INSTALL_ROOT, ""):
            for candidate in [
                r"C:\Program Files\Roberts Space Industries\StarCitizen",
                r"C:\Program Files (x86)\Roberts Space Industries\StarCitizen",
            ]:
                if Path(candidate).exists():
                    AppSettings.set_sc_install_root(candidate)
                    break

        # Idempotent — return immediately if the global source is already registered.
        if settings.value(f"{AppSettings.DATA_SOURCES_PREFIX}/{AppSettings.SOURCE_GLOBAL}/path"):
            return

        # Global: locally-cached base.ini, populated by P4K extraction.
        global_local_path = str(AppSettings.get_cache_dir() / "base.ini")
        AppSettings.set_source_path(AppSettings.SOURCE_GLOBAL, global_local_path)
        AppSettings.set_source_enabled(AppSettings.SOURCE_GLOBAL, True)
        AppSettings.set_source_auto_update(AppSettings.SOURCE_GLOBAL, False)

        # User: per-channel user.ini.
        user_path = str(AppSettings.get_user_ini_path())
        AppSettings.set_source_path(AppSettings.SOURCE_USER, user_path)

        # Default hierarchy: global → user. The enhancements source is
        # auto-inserted between them at load time when its files exist.
        AppSettings.set_merge_hierarchy([AppSettings.SOURCE_GLOBAL, AppSettings.SOURCE_USER])

    @staticmethod
    def _resolve_docs_base() -> Path:
        """Resolve the real Documents root (honors OneDrive redirection)."""
        if sys.platform == "win32":
            try:
                import winreg

                key = winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
                )
                docs_path = Path(winreg.QueryValueEx(key, "Personal")[0])
                winreg.CloseKey(key)
            except OSError:
                docs_path = Path.home() / "Documents"
        else:
            docs_path = Path.home() / "Documents"
        return docs_path

    @staticmethod
    def get_user_data_dir() -> Path:
        r"""Get the user data directory.

        Resolution order:
          1. Registry override ``USER_DATA_DIR`` — set by users who want the
             cache/user.ini off a OneDrive-synced Documents folder (extraction
             and rmtree are much slower under OneDrive's sync hooks).
          2. ``Documents\Open Strings\`` via the ``Personal`` shell-folder
             key, which honors OneDrive/folder redirection.
          3. ``~/Documents/Open Strings\`` as a last-ditch fallback.

        Returns:
            Path to the resolved directory (created if needed).
        """
        override = AppSettings.settings().value(AppSettings.USER_DATA_DIR, "", type=str)
        if override:
            override_path = Path(override)
            try:
                override_path.mkdir(parents=True, exist_ok=True)
                return override_path
            except OSError as e:
                logger.warning(
                    f"USER_DATA_DIR override {override!r} not usable ({e}); falling back to Documents default"
                )
        data_dir = AppSettings._resolve_docs_base() / "Open Strings"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir

    @staticmethod
    def set_user_data_dir(path: str | Path | None) -> None:
        r"""Override the user data directory. Pass ``None`` or an empty
        string to clear the override and revert to the Documents default.

        Writes to the per-user QSettings registry node (same scope as every
        other AppSettings value), so it survives reinstalls.
        """
        if not path:
            AppSettings.settings().remove(AppSettings.USER_DATA_DIR)
        else:
            AppSettings.settings().setValue(AppSettings.USER_DATA_DIR, str(path))
        AppSettings.settings().sync()

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
        logger.warning(f"Unknown active_channel {value!r}; defaulting to {AppSettings.DEFAULT_CHANNEL}")
        return AppSettings.DEFAULT_CHANNEL

    @staticmethod
    def set_active_channel(channel: str) -> None:
        """Persist the active channel name. Must be a member of AVAILABLE_CHANNELS."""
        if channel not in AppSettings.AVAILABLE_CHANNELS:
            raise ValueError(f"Unknown channel {channel!r}; expected one of {AppSettings.AVAILABLE_CHANNELS}")
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
        if saved:
            return saved

        # Derive from the legacy per-channel path if it's set.
        legacy = AppSettings.settings().value(AppSettings.GAME_INSTALL_PATH, "")
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
        return [channel for channel in AppSettings.AVAILABLE_CHANNELS if (root_path / channel / "Data.p4k").exists()]

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
    def get_unp4k_exe_path() -> Path:
        """Resolve unp4k.exe from the versioned local tools directory."""
        from src.utils.tools_manager import get_tools_dir

        return get_tools_dir() / "unp4k.exe"

    @staticmethod
    def get_unforge_exe_path() -> Path:
        """Resolve unforge.exe from the versioned local tools directory."""
        from src.utils.tools_manager import get_tools_dir

        return get_tools_dir() / "unforge.exe"

    @staticmethod
    def get_dataforge_cache_dir() -> Path:
        """Return the directory where DataForge entity XMLs are cached after unforge."""
        return AppSettings.get_cache_dir() / "dataforge"

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
        return game_path / AppSettings.get_active_channel() / "data" / "Localization" / "english" / "global.ini"

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
