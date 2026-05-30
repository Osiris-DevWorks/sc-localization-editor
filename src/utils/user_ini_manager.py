"""User INI persistence and import utilities."""
import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from src.models.string_model import StringEntry
from src.parser.ini_parser import parse_ini_file
from src.utils.perf import timed

logger = logging.getLogger(__name__)


def migrate_user_data_dir(old_root: "str | Path", new_root: "str | Path") -> int:
    """Copy user data from ``old_root`` into ``new_root`` after the user moves
    the Smart Citizen data folder (issue #103).

    Copies every file under ``old_root`` to the matching path under
    ``new_root``, **merging** rather than overwriting: any file that already
    exists at the destination is left untouched, so data already in the new
    location always wins. The originals are left in place (copy, not move),
    so a mistaken move is recoverable.

    Returns the number of files copied. A no-op (returns 0) when the old root
    is missing or resolves to the same directory as the new root.

    Handles the case where the new folder is nested inside the old one: the
    file list is snapshotted before any copy (so freshly-written files can't
    be fed back into a lazy walk), and any source already under the
    destination is skipped (so the new folder's own contents aren't recursively
    re-copied into themselves).
    """
    old_root = Path(old_root)
    new_root = Path(new_root)
    try:
        old_resolved = old_root.resolve()
        new_resolved = new_root.resolve()
    except OSError:
        return 0
    if not old_root.exists() or old_resolved == new_resolved:
        return 0

    copied = 0
    # Snapshot up front — if new_root is nested in old_root, copying into it
    # mid-walk would otherwise let a lazy rglob re-yield the new files.
    for src in list(old_root.rglob("*")):
        if src.is_dir():
            continue
        # Skip anything already under the destination (the new-inside-old
        # case), so we don't recursively re-copy the new folder's contents.
        try:
            src.resolve().relative_to(new_resolved)
            continue  # src is inside new_root → leave it alone
        except (ValueError, OSError):
            pass  # not under new_root → migrate it
        rel = src.relative_to(old_root)
        dest = new_root / rel
        if dest.exists():
            continue  # never clobber data already present in the new location
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied += 1
        except OSError as e:
            logger.warning(f"Could not migrate {src} -> {dest}: {e}")
    logger.info(f"Migrated {copied} file(s) from {old_root} to {new_root}")
    return copied


def reset_user_ini(user_ini_path: Path, backup: bool = True) -> Optional[Path]:
    """Remove ``user.ini`` for the active channel, optionally renaming it to a
    timestamped backup first.

    Used by the "Reset user.ini" tools-tab button. Returns the backup path
    when ``backup=True`` and a rename happened, otherwise ``None``.

    If the file doesn't exist, returns ``None`` — caller should treat that
    as a no-op (e.g. surface "already at stock values").

    Backup naming: ``user.ini.bak-YYYYMMDD-HHMMSS`` next to the original. If
    the timestamped target somehow already exists (double-click producing
    two resets inside one second), a numeric suffix ``-2`` / ``-3`` / … is
    appended until a free name is found, so the second click can never
    silently destroy the first backup.
    """
    if not user_ini_path.exists():
        return None

    if not backup:
        user_ini_path.unlink()
        logger.info(f"Deleted user.ini (no backup) at {user_ini_path}")
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = user_ini_path.with_name(f"{user_ini_path.name}.bak-{timestamp}")
    suffix = 2
    while candidate.exists():
        candidate = user_ini_path.with_name(
            f"{user_ini_path.name}.bak-{timestamp}-{suffix}"
        )
        suffix += 1

    user_ini_path.rename(candidate)
    logger.info(f"Reset user.ini: {user_ini_path} → backup {candidate}")
    return candidate


def should_autosave_user_ini(entries: List[StringEntry], user_ini_path: Path) -> bool:
    """Decide whether the close-time autosave is safe to run.

    Returns False — and the caller skips the write — when the in-memory entry
    list has zero modified entries but ``user_ini_path`` already exists on
    disk with non-zero content. Under those conditions a write would
    truncate the file to 0 bytes, which is the data-loss path reported
    against 1.3.0: a load mismatch (channel/path drift after a migration,
    or a transient I/O hiccup) leaves every entry with an empty
    ``custom_value``, and the unconditional close-time write then clobbers
    a populated user.ini with an empty one.

    All other cases return True:
      * Modified entries exist → write captures the user's edits.
      * File doesn't exist → first save, nothing to protect.
      * File is already empty → write is a no-op rewrite.

    Trade-off: a user who manually reverts *every* edit and closes will
    not have their clear persisted via autosave. The explicit Apply-to-Game
    path remains the authoritative "persist current state" action.
    """
    if any(e.is_modified for e in entries):
        return True
    try:
        if user_ini_path.exists() and user_ini_path.stat().st_size > 0:
            logger.warning(
                f"Skipping autosave: in-memory state has no overrides but "
                f"on-disk user.ini has {user_ini_path.stat().st_size} bytes "
                f"({user_ini_path}). Preserving disk contents to guard against "
                f"a load mismatch."
            )
            return False
    except OSError as e:
        logger.warning(f"Could not stat user.ini for autosave guard ({user_ini_path}): {e}")
    return True


@timed
def save_user_ini(entries: List[StringEntry], user_ini_path: Path) -> int:
    """Write only user-modified entries to user.ini.

    Args:
        entries: List of StringEntry objects from self.entries
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written

    Raises:
        IOError: If write fails
    """
    # Filter to entries the user actually modified (custom differs from original)
    user_edits = {
        entry.key: entry.custom_value
        for entry in entries
        if entry.is_modified
    }

    user_ini_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            for key, value in user_edits.items():
                f.write(f"{key}={value}\n")

        count = len(user_edits)
        logger.info(f"Saved {count} user edits to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def save_user_ini_dict(data: Dict[str, str], user_ini_path: Path) -> int:
    """Write a raw key-value dict to user.ini.

    Used by the import flow where we have a pre-merged dict rather than
    StringEntry objects.

    Args:
        data: Dict of key → value pairs to write
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written
    """
    user_ini_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            for key, value in data.items():
                f.write(f"{key}={value}\n")

        count = len(data)
        logger.info(f"Saved {count} entries to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def generate_user_ini_from_diff(
    reference_path: Path,
    current_path: Path,
    user_ini_path: Path
) -> int:
    """Diff reference vs current file, write differing keys as user.ini.

    Used on first run to bootstrap user edits from existing game file.

    Args:
        reference_path: Path to reference base file (base.ini)
        current_path: Path to current game file (global.ini)
        user_ini_path: Destination path for user.ini

    Returns:
        Number of entries written, or 0 if skipped (missing files, etc.)
    """
    if not reference_path.exists():
        logger.debug(f"Reference file not found: {reference_path}")
        return 0

    if not current_path.exists():
        logger.debug(f"Current file not found: {current_path}")
        return 0

    if user_ini_path.exists():
        logger.debug(f"user.ini already exists: {user_ini_path}")
        return 0

    try:
        reference = parse_ini_file(reference_path)
        current = parse_ini_file(current_path)

        diffs = {}
        for key, current_value in current.items():
            reference_value = reference.get(key, "")
            if current_value != reference_value:
                diffs[key] = current_value

        if not diffs:
            logger.info("No differences found between reference and current file")
            return 0

        user_ini_path.parent.mkdir(parents=True, exist_ok=True)
        with open(user_ini_path, 'w', encoding='utf-8') as f:
            for key, value in diffs.items():
                f.write(f"{key}={value}\n")

        logger.info(f"Bootstrapped {len(diffs)} user edits from diff")
        return len(diffs)

    except Exception as e:
        logger.warning(f"Failed to generate user.ini from diff: {e}")
        return 0
