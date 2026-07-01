"""Package an applied global.ini into a shareable zip.

The "Export Loc-Pack" toolbar action reads the already-applied
``global.ini`` from the game's localization directory and writes it
into a zip suitable for sharing on Discord, an org website, etc. The
zip contains a single ``global.ini`` at the root — recipients (whether
or not they use Smart Citizen) drop it into their own
``StarCitizen\\<channel>\\data\\Localization\\english\\global.ini``.

This module owns the file I/O so the logic is testable without Qt.
"""
from __future__ import annotations

import logging
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def default_locpack_filename(channel: str, today: datetime | None = None) -> str:
    """Return a sensible default filename for the export dialog.

    Format: ``SmartCitizen-LocPack-{channel}-{YYYYMMDD}.zip``. The channel
    is included because loc-files are channel-specific (a PTU export should
    not be applied to LIVE — different stock keys); the date helps the user
    distinguish revisions when iterating.
    """
    when = today or datetime.now()
    return f"SmartCitizen-LocPack-{channel}-{when.strftime('%Y%m%d')}.zip"


def write_locpack_zip(source_global_ini: Path, output_zip_path: Path) -> int:
    """Write ``source_global_ini`` into ``output_zip_path`` as ``global.ini``.

    Args:
        source_global_ini: Absolute path to the already-applied
            ``global.ini`` in the game's localization directory.
        output_zip_path: Absolute path the zip will be written to. Parent
            directory must exist (caller's responsibility — typically the
            QFileDialog already enforces this).

    Returns:
        Number of bytes written for the zipped ``global.ini`` entry
        (uncompressed source size). Useful for status-bar feedback.

    Raises:
        FileNotFoundError: if ``source_global_ini`` doesn't exist. Callers
            (the MainWindow handler) should surface a friendly "Apply to
            Game first" message rather than letting this propagate.
        OSError: any other I/O failure during the write.
    """
    if not source_global_ini.exists():
        raise FileNotFoundError(
            f"Applied global.ini not found at {source_global_ini}. "
            "Click 'Apply Enhancements' first, then Export."
        )

    source_size = source_global_ini.stat().st_size

    # ZIP_DEFLATED gives ~85% compression on typical loc-files (mostly
    # repetitive English text); compresslevel=9 is the slowest of the
    # deflate levels but a 4MB→600KB difference is invisible at this size
    # and the user only runs this on demand. STORED would skip compression
    # entirely and produce a 4MB+ zip — bad for Discord 25MB upload limit
    # when org members add their own loc-pack art / READMEs in the future.
    with zipfile.ZipFile(output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        # Use the bare filename inside the zip — recipients see "global.ini"
        # at the root, no nested directories. Matches what they'd expect to
        # drop straight into the game.
        zf.write(source_global_ini, arcname="global.ini")

    logger.info(
        "Wrote loc-pack zip: %s (source %d bytes → zip %d bytes)",
        output_zip_path,
        source_size,
        output_zip_path.stat().st_size,
    )
    return source_size
