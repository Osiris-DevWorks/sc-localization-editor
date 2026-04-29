"""User INI persistence and import utilities."""

import logging
from pathlib import Path

from src.models.string_model import StringEntry
from src.parser.ini_parser import parse_ini_file
from src.utils.perf import timed

logger = logging.getLogger(__name__)


@timed
def save_user_ini(entries: list[StringEntry], user_ini_path: Path) -> int:
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
    user_edits = {entry.key: entry.custom_value for entry in entries if entry.is_modified}

    user_ini_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(user_ini_path, "w", encoding="utf-8") as f:
            for key, value in user_edits.items():
                f.write(f"{key}={value}\n")

        count = len(user_edits)
        logger.info(f"Saved {count} user edits to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def save_user_ini_dict(data: dict[str, str], user_ini_path: Path) -> int:
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
        with open(user_ini_path, "w", encoding="utf-8") as f:
            for key, value in data.items():
                f.write(f"{key}={value}\n")

        count = len(data)
        logger.info(f"Saved {count} entries to {user_ini_path}")
        return count

    except Exception as e:
        logger.error(f"Failed to save user.ini: {e}")
        raise


@timed
def generate_user_ini_from_diff(reference_path: Path, current_path: Path, user_ini_path: Path) -> int:
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
        with open(user_ini_path, "w", encoding="utf-8") as f:
            for key, value in diffs.items():
                f.write(f"{key}={value}\n")

        logger.info(f"Bootstrapped {len(diffs)} user edits from diff")
        return len(diffs)

    except Exception as e:
        logger.warning(f"Failed to generate user.ini from diff: {e}")
        return 0
