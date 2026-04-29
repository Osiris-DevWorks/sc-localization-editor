"""Diff kraken 4.7 fixture BP tags against 0.9.3 mission_rewards_enhancements.ini output.

Kraken uses [BP] (all) and [BP]* (partial). We emit [BP] / [BP?] with the
same semantics. Report keys where kraken has a BP tag but our output does
not — those are missing annotations users will feel.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

KRAKEN_BP = re.compile(r"\[BP\]\*?")  # [BP] or [BP]*
OURS_BP = re.compile(r"\[BP[*?]?\]")  # [BP], [BP*], or [BP?]


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line or line.startswith(";") or line.startswith("[") or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v
    return out


def kraken_tag(v: str) -> str | None:
    m = KRAKEN_BP.search(v)
    return m.group(0) if m else None


def ours_tag(v: str) -> str | None:
    m = OURS_BP.search(v)
    return m.group(0) if m else None


def main() -> int:
    kraken_path = Path(sys.argv[1])
    mission_path = Path(sys.argv[2])

    kraken = parse(kraken_path)
    mission = parse(mission_path)

    kraken_tagged = {k: kraken_tag(v) for k, v in kraken.items() if kraken_tag(v)}

    missing: list[tuple[str, str, str]] = []
    present_mismatch: list[tuple[str, str, str]] = []

    for k, kt in kraken_tagged.items():
        mv = mission.get(k)
        if mv is None:
            missing.append((k, kt, "(not in our output)"))
            continue
        ot = ours_tag(mv)
        if ot is None:
            missing.append((k, kt, mv[:120]))
        elif (kt == "[BP]" and ot != "[BP]") or (kt == "[BP]*" and ot not in ("[BP?]", "[BP*]")):
            present_mismatch.append((k, kt, ot))

    print(f"Kraken BP-tagged keys: {len(kraken_tagged)}")
    print(f"  Missing tag in ours: {len(missing)}")
    print(f"  Tag variant mismatch: {len(present_mismatch)}")
    print()

    if missing:
        print("=" * 80)
        print("MISSING IN 0.9.3 (kraken has BP tag; ours has none):")
        print("=" * 80)
        for k, kt, mv in sorted(missing):
            print(f"  [{kt}]  {k}")
            if mv != "(not in our output)":
                print(f"         0.9.3: {mv}")

    if present_mismatch:
        print("\n" + "=" * 80)
        print("TAG MISMATCH ([BP] vs [BP?]):")
        print("=" * 80)
        for k, kt, ot in sorted(present_mismatch):
            print(f"  {k}: kraken={kt}  ours={ot}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
