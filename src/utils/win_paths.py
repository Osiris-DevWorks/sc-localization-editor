"""Windows extended-length path helper, shared by any module that reads or
writes deep into the DataForge cache tree.
"""
import sys
from pathlib import Path


def win_long_path(path) -> str:
    """Return *path* as a Windows extended-length path string when needed.

    DataForge's ~28k-file entity tree uses long CIG-authored filenames
    (e.g. ``softlock_terminal_standard_lowtech_commoditykiosk_console_
    transfers_1_straight_a.xml``); once nested under a user's install
    directory plus the per-channel cache layout, the destination path can
    exceed the legacy 260-char ``MAX_PATH``, and ``shutil``/``os``/lxml raise
    ``WinError 3`` ("The system cannot find the path specified") even
    though the path is otherwise valid (#221). The ``\\\\?\\`` prefix tells
    the Win32 API to skip that check (paths up to ~32,767 chars). No-op on
    non-Windows platforms and on paths that are already prefixed.
    """
    if sys.platform != "win32":
        return str(path)
    p = str(Path(path).resolve())
    if p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        # UNC path: \\server\share\... -> \\?\UNC\server\share\...
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p
