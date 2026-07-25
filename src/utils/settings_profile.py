"""Package a user's Smart Citizen settings into a portable backup zip.

The **Export Settings / Import Settings** feature (Config tab) lets a user
snapshot everything that makes their install *theirs* — preferences plus
per-channel ``user.ini`` string overrides — into one small ``.zip`` they can
stash, move to a new PC, or restore after a fresh (portable) unzip. The pain
it solves: portable updates land in a fresh versioned folder with an empty
``data/``, so without this a user re-does all their settings every release.

**What's in the zip** (and what's deliberately not):

  SmartCitizen-Settings-Backup-{version}-{YYYYMMDD}.zip
  ├── manifest.json          # schema + app version + when + source mode + channels
  ├── settings.json          # every backend key/value, machine-specific keys stripped
  └── overrides/
      ├── LIVE/user.ini       # the user's own string overrides, per channel
      └── PTU/user.ini

  Excluded on purpose:
    - the DataForge / base.ini **cache** (tens of MB, regenerates from the game)
    - **backups/** (historical safety-nets, not part of the current settings)
    - machine-specific settings (SC install path, data-dir / cache overrides,
      window geometry) — those must re-detect or stay local on the target PC.
      The exclusion of *settings* keys is the caller's job (it hands us an
      already-filtered dict via ``AppSettings.export_all_values``); this module
      only ever writes what it's given.

This module owns the zip I/O and is deliberately **Qt-free and
settings-free** (takes plain dicts + strings, returns plain data), so the
pack/unpack contract is unit-testable without a QApplication or a real
registry — same split as ``locpack_exporter.py``.
"""
from __future__ import annotations

import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Bump when the on-disk layout changes in a way older readers can't handle.
# read_profile_zip refuses a zip whose schema is newer than this so a backup
# made by a future version doesn't get half-restored by an old one.
SCHEMA_VERSION = 1

MANIFEST_NAME = "manifest.json"
SETTINGS_NAME = "settings.json"
OVERRIDES_DIR = "overrides"

SOURCE_MODE_PORTABLE = "portable"
SOURCE_MODE_REGISTRY = "registry"


class InvalidProfileError(ValueError):
    """Raised when a file isn't a readable Smart Citizen settings backup.

    Covers: not a zip, missing/garbled manifest, wrong app marker, or a
    schema newer than this build understands. Callers surface a friendly
    "that's not a Smart Citizen backup" message rather than crashing.
    """


@dataclass
class ProfileContents:
    """Everything read back out of a settings backup zip.

    ``settings`` is the raw key/value dict (the caller decides which keys to
    actually apply — see ``AppSettings.import_values``). ``overrides`` maps a
    channel name (e.g. ``"LIVE"``) to that channel's ``user.ini`` text.
    """

    settings: dict[str, Any] = field(default_factory=dict)
    overrides: dict[str, str] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION
    app_version: str = ""
    exported_at: str = ""
    source_mode: str = ""


def default_backup_filename(today: Optional[datetime] = None) -> str:
    """Return a sensible default filename for the export dialog.

    Format: ``SmartCitizen-Settings-Backup-{YYYYMMDD}.zip``. The word
    "Backup" (not "Setup") keeps it from being mistaken for an installer,
    and the date lets a user who keeps several snapshots tell them apart.

    Deliberately **no version number**: backups are portable across app
    versions (import only refuses a *newer* ``SCHEMA_VERSION`` than the
    running build understands — see :func:`read_profile_zip`), and stamping
    a version on the filename wrongly implies it's tied to that release.
    The exporting version is still recorded in the manifest and shown in
    the import confirmation.
    """
    when = today or datetime.now()
    return f"SmartCitizen-Settings-Backup-{when.strftime('%Y%m%d')}.zip"


def write_profile_zip(
    output_zip_path,
    *,
    settings: dict[str, Any],
    overrides: dict[str, str],
    app_version: str,
    source_mode: str,
    now: Optional[datetime] = None,
) -> int:
    """Write a settings backup zip. Returns the number of entries written.

    Args:
        output_zip_path: Destination path (parent must exist — the
            QFileDialog enforces this in the GUI path).
        settings: Key/value dict to store as ``settings.json``. The caller is
            responsible for having already stripped machine-specific keys.
        overrides: ``{channel: user.ini text}``. Empty/missing channels are
            simply absent — no placeholder files.
        app_version: The exporting build's version, recorded in the manifest.
        source_mode: ``"portable"`` or ``"registry"`` — informational; import
            works regardless of which mode produced the zip (the settings keys
            are identical across modes).
        now: Injectable timestamp for deterministic tests.

    Raises:
        OSError: any I/O failure during the write.
    """
    when = now or datetime.now()
    manifest = {
        "app": "SmartCitizen",
        "kind": "settings-backup",
        "schema_version": SCHEMA_VERSION,
        "app_version": app_version,
        "exported_at": when.isoformat(timespec="seconds"),
        "source_mode": source_mode,
        "channels": sorted(overrides.keys()),
    }

    entries = 0
    # ZIP_DEFLATED: the payload is a few KB of JSON/INI text and compresses
    # heavily. compresslevel=9 is free at this size and the user runs it on
    # demand.
    with zipfile.ZipFile(
        output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as zf:
        zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2, sort_keys=True))
        entries += 1
        zf.writestr(
            SETTINGS_NAME,
            json.dumps(settings, indent=2, sort_keys=True, ensure_ascii=False),
        )
        entries += 1
        for channel, text in sorted(overrides.items()):
            # Forward slash inside the zip regardless of host OS (zip spec).
            zf.writestr(f"{OVERRIDES_DIR}/{channel}/user.ini", text)
            entries += 1

    logger.info(
        "Wrote settings backup: %s (%d entries, %d settings, %d channel overrides)",
        output_zip_path, entries, len(settings), len(overrides),
    )
    return entries


def read_profile_zip(zip_path) -> ProfileContents:
    """Read + validate a settings backup zip into a :class:`ProfileContents`.

    Raises:
        InvalidProfileError: not a zip, missing/garbled manifest, not a Smart
            Citizen settings backup, or a schema newer than this build supports.
    """
    try:
        zf = zipfile.ZipFile(zip_path, mode="r")
    except (zipfile.BadZipFile, OSError) as e:
        raise InvalidProfileError(f"Not a readable zip file: {e}") from e

    with zf:
        names = set(zf.namelist())
        if MANIFEST_NAME not in names:
            raise InvalidProfileError(
                "This zip has no manifest — it isn't a Smart Citizen settings backup."
            )
        try:
            manifest = json.loads(zf.read(MANIFEST_NAME).decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise InvalidProfileError(f"Backup manifest is unreadable: {e}") from e

        if not isinstance(manifest, dict) or manifest.get("app") != "SmartCitizen":
            raise InvalidProfileError(
                "This backup wasn't made by Smart Citizen."
            )

        schema = manifest.get("schema_version")
        if not isinstance(schema, int):
            raise InvalidProfileError("Backup manifest is missing a schema version.")
        if schema > SCHEMA_VERSION:
            raise InvalidProfileError(
                f"This backup was made by a newer version of Smart Citizen "
                f"(backup schema {schema}, this build supports {SCHEMA_VERSION}). "
                f"Update Smart Citizen, then import again."
            )

        # settings.json — tolerate absence (empty settings) but not corruption.
        settings: dict[str, Any] = {}
        if SETTINGS_NAME in names:
            try:
                loaded = json.loads(zf.read(SETTINGS_NAME).decode("utf-8"))
            except (ValueError, UnicodeDecodeError) as e:
                raise InvalidProfileError(f"Backup settings are unreadable: {e}") from e
            if isinstance(loaded, dict):
                settings = loaded
            else:
                raise InvalidProfileError(
                    "Backup settings.json is not a JSON object."
                )

        # overrides/{channel}/user.ini — read each channel's text.
        overrides: dict[str, str] = {}
        prefix = f"{OVERRIDES_DIR}/"
        for name in names:
            if not name.startswith(prefix) or not name.endswith("/user.ini"):
                continue
            channel = name[len(prefix):-len("/user.ini")]
            # Only accept a single, non-empty path segment as the channel
            # (guards against a maliciously nested zip entry).
            if not channel or "/" in channel:
                continue
            try:
                overrides[channel] = zf.read(name).decode("utf-8")
            except (UnicodeDecodeError, OSError) as e:
                logger.warning("Skipping unreadable override %s: %s", name, e)

    return ProfileContents(
        settings=settings,
        overrides=overrides,
        schema_version=schema,
        app_version=str(manifest.get("app_version") or ""),
        exported_at=str(manifest.get("exported_at") or ""),
        source_mode=str(manifest.get("source_mode") or ""),
    )
