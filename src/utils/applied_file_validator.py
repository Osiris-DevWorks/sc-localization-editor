"""Validate a written global.ini against the stock base.ini.

Extracted from MainWindow._validate_applied_file so this logic can be
tested independently of Qt.
"""

import logging
from pathlib import Path

from src.parser.ini_parser import parse_ini_file

logger = logging.getLogger(__name__)


def validate_applied_file(
    written_path: Path,
    cache_dir: Path,
    stock_keys: set[str] | None = None,
) -> str:
    """Validate the written global.ini against the stock base.ini.

    Checks that every key in base.ini is present in the written file.
    Values are allowed to differ. Extra keys (from components/contracts/
    commodities sources) are expected and not treated as errors.

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
        describing any missing or unexpected keys.
    """
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
        f"missing={len(missing)}, extra={len(extra)}"
    )

    if not missing and not extra:
        return ""

    lines = []

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
