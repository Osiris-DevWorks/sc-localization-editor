"""Diff the cached base.ini between two Star Citizen channels.

Open Strings extracts each channel's stock localization (LIVE / PTU / EPTU /
HOTFIX / TECH-PREVIEW) into ``Documents\\Open Strings\\<channel>\\cache\\base.ini``.
This tool diffs two of those files and reports added / removed / changed loc
keys, both as a category-bucket summary and (optionally) as a full
machine-readable list.

Usage:
    python scripts/diff_base_ini_channels.py LIVE PTU
    python scripts/diff_base_ini_channels.py LIVE PTU --out diff.txt
    python scripts/diff_base_ini_channels.py LIVE PTU --user-data "D:/..."

The user data root defaults to ``%USERPROFILE%\\Documents\\Open Strings`` which
matches a standard install. Pass ``--user-data`` to override (e.g. for a
OneDrive-redirected Documents folder).
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from models.string_model import StringEntry  # noqa: E402


def parse_ini(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith((";", "[", "#")):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def default_user_data_root() -> Path:
    return Path(os.environ.get("USERPROFILE", "~")).expanduser() / "Documents" / "Open Strings"


def base_ini_path(user_data_root: Path, channel: str) -> Path:
    return user_data_root / channel / "cache" / "base.ini"


def write_report(
    out: list[str] | object,  # list to append, or a TextIO-like .write
    a_label: str,
    b_label: str,
    a: dict[str, str],
    b: dict[str, str],
    *,
    full: bool,
) -> None:
    added = sorted(k for k in b if k not in a)
    removed = sorted(k for k in a if k not in b)
    changed = sorted(k for k in b if k in a and a[k] != b[k])

    def emit(line: str = "") -> None:
        if isinstance(out, list):
            out.append(line)
        else:
            out.write(line + "\n")

    emit(f"{a_label} keys:    {len(a):>6}")
    emit(f"{b_label}  keys:   {len(b):>6}")
    emit(f"  Added (in {b_label} only):    {len(added):>5}")
    emit(f"  Removed (in {a_label} only):  {len(removed):>5}")
    emit(f"  Changed (value diff):         {len(changed):>5}")
    emit()

    def cat_breakdown(keys: list[str], label: str) -> None:
        cats = Counter(StringEntry.extract_category(k) for k in keys)
        emit(f"--- {label} by category ---")
        for cat, n in cats.most_common():
            emit(f"  {cat:>15}  {n}")
        emit()

    cat_breakdown(added, f"ADDED in {b_label}")
    cat_breakdown(removed, f"REMOVED from {a_label}")
    cat_breakdown(changed, "CHANGED")

    if not full:
        # Keep stdout focused on the summary; only dump samples interactively.
        for label, keys in (("ADDED", added), ("REMOVED", removed)):
            emit(f"--- sample of {label} (first 30) ---")
            for k in keys[:30]:
                emit(f"  {k}")
            if len(keys) > 30:
                emit(f"  ... +{len(keys) - 30} more")
            emit()
        return

    # Full machine-readable dump for inspection / grepping.
    emit(f"=== ALL ADDED ({len(added)}) ===")
    for k in added:
        emit(f"  + {k}")
        emit(f"      {b[k]}")
    emit()
    emit(f"=== ALL REMOVED ({len(removed)}) ===")
    for k in removed:
        emit(f"  - {k}")
        emit(f"      {a[k]}")
    emit()
    emit(f"=== ALL CHANGED ({len(changed)}) ===")
    for k in changed:
        emit(f"  ~ {k}")
        emit(f"      {a_label}: {a[k]}")
        emit(f"      {b_label}: {b[k]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel_a", help="First channel name (e.g. LIVE)")
    ap.add_argument("channel_b", help="Second channel name (e.g. PTU)")
    ap.add_argument("--user-data", type=Path, default=None, help="Override Smart Citizen user data root")
    ap.add_argument("--out", type=Path, default=None, help="Write the full diff (every key) to this file")
    args = ap.parse_args(argv)

    root = args.user_data or default_user_data_root()
    path_a = base_ini_path(root, args.channel_a)
    path_b = base_ini_path(root, args.channel_b)
    for p in (path_a, path_b):
        if not p.exists():
            print(f"error: missing {p}", file=sys.stderr)
            return 1

    a = parse_ini(path_a)
    b = parse_ini(path_b)

    # Always print summary to stdout.
    write_report(sys.stdout, args.channel_a, args.channel_b, a, b, full=False)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            write_report(fh, args.channel_a, args.channel_b, a, b, full=True)
        print(f"\nFull diff written to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
