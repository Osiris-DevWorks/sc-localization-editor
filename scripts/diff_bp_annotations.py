"""One-off: diff [BP] annotations between truth-set global.ini and 0.9.3 cache output.

Truth set = currently-applied LIVE/data/Localization/english/global.ini (reference
the user vouches for).
0.9.3 output = cache/mission_rewards_enhancements.ini merged over cache/base.ini.

Reports keys where the truth set has a [BP]/[BP*]/[BP?] tag but the 0.9.3
merged output does not.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

BP_RE = re.compile(r"\[BP[*?]?\]")


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


def has_bp(v: str) -> bool:
    return bool(BP_RE.search(v))


def main() -> int:
    truth_path = Path(sys.argv[1])
    base_path = Path(sys.argv[2])
    mission_path = Path(sys.argv[3])

    truth = parse(truth_path)
    base = parse(base_path)
    mission = parse(mission_path)

    merged = dict(base)
    merged.update(mission)

    truth_bp = {k: v for k, v in truth.items() if has_bp(v)}

    missing: list[tuple[str, str, str]] = []
    tag_diff: list[tuple[str, str, str]] = []
    not_in_0_9_3: list[tuple[str, str]] = []

    for k, tv in truth_bp.items():
        mv = merged.get(k)
        if mv is None:
            not_in_0_9_3.append((k, tv))
            continue
        if not has_bp(mv):
            missing.append((k, tv, mv))
        else:
            t_tags = sorted(BP_RE.findall(tv))
            m_tags = sorted(BP_RE.findall(mv))
            if t_tags != m_tags:
                tag_diff.append((k, " ".join(t_tags), " ".join(m_tags)))

    print(f"Truth set [BP]-tagged keys: {len(truth_bp)}")
    print(f"  Missing from 0.9.3 merged output: {len(missing)}")
    print(f"  Key absent entirely from 0.9.3: {len(not_in_0_9_3)}")
    print(f"  Tag variant mismatch (both tagged, different tag): {len(tag_diff)}")
    print()

    if missing:
        print("=" * 80)
        print("MISSING [BP] TAG IN 0.9.3 (truth set has tag; 0.9.3 merge does not):")
        print("=" * 80)
        for k, tv, mv in sorted(missing):
            print(f"\nKEY: {k}")
            t_short = tv[:200] + ("..." if len(tv) > 200 else "")
            m_short = mv[:200] + ("..." if len(mv) > 200 else "")
            print(f"  TRUTH : {t_short}")
            print(f"  0.9.3 : {m_short}")

    if tag_diff:
        print("\n" + "=" * 80)
        print("TAG VARIANT MISMATCH:")
        print("=" * 80)
        for k, t_tags, m_tags in sorted(tag_diff):
            print(f"  {k}: truth={t_tags}  0.9.3={m_tags}")

    if not_in_0_9_3:
        print("\n" + "=" * 80)
        print("KEYS NOT PRESENT IN 0.9.3 AT ALL:")
        print("=" * 80)
        for k, tv in sorted(not_in_0_9_3):
            print(f"  {k}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
