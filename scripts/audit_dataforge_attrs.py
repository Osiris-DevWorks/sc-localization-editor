"""audit_dataforge_attrs.py
──────────────────────────
After each Star Citizen patch, CIG may add new attributes to DataForge XML
records that our enhancement functions don't yet read. This script walks the
DataForge cache and dumps a sorted list of every XML element + attribute
combination seen across each component category directory to a text file.

Run it once per patch after extracting DataForge, then diff the output
against the previous patch's snapshot to see exactly what changed:

    python scripts/audit_dataforge_attrs.py
    python scripts/audit_dataforge_attrs.py --diff previous_attrs.txt

If new attributes appear you'll know to review the relevant enhancements_*
function in generate_enhancements_ini.py and decide whether to add a line.

Output: Documents/Open Strings/cache/dataforge_attrs_<version>.txt
        (also written as dataforge_attrs_latest.txt for easy diffing)

Usage:
    python scripts/audit_dataforge_attrs.py [dataforge_cache_dir] [--diff <previous.txt>]
"""

from __future__ import annotations

import io
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

# Make stdout UTF-8-safe on Windows consoles
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
except Exception:
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass


# ── Paths ──────────────────────────────────────────────────────────────────


def _get_documents_dir() -> Path:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        docs = Path(winreg.QueryValueEx(key, "Personal")[0])
        winreg.CloseKey(key)
        return docs
    except Exception:
        return Path.home() / "Documents"


APP_CACHE_DIR = _get_documents_dir() / "Open Strings" / "cache"
DEFAULT_FORGE_DIR = APP_CACHE_DIR / "dataforge"

# Subdirectories under records/entities/scitem/ships/ that our enhancement
# functions cover. Listed explicitly so the audit only covers what we care about;
# add new categories here if generate_enhancements_ini.py gains new component types.
COMPONENT_DIRS = [
    "shieldgenerator",
    "cooler",
    "powerplant",
    "quantumdrive",
    "radar",
    # ships (vehicles) covered separately below
]

# ── Internal names our enhancement functions read from these elements.
# Used to highlight NEW attributes (present in XML but not in this set) in
# the diff report so you know exactly what to evaluate.
# Keep this in sync with generate_enhancements_ini.py's enhancements_* functions.
KNOWN_ATTRS: dict[str, set[str]] = {
    # SCItemQuantumDriveParams
    "SCItemQuantumDriveParams": {"quantumFuelRequirement"},
    # SQuantumDriveParams
    "SQuantumDriveParams": {
        "driveSpeed",
        "spoolUpTime",
        "cooldownTime",
        "calibrationRate",
        "minCalibrationRequirement",
        "maxCalibrationRequirement",
        "stageOneAccelRate",
        "stageTwoAccelRate",
    },
    # Shield
    "SCItemShieldGeneratorParams": {"MaxShieldHealth", "MaxShieldRegen", "DownedRegenDelay", "StartRegen"},
    # Cooler
    "SCItemCoolerParams": {"CoolingRate"},
    # Power plant
    # (power plant stats come from resource network, not a direct params element)
    # Shared across all components
    "SHealthComponentParams": {"Health"},
    "EMSignature": {"nominalSignature"},
    "IRSignature": {"nominalSignature"},
    "itemResourceParams": {"overheatTemperature"},
    "SDistortionParams": {"Maximum"},
    # Vehicle / ship
    "SCItemVehicleParamsComponentParams": {
        "maxSpeed",
        "maxAfterburnSpeed",
        "scmSpeed",
        "zeroToScm",
        "zeroToMax",
        "acceleration",
        "decceleration",
    },
    "SEntityPhysicsControllerParams": {"mass"},
    "IFCSParams": {
        "maxSpeed",
        "maxAfterburnSpeed",
        "scmSpeed",
        "zeroToScm",
        "zeroToMax",
        "acceleration",
        "decceleration",
    },
}


# ── Core ───────────────────────────────────────────────────────────────────


def collect_attrs(xml_dir: Path) -> dict[str, set[str]]:
    """Walk xml_dir recursively and return {element_tag: {attr_name, ...}}."""
    seen: dict[str, set[str]] = defaultdict(set)
    for xml_file in xml_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        for el in root.iter():
            tag = el.tag
            # Strip __type if it's the only differentiator (old DataForge format)
            type_override = el.get("__type")
            effective_tag = type_override if type_override else tag
            for attr in el.attrib:
                if attr == "__type":
                    continue
                seen[effective_tag].add(attr)
    return dict(seen)


def format_attrs(category: str, attrs: dict[str, set[str]]) -> list[str]:
    lines = [f"=== {category} ==="]
    for tag in sorted(attrs):
        for attr in sorted(attrs[tag]):
            lines.append(f"  {tag}.{attr}")
    return lines


def parse_attrs_file(path: Path) -> dict[str, set[str]]:
    """Parse a previously written attrs snapshot back into {tag: {attrs}}."""
    result: dict[str, set[str]] = defaultdict(set)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("=") or line.startswith("#"):
            continue
        if "." in line:
            tag, _, attr = line.partition(".")
            result[tag.strip()].add(attr.strip())
    return dict(result)


def diff_attrs(
    previous: dict[str, set[str]],
    current: dict[str, set[str]],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (added, removed) attribute sets between two snapshots."""
    added: dict[str, set[str]] = {}
    removed: dict[str, set[str]] = {}
    all_tags = set(previous) | set(current)
    for tag in all_tags:
        prev_attrs = previous.get(tag, set())
        curr_attrs = current.get(tag, set())
        new = curr_attrs - prev_attrs
        gone = prev_attrs - curr_attrs
        if new:
            added[tag] = new
        if gone:
            removed[tag] = gone
    return added, removed


def read_game_version(forge_dir: Path) -> str:
    """Try to read the game version from the DataForge stamp or version file."""
    stamp = forge_dir / ".p4k_mtime"
    if stamp.exists():
        try:
            return f"mtime-{stamp.read_text(encoding='utf-8').strip()}"
        except OSError:
            pass
    return "unknown"


# ── Main ───────────────────────────────────────────────────────────────────


def main() -> None:
    args = sys.argv[1:]

    # Parse --diff flag
    diff_path: Path | None = None
    filtered_args = []
    i = 0
    while i < len(args):
        if args[i] == "--diff" and i + 1 < len(args):
            diff_path = Path(args[i + 1])
            i += 2
        else:
            filtered_args.append(args[i])
            i += 1

    forge_dir = Path(filtered_args[0]) if filtered_args else DEFAULT_FORGE_DIR
    records = forge_dir / "raw" / "libs" / "foundry" / "records"
    scitem = records / "entities" / "scitem" / "ships"

    if not scitem.exists():
        print(f"ERROR: DataForge cache not found at {scitem}")
        print("Run 'Extract DataForge' in the app first (Enhancements tab).")
        sys.exit(1)

    version = read_game_version(forge_dir)
    print(f"DataForge version stamp: {version}")

    all_output_lines: list[str] = [f"# DataForge attribute audit — {version}", ""]
    all_current_attrs: dict[str, set[str]] = defaultdict(set)

    # Component categories
    for subdir in COMPONENT_DIRS:
        d = scitem / subdir
        if not d.exists():
            print(f"  [skip] {subdir} — directory not found")
            continue
        attrs = collect_attrs(d)
        for tag, attr_set in attrs.items():
            all_current_attrs[tag] |= attr_set
        lines = format_attrs(subdir, attrs)
        all_output_lines.extend(lines)
        all_output_lines.append("")
        print(f"  {subdir}: {sum(len(v) for v in attrs.values())} element·attr pairs across {len(attrs)} element types")

    # Vehicles (ships)
    vehicles_dir = records / "entities" / "spaceships"
    if not vehicles_dir.exists():
        vehicles_dir = records / "entities" / "vehicles"
    if vehicles_dir.exists():
        attrs = collect_attrs(vehicles_dir)
        for tag, attr_set in attrs.items():
            all_current_attrs[tag] |= attr_set
        lines = format_attrs("vehicles", attrs)
        all_output_lines.extend(lines)
        all_output_lines.append("")
        print(f"  vehicles: {sum(len(v) for v in attrs.values())} element·attr pairs")

    # Write output files
    out_versioned = APP_CACHE_DIR / f"dataforge_attrs_{version}.txt"
    out_latest = APP_CACHE_DIR / "dataforge_attrs_latest.txt"
    APP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    content = "\n".join(all_output_lines)
    out_versioned.write_text(content, encoding="utf-8")
    out_latest.write_text(content, encoding="utf-8")
    print(f"\nWritten: {out_versioned}")
    print(f"Written: {out_latest}")

    # Diff against previous snapshot if requested
    if diff_path is not None:
        if not diff_path.exists():
            print(f"\nERROR: previous snapshot not found: {diff_path}")
            sys.exit(1)
        previous_attrs = parse_attrs_file(diff_path)
        added, removed = diff_attrs(previous_attrs, dict(all_current_attrs))

        print(f"\n── Diff vs {diff_path.name} ──────────────────────────────────")
        if not added and not removed:
            print("No attribute changes detected.")
        else:
            if added:
                print("\nNEW attributes (review enhancements_* functions for these):")
                for tag in sorted(added):
                    for attr in sorted(added[tag]):
                        known = KNOWN_ATTRS.get(tag, set())
                        flag = "  ← already handled" if attr in known else "  ← NOT YET HANDLED — review needed"
                        print(f"  + {tag}.{attr}{flag}")
            if removed:
                print("\nREMOVED attributes (may indicate XML restructure or stat rename):")
                for tag in sorted(removed):
                    for attr in sorted(removed[tag]):
                        known = KNOWN_ATTRS.get(tag, set())
                        flag = "  ← was being read" if attr in known else ""
                        print(f"  - {tag}.{attr}{flag}")
    else:
        # Even without a diff, flag any attribute the XML currently has that
        # isn't in KNOWN_ATTRS — potential stats we haven't added yet.
        unhandled: dict[str, set[str]] = {}
        for tag, attrs in all_current_attrs.items():
            known = KNOWN_ATTRS.get(tag, set())
            new_attrs = attrs - known
            if new_attrs and tag in KNOWN_ATTRS:
                # Only flag tags we explicitly track — avoids noise from CIG-internal bookkeeping
                unhandled[tag] = new_attrs
        if unhandled:
            print("\nAttributes present in XML but not read by any enhancements_* function:")
            for tag in sorted(unhandled):
                for attr in sorted(unhandled[tag]):
                    print(f"  {tag}.{attr}")
            print("\nThese may be worth adding — check the relevant enhancements_* function.")
        else:
            print("\nAll tracked XML attributes are handled.")


if __name__ == "__main__":
    main()
