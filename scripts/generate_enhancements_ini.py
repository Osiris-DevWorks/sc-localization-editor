"""
generate_enhancements_ini.py
────────────────────────────
Generates enhancement-augmented INI files for use as additional sources in
SC Localization Editor.

All enhancements are sourced directly from the game's DataForge entity XML files
(extracted from Data.p4k via unp4k + unforge).  No external JSON sources.

Output files (written to OUTPUT_DIR / cache):
  ships_desc_enhancements.ini        – vehicle_Desc* entries with flight/specs data
  components_desc_enhancements.ini   – item_Desc* COOL/SHLD/POWR/QDRV with numerical data
  ship_weapons_desc_enhancements.ini – item_Desc* ship weapon data
  fps_weapons_desc_enhancements.ini  – item_Desc* FPS weapon data

Usage:
  python scripts/generate_enhancements_ini.py [base_ini_path [dataforge_cache_dir]]
"""

import logging
import pickle
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _get_documents_dir() -> Path:
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        docs = Path(winreg.QueryValueEx(key, "Personal")[0])
        winreg.CloseKey(key)
        return docs
    except Exception:
        return Path.home() / "Documents"


APP_CACHE_DIR = _get_documents_dir() / "Smart Citizen" / "cache"
DEFAULT_BASE_INI = APP_CACHE_DIR / "base.ini"
DEFAULT_FORGE_DIR = APP_CACHE_DIR / "dataforge"

OUTPUT_DIR = APP_CACHE_DIR


# ── INI helpers ───────────────────────────────────────────────────────────────


def parse_ini(path: Path) -> dict[str, str]:
    result = {}
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line.strip() or line.strip().startswith(";"):
                continue
            if "=" not in line:
                continue
            k, _, v = line.partition("=")
            lookup_key = k.strip().split(",")[0].strip()
            if lookup_key:
                result[lookup_key] = v.strip()
    return result


def write_ini(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(entries.items())]
    path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(f"Written {len(entries):,} entries -> {path}")


# ── Derived-lookup disk cache ─────────────────────────────────────────────────
# Walking the DataForge tree is expensive (~85s for scitem alone). These
# lookups are pure functions of the DataForge cache contents, so we pickle
# them under cache/dataforge/.lookups/ keyed on the .p4k_mtime stamp written
# by pak_extractor.py. When DataForge is re-extracted, the stamp changes and
# the cache is invalidated automatically.


def _dataforge_cache_key(forge_dir: Path) -> str:
    """Return a stable fingerprint for the current DataForge cache.

    Uses the .p4k_mtime stamp file written by pak_extractor. Falls back to
    the records directory mtime so the cache is still key-able if the stamp
    is missing (e.g. manually extracted dataforge).
    """
    stamp = forge_dir / ".p4k_mtime"
    if stamp.exists():
        try:
            return stamp.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    records = forge_dir / "raw" / "libs" / "foundry" / "records"
    if records.exists():
        return f"mtime:{int(records.stat().st_mtime)}"
    return "unknown"


def _cached_lookup(forge_dir: Path, name: str, builder):
    """Memoize *builder*'s output to cache/dataforge/.lookups/{name}.pkl.

    The cache is invalidated when _dataforge_cache_key() changes. On cache
    hit the pickled result is returned; on miss we call builder() and write
    the result back. Pickle errors silently fall back to rebuilding.
    """
    cache_dir = forge_dir / ".lookups"
    cache_file = cache_dir / f"{name}.pkl"
    key = _dataforge_cache_key(forge_dir)

    if cache_file.exists():
        try:
            with cache_file.open("rb") as f:
                stored_key, value = pickle.load(f)
            if stored_key == key:
                logger.info(f"Lookup cache hit: {name}")
                return value
        except (pickle.PickleError, OSError, EOFError, ValueError):
            pass

    value = builder()
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with cache_file.open("wb") as f:
            pickle.dump((key, value), f, protocol=pickle.HIGHEST_PROTOCOL)
    except (pickle.PickleError, OSError) as e:
        logger.debug(f"Could not write lookup cache {name}: {e}")
    return value


ENHANCEMENT_SEPARATOR = "\\n\\n--- STATS ---\\n"
MISSION_SEPARATOR = "\\n\\n<EM3>MISSION DETAILS</EM3>\\n"


def append_enhancements(existing_value: str, enhancements_block: str, separator: str = ENHANCEMENT_SEPARATOR) -> str:
    if not enhancements_block:
        return existing_value
    # Strip any existing stats/mission details block. BP/ITEMS/BLUEPRINT DATA
    # markers are intentionally NOT listed here — they're sibling sections to
    # MISSION DETAILS and belong with the base content, not treated as stale
    # augmentation. Stripping them would remove content the caller just
    # prepended in the same run (see mission desc construction in main()).
    for marker in (
        "\\n\\n--- STATS ---",
        "\\n\\n<EM3>STATS</EM3>",
        "\\n\\n<EM3>MISSION DETAILS</EM3>",
        "\\n\\n<EM3>== Stats ==</EM3>",
        "\\n\\n<EM3>== Mission Details ==</EM3>",
        "\\n\\n== Stats ==",
        "\\n\\n== Mission Details ==",
    ):
        if marker in existing_value:
            existing_value = existing_value[: existing_value.index(marker)]
            break
    return existing_value + separator + enhancements_block


# ── Stat formatters ───────────────────────────────────────────────────────────

_OVERHEAT_PLACEHOLDER = 450_000  # Items with this overheat temp have no real overheat stat


def _fmt(value, unit="", decimals=0) -> str:
    if value is None:
        return "?"
    try:
        v = float(value)
        if decimals:
            return f"{v:,.{decimals}f}{unit}"
        return f"{int(round(v)):,}{unit}"
    except (TypeError, ValueError):
        return str(value)


# ── XML parsing helpers ───────────────────────────────────────────────────────


def _find(root: ET.Element, tag: str) -> ET.Element | None:
    """Find first element with the given tag anywhere in the tree."""
    return root.find(f".//{tag}")


def _find_by_type(root: ET.Element, type_name: str) -> ET.Element | None:
    """Find first element matching *type_name* by either ``__type`` attribute
    (old DataForge format) or element tag (newer unforge builds emit the type
    as the tag itself and drop ``__type``)."""
    for el in root.iter():
        if el.get("__type") == type_name or el.tag == type_name:
            return el
    return None


def _attr(root: ET.Element, tag: str, attr: str, default=None):
    el = _find(root, tag)
    return el.get(attr, default) if el is not None else default


# CIG system-sentinel loc keys. When a ContractStringParam or entity
# Localization reference points at one of these, the game resolves it at
# runtime to a literal placeholder string (``<= UNINITIALIZED =>`` etc.)
# that surfaces anywhere a reference fails to bind — objective panels,
# inner-thoughts, tooltips. Augmenting these keys turns every such
# placeholder surface into a POTENTIAL BLUEPRINTS / ITEM REWARDS block,
# which is the bug we guard against in scan_contract_generators and
# _loc_key. Keep this list synced with the ``LOC_*`` entries at the top
# of base.ini.
_SENTINEL_LOC_KEYS = frozenset(
    {
        "LOC_BADSTRING",
        "LOC_BADTOKEN",
        "LOC_DEBUG",
        "LOC_EMPTY",
        "LOC_INVALID",
        "LOC_NOINNERTHOUGHT",
        "LOC_PLACEHOLDER",
        "LOC_UNINITIALIZED",
    }
)


def _is_sentinel_loc_ref(ref: str) -> bool:
    """Return True if *ref* (e.g. ``@LOC_UNINITIALIZED``) is a CIG sentinel.

    Accepts the raw ``@Name`` form that ContractStringParam / Localization
    attributes carry. Stripping the leading ``@`` before lookup keeps the
    check identical to the contract-generator path's set check.
    """
    if not ref:
        return True
    return ref.lstrip("@") in _SENTINEL_LOC_KEYS


# Resolved-text counterparts of the sentinel loc-keys above. When a
# `@LOC_PLACEHOLDER` reference makes it past _is_sentinel_loc_ref (e.g. via
# an attribute that doesn't go through that gate) and gets resolved by
# `loc.get`, we still want to drop the resulting `<= PLACEHOLDER =>`
# string before it appears in a stats list.
_PLACEHOLDER_TEXTS = frozenset(
    {
        "<= PLACEHOLDER =>",
        "<= UNINITIALIZED =>",
        "<= BADSTRING =>",
        "<= BADTOKEN =>",
        "<= DEBUG =>",
        "<= EMPTY =>",
        "<= INVALID =>",
        "<= NOINNERTHOUGHT =>",
    }
)


def _is_placeholder_text(s: str) -> bool:
    return s.strip() in _PLACEHOLDER_TEXTS


def _loc_key(root: ET.Element) -> str | None:
    """Extract the item_Desc* localization key from the entity XML."""
    for el in root.iter("Localization"):
        desc = el.get("Description", "")
        if desc.startswith("@") and not _is_sentinel_loc_ref(desc):
            return desc.lstrip("@")
    return None


def _loc_name_key(root: ET.Element) -> str | None:
    """Extract the item_Name* localization key from the entity XML."""
    for el in root.iter("Localization"):
        name = el.get("Name", "")
        if name.startswith("@") and not _is_sentinel_loc_ref(name):
            return name.lstrip("@")
    return None


# Classification abbreviations for component name tags
_CLASS_ABBREV = {
    "Competition": "CMP",
    "Military": "MIL",
    "Civilian": "CIV",
    "Industrial": "IND",
    "Stealth": "STH",
}


def _component_name_tag(desc_value: str, root: ET.Element | None = None) -> str | None:
    """Extract [CLASS-S{size}-{grade}] tag from a component description string.

    Parses the structured header lines (Size: N, Grade: X, Class: Y) that appear
    at the top of ship component descriptions in the base localization.

    Returns:
        Tag string like "[MIL-S1-A]" or None if parsing fails.
    """
    import re

    size_m = re.search(r"Size:\s*(\d+)", desc_value)
    grade_m = re.search(r"Grade:\s*([A-D])", desc_value)
    class_m = re.search(r"Class:\s*(\w+)", desc_value)
    if not (size_m and grade_m and class_m):
        return None
    abbrev = _CLASS_ABBREV.get(class_m.group(1))
    if not abbrev:
        return None
    return f"[{abbrev}-S{size_m.group(1)}-{grade_m.group(1)}]"


# CIG's internal trackingSignalType values → in-game community shorthand.
_MISSILE_TRACKING_ABBREV = {
    "CrossSection": "CS",
    "Electromagnetic": "EM",
    "Infrared": "IR",
}


def _missile_name_tag(desc_value: str, root: ET.Element | None = None) -> str | None:
    """Extract [S{size}-{seeker}] tag for guided missiles (e.g. [S1-CS]).

    Prefers the XML's ``trackingSignalType`` attribute (on ``<targetingParams>``)
    over the loc-text "Tracking Signal: …" line so we stay correct even if a
    description is edited or translated. Bombs (no guidance) fall through to a
    plain [S{size}] tag.
    """
    import re

    size_m = re.search(r"Size:\s*(\d+)", desc_value)
    if not size_m:
        return None
    size = size_m.group(1)

    seeker_abbrev = None
    if root is not None:
        for el in root.iter():
            if el.tag.endswith("targetingParams") or el.tag.endswith("TargetingParams"):
                raw = el.get("trackingSignalType")
                if raw and raw in _MISSILE_TRACKING_ABBREV:
                    seeker_abbrev = _MISSILE_TRACKING_ABBREV[raw]
                    break
    if seeker_abbrev is None:
        m = re.search(r"Tracking Signal:\s*([A-Za-z ]+?)(?:\\n|\n|$)", desc_value)
        if m:
            normalized = m.group(1).replace(" ", "")
            for raw, abbrev in _MISSILE_TRACKING_ABBREV.items():
                if normalized.lower() == raw.lower():
                    seeker_abbrev = abbrev
                    break

    # Guided missiles get just the seeker abbreviation ([CS]/[EM]/[IR]) so
    # the tag stays compact in-game — the size is already encoded in the
    # missile's display name. Bombs (no seeker) keep [S{size}] since that's
    # the only differentiator they have.
    if seeker_abbrev:
        return f"[{seeker_abbrev}]"
    return f"[S{size}]"


def _mission_loc_key(root: ET.Element) -> str | None:
    """Extract the mission description localization key from MissionBrokerEntry XML.

    Missions store the localization key in the 'description' attribute of the root element.
    """
    desc = root.get("description", "")
    if desc.startswith("@") and not _is_sentinel_loc_ref(desc):
        return desc.lstrip("@")
    return None


def _resource_amount(amount_el: ET.Element) -> str | None:
    """Extract the numeric value from a resourceAmountPerSecond element."""
    unit = amount_el.find(".//SPowerSegmentResourceUnit")
    if unit is not None:
        return unit.get("units")
    std = amount_el.find(".//SStandardResourceUnit")
    if std is not None:
        return std.get("standardResourceUnits")
    micro = amount_el.find(".//SMicroResourceUnit")
    if micro is not None:
        return micro.get("microResourceUnits")
    return None


def _find_resource(root: ET.Element, resource: str) -> str | None:
    """
    Find the amount/s for a given resource anywhere in the resource network,
    searching both Generation and Conversion delta types.

    For Conversion deltas, checks both <consumption> and <generation> children.
    """
    for delta_type in ("ItemResourceDeltaGeneration", "ItemResourceDeltaConversion", "ItemResourceDeltaConsumption"):
        for delta in root.iter(delta_type):
            for child in delta:
                if child.get("resource") == resource:
                    val = _resource_amount(child)
                    if val is not None:
                        return val
    return None


def _fire_rate(root: ET.Element) -> str | None:
    """Return the primary fire rate found in weapon fire actions.

    Searches in priority order:
    1. Default or primary fire mode (if marked)
    2. Highest fire rate if multiple modes exist
    """
    fire_rates = []  # List of (rate_value, is_primary)

    try:
        for el in root.iter():
            if "WeaponActionFire" in el.tag:
                fr = el.get("fireRate")
                if not fr:
                    continue

                try:
                    v = float(fr)
                    if v <= 0:
                        continue

                    # Check if this is marked as default/primary
                    is_default = el.get("default") == "1" or el.get("isDefault") == "true"
                    action_type = el.get("actionType", "")
                    is_primary = is_default or "primary" in action_type.lower()

                    fire_rates.append((v, is_primary))
                except (ValueError, TypeError):
                    pass
    except Exception:
        pass

    if not fire_rates:
        return None

    # Sort by primary first, then by rate (highest)
    fire_rates.sort(key=lambda x: (-int(x[1]), -x[0]))
    return str(fire_rates[0][0])


_FIRE_MODE_LABELS = {
    "rapid": "Auto",
    "single": "Semi-Auto",
    "burst": "Burst",
    "charge": "Charge",
    "shotgun": "Shotgun",
}


def _fire_modes(root: ET.Element, loc: dict | None = None) -> list[str]:
    names = []
    for el in root.iter():
        if "WeaponActionFire" in el.tag:
            # Prefer a clean label from the raw name attribute
            raw_name = (el.get("name") or "").strip()
            label = _FIRE_MODE_LABELS.get(raw_name.lower())
            if not label:
                # Try localized name, stripping brackets. Skip CIG sentinel
                # loc-keys (e.g. @LOC_PLACEHOLDER) — they resolve to literal
                # ``<= PLACEHOLDER =>`` strings that should not surface in
                # the in-game stats list.
                loc_key = el.get("localisedName", "")
                if _is_sentinel_loc_ref(loc_key):
                    continue
                if loc_key.startswith("@") and loc is not None:
                    label = (loc.get(loc_key[1:]) or raw_name or "").strip("[] ")
                else:
                    label = raw_name or loc_key.strip("[] ")
            if label and not _is_placeholder_text(label) and label not in names:
                names.append(label)
    return names


_DAMAGE_TYPES = (
    "DamagePhysical",
    "DamageEnergy",
    "DamageDistortion",
    "DamageThermal",
    "DamageBiochemical",
    "DamageStun",
)
_DAMAGE_LABELS = {
    "DamagePhysical": "Phys",
    "DamageEnergy": "Energy",
    "DamageDistortion": "Distort",
    "DamageThermal": "Thermal",
    "DamageBiochemical": "Bio",
    "DamageStun": "Stun",
}


def _ammo_damage(ammo_root: ET.Element) -> float:
    """Sum all damage types from the ammo's DamageInfo element."""
    total = 0.0
    for info in ammo_root.iter("DamageInfo"):
        for attr in _DAMAGE_TYPES:
            try:
                total += float(info.get(attr, 0))
            except ValueError:
                pass
    return total


def _ammo_damage_breakdown(ammo_root: ET.Element) -> tuple[float, dict]:
    """Return (total_damage, {label: amount}) for non-zero damage types.

    Only reads the primary <damage> element, not damage drop-off values.
    """
    totals: dict[str, float] = {}
    # Find the primary damage element (direct child of projectile params, not drop-off)
    damage_elem = ammo_root.find(".//damage")
    if damage_elem is not None:
        for info in damage_elem.iter("DamageInfo"):
            for attr in _DAMAGE_TYPES:
                try:
                    v = float(info.get(attr, 0))
                    if v:
                        lbl = _DAMAGE_LABELS[attr]
                        totals[lbl] = totals.get(lbl, 0.0) + v
                except ValueError:
                    pass
    else:
        # Fallback: look for DamageInfo that's NOT inside damageDropParams
        for info in ammo_root.iter("DamageInfo"):
            # Skip DamageInfo elements inside damageDropParams
            parent_tags = set()
            node = info
            while node is not None:
                parent_tags.add(node.tag)
                node = None  # ElementTree doesn't support parent traversal easily
            for attr in _DAMAGE_TYPES:
                try:
                    v = float(info.get(attr, 0))
                    if v:
                        lbl = _DAMAGE_LABELS[attr]
                        totals[lbl] = totals.get(lbl, 0.0) + v
                except ValueError:
                    pass
            break  # Only use the first DamageInfo found
    return sum(totals.values()), totals


# ── Per-type stat generators ──────────────────────────────────────────────────


def enhancements_shield(root: ET.Element) -> str:
    el = _find(root, "SCItemShieldGeneratorParams")
    if el is None:
        return ""
    hp = el.get("MaxShieldHealth")
    regen = el.get("MaxShieldRegen")
    downed = el.get("DownedRegenDelay")
    damaged = el.get("DamagedRegenDelay")
    pwr = _find_resource(root, "Power")
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")

    # ShieldResistance is a 6-entry array under SCItemShieldGeneratorParams.
    # Order is inferred from the standard SC damage-type ordering used elsewhere
    # in the codebase (Phys, Energy, Distortion, Thermal, Bio, Stun) — index 0
    # consistently shows mild positive resistance (~0–25%) and index 1 shows
    # negative values (vulnerability), which matches SC's "energy shreds
    # shields, physical penetrates partially" mechanic. Each entry has Max/Min
    # spanning the power-allocation range (no power → full power). We expose
    # the two players actually engage with: physical and energy.
    resist_entries = list(el.findall("ShieldResistance/SShieldResistance"))

    def _resist_pct(idx: int) -> str | None:
        if idx >= len(resist_entries):
            return None
        e = resist_entries[idx]
        try:
            mn = float(e.get("Min", "0")) * 100
            mx = float(e.get("Max", "0")) * 100
        except (TypeError, ValueError):
            return None
        if mn == 0 and mx == 0:
            return None
        # Lower bound first for readability ("−77% – −26%" reads top-down).
        lo, hi = (mn, mx) if mn <= mx else (mx, mn)
        return f"{lo:+.0f}% – {hi:+.0f}%"

    lines = []
    if hp is not None or regen is not None:
        lines.append(f"Max HP: {_fmt(hp)}  |  Regen: {_fmt(regen, ' HP/s')}")
    delays = []
    if downed is not None:
        delays.append(f"Downed Delay: {_fmt(downed, 's', 1)}")
    if damaged is not None:
        delays.append(f"Damaged Delay: {_fmt(damaged, 's', 1)}")
    if delays:
        lines.append("  |  ".join(delays))

    phys_resist = _resist_pct(0)
    energy_resist = _resist_pct(1)
    if phys_resist or energy_resist:
        parts = []
        if phys_resist:
            parts.append(f"Phys: {phys_resist}")
        if energy_resist:
            parts.append(f"Energy: {energy_resist}")
        lines.append("Resist:  " + "  |  ".join(parts))

    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None:
            parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None:
            parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))

    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    return "\\n".join(lines)


def enhancements_missile(root: ET.Element) -> str:
    """Extract missile/rocket/bomb enhancements: velocity, guidance, seeker type, lock ranges, tracking range,
    turn rate, detonation mode, proximity fuse range, G-force, acceleration, damage, blast radius,
    effective range, EM/IR signature, and component HP."""
    lines = []

    try:
        # Primary missile params container
        for el in root.iter():
            try:
                # Missile velocity and lifetime
                if "missile" in el.tag.lower() or "projectile" in el.tag.lower():
                    velocity = el.get("speed") or el.get("velocity") or el.get("initialVelocity")
                    if velocity and velocity != "0":
                        try:
                            vel_val = float(velocity)
                            if vel_val > 0:
                                lines.append(f"Velocity: {vel_val:,.0f} m/s")
                        except (ValueError, TypeError):
                            pass

                    lifetime = el.get("lifetime") or el.get("maxLifetime") or el.get("burnTime")
                    if lifetime and lifetime != "0":
                        try:
                            life_val = float(lifetime)
                            if life_val > 0:
                                lines.append(f"Lifetime: {life_val:.2f}s")
                        except (ValueError, TypeError):
                            pass

                # Guidance and tracking parameters
                if "guidance" in el.tag.lower() or "tracking" in el.tag.lower():
                    guidance_type = (
                        el.get("guidanceType")
                        or el.get("type")
                        or el.tag.replace("Guidance", "").replace("Tracking", "")
                    )
                    if guidance_type and "none" not in guidance_type.lower():
                        lines.append(f"Guidance: {guidance_type}")

                    # Seeker type (passive vs active)
                    seeker_type = el.get("seekerType") or el.get("seekerMode")
                    if seeker_type and "none" not in seeker_type.lower():
                        lines.append(f"Seeker: {seeker_type}")

                    # Lock-on time (how long to acquire lock)
                    lock_time = el.get("lockTime") or el.get("lockOnTime") or el.get("lockAcquisitionTime")
                    if lock_time and lock_time != "0":
                        try:
                            time_val = float(lock_time)
                            if time_val > 0:
                                lines.append(f"Lock Time: {time_val:.2f}s")
                        except (ValueError, TypeError):
                            pass

                    # Minimum lock range
                    min_lock = el.get("minLockRange") or el.get("minimumLockRange")
                    if min_lock and min_lock != "0":
                        try:
                            min_val = float(min_lock) / 1000  # Convert to km
                            if min_val > 0:
                                lines.append(f"Min Lock Range: {min_val:,.1f} km")
                        except (ValueError, TypeError):
                            pass

                    # Maximum lock range
                    max_lock = el.get("maxLockRange") or el.get("lockOnRange") or el.get("launchRange")
                    if max_lock and max_lock != "0":
                        try:
                            max_val = float(max_lock) / 1000  # Convert to km
                            if max_val > 0:
                                lines.append(f"Max Lock Range: {max_val:,.1f} km")
                        except (ValueError, TypeError):
                            pass

                    # Tracking range (how far missile can follow locked target)
                    track_range = el.get("trackingRange") or el.get("engagementRange") or el.get("maxEngagementRange")
                    if track_range and track_range != "0":
                        try:
                            track_val = float(track_range) / 1000  # Convert to km
                            if track_val > 0:
                                lines.append(f"Tracking Range: {track_val:,.1f} km")
                        except (ValueError, TypeError):
                            pass

                    # Proximity fuse range (detonation distance from target)
                    prox_range = el.get("proximityFuseRange") or el.get("detonationRange") or el.get("fuseRange")
                    if prox_range and prox_range != "0":
                        try:
                            prox_val = float(prox_range)
                            if prox_val > 0:
                                lines.append(f"Proximity Range: {prox_val:,.0f} m")
                        except (ValueError, TypeError):
                            pass

                    # Turn rate / Max G-force for guided missiles
                    max_g = el.get("maxGForce") or el.get("maxAcceleration") or el.get("maxG")
                    if max_g and max_g != "0":
                        try:
                            g_val = float(max_g)
                            if g_val > 0:
                                lines.append(f"Max G-Force: {g_val:.1f}G")
                        except (ValueError, TypeError):
                            pass

                    turn_rate = el.get("turnRate") or el.get("maxTurnRate") or el.get("angularVelocity")
                    if turn_rate and turn_rate != "0":
                        try:
                            turn_val = float(turn_rate)
                            if turn_val > 0:
                                lines.append(f"Turn Rate: {turn_val:.1f}°/s")
                        except (ValueError, TypeError):
                            pass

                    # Detonation mode
                    detonation = el.get("detonationMode") or el.get("fuseMode") or el.get("detonationType")
                    if detonation and "none" not in detonation.lower():
                        lines.append(f"Detonation: {detonation}")

                # Acceleration / Thrust
                if "propulsion" in el.tag.lower() or "thruster" in el.tag.lower() or "engine" in el.tag.lower():
                    accel = el.get("acceleration") or el.get("maxAcceleration") or el.get("thrust")
                    if accel and accel != "0":
                        try:
                            accel_val = float(accel)
                            if accel_val > 0:
                                lines.append(f"Acceleration: {accel_val:,.1f} m/s²")
                        except (ValueError, TypeError):
                            pass

                # Fuel/propellant for rockets and missiles
                if "propellant" in el.tag.lower() or "fuel" in el.tag.lower():
                    fuel_amount = el.get("amount") or el.get("fuelAmount")
                    if fuel_amount and fuel_amount != "0":
                        try:
                            fuel_val = float(fuel_amount)
                            if fuel_val > 0:
                                lines.append(f"Fuel: {fuel_val:.1f}s")
                        except (ValueError, TypeError):
                            pass
            except Exception:
                pass

        # Lock range (min / max) — actual attribute names on <targetingParams>
        # are `lockRangeMin` / `lockRangeMax` (in meters), not the speculative
        # `minLockRange` / `maxLockRange` the loop above tries. Pull them
        # directly so this stat actually shows up.
        lock_min = _attr(root, "targetingParams", "lockRangeMin")
        lock_max = _attr(root, "targetingParams", "lockRangeMax")
        try:
            lmn = float(lock_min) if lock_min else None
        except (ValueError, TypeError):
            lmn = None
        try:
            lmx = float(lock_max) if lock_max else None
        except (ValueError, TypeError):
            lmx = None

        def _fmt_range_m(v: float) -> str:
            return f"{v / 1000:,.1f} km" if v >= 1000 else f"{v:,.0f} m"

        if lmn is not None and lmn > 0 and lmx is not None and lmx > 0:
            lines.append(f"Lock Range: {_fmt_range_m(lmn)} – {_fmt_range_m(lmx)}")
        elif lmn is not None and lmn > 0:
            lines.append(f"Min Lock Range: {_fmt_range_m(lmn)}")
        elif lmx is not None and lmx > 0:
            lines.append(f"Max Lock Range: {_fmt_range_m(lmx)}")

        # Arming — `armTime` (seconds before warhead arms) and
        # `explosionSafetyDistance` (meters within which the missile won't
        # detonate, near-launcher safety) live on <SCItemMissileParams>.
        # Practical min arming distance ≈ armTime × cruise speed; surface
        # both raw values plus the computed distance so players can compare
        # missiles meaningfully.
        arm_time = _attr(root, "SCItemMissileParams", "armTime")
        safety_dist = _attr(root, "SCItemMissileParams", "explosionSafetyDistance")
        cruise_speed = _attr(root, "GCSParams", "linearSpeed")

        try:
            arm_t = float(arm_time) if arm_time else None
        except (ValueError, TypeError):
            arm_t = None
        try:
            safety = float(safety_dist) if safety_dist else None
        except (ValueError, TypeError):
            safety = None
        try:
            speed = float(cruise_speed) if cruise_speed else None
        except (ValueError, TypeError):
            speed = None

        arm_parts = []
        if arm_t and arm_t > 0:
            arm_parts.append(f"Arm Time: {arm_t:.1f}s")
        if arm_t and arm_t > 0 and speed and speed > 0:
            arm_dist = arm_t * speed
            arm_parts.append(f"Arm Dist: {_fmt_range_m(arm_dist)}")
        if safety and safety > 0:
            arm_parts.append(f"Min Detonate: {safety:,.0f} m")
        if arm_parts:
            lines.append("  |  ".join(arm_parts))

        # Damage (inherited from base weapon/ammo structure)
        damage_info = _find(root, "DamageInfo")
        if damage_info is not None:
            total_dmg, breakdown = _ammo_damage_breakdown(root)
            if total_dmg and total_dmg > 0:
                type_str = ""
                if breakdown and len(breakdown) == 1:
                    type_str = f" ({list(breakdown.keys())[0]})"
                elif breakdown and len(breakdown) > 1:
                    type_str = " (" + " / ".join(f"{lbl}: {v:.1f}" for lbl, v in breakdown.items()) + ")"
                lines.append(f"Damage: {_fmt(total_dmg, '', 1)}{type_str}")

        # Blast radius (warhead explosion radius)
        blast = _attr(root, "ExplosionParams", "maxRadius")
        if not blast:
            blast = _attr(root, "ExplosionParams", "minRadius")
        if not blast:
            blast = _attr(root, "Warhead", "blastRadius")
        if not blast:
            blast = _attr(root, "DamageInfo", "DamageDropOffEnd")
        if blast:
            try:
                blast_val = float(blast)
                if blast_val > 0:
                    lines.append(f"Blast Radius: {blast_val:,.0f} m")
            except (ValueError, TypeError):
                pass

        # Effective range (calculated or stored)
        eff_range = _attr(root, "ProjectileParams", "effectiveRange")
        if eff_range and eff_range != "0":
            try:
                eff_val = float(eff_range) / 1000  # Convert to km
                if eff_val > 0:
                    lines.append(f"Effective Range: {eff_val:,.1f} km")
            except (ValueError, TypeError):
                pass

        # EM and IR signatures (how detectable the missile is)
        em_sig = _attr(root, "EMSignature", "nominalSignature")
        if em_sig and em_sig != "0":
            try:
                em_val = float(em_sig)
                if em_val > 0:
                    lines.append(f"EM Signature: {em_val:,.0f}")
            except (ValueError, TypeError):
                pass

        ir_sig = _attr(root, "IRSignature", "nominalSignature")
        if ir_sig and ir_sig != "0":
            try:
                ir_val = float(ir_sig)
                if ir_val > 0:
                    lines.append(f"IR Signature: {ir_val:,.0f}")
            except (ValueError, TypeError):
                pass

        # Component HP
        comp_hp = _attr(root, "SHealthComponentParams", "Health")
        if comp_hp is not None:
            lines.append(f"Component HP: {_fmt(comp_hp)}")
    except Exception:
        pass

    return "\\n".join(lines) if lines else ""


def enhancements_radar(root: ET.Element) -> str:
    """Extract radar/sensor stats.

    Detection range itself isn't stored as a flat value — the shared params
    record (`radarsystem/vehicleradarsystemsharedparams.xml`) sets both
    maxPassiveDistance and maxActiveDistance to 0 (unlimited) and leaves
    actual range to a runtime sensitivity × signature × atmospheric
    formula. We surface the per-radar values that ARE meaningful and
    intuitive: aim-assist target acquisition range, ping cooldown, what
    detection modes the radar permits, and the standard power/health pair.
    Abstract sensitivity/piercing scalars are intentionally dropped — they
    require knowing CIG's internal math to interpret.
    """
    lines = []

    # Aim-assist auto-target acquisition range (meters). Varies per radar
    # 585–3588m; useful proxy for "how far this radar can lock targets for
    # gimbal aim assist" even though it's not pure detection range.
    for el in root.iter("aimAssist"):
        min_dist = el.get("distanceMinAssignment")
        max_dist = el.get("distanceMaxAssignment")
        try:
            min_v = float(min_dist) if min_dist else None
            max_v = float(max_dist) if max_dist else None
        except (TypeError, ValueError):
            min_v = max_v = None
        if min_v is not None and max_v is not None and max_v > 0:
            lines.append(f"Aim Assist Range: {min_v:,.0f}–{max_v:,.0f} m")
        break

    # Ping cooldown (seconds between active radar pings).
    for el in root.iter("pingProperties"):
        cd = el.get("cooldownTime")
        if cd:
            try:
                cd_v = float(cd)
                lines.append(f"Ping Cooldown: {cd_v:.1f}s")
            except (TypeError, ValueError):
                pass
        break

    # Passive/Active detection capability (which kinds of scanning the
    # radar supports — orthogonal to range, but useful for stealth-vs-
    # combat ship loadout decisions).
    passive_capable = False
    active_capable = False
    for el in root.iter("SCItemRadarSignatureDetection"):
        if el.get("permitPassiveDetection") == "1":
            passive_capable = True
        if el.get("permitActiveDetection") == "1":
            active_capable = True

    modes = []
    if passive_capable:
        modes.append("Passive")
    if active_capable:
        modes.append("Active")
    if modes:
        lines.append(f"Detection Mode: {' / '.join(modes)}")

    # Power consumption.
    pwr = _find_resource(root, "Power")
    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")

    # Component health.
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")

    return "\\n".join(lines) if lines else ""

    return "\\n".join(lines) if lines else ""


def enhancements_cooler(root: ET.Element) -> str:
    cooling = _find_resource(root, "Coolant")
    pwr = _find_resource(root, "Power")
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")
    overheat = _attr(root, "itemResourceParams", "overheatTemperature")

    lines = []
    if cooling is not None:
        lines.append(f"Cooling Rate: {_fmt(cooling, ' CR/s')}")
    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None:
            parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None:
            parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))
    if overheat is not None:
        try:
            if float(overheat) < _OVERHEAT_PLACEHOLDER:
                lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
        except (ValueError, TypeError):
            lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
    return "\\n".join(lines)


def enhancements_powerplant(root: ET.Element) -> str:
    gen = _find_resource(root, "Power")
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")
    overheat = _attr(root, "itemResourceParams", "overheatTemperature")
    distort = _attr(root, "SDistortionParams", "Maximum")

    lines = []
    if gen is not None:
        lines.append(f"Power Output: {_fmt(gen, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None:
            parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None:
            parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))
    if overheat is not None:
        try:
            if float(overheat) < _OVERHEAT_PLACEHOLDER:
                lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
        except (ValueError, TypeError):
            lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
    if distort is not None:
        lines.append(f"Max Distortion: {_fmt(distort)}")
    return "\\n".join(lines)


def enhancements_quantum_drive(root: ET.Element) -> str:
    qd = _find(root, "SCItemQuantumDriveParams")
    if qd is None:
        return ""
    fuel_req = qd.get("quantumFuelRequirement")

    # SQuantumDriveParams is an inline struct: <params __type="SQuantumDriveParams" driveSpeed=... />
    params = _find_by_type(root, "SQuantumDriveParams")
    speed = params.get("driveSpeed") if params is not None else None
    spool = params.get("spoolUpTime") if params is not None else None
    cooldown = params.get("cooldownTime") if params is not None else None
    cal_rate = params.get("calibrationRate") if params is not None else None
    cal_min = params.get("minCalibrationRequirement") if params is not None else None
    cal_max = params.get("maxCalibrationRequirement") if params is not None else None
    accel1 = params.get("stageOneAccelRate") if params is not None else None
    accel2 = params.get("stageTwoAccelRate") if params is not None else None

    pwr = _find_resource(root, "Power")
    qt_fuel = _find_resource(root, "QuantumFuel")
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")
    overheat = _attr(root, "itemResourceParams", "overheatTemperature")
    distort = _attr(root, "SDistortionParams", "Maximum")

    lines = []
    if speed is not None:
        speed_mm = float(speed) / 1_000_000
        spool_str = _fmt(spool, "s") if spool else "?"
        lines.append(f"QT Speed: {speed_mm:,.0f} Mm/s  |  Spool: {spool_str}")
    if cooldown is not None:
        lines.append(f"Cooldown: {_fmt(cooldown, 's', 1)}")
    if fuel_req is not None:
        lines.append(f"Fuel/Gm: {float(fuel_req):.4f}")
    if qt_fuel is not None:
        lines.append(f"QT Fuel Use: {_fmt(qt_fuel)} μ/s")
    if accel1 is not None or accel2 is not None:
        parts = []
        if accel1:
            parts.append(f"S1: {_fmt(accel1)}")
        if accel2:
            parts.append(f"S2: {_fmt(accel2)}")
        lines.append("Accel:  " + "  |  ".join(parts))
    if cal_rate is not None:
        lines.append(f"Cal Rate: {_fmt(cal_rate)}  |  Required: {_fmt(cal_min)}–{_fmt(cal_max)}")
    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None:
            parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None:
            parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))
    if overheat is not None:
        try:
            if float(overheat) < _OVERHEAT_PLACEHOLDER:
                lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
        except (ValueError, TypeError):
            lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
    if distort is not None:
        lines.append(f"Max Distortion: {_fmt(distort)}")
    return "\\n".join(lines)


def _extract_mission_xp(root: ET.Element, reputation_lookup: dict[str, int] | None = None) -> int:
    """Extract mission success XP from primary reputation scope only.

    Gets the first (success outcome) reputation rewards, but only sums from the PRIMARY faction.
    Ignores bonus reputation for secondary factions/scopes. This matches SCMDB mission XP values
    which show only the primary faction reward, not bonuses.
    """
    reputation_lookup = reputation_lookup or {}
    total_rep_xp = 0

    # Only process the first SReputationAmountListParams (the success outcome)
    rep_lists = root.findall(".//missionResultReputationRewards/SReputationAmountListParams")
    if rep_lists:
        first_outcome = rep_lists[0]
        rep_amounts = first_outcome.findall(".//SReputationAmountParams")

        # Only count the FIRST reputation scope (primary faction)
        # Skip bonus reputation for secondary factions/scopes
        if rep_amounts:
            primary_scope = rep_amounts[0].get("reputationScope")
            for rep_amount in rep_amounts:
                # Only count rewards from the primary reputation scope
                if rep_amount.get("reputationScope") == primary_scope:
                    reward_uuid = rep_amount.get("reward")
                    if reward_uuid and reward_uuid in reputation_lookup:
                        xp_val = reputation_lookup[reward_uuid]
                        total_rep_xp += xp_val

    return total_rep_xp


def _extract_spawn_counts(element: ET.Element) -> tuple[int, int, int]:
    """Extract wave count, enemy count, and non-enemy count from spawn descriptions.

    Parses SpawnDescription_ShipGroup and SpawnDescription_NPC_Group elements
    within the given XML element scope.

    Returns:
        (num_waves, num_enemies, num_not_enemies)
    """
    num_enemies = 0
    num_not_enemies = 0
    wave_groups = 0

    # Ship-based spawns (hostile)
    for sg in element.findall(".//SpawnDescription_ShipGroup"):
        name = sg.get("Name", "").lower()
        ships = sg.findall(".//SpawnDescription_Ship")
        total = sum(int(s.get("concurrentAmount", "0")) for s in ships)
        if total <= 0:
            continue
        # Classify by group name
        if any(kw in name for kw in ("target", "reinforcement", "enemy", "hostile", "pirate", "bandit")):
            num_enemies += total
            wave_groups += 1
        elif any(kw in name for kw in ("escort", "friendly", "salvage", "defend", "protect")):
            num_not_enemies += total
        else:
            # Default: assume hostile if in a combat context
            num_enemies += total
            wave_groups += 1

    # NPC-based spawns
    for ng in element.findall(".//SpawnDescription_NPC_Group"):
        name = ng.get("Name", "")
        auto_settings = ng.findall(".//autoSpawnSettings")
        total_npcs = 0
        for auto in auto_settings:
            max_spawns = auto.get("maxSpawns", "0")
            if max_spawns != "-1":
                total_npcs += max(int(max_spawns), 0)
            else:
                max_concurrent = auto.get("maxConcurrentSpawns", "0")
                if max_concurrent != "-1":
                    total_npcs += max(int(max_concurrent), 0)

        if total_npcs <= 0:
            # Try parsing count from name (e.g., "Soldier x 3")
            import re

            m = re.search(r"x\s*(\d+)", name)
            if m:
                total_npcs = int(m.group(1))

        if total_npcs > 0:
            name_lower = name.lower()
            if any(
                kw in name_lower for kw in ("target", "soldier", "cqc", "sniper", "tech", "guard", "sentry", "captain")
            ):
                num_enemies += total_npcs
                wave_groups += 1
            elif any(kw in name_lower for kw in ("escort", "friendly", "civilian", "hostage")):
                num_not_enemies += total_npcs
            else:
                num_enemies += total_npcs
                wave_groups += 1

    return wave_groups, num_enemies, num_not_enemies


def _parse_difficulty_rating(value: str) -> int:
    """Extract the trailing numeric rating from a difficulty attribute value.

    Example: 'Hard_PvE_or_Easy_PvP_action_5' → 5
    """
    if not value:
        return 0
    parts = value.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def _extract_difficulty(element: ET.Element) -> str:
    """Extract difficulty rating from a ContractDifficulty element or missionDifficulty attribute.

    For contract generators: parses the 4-axis ContractDifficulty element.
    For pu_missions: falls back to the simple missionDifficulty integer attribute.

    Returns a formatted difficulty string, or empty string if not available.
    """
    # Try ContractDifficulty element first (contract generators)
    diff_elem = element.find(".//ContractDifficulty")
    if diff_elem is not None:
        combat = _parse_difficulty_rating(diff_elem.get("mechanicalSkill", ""))
        complexity = _parse_difficulty_rating(diff_elem.get("mentalLoad", ""))
        risk = _parse_difficulty_rating(diff_elem.get("riskOfLoss", ""))
        knowledge = _parse_difficulty_rating(diff_elem.get("gameKnowledge", ""))
        if any([combat, complexity, risk, knowledge]):
            parts = []
            if combat:
                parts.append(f"Combat {combat}/7")
            if complexity:
                parts.append(f"Complexity {complexity}/7")
            if risk:
                parts.append(f"Risk {risk}/7")
            if knowledge:
                parts.append(f"Knowledge {knowledge}/7")
            return " | ".join(parts)

    # Fallback: simple missionDifficulty attribute (pu_missions)
    diff_val = element.get("missionDifficulty", "-1")
    if diff_val and diff_val != "-1":
        try:
            return f"{int(diff_val)}/7"
        except ValueError:
            pass

    return ""


def _extract_mission_flags(root: ET.Element) -> list[str]:
    """Extract boolean mission flags from a MissionBrokerEntry XML root.

    Returns list of flag strings like 'Chain', 'Starter', 'Unique'.
    """
    null_uuid = "00000000-0000-0000-0000-000000000000"
    flags = []

    linked = root.get("linkedMission", null_uuid)
    if linked != null_uuid:
        flags.append("Chain")

    if root.get("tutorial") == "1":
        flags.append("Starter")

    if root.get("onceOnly") == "1":
        flags.append("Unique")

    return flags


def enhancements_mission(root: ET.Element, reputation_lookup: dict[str, int] | None = None) -> str:
    """Extract mission/contract reward stats (aUEC + Reputation XP) and flags.

    Extracts:
    - aUEC mission reward amount
    - Reputation XP from reward UUID references using the reputation_lookup table
    - Mission flags (Chain, Starter, Unique)
    """
    lines = []
    reputation_lookup = reputation_lookup or {}

    try:
        # Extract mission flags
        flags = _extract_mission_flags(root)
        lines.append(f"<EM4>Mission Type:</EM4> {', '.join(flags) if flags else 'Standard'}")

        # Extract difficulty rating
        difficulty = _extract_difficulty(root)
        if difficulty:
            lines.append(f"<EM4>Difficulty (1-7):</EM4> {difficulty}")

        # Extract mission success XP (from first/success outcome only, not all outcomes)
        total_rep_xp = _extract_mission_xp(root, reputation_lookup)
        if total_rep_xp > 0:
            lines.append(f"<EM4>Reputation XP:</EM4> +{total_rep_xp:,}")

        # Extract spawn/wave counts
        wave_groups, num_enemies, num_not_enemies = _extract_spawn_counts(root)
        if num_enemies > 0:
            lines.append(f"<EM4>Enemies:</EM4> {num_enemies}")
        if num_not_enemies > 0:
            lines.append(f"<EM4>Non-hostiles:</EM4> {num_not_enemies}")

    except Exception:
        pass

    return "\\n".join(lines) if lines else ""


def build_blueprint_pool_lookup(
    pool_dir: Path,
    bp_dir: Path,
    entity_names: dict[str, str],
) -> dict[str, list[str]]:
    """Build mapping of blueprint pool UUID → list of craftable item display names.

    Args:
        pool_dir: Directory containing BlueprintPoolRecord XMLs (blueprintmissionpools)
        bp_dir: Directory containing CraftingBlueprintRecord XMLs (blueprints/crafting)
        entity_names: UUID → display name lookup for resolving crafted item entities

    Returns:
        Dict mapping pool __ref UUID → sorted list of item display names
    """
    if not pool_dir.exists() or not bp_dir.exists():
        return {}

    # Index all blueprint files by __ref UUID → entityClass UUID
    bp_entity: dict[str, str] = {}
    for xml_file in bp_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            ref = root.get("__ref", "")
            if not ref:
                continue
            for elem in root.iter():
                if _poly_type(elem) == "CraftingProcess_Creation":
                    bp_entity[ref] = elem.get("entityClass", "")
                    break
        except ET.ParseError:
            continue

    # Build pool UUID → item names
    pool_items: dict[str, list[str]] = {}
    for xml_file in pool_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            pool_uuid = root.get("__ref", "")
            if not pool_uuid:
                continue
            names = []
            for elem in root.iter("BlueprintReward"):
                bp_ref = elem.get("blueprintRecord", "")
                if bp_ref and bp_ref in bp_entity:
                    entity_ref = bp_entity[bp_ref]
                    if entity_ref in entity_names:
                        name = entity_names[entity_ref]
                        if name not in names:
                            names.append(name)
            if names:
                pool_items[pool_uuid] = sorted(names)
        except ET.ParseError:
            continue

    logger.info(f"Blueprint pool lookup: {len(pool_items)} pools with items")
    return pool_items


def _build_template_lookup(templates_dir: Path) -> dict[str, tuple[str, str]]:
    """Build mapping of contract template UUID → (title_loc_key, desc_loc_key).

    Some contracts don't have inline ContractStringParam elements and instead
    inherit title/description from their template via LocID elements.
    """
    lookup: dict[str, tuple[str, str]] = {}
    if not templates_dir.exists():
        return lookup

    for xml_file in templates_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            ref = root.get("__ref", "")
            if not ref:
                continue
            title_key = ""
            desc_key = ""
            for lid in root.findall(".//LocID"):
                val = lid.get("value", "")
                if not val or not val.startswith("@") or "LOC_EMPTY" in val or "UNINITIALIZED" in val:
                    continue
                key = val.lstrip("@")
                if "_title" in key.lower() and not title_key:
                    title_key = key
                elif "_desc" in key.lower() and not desc_key:
                    desc_key = key
            if title_key:
                lookup[ref] = (title_key, desc_key)
        except ET.ParseError:
            continue

    logger.info(f"Contract template lookup: {len(lookup)} templates with titles")
    return lookup


def _variant_label_short(debug_name: str) -> str:
    """Extract a short, human-readable variant label from a contract debugName.

    Strips common family prefixes (Bounty Hunters Guild career / bounties /
    elimination) so the region or distinguishing token becomes the label:
      BountyHuntersGuild_Bounties_Nyx_Career     → Nyx
      BountyHuntersGuild_Bounty_Stanton_Easy     → Stanton
      BountyHuntersGuild_PAF_EliminateSpecific   → PAF
      BountyHuntersGuild_FPS_Nyx                 → FPS
    Falls back to the final underscore-separated token when no known family
    prefix matches, preserving the previous behavior for unfamiliar contracts.
    """
    if not debug_name:
        return ""
    for prefix in (
        "BountyHuntersGuild_Bounties_",
        "BountyHuntersGuild_Bounty_",
        "BountyHuntersGuild_",
    ):
        if debug_name.startswith(prefix):
            tail = debug_name[len(prefix) :]
            return tail.split("_", 1)[0]
    return debug_name.rsplit("_", 1)[-1]


def scan_contract_generators(
    contractgen_dir: Path,
    reputation_lookup: dict[str, int] | None = None,
    blueprint_pools: dict[str, list[str]] | None = None,
    entity_names: dict[str, str] | None = None,
):
    """Scan contract generator XMLs for mission variants with different systems.

    Returns tuple of:
        - missions: dict mapping title_key → [(system_name, success_xp, failure_xp, desc_key, flags, num_enemies, num_not_enemies), ...]
        - mission_blueprints: dict title_key → dict system_name → list of craftable item display names.
          Multiple entries indicate per-region pools (e.g. Stanton vs Pyro Shubin HandMining). A single entry is rendered flat.
        - mission_items: dict mapping title_key → list of reward item display names
    Sorted by system name for consistent output.
    """
    if not contractgen_dir.exists():
        return {}, {}, {}

    reputation_lookup = reputation_lookup or {}
    blueprint_pools = blueprint_pools or {}
    entity_names = entity_names or {}
    # Variant tuple: (system_name, success_xp, failure_xp, desc_key, flags, num_enemies, num_not_enemies)
    missions: dict[str, list[tuple[str, int, int, str, list[str], int, int]]] = {}
    # Per-system pool items, so desc output can render regional sub-sections
    # when a title_key has distinct pools for different systems.
    mission_blueprints: dict[str, dict[str, list[str]]] = {}
    mission_bp_chance: dict[str, float] = {}
    mission_items: dict[str, list[str]] = {}

    # Build template lookup for contracts that inherit title/desc from templates
    templates_dir = contractgen_dir.parent / "contracttemplates"
    template_lookup = _build_template_lookup(templates_dir)

    try:
        for xml_file in contractgen_dir.rglob("*.xml"):
            try:
                root = ET.parse(xml_file).getroot()
            except ET.ParseError:
                continue

            # Process both Career and List handler types
            # Career handlers contain CareerContract children; List handlers contain Contract children
            handler_configs = [
                (".//ContractGeneratorHandler_Career", ".//CareerContract"),
                (".//ContractGeneratorHandler_List", ".//Contract"),
            ]

            known_systems = {"Stanton", "Pyro", "Nyx", "Desert", "ArcCorp", "Crusader"}
            # Intra-system region markers used by Headhunters / CFP / etc.
            # to partition contracts within a single system (different pools
            # per region). Matches ``RegionA``, ``RegionB1``, etc.
            _region_token_re = re.compile(r"^Region[A-Z][0-9]*$")

            def _extract_system(name: str, fallback: str) -> str:
                """Pick system token(s) from *name*, else *fallback*.

                Splits on both ``_`` and ``/`` to handle dual-system contract
                debugNames like ``Shubin_RG_Discovery_ShipMining_Nyx/Stanton_Stileron``
                (tokens = ..., ``Nyx/Stanton``, ...). When an intra-system
                ``Region<X>`` token follows the system, append it so pools
                that differ within a single system (e.g. Pyro RegionA vs
                RegionC Headhunters contracts) get separate labels.
                """
                if not name:
                    return fallback
                sys_token = None
                region_token = None
                for token in name.split("_"):
                    sub = token.split("/")
                    if sub and all(s in known_systems for s in sub):
                        sys_token = token
                        region_token = None  # reset — a later system wins
                    elif sys_token and _region_token_re.match(token):
                        region_token = token
                if sys_token is None:
                    return fallback
                return f"{sys_token} {region_token}" if region_token else sys_token

            for handler_xpath, contract_xpath in handler_configs:
                for handler in root.findall(handler_xpath):
                    debug_name = handler.get("debugName", "")

                    handler_system_name = _extract_system(debug_name, debug_name or "Unknown")

                    # Extract handler-level flags from defaultAvailability
                    handler_flags = []
                    da = handler.find(".//defaultAvailability")
                    if da is not None:
                        if da.get("onceOnly") == "1":
                            handler_flags.append("Unique")
                    # Chain detection: has prerequisite completed contract tags
                    has_chain_prereqs = len(handler.findall(".//ContractPrerequisite_CompletedContractTags")) > 0
                    if has_chain_prereqs:
                        handler_flags.append("Chain")

                    # Extract handler-level spawn counts (shared across contracts)
                    _, handler_enemies, handler_not_enemies = _extract_spawn_counts(handler)

                    contracts = handler.findall(contract_xpath)

                    for contract in contracts:
                        try:
                            # Prefer the contract's own debugName when picking
                            # a system token — one handler can host contracts
                            # for multiple systems (Shubin Rank0 has Stanton &
                            # Pyro Intro siblings) and the handler name carries
                            # rank info, not region.
                            contract_name = contract.get("debugName", "")
                            system_name = _extract_system(contract_name, handler_system_name)
                            # Extract title and description keys
                            title_param = contract.find(".//ContractStringParam[@param='Title']")
                            desc_param = contract.find(".//ContractStringParam[@param='Description']")

                            title_key = ""
                            desc_key = ""

                            if title_param is not None:
                                title_key = title_param.get("value", "").lstrip("@")
                            if desc_param is not None:
                                desc_key = desc_param.get("value", "").lstrip("@")

                            # Resolve either key from the contract template when
                            # the inline ContractStringParam is missing. The
                            # previous version only triggered this fallback when
                            # *title* was missing — so a contract with a title
                            # but no desc_param silently dropped its description
                            # path, and its title_key never appeared in
                            # unique_desc_keys. That meant no BP / stats block
                            # ever got written for that mission's desc (e.g.
                            # Jorrit Dossier P2M4 "Updated Power Usage Data" in
                            # 4.7.177's output).
                            if not title_key or not desc_key:
                                tmpl_uuid = contract.get("template", "")
                                if tmpl_uuid and tmpl_uuid in template_lookup:
                                    tmpl_title, tmpl_desc = template_lookup[tmpl_uuid]
                                    if not title_key:
                                        title_key = tmpl_title
                                    if not desc_key:
                                        desc_key = tmpl_desc

                            # Reject CIG's system-sentinel loc-keys — a few
                            # contracts (e.g. citizensforprosperity_destroyitems,
                            # thecollector) have ``Title`` or ``Description``
                            # set to ``@LOC_UNINITIALIZED`` / ``@LOC_EMPTY`` /
                            # ``@LOC_PLACEHOLDER``. These resolve at runtime
                            # to literal strings like ``<= UNINITIALIZED =>``
                            # that the game renders anywhere a reference fails
                            # to bind. If we let them enter ``missions`` /
                            # ``mission_blueprints``, the augmentation
                            # machinery writes the full POTENTIAL BLUEPRINTS
                            # / ITEM REWARDS / MISSION DETAILS block into
                            # the sentinel itself, corrupting *every* UI
                            # surface in-game that falls back to that
                            # sentinel (most visibly, the Primary Objectives
                            # panel for hauling contracts whose item entity
                            # class has no loc-name).
                            if title_key in _SENTINEL_LOC_KEYS:
                                title_key = ""
                            if desc_key in _SENTINEL_LOC_KEYS:
                                desc_key = ""

                            if not title_key:
                                continue

                            # Extract blueprint pool UUID and drop chance if present.
                            # Record the pool under the variant's system_name
                            # so the main loop can emit per-region sub-sections
                            # when a title_key spans multiple systems with
                            # distinct pools (e.g. Shubin FPSMine Stanton vs
                            # Pyro Intro both use
                            # Shubin_Industrial_HandMining_Intro_Local_Desc_001
                            # but award different pools).
                            contract_has_bp = False
                            contract_bp_chance = 0.0
                            contract_bp_variant = contract.get("debugName", "")
                            for bp_elem in contract.iter("BlueprintRewards"):
                                pool_uuid = bp_elem.get("blueprintPool", "")
                                null_uuid = "00000000-0000-0000-0000-000000000000"
                                if pool_uuid and pool_uuid != null_uuid and pool_uuid in blueprint_pools:
                                    contract_has_bp = True
                                    pool_items = blueprint_pools[pool_uuid]
                                    per_system = mission_blueprints.setdefault(title_key, {})
                                    if system_name not in per_system:
                                        per_system[system_name] = pool_items
                                    try:
                                        contract_bp_chance = float(bp_elem.get("chance", "1"))
                                    except (ValueError, TypeError):
                                        contract_bp_chance = 1.0
                                    if title_key not in mission_bp_chance:
                                        mission_bp_chance[title_key] = contract_bp_chance

                            # Extract item rewards
                            null_uuid = "00000000-0000-0000-0000-000000000000"
                            if entity_names:
                                item_names = []
                                for item_elem in contract.findall(".//ContractResult_Item"):
                                    ec = item_elem.get("entityClass", "")
                                    if ec and ec != null_uuid and ec in entity_names:
                                        name = entity_names[ec]
                                        if name not in item_names:
                                            item_names.append(name)
                                for weighted_elem in contract.findall(".//ItemAwardEntityClass"):
                                    ec = weighted_elem.get("entityClass", "")
                                    if ec and ec != null_uuid and ec in entity_names:
                                        name = entity_names[ec]
                                        if name not in item_names:
                                            item_names.append(name)
                                if item_names and title_key not in mission_items:
                                    mission_items[title_key] = item_names

                            # Extract XP from ContractResult_LegacyReputation blocks
                            # First block with positive XP = success, first with negative = failure
                            legacy_reps = contract.findall(".//ContractResult_LegacyReputation")
                            success_xp = 0
                            failure_xp = 0

                            for legacy_rep in legacy_reps:
                                rep_amount = legacy_rep.find("contractResultReputationAmounts")
                                if rep_amount is not None:
                                    reward_uuid = rep_amount.get("reward")
                                    if reward_uuid and reward_uuid in reputation_lookup:
                                        val = reputation_lookup[reward_uuid]
                                        if val > 0 and success_xp == 0:
                                            success_xp = val
                                        elif val < 0 and failure_xp == 0:
                                            failure_xp = val

                            # Fallback: some contracts (e.g. CleanAir bulk hauls)
                            # use ContractResult_ScenarioProgress with a flat
                            # PointsToAward attribute instead of LegacyReputation.
                            # First missionResults Bool="1" marks it as the
                            # success-outcome reward.
                            if success_xp == 0:
                                for sp in contract.findall(".//ContractResult_ScenarioProgress"):
                                    points = sp.get("PointsToAward", "")
                                    if not points:
                                        continue
                                    first_result = sp.find("./missionResults/Bool")
                                    if first_result is None or first_result.get("value") != "1":
                                        continue
                                    try:
                                        val = int(float(points))
                                    except (ValueError, TypeError):
                                        continue
                                    if val > 0:
                                        success_xp = val
                                        break

                            # Extract per-contract flags (starter = no minStanding requirement)
                            contract_flags = list(handler_flags)  # inherit handler flags
                            contract.get("minStanding", "")
                            null_uuid = "00000000-0000-0000-0000-000000000000"
                            # A contract with no standing requirement at handler intro level is a starter
                            # (detected by debugName containing "Intro" or being first in a career chain)
                            contract_debug = contract.get("debugName", "")
                            if "Intro" in contract_debug or "intro" in contract_debug:
                                if "Starter" not in contract_flags:
                                    contract_flags.append("Starter")

                            # Extract per-contract spawn counts (fallback to handler-level)
                            _, contract_enemies, contract_not_enemies = _extract_spawn_counts(contract)
                            enemies = contract_enemies or handler_enemies
                            not_enemies = contract_not_enemies or handler_not_enemies

                            # Extract per-contract difficulty
                            contract_difficulty = _extract_difficulty(contract)

                            # Add all missions (not just those with XP/blueprint data)
                            if title_key not in missions:
                                missions[title_key] = []
                            missions[title_key].append(
                                (
                                    system_name,
                                    success_xp,
                                    failure_xp,
                                    desc_key,
                                    contract_flags,
                                    enemies,
                                    not_enemies,
                                    contract_difficulty,
                                    contract_has_bp,
                                    contract_bp_chance,
                                    contract_bp_variant,
                                )
                            )
                        except Exception:
                            pass

        # Sort variants by system name for consistent output (Stanton first, then others alphabetically)
        for title_key in missions:
            missions[title_key].sort(key=lambda v: (v[0] != "Stanton", v[0]))

    except Exception as e:
        logger.warning(f"Error scanning contract generators: {e}")

    logger.info(
        f"Contract generators: {len(missions)} missions, {len(mission_blueprints)} with blueprints, {len(mission_items)} with items"
    )
    return missions, mission_blueprints, mission_bp_chance, mission_items


def _resolve_resource_uuids(bp_dir: Path) -> set[str]:
    """Collect all CraftingCost_Resource UUIDs referenced in blueprint XMLs."""
    uuids: set[str] = set()
    if not bp_dir.exists():
        return uuids
    for xml_file in bp_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            for elem in root.iter():
                if _poly_type(elem) == "CraftingCost_Resource":
                    r = elem.get("resource", "")
                    if r and r != "00000000-0000-0000-0000-000000000000":
                        uuids.add(r)
        except ET.ParseError:
            pass
    return uuids


def _poly_type(elem: ET.Element) -> str:
    """Return the effective polymorphic type of a DataForge element.

    Historically CIG/unforge emitted elements like
    ``<CraftingProcess_Base __polymorphicType="CraftingProcess_Creation" ... />``
    and the generator filtered on the attribute. Newer unforge builds drop
    ``__type``/``__polymorphicType`` entirely and emit the concrete type as
    the element tag itself
    (``<CraftingProcess_Creation ... />``), which silently zeros out every
    attribute-based filter. Returning ``__polymorphicType or elem.tag`` makes
    every call site compatible with both formats without branching.
    """
    return elem.get("__polymorphicType") or elem.tag


def _normalize_commodity_name(raw: str) -> str:
    """Strip ore_/raw-style prefixes and suffixes to get the canonical commodity stem.

    CIG has multiple carryable variants per commodity — refined (``commodity_metal_iron``),
    raw ore (``commodity_metal_ore_iron`` or ``commodity_mineral_hephaestanite_raw``),
    processed, etc. — and the regex used to extract the stem sometimes captures the
    variant prefix/suffix. Normalize everything back to the commodity root so the
    downstream loc-key lookup finds a match.
    """
    n = raw.lower()
    for prefix in ("ore_", "raw_", "processed_", "refined_"):
        if n.startswith(prefix):
            n = n[len(prefix) :]
    for suffix in ("_ore", "_raw", "_processed", "_refined"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


def _build_uuid_to_commodity(uuids: set[str], carryables_dir: Path) -> dict[str, str]:
    """Map resource UUIDs to commodity internal names by scanning carryable entity files."""
    uuid_names: dict[str, str] = {}
    if not carryables_dir.exists() or not uuids:
        return uuid_names
    for xml_file in carryables_dir.rglob("*.xml"):
        try:
            content = xml_file.read_text(encoding="utf-8", errors="ignore")
            matched_uuids = [u for u in uuids if u in content]
            if not matched_uuids:
                continue
            fname = xml_file.stem
            m = re.search(r"commodity_(?:metal|mineral|minerals|nonmetal|gas)_(\w+?)(?:_[a-d])?$", fname)
            if m:
                commodity = _normalize_commodity_name(m.group(1))
                for uid in matched_uuids:
                    uuid_names[uid] = commodity
        except Exception:
            pass
    return uuid_names


def _discover_commodity_loc_pairs(internal_name: str, loc: dict[str, str]) -> list[tuple[str, str]]:
    """Find every (name_key, desc_key) pair in *loc* for a given commodity stem.

    Scans loc case-insensitively for ``items_commodities_<name>*`` keys and pairs
    each name-style key (refined, _ore, _raw, etc.) with its matching desc key.
    CIG's loc typos mean descs may end in either ``_desc`` or ``_des`` — both are
    accepted. Returning every matching variant means a refined and a raw form
    both get the [CF] tag + BLUEPRINT DATA block.
    """
    prefix = f"items_commodities_{internal_name.lower()}"
    name_keys: list[str] = []
    desc_by_base: dict[str, str] = {}  # lowercase name stem -> actual desc key

    for key in loc:
        klow = key.lower()
        if not klow.startswith(prefix):
            continue
        if klow.endswith("_desc"):
            desc_by_base[klow[:-5]] = key
        elif klow.endswith("_des"):
            desc_by_base.setdefault(klow[:-4], key)
        else:
            name_keys.append(key)

    pairs: list[tuple[str, str]] = []
    for name_key in name_keys:
        desc_key = desc_by_base.get(name_key.lower())
        if desc_key:
            pairs.append((name_key, desc_key))
    return pairs


def _condense_crafted_items(items_list: list[tuple[str, str]]) -> list[str]:
    """Condense crafted items into readable summary lines, grouped by blueprint category."""
    from collections import defaultdict

    by_cat: dict[str, list[str]] = defaultdict(list)
    for cat, name in items_list:
        by_cat[cat].append(name)
    lines = []
    for cat in sorted(by_cat.keys()):
        names = sorted(set(by_cat[cat]))
        parts = cat.split("/")
        if "ammo" in cat:
            ammo_type = parts[-1].title() if len(parts) > 2 else "Ammo"
            lines.append(f"{ammo_type} Ammo")
            continue
        if "weapons" in cat:
            base_names = set()
            for n in names:
                clean = re.sub(r'\s*"[^"]*"\s*', " ", n).strip()
                clean = re.sub(r"\s+", " ", clean)
                base_names.add(clean)
            if len(base_names) <= 3:
                lines.append(", ".join(sorted(base_names)))
            else:
                weapon_type = parts[-1].title()
                lines.append(f"{weapon_type}s ({len(base_names)} types)")
            continue
        if "armour" in cat:
            weight = parts[-1].title() if len(parts) > 2 else ""
            armour_type = parts[-2].title() if len(parts) > 2 else "Armour"
            set_names = set()
            for n in names:
                m2 = re.match(r"^([\w-]+(?:\s[\w-]+)?)\s+(?:Arms|Core|Legs|Helmet|Backpack|Suit|Armor)", n)
                if m2:
                    set_names.add(m2.group(1))
                else:
                    set_names.add(n.split()[0] if n else n)
            if len(set_names) <= 3:
                label = ", ".join(sorted(set_names))
            else:
                label = f"{len(set_names)} sets"
            if weight and armour_type != weight:
                lines.append(f"{label} ({weight} {armour_type})")
            else:
                lines.append(f"{label} ({armour_type})")
            continue
        lines.append(f"{cat}: {len(names)} items")
    return lines


def scan_crafting_blueprints(
    bp_dir: Path,
    carryables_dir: Path,
    entity_names: dict[str, str],
    loc: dict[str, str],
) -> dict[str, str]:
    """Scan crafting blueprints and produce commodity_crafting_stats entries.

    Returns a dict of localization key → augmented value for commodity names and
    descriptions that are used as crafting materials.
    """
    import os
    from collections import defaultdict

    if not bp_dir.exists():
        logger.info("No crafting blueprints directory found")
        return {}

    # Step 1: Collect resource UUIDs from blueprints
    resource_uuids = _resolve_resource_uuids(bp_dir)
    logger.info(f"Found {len(resource_uuids)} unique resource UUIDs in blueprints")

    # Step 2: Resolve UUIDs to commodity names via carryables
    uuid_names = _build_uuid_to_commodity(resource_uuids, carryables_dir)
    logger.info(f"Resolved {len(uuid_names)} resource UUIDs to commodity names")

    # Step 3: Parse blueprints to build commodity → crafted items map
    commodity_items: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for xml_file in sorted(bp_dir.rglob("*.xml")):
        try:
            root = ET.parse(xml_file).getroot()
            rel = xml_file.relative_to(bp_dir)
            category = str(rel.parent).replace(os.sep, "/")
            item_name = xml_file.stem.replace("bp_craft_", "")
            # Try to resolve display name from entity reference
            for elem in root.iter():
                if _poly_type(elem) == "CraftingProcess_Creation":
                    entity_ref = elem.get("entityClass", "")
                    if entity_ref in entity_names:
                        item_name = entity_names[entity_ref]
                    break
            materials: set[str] = set()
            for elem in root.iter():
                if _poly_type(elem) == "CraftingCost_Resource":
                    r = elem.get("resource", "")
                    if r in uuid_names:
                        materials.add(uuid_names[r])
            for mat in materials:
                commodity_items[mat].append((category, item_name))
        except ET.ParseError:
            pass

    # Sanity-check that the localization dict actually carries commodity keys.
    # Hitting 0 here almost always means base.ini is stale (missing modern
    # commodity strings) — surfacing that in the log beats silently writing an
    # empty enhancements file.
    loc_commodity_key_count = sum(1 for k in loc if k.lower().startswith("items_commodities_"))
    logger.info(
        f"Crafting: {len(commodity_items)} commodities discovered from blueprints; "
        f"{loc_commodity_key_count} items_commodities_* keys in loc"
    )

    # Build commodity output via dynamic loc discovery — no hardcoded key map.
    # Each commodity stem (iron, hephaestanite, …) pulls every matching loc
    # variant (refined, _ore, _raw, etc.) so the freight-elevator view tags
    # every form the player might see.
    out: dict[str, str] = {}
    skipped_no_loc: list[str] = []
    for commodity in sorted(commodity_items.keys()):
        pairs = _discover_commodity_loc_pairs(commodity, loc)
        if not pairs:
            skipped_no_loc.append(commodity)
            continue
        condensed = _condense_crafted_items(commodity_items[commodity])
        bp_block = "\\n".join(f"- {line}" for line in condensed)
        enhancements_block = f"<EM3>BLUEPRINT DATA</EM3>\\n{bp_block}"

        for name_key, desc_key in pairs:
            base_name = loc.get(name_key, "")
            if base_name and name_key not in out:
                out[name_key] = f"{base_name} <EM4>[CF]</EM4>"

            base_desc = loc.get(desc_key, "")
            if base_desc and desc_key not in out:
                out[desc_key] = f"{base_desc}\\n\\n{enhancements_block}"

    if skipped_no_loc:
        logger.warning(
            f"Crafting: {len(skipped_no_loc)} commodities had no matching loc keys "
            f"(first few: {', '.join(skipped_no_loc[:8])})"
        )
    logger.info(f"Crafting: {len(out)} commodity entries augmented from {len(commodity_items)} commodities")

    # Build journal output (separate dict for independent toggling)
    out_journal: dict[str, str] = {}
    journal_title_key = "Journal_General_Mining_Compendium_Title"
    journal_content_key = "Journal_General_Mining_Compendium_Content"
    base_title = loc.get(journal_title_key, "")
    base_content = loc.get(journal_content_key, "")

    if base_title and base_content:
        out_journal[journal_title_key] = f"{base_title} <EM4>[SmC]</EM4>"

        mineral_crafting: dict[str, str] = {}
        for internal_name, items in commodity_items.items():
            condensed = _condense_crafted_items(items)
            if condensed:
                mineral_crafting[internal_name] = ", ".join(condensed)

        lines = base_content.split("\\n\\n")
        augmented_lines = []
        for line in lines:
            dash_idx = line.find(" - ")
            if dash_idx > 0:
                mineral_display = line[:dash_idx].strip()
                mineral_lower = mineral_display.lower()
                if mineral_lower in mineral_crafting:
                    line = f"{line}\\n  <EM4>>> Crafting:</EM4> {mineral_crafting[mineral_lower]}"
            augmented_lines.append(line)

        out_journal[journal_content_key] = "\\n\\n".join(augmented_lines)
        logger.info(f"Journal: augmented Mining Compendium with crafting data for {len(mineral_crafting)} minerals")

    return out, out_journal


def enhancements_weapon(
    root: ET.Element,
    ammo_lookup: dict[str, ET.Element],
    loc: dict | None = None,
    magazine_lookup: dict[str, tuple[str, str]] | None = None,
) -> str:
    """Ship or FPS weapon stats."""
    fr = _fire_rate(root)
    modes = _fire_modes(root, loc)
    pwr = _find_resource(root, "Power")

    # Component health / signatures / heat
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")
    overheat = _attr(root, "itemResourceParams", "overheatTemperature")

    # Weight (mass from physics controller)
    weight = None
    for elem in root.iter():
        pt = _poly_type(elem)
        if "RigidPhysics" in pt or "StaticPhysics" in pt:
            mass_val = elem.get("Mass")
            if mass_val:
                try:
                    weight = float(mass_val)
                except ValueError:
                    pass
            break

    # Pellet count (shotguns fire multiple pellets per shot)
    pellet_count = 1
    for elem in root.iter():
        if "SProjectileLauncher" in _poly_type(elem):
            try:
                pc = int(elem.get("pelletCount", "1"))
                if pc > 1:
                    pellet_count = pc
            except ValueError:
                pass
            break

    # Ammo damage — look up the ammo record by GUID
    ammo_container = _find(root, "SAmmoContainerComponentParams")
    ammo_record_id = ammo_container.get("ammoParamsRecord") if ammo_container is not None else None
    capacity = None

    # Fallback: for FPS weapons without inline ammo container, follow the magazine port chain
    if not ammo_record_id or ammo_record_id == "00000000-0000-0000-0000-000000000000":
        if magazine_lookup:
            for elem in root.iter():
                port_name = elem.get("itemPortName", "")
                entity_class = elem.get("entityClassName", "")
                if "magazine" in port_name.lower() and entity_class:
                    mag_info = magazine_lookup.get(entity_class)
                    if mag_info:
                        ammo_record_id, mag_capacity = mag_info
                        if mag_capacity:
                            capacity = mag_capacity
                    break

    total_dmg = breakdown = proj_speed = proj_lifetime = None
    dps = None
    ammo_root = None
    dmg_drop_min_dist = dmg_drop_per_m = dmg_drop_min = None
    if ammo_record_id and ammo_record_id != "00000000-0000-0000-0000-000000000000":
        ammo_root = ammo_lookup.get(ammo_record_id)
        if ammo_root is not None:
            total_dmg, breakdown = _ammo_damage_breakdown(ammo_root)
            # Multiply by pellet count for shotguns
            if pellet_count > 1 and total_dmg:
                total_dmg *= pellet_count
                breakdown = {k: v * pellet_count for k, v in breakdown.items()}
            # Try multiple field names for projectile speed (varies by ammo type)
            proj_speed = (
                ammo_root.get("speed")
                or ammo_root.get("velocity")
                or ammo_root.get("projectileSpeed")
                or ammo_root.get("initialSpeed")
            )
            # Try multiple field names for lifetime
            proj_lifetime = (
                ammo_root.get("lifetime") or ammo_root.get("projectileLifetime") or ammo_root.get("maxLifetime")
            )
            if total_dmg and fr:
                try:
                    dps = total_dmg * float(fr) / 60.0
                except ValueError:
                    pass

            # Damage drop-off parameters
            for elem in ammo_root.iter():
                tag = elem.tag
                if tag == "damageDropMinDistance":
                    for d in elem:
                        if _poly_type(d) == "DamageInfo" or "DamageInfo" in d.tag:
                            try:
                                dmg_drop_min_dist = float(d.get("DamagePhysical", 0)) + float(d.get("DamageEnergy", 0))
                            except ValueError:
                                pass
                elif tag == "damageDropPerMeter":
                    for d in elem:
                        if _poly_type(d) == "DamageInfo" or "DamageInfo" in d.tag:
                            try:
                                dmg_drop_per_m = float(d.get("DamagePhysical", 0)) + float(d.get("DamageEnergy", 0))
                            except ValueError:
                                pass
                elif tag == "damageDropMinDamage":
                    for d in elem:
                        if _poly_type(d) == "DamageInfo" or "DamageInfo" in d.tag:
                            try:
                                dmg_drop_min = float(d.get("DamagePhysical", 0)) + float(d.get("DamageEnergy", 0))
                            except ValueError:
                                pass

    # Capacity: energy weapons use regen pool; ballistic use fixed container
    regen = _find(root, "SWeaponRegenConsumerParams")
    regen_rate = regen_cooldown = regen_cost = None
    if regen is not None:
        if not capacity:
            capacity = regen.get("maxAmmoLoad")
        regen_rate = regen.get("requestedRegenPerSec")
        regen_cooldown = regen.get("regenerationCooldown")
        regen_cost = regen.get("regenerationCostPerBullet")
    elif ammo_container is not None and not capacity:
        capacity = ammo_container.get("maxAmmoCount")

    lines = []
    if weight is not None and weight > 0:
        lines.append(f"Weight: {weight:.1f} kg")
    if fr:
        lines.append(f"Fire Rate: {_fmt(fr, ' RPM')}")
    if modes:
        lines.append(f"Fire Modes: {' / '.join(modes)}")

    # Damage line with per-type breakdown
    if total_dmg is not None and total_dmg > 0:
        type_str = ""
        if breakdown and len(breakdown) == 1:
            type_str = f" ({list(breakdown.keys())[0]})"
        elif breakdown and len(breakdown) > 1:
            type_str = " (" + " / ".join(f"{lbl}: {v:.1f}" for lbl, v in breakdown.items()) + ")"
        pellet_str = f" x{pellet_count}" if pellet_count > 1 else ""
        dmg_part = f"Alpha Dmg: {_fmt(total_dmg, '', 1)}{pellet_str}{type_str}"
        dps_part = f"DPS: {_fmt(dps, '', 1)}" if dps else ""
        lines.append("  |  ".join(p for p in [dmg_part, dps_part] if p))

    if capacity:
        lines.append(f"Ammo: {_fmt(capacity)}")
    if regen_rate or regen_cooldown:
        parts = []
        if regen_rate:
            parts.append(f"Regen: {_fmt(regen_rate)}/s")
        if regen_cooldown:
            parts.append(f"Cooldown: {_fmt(regen_cooldown, 's', 1)}")
        if regen_cost:
            parts.append(f"Cost/Shot: {_fmt(regen_cost)}")
        lines.append("  |  ".join(parts))
    if proj_speed is not None:
        try:
            speed_f = float(proj_speed)
            lifetime_f = float(proj_lifetime)
            rng_m = speed_f * lifetime_f
            # FPS weapons get "Absolute Range" (clearer in-context — these
            # values are the projectile despawn distance, not effective
            # range); ship weapons keep "Range" since the field has been
            # stable there for releases. magazine_lookup is the FPS
            # discriminator — only the FPS callsite passes it.
            range_label = "Absolute Range" if magazine_lookup is not None else "Range"
            if rng_m >= 1000:
                lines.append(f"Velocity: {_fmt(proj_speed, ' m/s')}  |  {range_label}: {rng_m / 1000:,.1f} km")
            else:
                lines.append(f"Velocity: {_fmt(proj_speed, ' m/s')}  |  {range_label}: {rng_m:,.0f} m")
        except (TypeError, ValueError):
            pass

    # Damage drop-off
    if dmg_drop_min_dist is not None and dmg_drop_min_dist > 0:
        drop_parts = [f"Full Dmg to: {dmg_drop_min_dist:.0f} m"]
        if dmg_drop_per_m is not None and dmg_drop_per_m > 0:
            drop_parts.append(f"Drop: -{dmg_drop_per_m:.2f}/m")
        if dmg_drop_min is not None and dmg_drop_min > 0:
            drop_parts.append(f"Min Dmg: {dmg_drop_min:.1f}")
        lines.append("  |  ".join(drop_parts))

    if pwr:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None:
            parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None:
            parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))
    # Overheat temp is meaningful for ship weapons but not surfaced in-game
    # for FPS weapons; skip it on the FPS path (magazine_lookup is the FPS
    # discriminator — only the FPS callsite passes it).
    if overheat is not None and magazine_lookup is None:
        try:
            if float(overheat) < _OVERHEAT_PLACEHOLDER:
                lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
        except (ValueError, TypeError):
            lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
    return "\\n".join(lines)


# ── Ship enhancements (DataForge-based) ──────────────────────────────────────────────


def _extract_item_size(cls: str) -> str | None:
    """Extract size code from entity class name, e.g. 'SHLD_ASAS_S01_Shimmer_SCItem' → 'S1'."""
    m = re.search(r"_S0*(\d+)_", cls)
    return f"S{int(m.group(1))}" if m else None


def _loadout_summary(root: ET.Element) -> tuple[str, str]:
    """Parse SEntityComponentDefaultLoadoutParams and return (weapons_line, core_line).

    Only iterates TOP-LEVEL ship hardpoints (not nested sub-items inside turrets or
    mounted equipment) to avoid double-counting turret weapon slots as ship guns.

    Gun detection handles two naming conventions:
    - Avenger-style fixed slot: hardpoint_weapon_gun_class1_*  (size in port name)
    - Connie-style gimbal/fixed mount: hardpoint_weapon_* with Mount_Gimbal_S3 entity
      → size extracted from mount entity class name (Mount_Gimbal_S3 → S3)
    """
    guns: list[tuple[str, bool]] = []  # (size_str, filled)
    turrets: list[tuple[str, bool]] = []
    mracks: list[tuple[str, bool]] = []
    shields: list[str] = []  # size strings for filled slots
    powers: list[str] = []
    coolers: list[str] = []
    qd: list[str] = []

    # Only process direct children of the top-level loadout entries element
    # to avoid counting nested sub-weapon slots inside turrets/mounts
    comp = _find(root, "SEntityComponentDefaultLoadoutParams")
    if comp is None:
        return "", ""
    top_entries = comp.find(".//entries")
    if top_entries is None:
        return "", ""

    for entry in top_entries:
        if entry.tag != "SItemPortLoadoutEntryParams":
            continue
        port = entry.get("itemPortName", "").lower()
        cls = entry.get("entityClassName", "")

        if "controller" in port:
            continue

        # Size: _classN in port name (Avenger-style), or _S0N_ in entity class name
        sz = None
        m = re.search(r"_class_?(\d+)", port)
        if m:
            sz = f"S{int(m.group(1))}"
        elif cls:
            sz = _extract_item_size(cls)

        # Gimbal/fixed mount → counts as a gun slot; size from the mount entity (Mount_Gimbal_S3)
        if cls.startswith("Mount_Gimbal_") or cls.startswith("Mount_Fixed_"):
            guns.append((sz or "?", True))  # mount exists = slot is equipped
        # Avenger-style bare gun slot (may be empty)
        elif "weapon_gun" in port:
            guns.append((sz or "?", bool(cls)))
        elif "turret" in port and cls:
            turrets.append((sz or "?", bool(cls)))
        elif "missilerack" in port or "missilelauncher" in port:
            if cls:
                mracks.append((sz or "?", True))
        elif "shield_generator" in port and cls:
            shields.append(sz or "?")
        elif ("power_plant" in port or "powerplant" in port) and cls:
            powers.append(sz or "?")
        elif "cooler" in port and cls:
            coolers.append(sz or "?")
        elif "quantum_drive" in port and "fuel" not in port and cls:
            qd.append(sz or "?")

    def summarize_slots(slots: list[tuple[str, bool]]) -> str:
        counts: dict = {}
        for sz, filled in slots:
            key = (sz, filled)
            counts[key] = counts.get(key, 0) + 1
        parts = []
        for (sz, filled), cnt in sorted(counts.items()):
            suffix = "" if filled else " (empty)"
            if sz == "?":
                # Unknown size: show just count (e.g. turrets with no size info)
                parts.append(str(cnt))
            else:
                n = f"{cnt}× " if cnt > 1 else ""
                parts.append(f"{n}{sz}{suffix}")
        return "  ".join(p for p in parts if p)

    def summarize_items(sizes: list[str]) -> str:
        counts: dict = {}
        for sz in sizes:
            counts[sz] = counts.get(sz, 0) + 1
        parts = []
        for sz, cnt in sorted(counts.items()):
            n = f"{cnt}× " if cnt > 1 else ""
            parts.append(f"{n}{sz}")
        return "  ".join(parts)

    weapon_parts = []
    if guns:
        weapon_parts.append(f"Guns: {summarize_slots(guns)}")
    if turrets:
        weapon_parts.append(f"Turrets: {summarize_slots(turrets)}")
    if mracks:
        weapon_parts.append(f"MRacks: {summarize_slots(mracks)}")

    core_parts = []
    if shields:
        core_parts.append(f"Shields: {summarize_items(shields)}")
    if coolers:
        core_parts.append(f"Coolers: {summarize_items(coolers)}")
    if powers:
        core_parts.append(f"Power: {summarize_items(powers)}")
    if qd:
        core_parts.append(f"QD: {summarize_items(qd)}")

    return "  |  ".join(weapon_parts), "  |  ".join(core_parts)


def build_controller_lookup(controller_dir: Path) -> dict[str, ET.Element]:
    """Build lookup: ship_class_lower → flight controller XML root.

    Controller files are named 'controller_flight_{ship_class}.xml'.
    Blade/variant controllers (with '_flight_' in the class suffix) are
    included so each spaceship entity can find its exact match.
    """
    lookup: dict[str, ET.Element] = {}
    if not controller_dir.exists():
        logger.warning(f"Controller dir not found: {controller_dir}")
        return lookup
    for xml_file in controller_dir.glob("controller_flight_*.xml"):
        ship_class = xml_file.stem[len("controller_flight_") :]
        try:
            root = ET.parse(xml_file).getroot()
            lookup[ship_class.lower()] = root
        except ET.ParseError:
            pass
    return lookup


def build_armor_lookup(armor_dir: Path) -> dict[str, ET.Element]:
    """Build lookup: armor_class_lower → armor entity XML root.

    Armor files live at entities/scitem/ships/armor/*.xml and each has a root
    tag of the form 'EntityClassDefinition.ARMR_<MFR>_<ShipName>'. Ships
    reference them by entityClassName on an SItemPortLoadoutEntryParams with
    itemPortName='hardpoint_armour', so we index by the ClassName part
    lowercased for case-insensitive matching.
    """
    lookup: dict[str, ET.Element] = {}
    if not armor_dir.exists():
        return lookup
    for xml_file in armor_dir.glob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue
        tag = root.tag
        class_name = tag.split(".", 1)[1] if "." in tag else xml_file.stem
        lookup[class_name.lower()] = root
    return lookup


def _armor_stats_block(armor_root: ET.Element) -> str:
    """Format a ship armor record into stat lines (Health, Dmg Mult, Deflect).

    Returns lines already joined by the escaped '\\n' that the ini output
    layer uses (same convention as the rest of enhancements_ship_dataforge).
    """
    lines: list[str] = []

    health = _attr(armor_root, "SHealthComponentParams", "Health")
    if health is not None:
        lines.append(f"Armor HP: {_fmt(health)}")

    dm = _find(armor_root, "damageMultiplier")
    if dm is not None:
        di = dm.find("DamageInfo")
        if di is not None:
            p, e, d, t = (di.get(k) for k in ("DamagePhysical", "DamageEnergy", "DamageDistortion", "DamageThermal"))
            if any(v is not None for v in (p, e, d, t)):
                lines.append(
                    f"Dmg Mult: P {_fmt(p, 'x', 2)}  |  E {_fmt(e, 'x', 2)}"
                    f"  |  D {_fmt(d, 'x', 2)}  |  T {_fmt(t, 'x', 2)}"
                )

    ad = _find(armor_root, "armorDeflection")
    if ad is not None:
        dv = ad.find("deflectionValue")
        if dv is not None:
            p, e, d, t = (dv.get(k) for k in ("DamagePhysical", "DamageEnergy", "DamageDistortion", "DamageThermal"))
            if any(v is not None for v in (p, e, d, t)):
                lines.append(f"Deflect: P {_fmt(p)}  |  E {_fmt(e)}  |  D {_fmt(d)}  |  T {_fmt(t)}")

    return "\\n".join(lines)


def enhancements_ship_dataforge(
    root: ET.Element,
    controller_root: ET.Element | None,
    loc: dict | None = None,
    armor_lookup: dict[str, ET.Element] | None = None,
) -> str:
    """Generate stats block for a spaceship from DataForge entity + flight controller."""
    vpc = _find(root, "VehicleComponentParams")
    if vpc is None:
        return ""

    crew_size = vpc.get("crewSize")
    career_key = (vpc.get("vehicleCareer") or "").lstrip("@")
    role_key = (vpc.get("vehicleRole") or "").lstrip("@")
    career = (loc or {}).get(career_key) if career_key else None
    role = (loc or {}).get(role_key) if role_key else None

    bbox = vpc.find("maxBoundingBoxSize")
    length = bbox.get("y") if bbox is not None else None

    # Insurance — DataForge tag is lowercase 'shipInsuranceParams', __type is 'ShipInsuranceParams'
    ins = _find(root, "shipInsuranceParams")
    ins_base = ins.get("baseWaitTimeMinutes") if ins is not None else None
    ins_express = ins.get("mandatoryWaitTimeMinutes") if ins is not None else None

    # Default loadout summary
    weapons_line, core_line = _loadout_summary(root)

    # Default armor (via hardpoint_armor/hardpoint_armour loadout entry → armor
    # XML lookup). Both spellings appear in the data — American form is more
    # common (~554 ships) but some use British (~262).
    armor_block = ""
    if armor_lookup:
        for entry in root.iter("SItemPortLoadoutEntryParams"):
            if entry.get("itemPortName") in ("hardpoint_armor", "hardpoint_armour"):
                armor_class = (entry.get("entityClassName") or "").lower()
                if armor_class:
                    armor_root = armor_lookup.get(armor_class)
                    if armor_root is not None:
                        armor_block = _armor_stats_block(armor_root)
                break

    # Flight stats from controller
    scm = max_spd = boost_fwd = boost_bwd = None
    pitch = roll = yaw = None
    if controller_root is not None:
        ifcs = _find(controller_root, "IFCSParams")
        if ifcs is not None:
            scm = ifcs.get("scmSpeed")
            max_spd = ifcs.get("maxSpeed")
            boost_fwd = ifcs.get("boostSpeedForward")
            boost_bwd = ifcs.get("boostSpeedBackward")
        sp = _find_by_type(controller_root, "SIFCSSpeedProfile")
        if sp is not None:
            av = sp.find("angularVelocity")
            if av is not None:
                pitch = av.get("x")  # pitch rate °/s
                roll = av.get("y")  # roll rate  °/s
                yaw = av.get("z")  # yaw rate   °/s

    lines = []

    if scm is not None or max_spd is not None:
        lines.append(f"SCM: {_fmt(scm, ' m/s')}  |  Max: {_fmt(max_spd, ' m/s')}")
    if boost_fwd is not None or boost_bwd is not None:
        lines.append(f"Boost: +{_fmt(boost_fwd, ' m/s')}  /  -{_fmt(boost_bwd, ' m/s')}")
    if pitch is not None:
        lines.append(f"Pitch: {_fmt(pitch, '°/s')}  |  Roll: {_fmt(roll, '°/s')}  |  Yaw: {_fmt(yaw, '°/s')}")

    basics = []
    if crew_size is not None:
        basics.append(f"Crew: {_fmt(crew_size)}")
    if length is not None:
        basics.append(f"Length: {_fmt(length, 'm', 1)}")
    if career is not None:
        basics.append(f"Class: {career}")
    if role is not None:
        basics.append(f"Role: {role}")
    if basics:
        lines.append("  |  ".join(basics))

    if weapons_line:
        lines.append(weapons_line)
    if core_line:
        lines.append(core_line)
    if armor_block:
        lines.append(armor_block)

    if ins_base is not None:
        lines.append(f"Insurance: {_fmt(ins_base, ' min', 2)} base  |  {_fmt(ins_express, ' min', 2)} express")

    return "\\n".join(lines)


def scan_spaceships(
    spaceships_dir: Path,
    controller_lookup: dict,
    loc: dict,
    armor_lookup: dict | None = None,
) -> dict[str, str]:
    """Scan DataForge spaceship entities and generate ship stat descriptions."""
    out: dict[str, str] = {}
    matched = missed = skipped = 0

    for xml_file in sorted(spaceships_dir.glob("*.xml")):
        # Skip AI variants, templates, and unmanned variants
        stem = xml_file.stem.lower()
        if "_pu_ai_" in stem or "_ai_template" in stem or "_unmanned_" in stem:
            skipped += 1
            continue

        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        # Loc key from VehicleComponentParams.vehicleDescription
        vpc = _find(root, "VehicleComponentParams")
        if vpc is None:
            skipped += 1
            continue
        desc_attr = vpc.get("vehicleDescription", "")
        if not desc_attr.startswith("@") or _is_sentinel_loc_ref(desc_attr):
            skipped += 1
            continue
        loc_key = desc_attr.lstrip("@")

        base_value = loc.get(loc_key)
        if base_value is None:
            missed += 1
            continue

        # Match ship class to flight controller
        root_tag = root.tag
        ship_class = root_tag.split(".", 1)[1].lower() if "." in root_tag else stem
        controller_root = controller_lookup.get(ship_class)

        try:
            block = enhancements_ship_dataforge(root, controller_root, loc, armor_lookup)
        except Exception as e:
            logger.warning(f"Ship enhancements failed for {xml_file.name}: {e}")
            continue

        if block:
            # Deduplicate: first match for a given key wins
            if loc_key not in out:
                out[loc_key] = append_enhancements(base_value, block)
                matched += 1
        else:
            missed += 1

    logger.info(f"Spaceships: {matched} matched, {missed} no enhancements/key, {skipped} skipped (AI/templates)")
    return out


# ── Ammo lookup builder ───────────────────────────────────────────────────────


def build_ammo_lookup(ammo_dir: Path) -> dict[str, ET.Element]:
    """Parse all ammo XML files and index them by their __ref GUID.

    Falls back to root tag name if __ref is not available.
    """
    lookup: dict[str, ET.Element] = {}
    if not ammo_dir.exists():
        return lookup
    for xml_file in ammo_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            # Primary: use __ref attribute (GUID)
            ref = root.get("__ref")
            if ref:
                lookup[ref] = root
            # Fallback: index by file stem if no __ref (helps with FPS ammo)
            else:
                lookup[xml_file.stem] = root
        except ET.ParseError:
            pass
    return lookup


def build_scitem_lookups(
    scitem_dir: Path,
    loc: dict[str, str] | None = None,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Single-pass scan of scitem XMLs that produces two lookups:

    * mag_lookup: magazine entity class name → (ammoParamsRecord, maxAmmoCount)
      — derived from SAmmoContainerComponentParams elements.
    * entity_names: __ref UUID → display name (resolved via loc)
      — first @-prefixed Name attribute on any element.

    Walking the scitem tree once instead of twice (magazines + entity names
    used to iterate independently) cuts ~30s off the run since there are
    ~20k files under entities/scitem/.
    """
    mag_lookup: dict[str, tuple[str, str]] = {}
    entity_names: dict[str, str] = {}
    loc = loc or {}
    if not scitem_dir.exists():
        return mag_lookup, entity_names

    null_uuid = "00000000-0000-0000-0000-000000000000"
    for xml_file in scitem_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        ref = root.get("__ref", "")
        entity_name = root.tag.split(".")[-1] if "." in root.tag else xml_file.stem
        found_mag = False
        found_name = ref == ""  # skip name lookup entirely if no __ref

        for elem in root.iter():
            if not found_mag and _poly_type(elem) == "SAmmoContainerComponentParams":
                ammo_ref = elem.get("ammoParamsRecord", "")
                max_ammo = elem.get("maxAmmoCount", "")
                if ammo_ref and ammo_ref != null_uuid:
                    mag_lookup[entity_name] = (ammo_ref, max_ammo)
                found_mag = True
            if not found_name:
                name_attr = elem.get("Name", "")
                if name_attr and name_attr.startswith("@"):
                    loc_key = name_attr.lstrip("@")
                    entity_names[ref] = loc.get(loc_key, loc_key)
                    found_name = True
            if found_mag and found_name:
                break

    return mag_lookup, entity_names


def build_magazine_lookup(scitem_dir: Path) -> dict[str, tuple[str, str]]:
    """Back-compat wrapper around build_scitem_lookups — returns magazines only."""
    mag_lookup, _ = build_scitem_lookups(scitem_dir)
    return mag_lookup


# ── DataForge directory scanner ───────────────────────────────────────────────


def scan_entity_dir(
    entity_dir: Path,
    enhancement_fn,
    ammo_lookup: dict | None = None,
    loc: dict | None = None,
    loc_key_fn=None,
    generate_name_tags: bool = False,
    name_tag_fn=None,
    separator: str = ENHANCEMENT_SEPARATOR,
    capture_all: bool = False,
) -> dict[str, str]:
    """
    Scan all XML files in entity_dir, extract localization key + enhancements,
    and return {loc_key: augmented_value} for keys found in `loc`.

    ammo_lookup is passed to enhancement_fn only when it accepts it (weapons).
    loc is the base.ini localization dict for value lookup.
    loc_key_fn is an optional custom function to extract the localization key (defaults to _loc_key).
    generate_name_tags: if True, also generate item_Name* entries with [CLASS-SIZE-GRADE] tags
        derived from the component description text.
    capture_all: if True, emit entries even when enhancement_fn returns empty (for missions).
    """
    if loc_key_fn is None:
        loc_key_fn = _loc_key

    out: dict[str, str] = {}
    matched = missed = skipped = 0

    for xml_file in entity_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        key = loc_key_fn(root)
        if not key:
            skipped += 1
            continue

        base_value = (loc or {}).get(key)
        if base_value is None:
            missed += 1
            continue

        try:
            if ammo_lookup is not None:
                enhancements_block = enhancement_fn(root, ammo_lookup)
            else:
                enhancements_block = enhancement_fn(root)
        except Exception as e:
            logger.warning(f"Enhancements failed for {xml_file.name}: {e}")
            continue

        if enhancements_block:
            out[key] = append_enhancements(base_value, enhancements_block, separator)
            matched += 1
        elif capture_all:
            # Still emit the base value so all missions are captured
            if key not in out:
                out[key] = base_value
            matched += 1
        else:
            missed += 1

        # Generate item_Name* tag from description metadata (e.g., [MIL-S1-A]
        # or [S1-CS] for missiles). Also tag the matching *_short loc key
        # when base.ini carries one — the short name is what shows in
        # compact UI lanes (turret slots, loadout summaries, hangar cargo),
        # so the annotation is arguably more valuable there than on the
        # full name.
        if generate_name_tags and loc:
            name_key = _loc_name_key(root)
            if name_key:
                name_value = loc.get(name_key)
                if name_value:
                    tagger = name_tag_fn or _component_name_tag
                    tag = tagger(base_value, root)
                    if tag:
                        out[name_key] = f"{name_value} {tag}"
                        short_key = f"{name_key}_short"
                        short_value = loc.get(short_key)
                        if short_value:
                            out[short_key] = f"{short_value} {tag}"

    logger.info(f"{entity_dir.name}: {matched} matched, {missed} no enhancements, {skipped} no loc key")
    return out


# ── Main ──────────────────────────────────────────────────────────────────────


def main(
    base_ini_path: Path,
    forge_dir: Path | None = None,
    categories: set[str] | None = None,
    progress_callback: Callable[[int, int, str], None] | None = None,
    max_workers: int = 6,
    patches_dir: Path | None = None,
) -> None:
    import sys as sys_mod

    # Deferred import — the script is loaded by both the app worker (where
    # src.utils is on the path) and as a standalone CLI, so we swallow an
    # ImportError and run without a sink if the module isn't reachable.
    try:
        from src.utils.progress_sink import ProgressSink

        _sink = ProgressSink(callback=progress_callback)
    except ImportError:
        _sink = None

    def _flush():
        if sys_mod.stdout is not None:
            sys_mod.stdout.flush()
        if sys_mod.stderr is not None:
            sys_mod.stderr.flush()

    def _tick(message: str) -> None:
        """Mark a phase boundary: log, flush stdout, advance the progress sink."""
        logger.info(f"CHECKPOINT: {message}")
        _flush()
        if _sink is not None:
            _sink.advance(message=message)

    def _want(cat: str) -> bool:
        """Return True if *cat* should be generated (None means all)."""
        return categories is None or cat in categories

    logger.info("=== SC Enhancements INI Generator (DataForge edition) ===")
    if categories is not None:
        logger.info(f"Selective generation: {', '.join(sorted(categories))}")
    _flush()

    if forge_dir is None:
        forge_dir = DEFAULT_FORGE_DIR

    # Write output alongside the input base.ini. The module-level
    # OUTPUT_DIR constant is only used as a last-ditch fallback — it's
    # derived from the Windows "Personal" shell-folder key at import time
    # and therefore doesn't honor the AppSettings.USER_DATA_DIR override
    # (e.g. users who moved their data off a OneDrive-synced Documents).
    # Keying off base_ini_path.parent makes this script self-consistent
    # whether invoked from the CLI or from EnhancementsGeneratorWorker,
    # and keeps the cache co-located with the source data it reads.
    output_dir = base_ini_path.parent if base_ini_path.parent.exists() else OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Parse base.ini ─────────────────────────────────────────────────────────
    if not base_ini_path.exists():
        raise FileNotFoundError(f"base.ini not found at {base_ini_path}")
    loc = parse_ini(base_ini_path)
    logger.info(f"Loaded {len(loc):,} localization keys")
    _flush()

    # ── Check DataForge cache ─────────────────────────────────────────────────
    records = forge_dir / "raw" / "libs" / "foundry" / "records"
    if not forge_dir.exists() or not records.exists():
        raise FileNotFoundError(
            f"DataForge cache not found at {forge_dir}\nRun 'Extract DataForge' in the app first (Enhancements tab)."
        )

    # ── Estimate total phases for determinate progress ────────────────────────
    # One tick per logical phase. The sink caps at total, so over-counting is
    # safer than under-counting.
    need_mag = _want("ship_weapon_descs") or _want("fps_weapon_descs")
    need_names = _want("mission_rewards") or _want("commodity_crafting") or _want("journal")
    need_ammo = _want("ship_weapon_descs") or _want("fps_weapon_descs")
    phase_total = (
        1  # base.ini parsed
        + (1 if need_ammo else 0)
        + (1 if need_mag or need_names else 0)
        + (1 if _want("component_descs") else 0)
        + (1 if _want("missile_enhancements") else 0)
        + (1 if _want("ship_weapon_descs") else 0)
        + (1 if _want("fps_weapon_descs") else 0)
        + (2 if _want("ship_descs") else 0)  # controller+armor lookup, scan
        + (4 if _want("mission_rewards") else 0)  # rep lookup, scan, bp pools, contractgen+XP
        + (1 if _want("commodity_crafting") or _want("journal") else 0)
        + 1  # write files
    )
    if _sink is not None:
        _sink.set_total(phase_total)
    _tick(f"Loaded base.ini ({len(loc):,} keys)")

    # ── Parallel build of independent lookups (Group A) ───────────────────────
    # vehicle_ammo, fps_ammo, scitem_lookups, controller_lookup, armor_lookup,
    # and reputation_lookup have no cross-dependencies and are dominated by
    # XML parse + file I/O. Builders are pure: each returns a dict that is
    # never mutated again, so thread-safe by construction. _cached_lookup
    # writes to per-name pickle files, so parallel cache writes don't collide.
    vehicle_ammo: dict = {}
    fps_ammo: dict = {}
    mag_lookup: dict = {}
    entity_names: dict[str, str] = {}
    controller_lookup: dict = {}
    armor_lookup: dict = {}
    reputation_lookup: dict[str, int] = {}

    def _build_scitem_pair():
        return _cached_lookup(
            forge_dir,
            "scitem_lookups",
            lambda: build_scitem_lookups(records / "entities" / "scitem", loc),
        )

    def _build_reputation():
        rep_rewards_dir = records / "reputation" / "rewards" / "missionrewards_reputation"

        def _builder() -> dict[str, int]:
            out: dict[str, int] = {}
            if not rep_rewards_dir.exists():
                return out
            for xml_file in rep_rewards_dir.rglob("*.xml"):
                try:
                    root = ET.parse(xml_file).getroot()
                    uuid = root.get("__ref")
                    rep_amount = root.get("reputationAmount")
                    if uuid and rep_amount:
                        try:
                            out[uuid] = int(float(rep_amount))
                        except (ValueError, TypeError):
                            pass
                except ET.ParseError:
                    continue
            return out

        return _cached_lookup(forge_dir, "reputation", _builder)

    lookup_jobs: dict[str, Callable] = {}
    if need_ammo:
        lookup_jobs["vehicle_ammo"] = lambda: build_ammo_lookup(records / "ammoparams" / "vehicle")
        lookup_jobs["fps_ammo"] = lambda: build_ammo_lookup(records / "ammoparams" / "fps")
    if need_mag or need_names:
        lookup_jobs["scitem"] = _build_scitem_pair
    if _want("ship_descs"):
        lookup_jobs["controller"] = lambda: build_controller_lookup(
            records / "entities" / "scitem" / "ships" / "controller"
        )
        lookup_jobs["armor"] = lambda: build_armor_lookup(records / "entities" / "scitem" / "ships" / "armor")
    if _want("mission_rewards"):
        lookup_jobs["reputation"] = _build_reputation

    if lookup_jobs:
        logger.info(f"Building {len(lookup_jobs)} lookups in parallel (workers={min(max_workers, len(lookup_jobs))})…")
        _flush()
        with ThreadPoolExecutor(max_workers=min(max_workers, len(lookup_jobs)), thread_name_prefix="lookup") as pool:
            futures = {name: pool.submit(fn) for name, fn in lookup_jobs.items()}
            results = {name: fut.result() for name, fut in futures.items()}

        if "vehicle_ammo" in results:
            vehicle_ammo = results["vehicle_ammo"]
            fps_ammo = results["fps_ammo"]
            logger.info(f"Vehicle ammo: {len(vehicle_ammo)} records, FPS ammo: {len(fps_ammo)} records")
            _tick("Built ammo lookups")
        if "scitem" in results:
            mag_lookup, entity_names = results["scitem"]
            logger.info(f"Magazine lookup: {len(mag_lookup)} entries, Entity names: {len(entity_names)} entries")
            _tick("Built scitem lookups")
        if "controller" in results:
            controller_lookup = results["controller"]
            armor_lookup = results["armor"]
            logger.info(f"Controllers: {len(controller_lookup)}, Armors: {len(armor_lookup)}")
            _tick("Built ship controller + armor lookups")
        if "reputation" in results:
            reputation_lookup = results["reputation"]
            logger.info(f"Loaded {len(reputation_lookup)} reputation reward definitions")
            _tick("Built reputation lookup")

    # ── Output-file generators (parallel wave) ────────────────────────────────
    # Each closure captures the lookups it needs and returns its output dict(s).
    # Internal sub-phases within a closure (e.g. the mission scan → blueprint
    # pools → contractgen → title/desc augmentation → coverage report chain)
    # stay serial because each step consumes the prior step's in-memory result.
    # Across closures there is no shared mutable state — every output dict is
    # owned by exactly one closure — so they run safely on independent threads.
    ships_scitem = records / "entities" / "scitem" / "ships"
    scitem_dir = records / "entities" / "scitem"

    def _gen_components() -> dict[str, str]:
        out: dict[str, str] = {}
        logger.info("Processing ship components…")
        _flush()
        for subdir, fn in [
            ("shieldgenerator", enhancements_shield),
            ("cooler", enhancements_cooler),
            ("powerplant", enhancements_powerplant),
            ("quantumdrive", enhancements_quantum_drive),
        ]:
            logger.info(f"Processing {subdir}...")
            _flush()
            out.update(scan_entity_dir(ships_scitem / subdir, fn, loc=loc, generate_name_tags=True))
        radar_dir = ships_scitem / "radar"
        if radar_dir.exists():
            logger.info(f"Processing radars from {radar_dir}…")
            out.update(scan_entity_dir(radar_dir, enhancements_radar, loc=loc))
        else:
            logger.info("No radar directory found in cache")
        # Propagate stats from _SCItem keys to their non-SCItem siblings (base.ini
        # carries both patterns: item_DescTYPE_..._SCItem and item_Desc_TYPE_...).
        # Same treatment for name labels (item_nameTYPE → item_Name_TYPE).
        comp_types = ("COOL", "SHLD", "POWR", "QDRV")
        sibling_count = 0
        for key, value in list(out.items()):
            if not key.endswith("_SCItem"):
                continue
            base_key = key[: -len("_SCItem")]
            for ct in comp_types:
                desc_prefix = f"item_Desc{ct}_"
                if base_key.startswith(desc_prefix):
                    sibling = f"item_Desc_{ct}_{base_key[len(desc_prefix) :]}"
                    if sibling not in out and sibling in loc:
                        sibling_base = loc[sibling]
                        stats_marker = ENHANCEMENT_SEPARATOR
                        if stats_marker in value:
                            stats_block = value[value.index(stats_marker) :]
                            out[sibling] = sibling_base + stats_block
                        else:
                            out[sibling] = value
                        sibling_count += 1
                    break
                name_prefix = f"item_name{ct}_"
                if base_key.startswith(name_prefix):
                    sibling = f"item_Name_{ct}_{base_key[len(name_prefix) :]}"
                    if sibling not in out and sibling in loc:
                        out[sibling] = value
                        sibling_count += 1
                    break

        # Inverse propagation: some entities (e.g. SHLD_SECO_S01_HEX) reference
        # the underscored loc keys (item_Name_SHLD_*, item_Desc_SHLD_*) in the
        # XML, but base.ini *also* carries an unused legacy no-underscore pair
        # (item_NameSHLD_*, item_DescSHLD_*) which then shows up in the user's
        # category table with no annotations. Mirror the augmented underscore
        # value onto the no-underscore sibling so the Hex shield (and any
        # others in the same shape) stay consistent.
        inv_sibling_count = 0
        for key, value in list(out.items()):
            for prefix_with, prefix_without in (
                ("item_Desc_", "item_Desc"),
                ("item_Name_", "item_Name"),
            ):
                if not key.startswith(prefix_with):
                    continue
                rest = key[len(prefix_with) :]
                if not rest or "_" not in rest:
                    continue
                head = rest.split("_", 1)[0]
                if head not in comp_types:
                    continue
                legacy_sibling = prefix_without + rest
                if legacy_sibling in out or legacy_sibling not in loc:
                    continue
                if prefix_with == "item_Desc_":
                    legacy_base = loc[legacy_sibling]
                    stats_marker = ENHANCEMENT_SEPARATOR
                    if stats_marker in value:
                        out[legacy_sibling] = legacy_base + value[value.index(stats_marker) :]
                    else:
                        out[legacy_sibling] = value
                else:  # item_Name_
                    tag_match = re.search(r"\s(\[[A-Z0-9\-]+\])\s*$", value)
                    if tag_match:
                        out[legacy_sibling] = f"{loc[legacy_sibling]} {tag_match.group(1)}"
                    else:
                        out[legacy_sibling] = value
                inv_sibling_count += 1
                break

        if sibling_count or inv_sibling_count:
            logger.info(
                f"Propagated enhancements to {sibling_count} _SCItem siblings "
                f"and {inv_sibling_count} legacy no-underscore siblings"
            )
        _tick("Generated component enhancements")
        return out

    def _gen_missiles() -> dict[str, str]:
        out: dict[str, str] = {}
        logger.info("Processing missile/rocket/bomb enhancements…")
        weapons_dir = ships_scitem / "weapons"
        for missile_dir in [
            weapons_dir / "missiles",
            weapons_dir / "rocket_pods",
        ]:
            if missile_dir.exists():
                logger.info(f"Processing from {missile_dir}…")
                out.update(
                    scan_entity_dir(
                        missile_dir,
                        enhancements_missile,
                        loc=loc,
                        generate_name_tags=True,
                        name_tag_fn=_missile_name_tag,
                    )
                )
        _tick("Generated missile enhancements")
        return out

    def _gen_ship_weapons() -> dict[str, str]:
        out: dict[str, str] = {}
        weapons_dir = ships_scitem / "weapons"
        if weapons_dir.exists():
            out = scan_entity_dir(
                weapons_dir,
                lambda root: enhancements_weapon(root, vehicle_ammo, loc),
                loc=loc,
            )
        logger.info(f"Finished ship weapons ({len(out)} entries)")
        _tick("Generated ship weapon descriptions")
        return out

    def _gen_fps_weapons() -> dict[str, str]:
        out: dict[str, str] = {}
        fps_dir = records / "entities" / "scitem" / "weapons" / "fps_weapons"
        if fps_dir.exists():
            out = scan_entity_dir(
                fps_dir,
                lambda root: enhancements_weapon(root, fps_ammo, loc, mag_lookup),
                loc=loc,
            )
        logger.info(f"Finished FPS weapons ({len(out)} entries)")
        _tick("Generated FPS weapon descriptions")
        return out

    def _gen_ships() -> dict[str, str]:
        spaceships_dir = records / "entities" / "spaceships"
        out = scan_spaceships(spaceships_dir, controller_lookup, loc, armor_lookup)
        logger.info(f"Finished ships ({len(out)} entries)")
        _tick("Generated ship descriptions")
        return out

    def _gen_missions() -> dict[str, str]:
        # Sequential chain: scan → bp pools → contractgen → title/desc
        # augmentation → coverage report. Kept in one thread — each step
        # consumes the prior step's in-memory result.
        out: dict[str, str] = {}
        pu_missions_dir = records / "missionbroker" / "pu_missions"
        if pu_missions_dir.exists():
            logger.info(f"Processing {pu_missions_dir.name}…")
            _flush()
            out.update(
                scan_entity_dir(
                    pu_missions_dir,
                    lambda root: enhancements_mission(root, reputation_lookup),
                    loc=loc,
                    loc_key_fn=_mission_loc_key,
                    separator=MISSION_SEPARATOR,
                    capture_all=True,
                )
            )

        for mission_dir in [
            records / "entities" / "missions",
            records / "entities" / "contracts",
            records / "entities" / "jobterminal",
        ]:
            if mission_dir.exists():
                logger.info(f"Processing {mission_dir.name}…")
                _flush()
                out.update(
                    scan_entity_dir(
                        mission_dir,
                        lambda root: enhancements_mission(root, reputation_lookup),
                        loc=loc,
                        separator=MISSION_SEPARATOR,
                        capture_all=True,
                    )
                )

        logger.info(f"Finished missions scan ({len(out)} entries)")
        _tick("Scanned missions")

        # Blueprint pool lookup (needs entity_names from Group A)
        pool_dir = records / "crafting" / "blueprintrewards" / "blueprintmissionpools"
        bp_dir = records / "crafting" / "blueprints" / "crafting"
        blueprint_pools = _cached_lookup(
            forge_dir,
            "blueprint_pools",
            lambda: build_blueprint_pool_lookup(pool_dir, bp_dir, entity_names),
        )
        _tick("Built blueprint pool lookup")

        # Contract generator missions (multiple variants per title key)
        contractgen_dir = records / "contracts" / "contractgenerator"
        contractgen_missions, mission_blueprints, mission_bp_chance, mission_items = scan_contract_generators(
            contractgen_dir, reputation_lookup, blueprint_pools, entity_names
        )
        logger.info(
            f"Processed {len(contractgen_missions)} contract generator mission variants, {len(mission_blueprints)} with blueprints, {len(mission_items)} with items"
        )
        _flush()

        mission_titles_augmented = 0
        for title_key, variants in contractgen_missions.items():
            base_title = (loc or {}).get(title_key)
            if not base_title:
                continue

            # Collect unique (success_xp, failure_xp) tiers, preserving order
            seen_tiers: list[tuple[int, int]] = []
            for _, sxp, fxp, _, _, _, _, _, _, _, _ in variants:
                tier = (sxp, fxp)
                if tier not in seen_tiers:
                    seen_tiers.append(tier)

            unique_xp = sorted(set(sxp for sxp, _ in seen_tiers))

            # Title: [BP] when every variant awards a pool; [BP?] when at
            # least one variant does AND no single no-BP desc-key bucket
            # represents a majority (>50%) of variants. The majority check
            # suppresses BHG-style data where a lone BP variant drowns in
            # no-BP siblings (bhg_bounty_title_gen_001: 7 of 8 variants
            # share one no-BP desc_key — 87.5% — so tagging would mislead
            # that majority). Matches kraken_4.7.ini's [BP]* convention
            # and the missions_4.7.177.csv ground truth, which tag even
            # 50/50 splits like vaughn_assassination_FPS_UGF_legal_title_001
            # (legal_desc_001: 1 no-BP variant, legal_boss_desc_001: 1 BP
            # variant — 50% no-BP bucket, not a majority, so tagged).
            has_blueprints = title_key in mission_blueprints
            _bp_variants = [v[8] for v in variants]  # v[8] = contract_has_bp
            _all_have_bp = has_blueprints and all(_bp_variants)

            desc_bucket_has_bp: dict[str, bool] = {}
            desc_bucket_count: dict[str, int] = {}
            for v in variants:
                dk = v[3]
                if not dk:
                    continue
                desc_bucket_has_bp[dk] = desc_bucket_has_bp.get(dk, False) or v[8]
                desc_bucket_count[dk] = desc_bucket_count.get(dk, 0) + 1
            _total_bucketed = sum(desc_bucket_count.values())
            _any_variant_has_bp = any(_bp_variants)
            _has_dominant_no_bp_bucket = _total_bucketed > 0 and any(
                not desc_bucket_has_bp[dk] and desc_bucket_count[dk] / _total_bucketed > 0.5
                for dk in desc_bucket_has_bp
            )
            _bp_partial = has_blueprints and _any_variant_has_bp and not _has_dominant_no_bp_bucket
            augmented_title = base_title
            if _all_have_bp:
                augmented_title += " <EM4>[BP]</EM4>"
            elif _bp_partial:
                augmented_title += " <EM4>[BP?]</EM4>"
            nonzero_xp = [x for x in unique_xp if x > 0]
            if len(nonzero_xp) == 1:
                augmented_title += f" <EM4>[{nonzero_xp[0]:,} XP]</EM4>"
            elif len(nonzero_xp) > 1:
                augmented_title += f" <EM4>[{min(nonzero_xp):,}\u2013{max(nonzero_xp):,} XP]</EM4>"
            out[title_key] = augmented_title
            mission_titles_augmented += 1

            # Description: emit per unique desc_key. Skip desc_keys that a
            # *different* title_key already wrote this run (game-side data
            # bug: some contracts have broken desc_params pointing at
            # another mission's loc-key — e.g. P2M4 → P2M1_Repeat_desc).
            unique_desc_keys: list[str] = []
            for v in variants:
                dk = v[3]
                if dk and dk in loc and dk not in unique_desc_keys:
                    unique_desc_keys.append(dk)

            for desc_key in unique_desc_keys:
                desc_variants = [v for v in variants if v[3] == desc_key]
                base_desc = loc[desc_key]

                all_flags: list[str] = []
                max_enemies = 0
                max_not_enemies = 0
                all_difficulties: list[str] = []
                bp_variant_names: list[str] = []
                all_variants_have_bp = True
                any_variant_has_bp = False
                variant_bp_chance = 0.0
                desc_seen_tiers: list[tuple[int, int]] = []
                for _, vsxp, vfxp, _, vflags, venemies, vnot, vdiff, vhas_bp, vbp_chance, vbp_variant in desc_variants:
                    for f in vflags:
                        if f not in all_flags:
                            all_flags.append(f)
                    max_enemies = max(max_enemies, venemies)
                    max_not_enemies = max(max_not_enemies, vnot)
                    if vdiff and vdiff not in all_difficulties:
                        all_difficulties.append(vdiff)
                    if vhas_bp:
                        any_variant_has_bp = True
                        variant_bp_chance = max(variant_bp_chance, vbp_chance)
                        short_name = _variant_label_short(vbp_variant)
                        if short_name and short_name not in bp_variant_names:
                            bp_variant_names.append(short_name)
                    else:
                        all_variants_have_bp = False
                    tier = (vsxp, vfxp)
                    if tier not in desc_seen_tiers:
                        desc_seen_tiers.append(tier)

                details_lines = []
                details_lines.append(f"<EM4>Mission Type:</EM4> {', '.join(all_flags) if all_flags else 'Standard'}")
                if all_difficulties:
                    details_lines.append(f"<EM4>Difficulty (1-7):</EM4> {all_difficulties[0]}")
                if max_enemies > 0:
                    details_lines.append(f"<EM4>Enemies:</EM4> {max_enemies}")
                if max_not_enemies > 0:
                    details_lines.append(f"<EM4>Non-hostiles:</EM4> {max_not_enemies}")

                nonzero_tiers = [(s, f) for s, f in desc_seen_tiers if s > 0]
                if len(nonzero_tiers) == 1:
                    sxp, fxp = nonzero_tiers[0]
                    details_lines.append(f"<EM4>Reputation XP:</EM4> +{sxp:,}")
                    if fxp < 0:
                        details_lines.append(f"<EM4>Failure Penalty:</EM4> {fxp:,} XP")
                elif len(nonzero_tiers) > 1:
                    for i, (sxp, fxp) in enumerate(sorted(nonzero_tiers, key=lambda t: t[0]), 1):
                        line = f"<EM4>Tier {i}:</EM4> +{sxp:,} XP"
                        if fxp < 0:
                            line += f" (Failure: {fxp:,})"
                        details_lines.append(line)

                # Build sections: base → POTENTIAL BLUEPRINTS → ITEM REWARDS
                # → MISSION DETAILS. base_desc comes from pristine loc, so no
                # strip pass needed — assemble directly.
                sections: list[str] = [base_desc]

                if any_variant_has_bp and has_blueprints:
                    chance_pct = int(variant_bp_chance * 100)
                    if all_variants_have_bp:
                        bp_header = (
                            f"<EM4>Blueprint Reward:</EM4> {chance_pct}% chance"
                            if chance_pct < 100
                            else "<EM4>Blueprint Reward:</EM4> Guaranteed"
                        )
                    else:
                        variant_note = ", ".join(bp_variant_names) if bp_variant_names else "select variants"
                        bp_header = f"<EM4>Blueprint Reward:</EM4> {chance_pct}% chance ({variant_note} only)"
                    details_lines.append(bp_header)

                    # Restrict rendered pools to the systems actually
                    # represented among THIS desc_key's variants (a title may
                    # have a wider per-system pool set than any one desc does).
                    pools_by_system = mission_blueprints.get(title_key, {})
                    desc_systems = {v[0] for v in desc_variants if v[8]}  # v[0]=system, v[8]=has_bp
                    desc_pools = {s: items for s, items in pools_by_system.items() if s in desc_systems}
                    if not desc_pools:
                        # Fallback: no intersection (defensive — shouldn't
                        # happen if any_variant_has_bp holds) — show whatever
                        # pools this title has.
                        desc_pools = pools_by_system
                    # If distinct pools share identical item sets (same pool
                    # UUID reused across systems), collapse to one section.
                    unique_fps = {}
                    for sys_name, items in desc_pools.items():
                        fp = tuple(items)
                        unique_fps.setdefault(fp, []).append(sys_name)

                    bp_body_parts: list[str] = []
                    if len(unique_fps) == 1:
                        # One effective pool — render flat.
                        items = list(next(iter(unique_fps)))
                        bp_body_parts.append("\\n".join(f"- {name}" for name in items))
                    else:
                        # Multiple regional pools — one sub-section each,
                        # sorted by system name for stable output.
                        for fp, systems in sorted(unique_fps.items(), key=lambda kv: sorted(kv[1])):
                            label = ", ".join(sorted(systems))
                            region_list = "\\n".join(f"- {name}" for name in fp)
                            bp_body_parts.append(f"<EM4>[{label}]</EM4>\\n{region_list}")
                    sections.append("<EM3>POTENTIAL BLUEPRINTS</EM3>\\n" + "\\n".join(bp_body_parts))

                if title_key in mission_items:
                    item_list = "\\n".join(f"- {name}" for name in mission_items[title_key])
                    sections.append(f"<EM3>ITEM REWARDS</EM3>\\n{item_list}")

                details_block = "\\n".join(details_lines)
                if details_block:
                    sections.append(f"<EM3>MISSION DETAILS</EM3>\\n{details_block}")

                if any_variant_has_bp and has_blueprints and not all_variants_have_bp:
                    if bp_variant_names:
                        quoted = ", ".join(bp_variant_names)
                        if len(bp_variant_names) == 1:
                            sections.append(f"<EM4>? = only the {quoted} variant awards blueprints</EM4>")
                        else:
                            sections.append(f"<EM4>? = only the {quoted} variants award blueprints</EM4>")
                    else:
                        sections.append("<EM4>? = only some variants award blueprints</EM4>")

                new_text = "\\n\\n".join(sections)
                new_has_bp = "<EM3>POTENTIAL BLUEPRINTS</EM3>" in new_text
                existing = out.get(desc_key)
                if existing is None:
                    out[desc_key] = new_text
                elif new_has_bp and "<EM3>POTENTIAL BLUEPRINTS</EM3>" not in existing:
                    # Upgrade: an earlier title_key wrote this desc without a
                    # blueprint section; overwrite with the version that has
                    # one. Common when a desc loc-key is shared between a
                    # titles-without-pool contract and a title-with-pool one
                    # (e.g. bhg_bounty_desc_FPS_intro used by both
                    # FPS_Stanton [no pool] and the PAF contract [has pool]).
                    logger.debug(
                        f"Upgrading desc_key {desc_key!r} — earlier title wrote "
                        f"without blueprints, title_key {title_key!r} has them"
                    )
                    out[desc_key] = new_text
                else:
                    logger.debug(
                        f"Skipping shared desc_key {desc_key!r} for title_key {title_key!r}: "
                        f"already written by a prior title_key (likely a game-side data bug)"
                    )

        # Second pu_missions pass: aggregate XP values for titles the
        # contractgen scan couldn't extract XP for (e.g. templated titles
        # reusing one loc-key at many XP tiers, or ContractResult_CalculatedReward
        # missions like Covalex Interstellar hauling).
        pu_title_xps: dict[str, list[int]] = {}
        if pu_missions_dir.exists():
            for xml_file in pu_missions_dir.rglob("*.xml"):
                try:
                    root = ET.parse(xml_file).getroot()
                    title_attr = root.get("title", "")
                    desc_attr = root.get("description", "")
                    if not title_attr.startswith("@") or not desc_attr.startswith("@"):
                        continue
                    # Skip CIG sentinels — would otherwise append " [N XP]"
                    # onto LOC_UNINITIALIZED / LOC_PLACEHOLDER.
                    if _is_sentinel_loc_ref(title_attr) or _is_sentinel_loc_ref(desc_attr):
                        continue
                    title_key = title_attr.lstrip("@")
                    if not (loc or {}).get(title_key):
                        continue
                    xp = _extract_mission_xp(root, reputation_lookup)
                    if xp > 0:
                        pu_title_xps.setdefault(title_key, []).append(xp)
                except (ET.ParseError, Exception):
                    continue

        xp_tag_re = re.compile(r"<EM4>\[\d[\d,]*(?:[–\-]\d[\d,]*)?\s*XP\]</EM4>")
        for title_key, xps in pu_title_xps.items():
            base_title = (loc or {}).get(title_key)
            if not base_title:
                continue
            current = out.get(title_key, base_title)
            if xp_tag_re.search(current):
                continue
            unique_xp = sorted(set(xps))
            if len(unique_xp) == 1:
                current += f" <EM4>[{unique_xp[0]:,} XP]</EM4>"
            else:
                current += f" <EM4>[{min(unique_xp):,}\u2013{max(unique_xp):,} XP]</EM4>"
            out[title_key] = current
            mission_titles_augmented += 1

        logger.info(f"Augmented {mission_titles_augmented} mission titles with XP")
        _tick("Augmented missions with XP + blueprint rewards")

        # Mission XP coverage report
        titles_with_xp = {k for k in out if re.search(r"\[\d", out[k])}
        desc_keys = {k for k in out if k not in titles_with_xp}
        titles_skipped_no_xp = 0
        titles_skipped_reasons: dict[str, list[str]] = {
            "no_rep_data": [],
            "no_base_title": [],
        }
        if pu_missions_dir.exists():
            for xml_file in pu_missions_dir.rglob("*.xml"):
                try:
                    root = ET.parse(xml_file).getroot()
                    title_attr = root.get("title", "")
                    desc_attr = root.get("description", "")
                    if not title_attr.startswith("@") or not desc_attr.startswith("@"):
                        continue
                    title_key = title_attr.lstrip("@")
                    if title_key in out:
                        continue  # Already augmented
                    if title_key in contractgen_missions:
                        continue  # Handled by contract generator
                    titles_skipped_no_xp += 1
                    if _extract_mission_xp(root, reputation_lookup) <= 0:
                        titles_skipped_reasons["no_rep_data"].append(title_key)
                    elif not (loc or {}).get(title_key):
                        titles_skipped_reasons["no_base_title"].append(title_key)
                except Exception:
                    continue

        logger.info(
            f"Mission XP coverage: {len(titles_with_xp)} titles augmented, "
            f"{len(desc_keys)} descriptions augmented, "
            f"{titles_skipped_no_xp} titles skipped"
        )
        for reason, keys in titles_skipped_reasons.items():
            if keys:
                logger.info(f"  Skipped ({reason}): {len(keys)} — e.g. {', '.join(keys[:5])}")
        _flush()
        return out

    def _gen_commodity_journal() -> tuple[dict[str, str], dict[str, str]]:
        logger.info("Processing crafting blueprints…")
        _flush()
        bp_dir = records / "crafting" / "blueprints" / "crafting"
        carryables_dir = scitem_dir / "carryables"
        out_c, out_j = scan_crafting_blueprints(bp_dir, carryables_dir, entity_names, loc)
        _tick("Generated commodity & journal enhancements")
        return out_c, out_j

    # ── Submit enabled generators to a thread pool ────────────────────────────
    gen_jobs: dict[str, Callable] = {}
    if _want("component_descs"):
        gen_jobs["components"] = _gen_components
    if _want("missile_enhancements"):
        gen_jobs["missiles"] = _gen_missiles
    if _want("ship_weapon_descs"):
        gen_jobs["ship_weapons"] = _gen_ship_weapons
    if _want("fps_weapon_descs"):
        gen_jobs["fps_weapons"] = _gen_fps_weapons
    if _want("ship_descs"):
        gen_jobs["ships"] = _gen_ships
    if _want("mission_rewards"):
        gen_jobs["missions"] = _gen_missions
    if _want("commodity_crafting") or _want("journal"):
        gen_jobs["commodity_journal"] = _gen_commodity_journal

    out_components: dict[str, str] = {}
    out_missiles: dict[str, str] = {}
    out_ship_weapons: dict[str, str] = {}
    out_fps_weapons: dict[str, str] = {}
    out_ships: dict[str, str] = {}
    out_missions: dict[str, str] = {}
    out_commodities: dict[str, str] = {}
    out_journal: dict[str, str] = {}

    if gen_jobs:
        logger.info(
            f"Running {len(gen_jobs)} output generators in parallel (workers={min(max_workers, len(gen_jobs))})…"
        )
        _flush()
        with ThreadPoolExecutor(max_workers=min(max_workers, len(gen_jobs)), thread_name_prefix="gen") as pool:
            futs = {name: pool.submit(fn) for name, fn in gen_jobs.items()}
            for name, fut in futs.items():
                result = fut.result()
                if name == "components":
                    out_components = result
                elif name == "missiles":
                    out_missiles = result
                elif name == "ship_weapons":
                    out_ship_weapons = result
                elif name == "fps_weapons":
                    out_fps_weapons = result
                elif name == "ships":
                    out_ships = result
                elif name == "missions":
                    out_missions = result
                elif name == "commodity_journal":
                    out_commodities, out_journal = result

    # ── Apply loc-string workarounds for CIG data bugs ────────────────────────
    # XML patches we ran before this script realigned the enhancement
    # generator's bookkeeping, but the game reads contract Title/Description
    # pointers directly from Data.p4k at runtime — so a CIG bug where a
    # contract's Description points at the wrong loc key still misroutes the
    # in-game display. Appending the intended desc's content onto the loc key
    # the game actually reads works around that.
    if patches_dir is not None:
        try:
            from src.utils.dataforge_patcher import (
                apply_locstring_workarounds,
                load_locstring_workarounds,
            )

            workarounds = load_locstring_workarounds(patches_dir)
            if workarounds:
                total_applied = 0
                for out_dict in (
                    out_missions,
                    out_components,
                    out_ship_weapons,
                    out_fps_weapons,
                    out_ships,
                    out_missiles,
                    out_commodities,
                    out_journal,
                ):
                    total_applied += apply_locstring_workarounds(out_dict, workarounds)
                logger.info(f"Loc-string workarounds: {total_applied}/{len(workarounds)} applied")
                _flush()
        except ImportError:
            logger.debug("src.utils.dataforge_patcher unavailable; skipping workarounds")

    # ── Write output ──────────────────────────────────────────────────────────
    logger.info("Writing output files…")
    _flush()
    if _want("ship_descs"):
        write_ini(output_dir / "ships_desc_enhancements.ini", out_ships)
    if _want("component_descs"):
        write_ini(output_dir / "components_desc_enhancements.ini", out_components)
    if _want("ship_weapon_descs"):
        write_ini(output_dir / "ship_weapons_desc_enhancements.ini", out_ship_weapons)
    if _want("fps_weapon_descs"):
        write_ini(output_dir / "fps_weapons_desc_enhancements.ini", out_fps_weapons)
    if _want("mission_rewards"):
        write_ini(output_dir / "mission_rewards_enhancements.ini", out_missions)
    if _want("commodity_crafting"):
        write_ini(output_dir / "commodity_crafting_enhancements.ini", out_commodities)
    if _want("journal"):
        write_ini(output_dir / "journal_enhancements.ini", out_journal)
    if _want("missile_enhancements"):
        write_ini(output_dir / "missile_enhancements.ini", out_missiles)

    total = (
        len(out_ships)
        + len(out_components)
        + len(out_ship_weapons)
        + len(out_fps_weapons)
        + len(out_missions)
        + len(out_commodities)
        + len(out_journal)
        + len(out_missiles)
    )
    logger.info(f"Done — {total:,} total stat entries written to {output_dir}")
    _tick("Wrote all output files")
    if _sink is not None:
        _sink.flush()


if __name__ == "__main__":
    base_ini = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASE_INI
    forge_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_FORGE_DIR
    main(base_ini, forge_dir)
