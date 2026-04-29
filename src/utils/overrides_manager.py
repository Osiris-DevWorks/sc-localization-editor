"""Backward-compatible overrides helpers.

Older tests and call sites expect ``load_overrides`` / ``save_overrides`` in
``utils.overrides_manager``. The app now uses ``user.ini`` helpers and the INI
parser directly, so this module keeps the legacy API available as a thin shim.
"""

from pathlib import Path

from src.parser.ini_parser import load_overrides as _load_overrides
from src.utils.user_ini_manager import save_user_ini_dict


def load_overrides(path: str | Path) -> dict[str, str]:
    """Load overrides from a plain key=value INI file."""
    return _load_overrides(path)


def save_overrides(data: dict[str, str], path: str | Path) -> int:
    """Save overrides to a plain key=value INI file."""
    return save_user_ini_dict(data, Path(path))
