"""Detect whether a path lives inside a OneDrive-managed folder (#172).

Windows OneDrive, especially with Known Folder Move redirecting Documents into
OneDrive, syncs and can dehydrate or empty files under its tree. Smart Citizen's
default data root is ``Documents\\Smart Citizen`` resolved via the shell
``Personal`` folder, which honors that redirection, so on a redirected machine
the per-user data (user.ini, cache, backups) lands inside OneDrive's reach. That
has caused user.ini data loss. These helpers let the app warn when its data root
is exposed and suggest a local alternative.

Qt-free and registry-free, so it is unit-testable with a plain environ dict.
"""
from __future__ import annotations

import os
from pathlib import Path

# OneDrive sets these in the user environment. Consumer and commercial (work /
# school) installs use different vars; check all.
_ONEDRIVE_ENV_VARS = ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")


def onedrive_roots(environ: dict | None = None) -> list[Path]:
    """OneDrive root folders known from the environment, de-duplicated."""
    env = os.environ if environ is None else environ
    roots: list[Path] = []
    seen: set[str] = set()
    for var in _ONEDRIVE_ENV_VARS:
        val = env.get(var)
        if not val:
            continue
        try:
            p = Path(val).expanduser()
        except (OSError, ValueError):
            continue
        key = os.path.normcase(os.path.normpath(str(p)))
        if key not in seen:
            seen.add(key)
            roots.append(p)
    return roots


def _is_onedrive_segment(seg: str) -> bool:
    """True for a path segment that names a OneDrive folder.

    Matches ``OneDrive`` and the org variants ``OneDrive - Contoso`` /
    ``OneDrive-Contoso``, but not unrelated names like ``OneDriveBackups``.
    """
    low = seg.strip().lower()
    return low == "onedrive" or low.startswith("onedrive - ") or low.startswith("onedrive-")


def is_onedrive_path(path, environ: dict | None = None) -> bool:
    """True if *path* is at or under a OneDrive-managed folder.

    Two independent signals, either sufficient:
      1. *path* is at/under a OneDrive root from the environment (``%OneDrive%``
         etc.) — the precise signal.
      2. *path* contains a ``OneDrive`` path segment — a fallback that catches
         org folders and contexts where the env var isn't set.
    """
    if not path:
        return False
    try:
        norm = os.path.normcase(os.path.normpath(str(Path(path).expanduser())))
    except (OSError, ValueError):
        return False

    # 1. Under a known OneDrive root.
    for root in onedrive_roots(environ):
        root_norm = os.path.normcase(os.path.normpath(str(root)))
        if norm == root_norm or norm.startswith(root_norm + os.sep):
            return True

    # 2. A "OneDrive" path segment anywhere in the path.
    return any(_is_onedrive_segment(seg) for seg in Path(norm).parts)


def suggest_local_data_dir(environ: dict | None = None) -> Path:
    """A sensible local (non-OneDrive) data folder.

    ``%USERPROFILE%\\Documents\\Smart Citizen``. ``%USERPROFILE%\\Documents`` is
    the real local path even when the shell's Documents has been redirected into
    OneDrive (Windows keeps the local folder). Mirrors the installer's
    ``SuggestLocalDataDir``.
    """
    env = os.environ if environ is None else environ
    profile = env.get("USERPROFILE") or str(Path.home())
    return Path(profile) / "Documents" / "Smart Citizen"
