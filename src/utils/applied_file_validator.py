"""Validate a written global.ini against the stock base.ini.

Extracted from MainWindow._validate_applied_file so this logic can be
tested independently of Qt.
"""

import logging
from pathlib import Path

from src.parser.ini_parser import parse_ini_file

logger = logging.getLogger(__name__)

# Data.p4k's own extracted global.ini ships with this UTF-8 BOM, and Star
# Citizen's own loc-string loader appears to need it to reliably detect the
# file's encoding — without it, the game can fail to resolve ANY key (every
# string shows its raw @KeyName placeholder) rather than degrading per-key
# (#261). merge_ini_files writes with utf-8-sig specifically to include this,
# but our OWN readers (parse_ini_file/read_ini_text) are utf-8-sig-aware and
# silently accept a file with the BOM stripped — so the key-presence check
# below would report a BOM-less file as fully valid even though the game
# can't parse it. This is a second, independent line of defense: if the BOM
# is ever dropped again (a future refactor, a hand-edited file, an external
# tool overwriting the output), this check fails loudly and the caller rolls
# back to the last known-good backup instead of leaving a file installed
# that Python can read fine but the game engine cannot.
_UTF8_BOM = b"\xef\xbb\xbf"


def validate_applied_file(
    written_path: Path,
    cache_dir: Path,
    stock_keys: set[str] | None = None,
) -> str:
    """Validate the written global.ini against the stock base.ini.

    Checks (1) that the file starts with a UTF-8 BOM — required by the
    game's own loc-string loader, see ``_UTF8_BOM`` above — and (2) that
    every key in base.ini is present in the written file. Values are
    allowed to differ. Extra keys (from components/contracts/commodities
    sources) are expected and not treated as errors.

    Args:
        written_path: Path to the global.ini just written to the game directory.
        cache_dir: Path to the application cache directory (used to locate
            base.ini when stock_keys is not provided).
        stock_keys: Optional pre-parsed set of base.ini keys. If provided,
            skips a redundant parse — callers that already have base.ini in
            memory should pass it here. The written-file parse always runs as
            independent verification.

    Returns:
        Empty string if validation passed, or a human-readable warning message
        describing the problem (missing BOM, and/or missing or unexpected keys).
    """
    try:
        with open(written_path, "rb") as f:
            has_bom = f.read(3) == _UTF8_BOM
    except OSError as e:
        logger.warning(f"Validation error reading written file for BOM check: {e}")
        return ""

    if stock_keys is None:
        stock_path = cache_dir / "base.ini"
        if not stock_path.exists():
            logger.warning("Validation skipped: base.ini not found in cache")
            return ""
        try:
            stock_keys = set(parse_ini_file(stock_path).keys())
        except Exception as e:
            logger.warning(f"Validation error reading stock base.ini: {e}")
            return ""

    try:
        written_keys = set(parse_ini_file(written_path).keys())
    except Exception as e:
        logger.warning(f"Validation error reading written file: {e}")
        return ""

    missing = stock_keys - written_keys
    extra = written_keys - stock_keys

    logger.info(
        f"Validation: stock={len(stock_keys)} keys, "
        f"written={len(written_keys)} keys, "
        f"missing={len(missing)}, extra={len(extra)}, has_bom={has_bom}"
    )

    if has_bom and not missing and not extra:
        return ""

    lines = []

    if not has_bom:
        lines += [
            "The written file is missing its UTF-8 BOM. Star Citizen's own "
            "localization loader needs this to detect the file's encoding — "
            "without it the game can fail to resolve every string (shown as "
            "raw @KeyName placeholders instead of text) rather than just the "
            "ones that changed.",
        ]

    if missing:
        sample = sorted(missing)[:20]
        lines += [f"{len(missing)} key(s) from base.ini are missing from the written file:"]
        lines += [f"  {k}" for k in sample]
        if len(missing) > 20:
            lines.append(f"  ... and {len(missing) - 20} more")

    if extra:
        if lines:
            lines.append("")
        sample = sorted(extra)[:20]
        lines += [f"{len(extra)} unexpected key(s) in written file (not in base.ini):"]
        lines += [f"  {k}" for k in sample]
        if len(extra) > 20:
            lines.append(f"  ... and {len(extra) - 20} more")

    lines += ["", "The previous file has been restored. Check your source configuration."]
    return "\n".join(lines)
