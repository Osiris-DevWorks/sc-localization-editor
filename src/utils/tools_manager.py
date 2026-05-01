"""Manages the download and local caching of unp4k / unforge extraction tools."""

import logging
import tempfile
import threading
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Pinned release — both binaries come from the same upstream tag.
TOOLS_VERSION = "v4.0.83"

_BASE_URL = f"https://github.com/dolkensp/unp4k/releases/download/{TOOLS_VERSION}"
_UNP4K_ZIP_URL = f"{_BASE_URL}/unp4k-win-x64-{TOOLS_VERSION}.zip"
_UNFORGE_ZIP_URL = f"{_BASE_URL}/unforge-win-x64-{TOOLS_VERSION}.zip"


def get_tools_dir() -> Path:
    """Return the versioned local cache directory for the tool binaries.

    Lives under ``%APPDATA%\\Open Strings\\tools\\<version>\\`` so it persists
    across app updates. A future version bump creates a fresh directory
    automatically without touching an older cached set.
    """
    import os

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
    return base / "Open Strings" / "tools" / TOOLS_VERSION


def tools_are_present() -> bool:
    """Return True if both unp4k.exe and unforge.exe exist in the tools directory."""
    d = get_tools_dir()
    return (d / "unp4k.exe").exists() and (d / "unforge.exe").exists()


def download_tools(
    progress_callback=None,
    cancel_event: threading.Event | None = None,
) -> None:
    """Download and extract unp4k and unforge into the tools directory.

    Downloads ``unp4k-win-x64-<version>.zip`` and
    ``unforge-win-x64-<version>.zip`` from the upstream GitHub release,
    extracts them (preserving directory structure) into :func:`get_tools_dir`.

    Args:
        progress_callback: Optional ``callable(str)`` called with a
            human-readable status message during download and extraction.
        cancel_event: Optional :class:`threading.Event`. When set, the
            download is aborted and a ``RuntimeError`` is raised.

    Raises:
        RuntimeError: If the download is cancelled via *cancel_event*.
        urllib.error.URLError: On network errors.
        zipfile.BadZipFile: If a downloaded file is corrupt.
    """
    tools_dir = get_tools_dir()
    tools_dir.mkdir(parents=True, exist_ok=True)

    _CHUNK = 65536

    for name, url in [("unp4k", _UNP4K_ZIP_URL), ("unforge", _UNFORGE_ZIP_URL)]:
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Download cancelled")

        _report(progress_callback, f"Downloading {name}…")
        logger.info(f"Downloading {name} from {url}")

        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
                tmp_path = Path(tmp_file.name)
                with urllib.request.urlopen(url) as response:
                    total = int(response.headers.get("Content-Length") or 0)
                    downloaded = 0
                    while True:
                        if cancel_event and cancel_event.is_set():
                            raise RuntimeError("Download cancelled")
                        chunk = response.read(_CHUNK)
                        if not chunk:
                            break
                        tmp_file.write(chunk)
                        downloaded += len(chunk)
                        mb_done = downloaded // (1024 * 1024)
                        if total:
                            mb_total = total // (1024 * 1024)
                            _report(
                                progress_callback,
                                f"Downloading {name}… {mb_done} / {mb_total} MB",
                            )
                        else:
                            _report(progress_callback, f"Downloading {name}… {mb_done} MB")

            _report(progress_callback, f"Extracting {name}…")
            logger.info(f"Extracting {name} to {tools_dir}")
            with zipfile.ZipFile(tmp_path) as zf:
                _safe_extractall(zf, tools_dir)
            logger.info(f"{name} extracted OK")

        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass


def _safe_extractall(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract *zf* into *dest*, rejecting any path-traversal entries.

    ``zipfile.ZipFile.extractall`` does not sanitise entry names, so a zip
    containing ``../../evil.exe`` would write outside *dest*.  We resolve
    each entry's target and refuse to extract anything that escapes the
    destination directory (CWE-22 / zip slip).
    """
    dest_resolved = dest.resolve()
    for entry in zf.infolist():
        target = (dest / entry.filename).resolve()
        if dest_resolved != target and dest_resolved not in target.parents:
            raise ValueError(f"Unsafe zip entry rejected (path traversal): {entry.filename!r}")
        zf.extract(entry, dest)


def _report(callback, message: str) -> None:
    if callback is not None:
        callback(message)
