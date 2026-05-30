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

import io
import logging
import pickle
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional
from lxml import etree as ET

logger = logging.getLogger(__name__)

# Tag-builder is in src.utils, which may not be on sys.path when this script
# runs as a standalone CLI from the scripts/ directory. Add the project root
# and fall through to the (now-only) defaults if the import still fails —
# keeps CLI use unchanged and the generator self-contained.
try:
    if str(PROJECT_ROOT) not in sys.path:  # type: ignore[name-defined]  # PROJECT_ROOT defined below
        pass
except NameError:
    pass
try:
    _gen_root = Path(__file__).parent.parent
    if str(_gen_root) not in sys.path:
        sys.path.insert(0, str(_gen_root))
    from src.utils.tag_builder import (
        DAMAGE_LABEL_TO_MAPPING_KEY, DEFAULT_COMPONENT_CLASS_MAPPING,
        DEFAULT_TAG_CONFIGS, TagConfig, render_tag,
    )
except ImportError:  # pragma: no cover — only triggers if src/ is removed
    DAMAGE_LABEL_TO_MAPPING_KEY = {}  # type: ignore[assignment]
    DEFAULT_COMPONENT_CLASS_MAPPING = {}  # type: ignore[assignment]
    DEFAULT_TAG_CONFIGS = {}  # type: ignore[assignment]
    TagConfig = None  # type: ignore[assignment]
    render_tag = None  # type: ignore[assignment]


# ── Paths ─────────────────────────────────────────────────────────────────────

SCRIPT_DIR   = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent


def _get_documents_dir() -> Path:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
        )
        docs = Path(winreg.QueryValueEx(key, "Personal")[0])
        winreg.CloseKey(key)
        return docs
    except Exception:
        return Path.home() / "Documents"


def _get_default_cache_dir() -> Path:
    """Resolve the app's active cache directory for standalone CLI defaults."""
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from src.utils.settings import AppSettings
        return AppSettings.get_cache_dir()
    except (ImportError, OSError) as e:
        logger.debug(f"Falling back to Documents cache default: {e}")
        return _get_documents_dir() / "Smart Citizen" / "LIVE" / "cache"


def _get_default_forge_dir() -> Path:
    """Resolve the DataForge cache directory for standalone CLI defaults.

    Mirrors AppSettings.get_dataforge_cache_dir() — AppData\\Local, not
    Documents, so the ~1.4 GB XML cache stays out of OneDrive.
    """
    try:
        if str(PROJECT_ROOT) not in sys.path:
            sys.path.insert(0, str(PROJECT_ROOT))
        from src.utils.settings import AppSettings
        return AppSettings.get_dataforge_cache_dir()
    except (ImportError, OSError) as e:
        logger.debug(f"Falling back to LocalAppData forge default: {e}")
        local_appdata = Path(
            os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        )
        return local_appdata / "Smart Citizen" / "LIVE" / "cache" / "dataforge"


APP_CACHE_DIR    = _get_default_cache_dir()
DEFAULT_BASE_INI = APP_CACHE_DIR / "base.ini"
DEFAULT_FORGE_DIR = _get_default_forge_dir()

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
    buf = io.StringIO()
    for k, v in sorted(entries.items()):
        buf.write(f"{k}={v}\n")
    path.write_text(buf.getvalue(), encoding="utf-8")
    logger.info(f"Written {len(entries):,} entries -> {path}")


# ── Derived-lookup disk cache ─────────────────────────────────────────────────
# Walking the DataForge tree is expensive (~85s for scitem alone). These
# lookups are pure functions of the DataForge cache contents, so we pickle
# them under cache/dataforge/.lookups/ keyed on the .p4k_mtime stamp written
# by pak_extractor.py. When DataForge is re-extracted, the stamp changes and
# the cache is invalidated automatically.

# Per-cache builder version. Bump the value whenever the builder for that
# cache changes its WHAT-it-collects semantics (new source dirs, schema
# additions, etc.) so existing pickled results from before the change get
# detected as stale and rebuilt — the .p4k_mtime fingerprint alone can't
# catch this because the underlying DataForge data hasn't changed, only
# our parsing of it has.
#
# History:
#   blueprint_pools v2 (1.3.1) — walks all crafting/blueprintrewards/
#     subdirs (was: only blueprintmissionpools/). Adds ~40 new pool
#     records that 4.8 PTU references via 48blueprints/ + a new
#     xenothreat2rewards/ dir.
#   blueprint_pools v3 (1.3.1) — fallback name from blueprint XML
#     filename when the entityClass UUID isn't __ref'd anywhere in
#     the cache (PTU WIP state — blueprints shipped ahead of their
#     entity records, e.g. fuel-nozzle blueprints in 4.8). Without
#     this the pool's names list ended up empty and the entire pool
#     was dropped, swallowing the [BP?] tag for those missions.
#   blueprint_pools v4 (1.3.1) — second-tier filename-stem fallback
#     (entity_names_by_filename) before falling through to the ugly
#     filename-derived placeholder. Recovers real localized names
#     ("Norfield", "Harkin", "RN-7s") for fuel-nozzle blueprints
#     whose entityClass UUIDs are CIG-WIP-broken — the entity XML
#     itself ships in entities/scitem/ with the matching stem and
#     a clean Localization Name attribute, we just couldn't reach
#     it via UUID. v3 produced "Nozzle Fuelgiver Grin Nozzlefast";
#     v4 produces "Norfield".
#   scitem_lookups v2 (1.3.1) — return tuple shape changed from
#     (mag_lookup, entity_names) to (mag_lookup, entity_names,
#     entity_names_by_filename) to feed the v4 blueprint_pools
#     filename-stem fallback. v1 pickles will fail to unpack into
#     the new 3-tuple, so we MUST invalidate them.
#   scitem_lookups v3 (1.4.0) — added a fourth tuple slot
#     (entity_name_tags: ref → "[CLASS-Sx-grade]") so blueprint pool
#     items get the same annotation components do in their stock title.
#     v2 pickles unpack as 3-tuples and would crash on the new 4-tuple
#     consumer, so bump invalidates them.
#   blueprint_pools v5 (1.4.0) — pool item names now carry the inline
#     [CLASS-Sx-grade] tag when the underlying entity is a tagged
#     component (shield/cooler/powerplant/qdrive/radar). Old v4 pickles
#     stored the un-annotated strings, so reusing them would silently
#     undo the new annotation on cache hit.
#   blueprint_pools v6 (1.4.0) — strip the leading CIG-baked size prefix
#     (``S0 ``, ``S00 ``, ``S1 ``…) from blueprint-list display names
#     so mining-head entries like "S0 Helix" render as "Helix" alongside
#     tagger-classified items, instead of carrying a second size
#     convention CIG embedded in the loc-name attribute. v5 pickles
#     hold the un-stripped names, so reusing them would defeat the strip.
#   scitem_lookups v4 / blueprint_pools v7 (1.4.0) — _component_name_tag
#     gained a fallback path that tags items lacking the full
#     Size:/Grade:/Class: trio, using Item Type: as a Class: substitute
#     and emitting partial shapes like [MIN-S0-B] (Helix) or [MIN-S0]
#     (Arbor MHV). Both lookups stored values produced by the strict-only
#     tagger and would silently keep mining heads / lasers untagged on
#     cache hit, so both invalidate together.
#   blueprint_pools v8 (1.4.0) — return tuple shape changed from
#     ``dict[uuid, items]`` to ``(dict[uuid, items], dict[uuid, name])``
#     so downstream rendering can derive rank-tier labels (Rank 0–1,
#     Rank 2–3, Rank 4) from the pool filename and emit them in the
#     POTENTIAL BLUEPRINTS sub-section headers. v7 pickles unpack as
#     a bare dict and crash the new 2-tuple consumer, so bump invalidates.
#   scitem_lookups v5 / blueprint_pools v9 (1.4.0) — ``build_scitem_lookups``
#     now honours the user's components ``TagConfig`` when rendering the
#     ``[CLASS-Sx-grade]`` entries that get baked onto mission POTENTIAL
#     BLUEPRINTS names. Pre-fix the tag was always rendered with the
#     DEFAULTS, so a user who set the Tag Builder to "Long (Military)" /
#     enclosing "Round" / etc. saw their components pipeline emit the new
#     style but mission descriptions still emitted ``[MIL-S3-B]``. The
#     cache key now folds in a hash of the components config (via
#     _cached_lookup's extra_key); both caches invalidate when the user
#     edits their config so the next run rebuilds with the new style.
_LOOKUP_VERSIONS: dict[str, str] = {
    "blueprint_pools": "v9",
    "scitem_lookups": "v5",
}


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


def _cached_lookup(forge_dir: Path, name: str, builder, extra_key: str = ""):
    """Memoize *builder*'s output to cache/dataforge/.lookups/{name}.pkl.

    Cache key is ``{builder_version}:{dataforge_fingerprint}[:extra_key]``.
    Any of the three changing invalidates the cache: re-extracting Data.p4k
    changes the fingerprint; updating the builder's collection logic bumps
    the version in _LOOKUP_VERSIONS; passing a different *extra_key* (used
    by scitem_lookups + blueprint_pools to fold in the user's components
    Tag Builder config so a config change rebuilds the baked-in tags)
    bumps the third segment. Pickle errors silently fall back to rebuilding.
    """
    cache_dir = forge_dir / ".lookups"
    cache_file = cache_dir / f"{name}.pkl"
    builder_version = _LOOKUP_VERSIONS.get(name, "v1")
    key = f"{builder_version}:{_dataforge_cache_key(forge_dir)}"
    if extra_key:
        key = f"{key}:{extra_key}"

    if cache_file.exists():
        try:
            with cache_file.open("rb") as f:
                stored_key, value = pickle.load(f)
            if stored_key == key:
                logger.info(f"Lookup cache hit: {name} ({builder_version})")
                return value
            else:
                logger.info(
                    f"Lookup cache invalidated: {name} "
                    f"(stored={stored_key!r}, expected={key!r})"
                )
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


def _build_xml_path_index(records_dir: Path) -> dict[str, list[str]]:
    """Single-pass walk of records_dir → {rel_posix_subdir: [sorted_abs_path_str, ...]}.

    Built once per DataForge cache version and pickled via _cached_lookup so
    the OS directory walk only happens on a cold cache. Callers use
    _index_rglob() to get the file list for a given directory subtree.
    """
    idx: dict[str, list[str]] = defaultdict(list)  # type: ignore[assignment]
    for xml_file in records_dir.rglob("*.xml"):
        key = xml_file.parent.relative_to(records_dir).as_posix()
        idx[key].append(str(xml_file))
    return {k: sorted(v) for k, v in idx.items()}


def _index_rglob(xml_path_index: dict, entity_dir: Path, records_dir: Path) -> list[Path]:
    """Return all XML paths under entity_dir using the pre-built index.

    Equivalent to list(entity_dir.rglob("*.xml")) but O(#dirs) instead of
    O(#files) when the index is already in memory.
    """
    prefix = entity_dir.relative_to(records_dir).as_posix()
    result: list[Path] = []
    for key, paths in xml_path_index.items():
        if key == prefix or key.startswith(prefix + "/"):
            result.extend(Path(p) for p in paths)
    return result


ENHANCEMENT_SEPARATOR = "\\n\\n--- STATS ---\\n"
MISSION_SEPARATOR = "\\n\\n<EM3>MISSION DETAILS</EM3>\\n"

# Default section header text — mirrored from AppSettings.MISSION_HEADER_DEFAULTS
# (not imported because this script runs standalone too). Keep these two
# locations in sync; the test_mission_headers regression guards either side.
_DEFAULT_MISSION_HEADERS = {
    "details":        "MISSION DETAILS",
    "blueprints":     "POTENTIAL BLUEPRINTS",
    "items":          "ITEM REWARDS",
    "blueprint_data": "BLUEPRINT DATA",
}
_DEFAULT_REP_XP_LABEL = "Rep"
_DEFAULT_MISSION_HEADER_EM_TAG = "EM3"


def _humanize_key(key: str) -> str:
    """Best-effort fallback display for a loc key with no human title:
    `Eckhart_Nyx_DefendShip` -> `Eckhart Nyx DefendShip`."""
    return key.replace("_", " ").strip()


def append_enhancements(existing_value: str, enhancements_block: str,
                        separator: str = ENHANCEMENT_SEPARATOR) -> str:
    if existing_value is None:
        existing_value = ""
    if not enhancements_block:
        return existing_value
    # Strip any existing stats/mission details block. BP/ITEMS/BLUEPRINT DATA
    # markers are intentionally NOT listed here — they're sibling sections to
    # MISSION DETAILS and belong with the base content, not treated as stale
    # augmentation. Stripping them would remove content the caller just
    # prepended in the same run (see mission desc construction in main()).
    for marker in ("\\n\\n--- STATS ---", "\\n\\n<EM3>STATS</EM3>",
                    "\\n\\n<EM3>MISSION DETAILS</EM3>",
                    "\\n\\n<EM3>== Stats ==</EM3>", "\\n\\n<EM3>== Mission Details ==</EM3>",
                    "\\n\\n== Stats ==", "\\n\\n== Mission Details =="):
        if marker in existing_value:
            existing_value = existing_value[:existing_value.index(marker)]
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
_SENTINEL_LOC_KEYS = frozenset({
    "LOC_BADSTRING",
    "LOC_BADTOKEN",
    "LOC_DEBUG",
    "LOC_EMPTY",
    "LOC_INVALID",
    "LOC_NOINNERTHOUGHT",
    "LOC_PLACEHOLDER",
    "LOC_UNINITIALIZED",
})


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
_PLACEHOLDER_TEXTS = frozenset({
    "<= PLACEHOLDER =>",
    "<= UNINITIALIZED =>",
    "<= BADSTRING =>",
    "<= BADTOKEN =>",
    "<= DEBUG =>",
    "<= EMPTY =>",
    "<= INVALID =>",
    "<= NOINNERTHOUGHT =>",
})


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


def _synthesize_description(root: ET.Element, xml_file: Path, key: str) -> str:
    """Build a synthetic description from XML attributes when base.ini has no entry.

    Returns the richest available description so discovered items still appear
    in the table with useful context.
    """
    parts: list[str] = []

    # 1. Item name: prefer the XML Name loc ref, fall back to filename
    name = _loc_name_key(root)
    if name:
        parts.append(name)
    else:
        stem = _humanize_key(xml_file.stem)
        if stem:
            parts.append(stem)

    # 2. Ship-specific attributes from VehicleComponentParams
    vpc = _find(root, "VehicleComponentParams")
    if vpc is not None:
        attrs: list[str] = []
        career = vpc.get("vehicleCareer", "")
        if career.startswith("@"):
            attrs.append(f"Class: {career.lstrip('@')}")
        role = vpc.get("vehicleRole", "")
        if role.startswith("@"):
            attrs.append(f"Role: {role.lstrip('@')}")
        crew = vpc.get("crewSize", "")
        if crew:
            attrs.append(f"Crew: {crew}")
        bbox = _find(root, "maxBoundingBoxSize")
        if bbox is not None:
            length = bbox.get("y", "")
            if length:
                attrs.append(f"Length: {length}m")
        if attrs:
            parts.append(" | ".join(attrs))

    # 3. Component attributes (ItemComponentParams)
    icp = _find(root, "ItemComponentParams")
    if icp is not None:
        item_type = icp.get("itemType", "")
        if item_type:
            parts.append(f"Item Type: {item_type}")

    # 4. Missile tracking signal type
    tp = _find(root, "targetingParams")
    if tp is not None:
        sig = tp.get("trackingSignalType", "")
        if sig:
            parts.append(f"Tracking: {sig}")

    return "\n".join(parts) if parts else key.replace("_", " ")


# ── Tag emitters ─────────────────────────────────────────────────────────────
# Each emitter pulls structured data off the description text and/or XML and
# hands it to render_tag(). Format strings, ordering, separators, and the
# class/ordinance/damage label mapping all come from the TagConfig passed
# in — the function only knows how to extract the *values*, not how to lay
# them out. Default behavior (when no config is passed) matches the
# pre-refactor hardcoded output byte-for-byte; locked by
# tests/test_tag_builder.py::TestDefaultBackwardsCompat.

# CIG's internal trackingSignalType values → mapping-key form used by the
# missile TagConfig.class_mapping dict.
_MISSILE_TRACKING_RAW = ("CrossSection", "Electromagnetic", "Infrared")

# Item Type → abbreviation, used as a Class: fallback when the description
# omits the Class: line. CIG authors ship components with the full
# Size:/Grade:/Class: trio but leaner items (mining heads, ship weapons,
# salvage heads) get only Size: + optional Grade: + an Item Type: line.
# Using Item Type for the abbreviation keeps those entries from falling
# through bare when they appear in blueprint lists.
#
# Ship-weapon Item Types are mapped to the same single-letter damage codes
# the strings-tab tagger (_ship_weapon_name_tag_factory) emits — "E" for
# energy (laser / plasma / neutron / tachyon), "B" for ballistic + railgun,
# "D" for distortion, "EMP" for EMP generators. That keeps the BP-list
# annotation visually consistent with the strings tab: a Tarantula GT-870
# shows as ``[B-S2] Tarantula …`` in both places. (Lookup is by ``Item
# Type:`` string after ``.strip()``, so trailing-space CIG variants like
# "Laser Cannon " match without needing duplicate keys.)
_ITEM_TYPE_ABBREV = {
    # Mining (already shipping pre-1.4.1)
    "Mining Laser":             "MIN",

    # Salvage / repair
    "Salvage Head":             "SAL",

    # Ship components
    "Shield Generator":         "SHLD",
    "Cooler":                   "COOL",
    "Power Plant":              "POWR",
    "Quantum Drive":            "QDRV",
    "Radar":                    "RADR",
    "Bomb Rack":                "BRK",

    # Ship weapons — energy damage
    "Laser Beam":               "E",
    "Laser Cannon":             "E",
    "Laser Gatling":            "E",
    "Laser Mine":               "E",
    "Laser Repeater":           "E",
    "Laser Scattergun":         "E",
    "Laser Turret":             "E",
    "Neutron Cannon":           "E",
    "Neutron Repeater":         "E",
    "Plasma Cannon":            "E",
    "Plasma Canon":             "E",  # CIG typo
    "Plasma Scattergun":        "E",
    "Tachyon Cannon":           "E",

    # Ship weapons — ballistic damage
    "Ballistic Cannon":         "B",
    "Ballistic Cannon Turret":  "B",
    "Ballistic Gatling":        "B",
    "Ballistic Gatling (x2)":   "B",
    "Ballistic Gatling Gun":    "B",
    "Ballistic Gatling Turret": "B",
    "Ballistic Repeater":       "B",
    "Ballistic Scattergun":     "B",
    "Mass Driver Cannon":       "B",
    "Railgun":                  "B",

    # Ship weapons — distortion damage
    "Distortion Cannon":        "D",
    "Distortion Repeater":      "D",
    "Distortion Scattergun":    "D",

    # Ship weapons — EMP / utility
    "EMP Generator":            "EMP",
}


def _component_name_tag(desc_value: str, root: ET.Element | None = None,
                        config: "TagConfig | None" = None,
                        component_type: str = "") -> str | None:
    """Build a bracket annotation tag from a component-style description.

    Two paths, both producing the same ``[…]`` shape:

      Strict — Size: N + Grade: A-D + Class: <recognised> → e.g. "[MIL-S1-A]"
        Ship components (shield, cooler, powerplant, qdrive, radar) all
        author this trio. Routed through ``render_tag`` so the user's
        component TagConfig (mapping / separator / enclosing / element
        ordering) is honoured. A defensive non-render_tag path preserves
        the legacy ``[CLASS-Sx-grade]`` output bit-for-bit when
        ``tag_builder`` isn't importable.

      Fallback — Size: present + at least one of {recognised Item Type,
      Grade A-D}. Class: is optional and the size may be written either
      as bare "N" or as the mining-style "SN" (S0, S00). Output shape:
        [TYPE-Sx-grade]  (e.g. "[MIN-S0-B]" — Helix, Hofstede)
        [TYPE-Sx]        (e.g. "[MIN-S0]"   — Arbor MHV with no Grade)
        [Sx-grade]       (Grade present but Item Type not in the abbreviation map)
      The fallback path skips ``render_tag`` — these items aren't the
      user-customisable ship-component case Tag Builder targets, and the
      partial output shapes don't align with the element-ordered render
      pipeline.

    Requiring at least one of {type_abbrev, grade_m} on the fallback path
    keeps a bare ``[Sx]`` from leaking onto anything that happens to have
    a Size: line (consumables, ammo containers, etc.) — the tag has to
    convey something beyond the size that's usually implied by the
    entity's own name anyway.

    Returns ``None`` when Size: itself is missing OR when the fallback's
    minimum-information bar isn't met. Those items pass through bare.
    """
    # Optional leading 'S' on the size value covers mining heads (Size: S0,
    # Size: S00) without breaking the bare-digit form ship components use
    # (Size: 0, Size: 1). The capture is the digits only; "S0" → "0",
    # "S00" → "00", "2" → "2", so the tag normalises to f"S{captured}".
    size_m = re.search(r"Size:\s*S?(\d+)", desc_value)
    if size_m:
        size = size_m.group(1)
    elif root is not None:
        # Fall back to XML: extract size from entity class name in root tag
        root_tag = root.tag.split(".")[-1] if "." in root.tag else root.tag
        xml_size = _extract_item_size(root_tag)
        if not xml_size:
            return None
        size = xml_size.lstrip("S")
    else:
        return None

    grade_m = re.search(r"Grade:\s*([A-D])", desc_value)
    class_m = re.search(r"Class:\s*(\w+)", desc_value)

    # AttachDef fallback (bomb racks, other ordnance containers): these
    # entities have no ItemComponentParams and their Grade is numeric (1→A).
    attach_def = None
    attach_grade_letter = None
    attach_class_name = None
    if root is not None:
        attach_el = _find(root, "SAttachableComponentParams")
        if attach_el is not None:
            attach_def = attach_el.find("AttachDef")

    if not grade_m and attach_def is not None:
        num_grade = attach_def.get("Grade", "")
        if num_grade.isdigit():
            g_idx = int(num_grade) - 1
            if 0 <= g_idx <= 3:
                attach_grade_letter = "ABCD"[g_idx]

    if not class_m and attach_def is not None:
        subtype = attach_def.get("SubType", "")
        if subtype:
            # CamelCase → space-separated (e.g. "BombRack" → "Bomb Rack")
            attach_class_name = re.sub(r"([a-z])([A-Z])", r"\1 \2", subtype)

    # Resolve effective grade and class for downstream paths
    grade_letter = (grade_m.group(1) if grade_m else None) or attach_grade_letter
    class_name = (class_m.group(1) if class_m else None) or attach_class_name

    # When Class: is missing from text, try to derive from XML ItemComponentParams
    xml_item_type = None
    if not class_name and root is not None:
        icp = _find(root, "ItemComponentParams")
        if icp is not None:
            raw_type = icp.get("itemType", "")
            # CamelCase → space-separated, same split as attach_class_name
            # (e.g. "ShieldGenerator" → "Shield Generator")
            xml_item_type = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_type)

    # Strict path: full ship-component trio with a recognised class →
    # render via the Tag Builder pipeline so user customisation applies.
    if grade_letter and class_name and class_name in DEFAULT_COMPONENT_CLASS_MAPPING:
        cfg = config or DEFAULT_TAG_CONFIGS.get("components")
        if cfg is not None and render_tag is not None:
            values = {
                "class": class_name,
                "size":  size,
                "grade": grade_letter,
            }
            if component_type:
                values["type"] = component_type
            out = render_tag(cfg, values)
            if out:
                return out
        # Defensive fallback when tag_builder isn't importable (e.g. tests
        # in environments without src/ on the path). Preserves the legacy
        # hardcoded output shape.
        abbrev_tuple = DEFAULT_COMPONENT_CLASS_MAPPING.get(class_name)
        if abbrev_tuple:
            return f"[{abbrev_tuple[1]}-S{size}-{grade_letter}]"

    # Fallback path: classify by Item Type when Class: is missing or
    # unrecognised. The character class excludes backslash so the capture
    # stops at CIG's literal "\n" line separator (two characters in the
    # parsed loc-value, not a real newline); the alternation covers both
    # the literal and the real-newline form for robustness.
    type_abbrev = None
    type_m = re.search(r"Item Type:\s*([^\\\n]+?)\s*(?:\\n|\n|$)", desc_value)
    if type_m:
        type_abbrev = _ITEM_TYPE_ABBREV.get(type_m.group(1).strip())
    # Fall back to XML-derived item type when text has no Item Type: line
    if not type_abbrev and xml_item_type:
        type_abbrev = _ITEM_TYPE_ABBREV.get(xml_item_type)
    # Fall back to AttachDef SubType (bomb racks, etc.)
    if not type_abbrev and class_name:
        type_abbrev = _ITEM_TYPE_ABBREV.get(class_name)

    if not (type_abbrev or grade_letter):
        return None

    parts: list[str] = []
    if type_abbrev:
        parts.append(type_abbrev)
    parts.append(f"S{size}")
    if grade_letter:
        parts.append(grade_letter)
    return f"[{'-'.join(parts)}]"


def _missile_name_tag(desc_value: str, root: ET.Element | None = None,
                      config: "TagConfig | None" = None) -> str | None:
    """Render the missile/torpedo/bomb tag.

    Prefers the XML's ``trackingSignalType`` attribute (on
    ``<targetingParams>``) over the loc-text "Tracking Signal: …" line so we
    stay correct even if a description is edited or translated. Bombs (no
    guidance) yield an empty ordinance value — render_tag's empty-drop then
    falls through to the size element alone (e.g. ``[S2]``).
    """
    size_m = re.search(r"Size:\s*(\d+)", desc_value)
    if not size_m:
        return None
    size = size_m.group(1)

    seeker_raw = None
    is_bomb = False
    if root is not None:
        for el in root.iter():
            # Bombs are unguided ordinance — they carry no trackingSignalType
            # but author `AttachDef Type="Bomb"` (and an SCItemBombParams
            # element) instead. Catch them on the same single-pass iter so
            # the ordinance element resolves to "Bomb" → "B" through
            # DEFAULT_MISSILE_ORDINANCE_MAPPING and the rendered tag is
            # [B-S3] rather than the pre-fix bare-size [S3].
            if not is_bomb and el.tag.endswith("AttachDef"):
                if el.get("Type") == "Bomb":
                    is_bomb = True
            if not is_bomb and (el.tag.endswith("SCItemBombParams")
                                or el.tag == "SCItemBombParams"):
                is_bomb = True
            if seeker_raw is None and (el.tag.endswith("targetingParams")
                                       or el.tag.endswith("TargetingParams")):
                raw = el.get("trackingSignalType")
                if raw in _MISSILE_TRACKING_RAW:
                    seeker_raw = raw
            if is_bomb and seeker_raw is not None:
                break
    if seeker_raw is None and not is_bomb:
        m = re.search(r"Tracking Signal:\s*([A-Za-z ]+?)(?:\\n|\n|$)", desc_value)
        if m:
            normalized = m.group(1).replace(" ", "")
            for raw in _MISSILE_TRACKING_RAW:
                if normalized.lower() == raw.lower():
                    seeker_raw = raw
                    break

    cfg = config or DEFAULT_TAG_CONFIGS.get("missiles")
    if cfg is None or render_tag is None:
        return None
    # Feed raw values; render_tag's empty-value drop handles both branches.
    # Guided missiles (seeker_raw set) keep size enabled by default →
    # [IRS2]; bombs resolve to "Bomb" → [B-S3] via the mapping; anything
    # else with neither marker collapses ordinance → [S2]. The [IRS2]
    # default is a deliberate change from the pre-refactor [IR] output —
    # issue thread feedback asked for size to be visible on guided
    # missiles ("might have multiple IR missiles and have to wait for the
    # name to scroll to identify what size it is"). Users who prefer the
    # old behavior can disable Size in the Tag Builder UI.
    ordinance = "Bomb" if is_bomb else (seeker_raw or "")
    out = render_tag(cfg, {"ordinance": ordinance, "size": size})
    return out or None


def _ship_weapon_name_tag_factory(ammo_lookup: dict, config: "TagConfig | None" = None):
    """Build a closure-tagger for ship weapons.

    Needs the ammo_lookup to resolve the dominant damage type, so it can't
    use the bare ``(desc, root)`` shape the other taggers use. Returns a
    function with the standard ``(desc_value, root)`` signature for
    ``scan_entity_dir``.
    """
    cfg = config or DEFAULT_TAG_CONFIGS.get("ship_weapons")

    def _tag(desc_value: str, root: ET.Element | None = None) -> str | None:
        if cfg is None or render_tag is None or root is None:
            return None

        # Size: prefer the entity class name attribute on root (matches
        # how _extract_item_size works elsewhere in this script). Fall
        # back to a Size: N line in the description.
        size = None
        name_attr = root.get("Name") or root.get("name") or ""
        m = re.search(r"_S0*(\d+)_", name_attr)
        if m:
            size = str(int(m.group(1)))
        if not size:
            ds = re.search(r"Size:\s*(\d+)", desc_value)
            if ds:
                size = ds.group(1)

        # Damage type: largest non-zero damage entry in the ammo record.
        # ammo_lookup is keyed by ammoParamsRecord GUID; SAmmoContainer-
        # ComponentParams on the weapon root holds the GUID.
        damage_label = ""
        try:
            ammo_container = root.find(".//SAmmoContainerComponentParams")
        except Exception:
            ammo_container = None
        ammo_id = ammo_container.get("ammoParamsRecord") if ammo_container is not None else None
        if ammo_id and ammo_id != "00000000-0000-0000-0000-000000000000":
            ammo_root = ammo_lookup.get(ammo_id)
            if ammo_root is not None:
                try:
                    total, breakdown = _ammo_damage_breakdown(ammo_root)
                except Exception:
                    breakdown = {}
                if breakdown:
                    damage_label = max(breakdown.items(), key=lambda kv: kv[1])[0]
                    # Translate the generator's compact label ("Phys",
                    # "Distort", "Bio") into the full English mapping key
                    # ("Physical", "Distortion", "Biochemical") that the
                    # Tag Builder's mapping editor exposes to users.
                    damage_label = DAMAGE_LABEL_TO_MAPPING_KEY.get(
                        damage_label, damage_label
                    )

        # Require a resolvable damage label. Items in ships/weapons/ that
        # lack a damage breakdown — EMP devices, tractor / towing beams,
        # mining lasers (which have their own enhancements_mining_laser
        # pipeline) — would otherwise emit a size-only tag like ``[S1]``
        # that's meaningless next to the entity's own name. Skip those.
        if not damage_label:
            return None
        out = render_tag(cfg, {"damage": damage_label, "size": size or ""})
        return out or None

    return _tag


def _mission_loc_key(root: ET.Element) -> str | None:
    """Extract the mission description localization key from MissionBrokerEntry XML.

    Missions store the localization key in the 'description' attribute of the root element.
    """
    desc = root.get("description", "")
    if desc.startswith("@") and not _is_sentinel_loc_ref(desc):
        return desc.lstrip("@")
    return None


# Loc-key tokens that flag a mission as on-foot / first-person. Lowercase
# substring match against the loc_key. CIG's own naming convention puts these
# in the key whenever the mission is FPS-themed (e.g.
# ``BountyHuntersGuild_FPS_Nyx``, ``vaughn_assassination_FPS_UGF_legal_…``,
# ``GoblinG_Crusader_RecoverCargoFPS_L_Title``). UGF = Underground Facility,
# always FPS. ``ugf`` is matched as a standalone token via word-boundary check
# below to avoid false-positives on substrings like ``frugfrog``.
_FPS_TOKENS = (
    "_fps_", "fps_", "_fps", "fpsmine",
    "_ugf_", "ugf_", "_ugf",
    "_onfoot_", "onfoot_", "_onfoot",
    "_foot_",
)

# Tokens that flag the mission also requires ship transport ON TOP OF the
# FPS work. Cargo recovery / salvage / hauling missions take the player
# in on foot to deal with hostiles + retrieve goods, then back out by ship
# to drop the cargo at a freight elevator (typical "RecoverCargoFPS"
# pattern). Combined with an FPS marker, this promotes the classification
# from ``FPS`` to ``FPS & Ship``.
_FPS_PLUS_SHIP_TOKENS = (
    "recovercargo", "cargo_recover",
    "salvage", "hauling",
    "freight",
)


def _classify_mission_engagement(loc_key: str | None) -> str:
    """Classify a mission as FPS / Ship / FPS & Ship from its loc_key.

    Conservative defaults — when in doubt, classify as ``Ship`` (the most
    common SC mission category and the safer mis-classification: a player
    who's expecting ship combat and gets dropped into FPS will reload and
    re-prep, but the inverse is rare in this dataset).

    Rules (applied in order):

    1. No FPS marker in the key → ``Ship``
    2. FPS marker present + cargo / salvage / freight token also present
       → ``FPS & Ship`` (mission needs FPS gear AND a ship for transport)
    3. FPS marker present, no transport token → ``FPS``
    """
    if not loc_key:
        return "Ship"

    key_lower = loc_key.lower()

    has_fps = any(tok in key_lower for tok in _FPS_TOKENS)
    if not has_fps:
        return "Ship"

    has_transport = any(tok in key_lower for tok in _FPS_PLUS_SHIP_TOKENS)
    if has_transport:
        return "FPS & Ship"

    return "FPS"


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
                    is_primary = (is_default or "primary" in action_type.lower())

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
    "rapid": "Auto", "single": "Semi-Auto", "burst": "Burst",
    "charge": "Charge", "shotgun": "Shotgun",
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


_DAMAGE_TYPES = ("DamagePhysical", "DamageEnergy", "DamageDistortion",
                 "DamageThermal", "DamageBiochemical", "DamageStun")
_DAMAGE_LABELS = {"DamagePhysical": "Phys", "DamageEnergy": "Energy",
                  "DamageDistortion": "Distort", "DamageThermal": "Thermal",
                  "DamageBiochemical": "Bio", "DamageStun": "Stun"}


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
    hp      = el.get("MaxShieldHealth")
    regen   = el.get("MaxShieldRegen")
    downed  = el.get("DownedRegenDelay")
    damaged = el.get("DamagedRegenDelay")
    pwr     = _find_resource(root, "Power")
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    em_sig  = _attr(root, "EMSignature", "nominalSignature")
    ir_sig  = _attr(root, "IRSignature", "nominalSignature")

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
    if downed  is not None: delays.append(f"Downed Delay: {_fmt(downed, 's', 1)}")
    if damaged is not None: delays.append(f"Damaged Delay: {_fmt(damaged, 's', 1)}")
    if delays:
        lines.append("  |  ".join(delays))

    phys_resist = _resist_pct(0)
    energy_resist = _resist_pct(1)
    if phys_resist or energy_resist:
        parts = []
        if phys_resist: parts.append(f"Phys: {phys_resist}")
        if energy_resist: parts.append(f"Energy: {energy_resist}")
        lines.append("Resist:  " + "  |  ".join(parts))

    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None: parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None: parts.append(f"IR: {_fmt(ir_sig)}")
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
                    guidance_type = el.get("guidanceType") or el.get("type") or el.tag.replace("Guidance", "").replace("Tracking", "")
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


def enhancements_bomb_rack(root: ET.Element) -> str:
    """Extract bomb-rack enhancements: size, grade, slot count, health."""
    # Bomb racks nest their Localization inside SAttachableComponentParams/AttachDef
    attach = _find(root, "SAttachableComponentParams")
    if attach is None:
        return ""
    ad = attach.find("AttachDef")
    if ad is None:
        return ""

    size = ad.get("Size", "")
    grade = ad.get("Grade", "")

    # Count bomb slots from SCItemMissileRackParams/slotTags
    rack = _find(root, "SCItemMissileRackParams")
    slot_count = 0
    if rack is not None:
        slot_tags = rack.find("slotTags")
        if slot_tags is not None:
            slot_count = len(list(slot_tags.findall("String")))

    comp_hp = _attr(root, "SHealthComponentParams", "Health")

    lines = []
    if size:
        lines.append(f"Size: S{size}")
    if grade:
        lines.append(f"Grade: {grade}")
    if slot_count > 0:
        lines.append(f"Bomb Slots: {slot_count}")
    if comp_hp:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
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
    cooling   = _find_resource(root, "Coolant")
    pwr       = _find_resource(root, "Power")
    comp_hp   = _attr(root, "SHealthComponentParams", "Health")
    em_sig    = _attr(root, "EMSignature", "nominalSignature")
    ir_sig    = _attr(root, "IRSignature", "nominalSignature")
    overheat  = _attr(root, "itemResourceParams", "overheatTemperature")

    lines = []
    if cooling is not None:
        lines.append(f"Cooling Rate: {_fmt(cooling, ' CR/s')}")
    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None: parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None: parts.append(f"IR: {_fmt(ir_sig)}")
        lines.append("Signatures:  " + "  |  ".join(parts))
    if overheat is not None:
        try:
            if float(overheat) < _OVERHEAT_PLACEHOLDER:
                lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
        except (ValueError, TypeError):
            lines.append(f"Overheat Temp: {_fmt(overheat, 'K')}")
    return "\\n".join(lines)


def enhancements_powerplant(root: ET.Element) -> str:
    gen       = _find_resource(root, "Power")
    comp_hp   = _attr(root, "SHealthComponentParams", "Health")
    em_sig    = _attr(root, "EMSignature", "nominalSignature")
    ir_sig    = _attr(root, "IRSignature", "nominalSignature")
    overheat  = _attr(root, "itemResourceParams", "overheatTemperature")
    distort   = _attr(root, "SDistortionParams", "Maximum")

    lines = []
    if gen is not None:
        lines.append(f"Power Output: {_fmt(gen, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None: parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None: parts.append(f"IR: {_fmt(ir_sig)}")
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
    params   = _find_by_type(root, "SQuantumDriveParams")
    speed    = params.get("driveSpeed")           if params is not None else None
    spool    = params.get("spoolUpTime")          if params is not None else None
    cooldown = params.get("cooldownTime")         if params is not None else None
    cal_rate = params.get("calibrationRate")      if params is not None else None
    cal_min  = params.get("minCalibrationRequirement") if params is not None else None
    cal_max  = params.get("maxCalibrationRequirement") if params is not None else None
    accel1   = params.get("stageOneAccelRate")    if params is not None else None
    accel2   = params.get("stageTwoAccelRate")    if params is not None else None

    pwr      = _find_resource(root, "Power")
    qt_fuel  = _find_resource(root, "QuantumFuel")
    comp_hp  = _attr(root, "SHealthComponentParams", "Health")
    em_sig   = _attr(root, "EMSignature", "nominalSignature")
    ir_sig   = _attr(root, "IRSignature", "nominalSignature")
    overheat = _attr(root, "itemResourceParams", "overheatTemperature")
    distort  = _attr(root, "SDistortionParams", "Maximum")

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
        if accel1: parts.append(f"S1: {_fmt(accel1)}")
        if accel2: parts.append(f"S2: {_fmt(accel2)}")
        lines.append("Accel:  " + "  |  ".join(parts))
    if cal_rate is not None:
        lines.append(f"Cal Rate: {_fmt(cal_rate)}  |  Required: {_fmt(cal_min)}–{_fmt(cal_max)}")
    if pwr is not None:
        lines.append(f"Power Draw: {_fmt(pwr, ' PU/s')}")
    if comp_hp is not None:
        lines.append(f"Component HP: {_fmt(comp_hp)}")
    if em_sig is not None or ir_sig is not None:
        parts = []
        if em_sig is not None: parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None: parts.append(f"IR: {_fmt(ir_sig)}")
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


def enhancements_mining_laser(root: ET.Element) -> str:
    """Extract stats for ship-mounted mining laser entities.

    Covers Arbor, Lancet, Helix, Hofstede, Klein, Impact (under
    ``ships/weapons/mining_laser_*.xml``). CIG's stock descriptions
    already author the headline numbers (Mining Laser Power, Optimal /
    Maximum Range, Module Slots, Resistance / Instability modifiers),
    so this function focuses on stats that DON'T appear in the
    description today: component HP, damage resistances, fire-beam
    energy draw + heat + wear, distortion threshold, and the per-mode
    damage-per-second values from the fire actions.

    The mining-laser modifier block (``SEntityComponentMiningLaserParams``)
    holds the laserInstability / chargeWindow / resistance / filter
    modifier values. Those duplicate what CIG already prints, but the
    user-confirmed convention for this gear category is "append always
    — CIG sometimes forgets to update the description after a balance
    pass", so they're emitted here too.

    Mining lasers that reference a globalParams record by UUID for
    their BASE values (mining-laser power range, optimal range, etc.)
    don't have those base values resolved here in v1 — local extraction
    only. That's a v2 enhancement; for now CIG's description is the
    source of truth for the base values and this function adds the
    overlay-style stats the user can't see elsewhere.
    """
    lines: list[str] = []

    # Per-fire-action damage-per-second + beam ranges + energy draw + heat.
    # Mining lasers have two fire actions in their <fireActions> wrapper:
    # the fracture beam (mining damage type) and the extraction beam.
    # Each carries its own DamageEnergy, full/zero range, and energy curve.
    fire_actions = root.findall(".//fireActions/SWeaponActionFireBeamParams")
    if not fire_actions:
        fire_actions = root.findall(".//SWeaponActionFireBeamParams")
    for idx, fa in enumerate(fire_actions, 1):
        # Mode label from mannequinTag (laser/tractor) → human label.
        mannequin = fa.find("mannequinTag")
        mtag = mannequin.get("tag") if mannequin is not None else ""
        mode = {"laser": "Fracture", "tractor": "Extraction"}.get(mtag, f"Beam {idx}")

        dps_el = fa.find("damagePerSecond/DamageInfo")
        dps = dps_el.get("DamageEnergy") if dps_el is not None else None
        full_r = fa.get("fullDamageRange")
        zero_r = fa.get("zeroDamageRange")
        e_min  = fa.get("minEnergyDraw")
        e_max  = fa.get("maxEnergyDraw")
        heat_s = fa.get("heatPerSecond")
        wear_s = fa.get("wearPerSecond")

        # Only emit a line if at least one numeric is non-zero; templates
        # ship with zeroed defaults that aren't worth showing.
        nonzero = any(
            v not in (None, "", "0", "0.0") for v in (dps, full_r, zero_r, e_min, e_max, heat_s, wear_s)
        )
        if not nonzero:
            continue
        parts: list[str] = []
        if dps not in (None, "0", "0.0"):
            parts.append(f"DPS: {_fmt(dps)}")
        if full_r not in (None, "0", "0.0") or zero_r not in (None, "0", "0.0"):
            parts.append(f"Range: {_fmt(full_r, 'm')}→{_fmt(zero_r, 'm')}")
        if e_max not in (None, "0", "0.0"):
            if e_min and e_min != e_max and e_min not in ("0", "0.0"):
                parts.append(f"Energy: {_fmt(e_min)}–{_fmt(e_max)} PU/s")
            else:
                parts.append(f"Energy: {_fmt(e_max)} PU/s")
        if heat_s not in (None, "0", "0.0"):
            parts.append(f"Heat: {_fmt(heat_s)}/s")
        if wear_s not in (None, "0", "0.0"):
            parts.append(f"Wear: {wear_s}/s")
        if parts:
            lines.append(f"<EM4>{mode}:</EM4>  " + "  |  ".join(parts))

    # Mining-laser modifier overlay. CIG's description has these but the
    # user wants them re-emitted from XML so balance updates surface even
    # when the description text rots.
    mlp = _find(root, "SEntityComponentMiningLaserParams")
    if mlp is not None:
        modifiers = mlp.find("miningLaserModifiers")
        if modifiers is not None:
            mod_parts: list[str] = []
            for child_tag, label in (
                ("laserInstability",                "Instability"),
                ("optimalChargeWindowSizeModifier","Optimal Charge Window"),
                ("resistanceModifier",             "Resistance"),
            ):
                fm = modifiers.find(f"{child_tag}/FloatModifierMultiplicative")
                if fm is not None:
                    val = fm.get("value")
                    if val and val not in ("0", "0.0"):
                        sign = "+" if float(val) > 0 else ""
                        mod_parts.append(f"{label}: {sign}{val}%")
            filter_fm = mlp.find("filterParams/filterModifier/FloatModifierMultiplicative")
            if filter_fm is not None:
                fval = filter_fm.get("value")
                if fval and fval not in ("0", "0.0"):
                    sign = "+" if float(fval) > 0 else ""
                    mod_parts.append(f"Inert Filter: {sign}{fval}%")
            if mod_parts:
                lines.append("<EM4>Modifiers:</EM4>  " + "  |  ".join(mod_parts))

    # Structural stats — component HP + distortion + ship-component-style
    # signatures if they happen to be present on a ship-mountable laser.
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    if comp_hp is not None:
        lines.append(f"<EM4>Component HP:</EM4> {_fmt(comp_hp)}")
    distort = _attr(root, "SDistortionParams", "Maximum")
    if distort is not None and distort not in ("0", "0.0"):
        lines.append(f"<EM4>Max Distortion:</EM4> {_fmt(distort)}")
    em_sig = _attr(root, "EMSignature", "nominalSignature")
    ir_sig = _attr(root, "IRSignature", "nominalSignature")
    if em_sig is not None or ir_sig is not None:
        sig_parts: list[str] = []
        if em_sig is not None and em_sig not in ("0", "0.0"):
            sig_parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None and ir_sig not in ("0", "0.0"):
            sig_parts.append(f"IR: {_fmt(ir_sig)}")
        if sig_parts:
            lines.append("<EM4>Signatures:</EM4>  " + "  |  ".join(sig_parts))

    return "\\n".join(lines) if lines else ""


def enhancements_salvage_tool(root: ET.Element) -> str:
    """Extract stats for handheld salvage tools.

    Covers the Renovar XTR (``weapons/fps_weapons/grin_salvage_repair_01.xml``)
    and the multitool's salvage_repair mode
    (``weapons/fps_weapons/grin_multitool_01_default_salvage_repair.xml``).
    Both expose a pair of ``SWeaponActionFireSalvageRepairParams`` —
    one for Repair mode, one for Salvage mode — each carrying its own
    repair-rate / efficiency / ramp-up curve. Renders both modes side
    by side so a player can compare a single tool's two halves without
    leaving the description.

    Skipped: ship-mounted salvage equipment under ``ships/salvagemunching``
    is currently placeholder XMLs with ``Name="@LOC_PLACEHOLDER"`` — no
    real stats to extract until CIG fleshes those records out.
    """
    lines: list[str] = []

    fire_actions = root.findall(".//SWeaponActionFireSalvageRepairParams")
    for fa in fire_actions:
        # Mode is encoded on the element itself via the `salvageRepairMode`
        # attribute ("Repair" / "Salvage"). Use it as the EM4-tagged header.
        mode = fa.get("salvageRepairMode") or fa.get("name") or "Mode"
        eff      = fa.get("materialEfficiency")
        hp_rate  = fa.get("maxHealthRepairRate")
        dmg_rate = fa.get("maxDamageMapRepairRate")
        h2a      = fa.get("healthToAmmoRatio")
        ramp_up  = fa.get("rampUpTime")
        ramp_dn  = fa.get("rampDownTime")
        e_min    = fa.get("minEnergyDraw")
        e_max    = fa.get("maxEnergyDraw")
        heat_s   = fa.get("heatPerSecond")
        wear_s   = fa.get("wearPerSecond")

        parts: list[str] = []
        if hp_rate not in (None, "0", "0.0"):
            parts.append(f"HP Rate: {_fmt(hp_rate)}/s")
        if dmg_rate not in (None, "0", "0.0"):
            parts.append(f"Damage-Map Rate: {_fmt(dmg_rate)}/s")
        if eff not in (None, "1", "1.0"):
            # 1.0 is the default no-op — only emit when CIG actually tunes
            # below unity (Renovar Salvage mode runs at 0.7 efficiency).
            parts.append(f"Material Efficiency: {_fmt(eff, '', 2)}")
        if h2a not in (None, "0", "0.0"):
            parts.append(f"HP/Ammo: {_fmt(h2a, '', 2)}")
        if ramp_up not in (None, "0", "0.0") or ramp_dn not in (None, "0", "0.0"):
            parts.append(f"Ramp: {_fmt(ramp_up, 's', 1)}↑ {_fmt(ramp_dn, 's', 1)}↓")
        if e_max not in (None, "0", "0.0"):
            if e_min and e_min != e_max and e_min not in ("0", "0.0"):
                parts.append(f"Energy: {_fmt(e_min)}–{_fmt(e_max)} PU/s")
            else:
                parts.append(f"Energy: {_fmt(e_max)} PU/s")
        if heat_s not in (None, "0", "0.0"):
            parts.append(f"Heat: {_fmt(heat_s)}/s")
        if wear_s not in (None, "0", "0.0"):
            parts.append(f"Wear: {wear_s}/s")
        if parts:
            lines.append(f"<EM4>{mode}:</EM4>  " + "  |  ".join(parts))

    # Structural stats (durability / wear) — same pattern as mining lasers.
    comp_hp = _attr(root, "SHealthComponentParams", "Health")
    if comp_hp is not None and comp_hp not in ("0", "0.0"):
        lines.append(f"<EM4>Component HP:</EM4> {_fmt(comp_hp)}")
    wear_max = _attr(root, "SWearAccumulatorParams", "MaxLifetimeHours")
    if wear_max is not None and wear_max not in ("0", "0.0"):
        lines.append(f"<EM4>Max Lifetime:</EM4> {_fmt(wear_max, 'h', 1)}")

    return "\\n".join(lines) if lines else ""


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


# Spawn-group classification buckets surfaced in the MISSION DETAILS block.
# The four-bucket model replaces the pre-1.4.1 binary "Enemies / Non-hostiles"
# tally that defaulted any unrecognized spawn-group name to hostile, silently
# miscounting civilians, recipients, and inanimate satellites as enemies.
SPAWN_HOSTILE = "hostile"
SPAWN_FRIENDLY = "friendly"
SPAWN_OBJECTIVE = "objective"
SPAWN_UNKNOWN = "unknown"

# Keyword table grounded in a full sweep of the LIVE DataForge cache
# (3,123 mission + contract XMLs, 86 distinct ship-group names + 368 NPC-group
# names). Earlier entries win — order is "specific compound names → objective
# patterns → specific NPC roles → civilians → faction names → generic hostile
# signals → wave/tier rollup → generic friendly catch-all". The kind column is
# "ship", "npc", or None (matches either). Substring match against name.lower().
#
# Notable calls locked here:
#   * "Allies" → hostile. In mercenary/council contracts the player IS the
#     attacker; the "Allies" group spawned under AlliedSpawnDescriptions_BP is
#     reinforcements allied with the antagonist NPC, not the player.
#   * "Defenders" → hostile in both kinds. Mercenary bounty-kill contracts
#     spawn them under MissionTargets_BP alongside the Target group — they
#     defend the bounty target. Pre-1.4.1, the bare "defend" substring routed
#     ship-context Defenders to friendly (wrong).
#   * "Civs" / "Civ" → friendly. Pre-1.4.1, only the literal "civilian"
#     substring matched, so the 80+ shorthand occurrences in infiltrate
#     missions defaulted to hostile.
#   * "Reinforcments" (missing 'e') and "Civillian" (extra 'l') are CIG typos
#     in the source data — matched explicitly so they don't fall to Unknown.
#   * Wave / tier / spawn-closet names roll up to a single "Hostiles" or
#     "Hostile Wave" label rather than fragmenting into per-tier sub-counts.
_SPAWN_KEYWORD_TABLE: tuple[tuple[str, str | None, str, str], ...] = (
    # --- Tier 1: highly specific compound names ---
    ("shiptodefend",     "ship", SPAWN_FRIENDLY,  "Ships to Defend"),
    ("ship to defend",   "ship", SPAWN_FRIENDLY,  "Ships to Defend"),
    ("escortship",       "ship", SPAWN_FRIENDLY,  "Escort Wings"),
    ("escort ship",      "ship", SPAWN_FRIENDLY,  "Escort Wings"),
    ("salvageable",      "ship", SPAWN_FRIENDLY,  "Salvageable Ships"),
    ("recipientship",    "ship", SPAWN_FRIENDLY,  "Recipient"),
    ("recipient",        "ship", SPAWN_FRIENDLY,  "Recipient"),
    ("friendlyship",     "ship", SPAWN_FRIENDLY,  "Friendlies"),
    ("interdiction",     "ship", SPAWN_HOSTILE,   "Interdiction Ships"),
    ("acepilotship",     "ship", SPAWN_HOSTILE,   "Ace Pilots"),
    ("acepilot",         "ship", SPAWN_HOSTILE,   "Ace Pilots"),
    ("ace pilot",        "ship", SPAWN_HOSTILE,   "Ace Pilots"),
    ("heist",            "ship", SPAWN_HOSTILE,   "Heist Target"),
    ("security ships",   "ship", SPAWN_HOSTILE,   "Security Forces"),
    ("security_ships",   "ship", SPAWN_HOSTILE,   "Security Forces"),
    # ``initialenemies`` is matched here (above the generic ``enemy`` substring
    # at tier 7) so the wave-style spawn label wins over the generic hostile
    # label — keeps it visually grouped with other waves ("Hostile Wave").
    ("initialenemies",   "ship", SPAWN_HOSTILE,   "Hostile Wave"),

    # --- Tier 2: specific hostile faction / creature names ---
    # These beat the generic NPC role keywords at tier 6 so a compound name
    # like "PrivSec - Sentry - 4" or "Soldier Pirate x 3" labels by faction
    # rather than role (the user explicitly asked for faction-level labels).
    ("pirate",           None,   SPAWN_HOSTILE,   "Pirates"),
    ("bandit",           None,   SPAWN_HOSTILE,   "Bandits"),
    ("xeno",             "ship", SPAWN_HOSTILE,   "Xeno Threat"),
    ("vulture",          "ship", SPAWN_HOSTILE,   "Xeno Threat"),
    ("ninetails",        None,   SPAWN_HOSTILE,   "Nine Tails"),
    ("nine tails",       None,   SPAWN_HOSTILE,   "Nine Tails"),
    ("nine_tails",       None,   SPAWN_HOSTILE,   "Nine Tails"),
    ("mauler",           "ship", SPAWN_HOSTILE,   "Maulers"),
    ("polaris",          "ship", SPAWN_HOSTILE,   "Polaris"),
    ("prospector",       "ship", SPAWN_HOSTILE,   "Prospectors"),
    ("kopion",           None,   SPAWN_HOSTILE,   "Kopions"),
    ("private security", "npc",  SPAWN_HOSTILE,   "Private Security"),
    ("privatesecurity",  "npc",  SPAWN_HOSTILE,   "Private Security"),
    ("privsec",          "npc",  SPAWN_HOSTILE,   "Private Security"),

    # --- Tier 3: civilians + hostages (friendly) ---
    # Placed before Objectives so "Probe Civillian" (CIG typo + civilian
    # context) lands in Friendlies rather than Objectives — civilian intent
    # is stronger than the inanimate-probe signal.
    ("civilian",         None,   SPAWN_FRIENDLY,  "Civilians"),
    ("civillian",        None,   SPAWN_FRIENDLY,  "Civilians"),  # CIG typo
    ("civs",             "npc",  SPAWN_FRIENDLY,  "Civilians"),
    ("civ",              "npc",  SPAWN_FRIENDLY,  "Civilians"),
    ("hostage",          "npc",  SPAWN_FRIENDLY,  "Hostages"),

    # --- Tier 4: inanimate / McGuffin objectives ---
    ("probe ",           "ship", SPAWN_OBJECTIVE, "Probe"),
    ("probe1",           "ship", SPAWN_OBJECTIVE, "Probe"),
    ("probe2",           "ship", SPAWN_OBJECTIVE, "Probe"),
    ("probe3",           "ship", SPAWN_OBJECTIVE, "Probe"),

    # --- Tier 5: Allies → hostile (ambush / mercenary context) ---
    ("allies",           "ship", SPAWN_HOSTILE,   "Hostile Allies"),
    ("ally",             "ship", SPAWN_HOSTILE,   "Hostile Allies"),

    # --- Tier 6: specific NPC roles ---
    ("boss",             "npc",  SPAWN_HOSTILE,   "Boss"),
    ("backup",           "npc",  SPAWN_HOSTILE,   "Backup"),
    ("juggernaut",       None,   SPAWN_HOSTILE,   "Juggernauts"),
    ("sniper",           "npc",  SPAWN_HOSTILE,   "Snipers"),
    ("cqc",              "npc",  SPAWN_HOSTILE,   "CQC"),
    ("soldier",          "npc",  SPAWN_HOSTILE,   "Soldiers"),
    ("techie",           "npc",  SPAWN_HOSTILE,   "Technicians"),
    ("techi",            "npc",  SPAWN_HOSTILE,   "Technicians"),
    ("tech",             "npc",  SPAWN_HOSTILE,   "Technicians"),
    ("captain",          "npc",  SPAWN_HOSTILE,   "Captain"),
    ("sentry",           "npc",  SPAWN_HOSTILE,   "Sentries"),
    ("guard",            "npc",  SPAWN_HOSTILE,   "Guards"),
    ("grunt",            "npc",  SPAWN_HOSTILE,   "Grunts"),
    ("attacker",         "npc",  SPAWN_HOSTILE,   "Attackers"),

    # --- Tier 7: generic hostile signal words ---
    ("target",           None,   SPAWN_HOSTILE,   "Targets"),
    ("reinforcement",    None,   SPAWN_HOSTILE,   "Reinforcements"),
    ("reinforcments",    None,   SPAWN_HOSTILE,   "Reinforcements"),  # CIG typo
    ("enemy",            None,   SPAWN_HOSTILE,   "Hostiles"),
    ("enemies",          None,   SPAWN_HOSTILE,   "Hostiles"),
    ("hostile",          None,   SPAWN_HOSTILE,   "Hostiles"),
    # Defenders OF the player's target (bounty kill, infiltrate) = hostile.
    ("defender",         None,   SPAWN_HOSTILE,   "Defenders"),

    # --- Tier 8: wave / tier / generic-hostile rollup ---
    ("wave",             "ship", SPAWN_HOSTILE,   "Hostile Wave"),
    # NPC tier / difficulty / location-coded spawns collapse to a single
    # "Hostiles" label so the breakdown doesn't fragment into Level-1-x3,
    # Level-2-x3, ... for every dataheist tier.
    ("level ",           "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("lightspawn",       "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("mediumspawn",      "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("heavyspawn",       "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("basic",            "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("easy",             "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("medium",           "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("hard",             "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("exterior",         "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("defence",          "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("building",         "npc",  SPAWN_HOSTILE,   "Hostiles"),
    ("spawncloset",      "npc",  SPAWN_HOSTILE,   "Hostiles"),

    # --- Tier 9: generic friendly catch-all (lowest priority) ---
    ("escort",           None,   SPAWN_FRIENDLY,  "Escorts"),
    ("friendly",         None,   SPAWN_FRIENDLY,  "Friendlies"),
    ("protect",          None,   SPAWN_FRIENDLY,  "Protected"),
)


def classify_spawn_group(name: str, kind: str) -> tuple[str, str]:
    """Return ``(bucket, display_label)`` for a spawn-group ``Name``.

    ``kind`` is ``"ship"`` or ``"npc"``. Falls through to
    ``(SPAWN_UNKNOWN, "Unknown")`` when no keyword matches — the new "Unknown"
    bucket replaces the pre-1.4.1 default-to-hostile behavior that silently
    miscounted any unrecognized name as an enemy. Callers that have the
    enclosing XML element handy can pass it to ``_wrapper_hostile_fallback``
    to recover a hostile classification when the Name itself is empty or
    unmatched but the parent ``MissionProperty`` wrapper is player-relative.
    """
    name_lower = name.lower()
    for substring, kind_filter, bucket, label in _SPAWN_KEYWORD_TABLE:
        if kind_filter is not None and kind_filter != kind:
            continue
        if substring in name_lower:
            return bucket, label
    return SPAWN_UNKNOWN, "Unknown"


# Player-relative MissionProperty wrappers that reliably indicate hostile-to-
# player intent regardless of mission template. Used as a fallback ONLY when
# Name-keyword classification returns Unknown — most commonly when CIG omits
# the spawn-group ``Name`` attribute entirely (e.g. 27 unnamed groups in the
# eckhart ship-ambush XML, all wrapped in ``TargetSpawnDescriptions_BP``).
#
# The relational wrappers — ``AlliedSpawnDescriptions_BP``,
# ``AttackedShipSpawnDescriptions_BP``, ``ReinforcementsSpawnDescriptions_BP``
# — are deliberately NOT in this list because their hostility flips per
# mission template (e.g. "Allies" of the antagonist NPC in an ambush mission
# are hostile to the player; reinforcements in a defend mission are friendly).
# Only wrappers whose semantics are stable from the player's perspective
# qualify: Hostile (literal), Target (player-relative — players target
# hostiles), Boss (always hostile), Eliminate (verb is unambiguous).
#
# Format: (lowercase_substring_match_against_missionVariableName, display_label).
# Earlier entries win.
_WRAPPER_HOSTILE_FALLBACK: tuple[tuple[str, str], ...] = (
    ("hostileshipspawn",   "Hostiles"),
    ("hostilespawn",       "Hostiles"),
    ("targetspawn",        "Targets"),
    ("eliminate",          "Hostiles"),
    ("boss",               "Boss"),
)


def _wrapper_hostile_fallback(group: ET.Element) -> tuple[str, str] | None:
    """Return ``(SPAWN_HOSTILE, label)`` if ``group`` sits inside a
    player-relative hostile ``MissionProperty`` wrapper, else ``None``.

    Walks up the XML tree via ``getparent()`` to find the nearest enclosing
    ``<MissionProperty missionVariableName="...">``; only the first one is
    inspected. When the wrapper name matches a substring in
    ``_WRAPPER_HOSTILE_FALLBACK``, the spawn group is reclassified as hostile
    with the wrapper-derived label; otherwise the lookup stops there (the
    wrapper IS the local mission context, walking further up doesn't help).
    """
    node = group.getparent()
    while node is not None:
        if node.tag == "MissionProperty":
            wrapper_name = (node.get("missionVariableName") or "").lower()
            for substring, label in _WRAPPER_HOSTILE_FALLBACK:
                if substring in wrapper_name:
                    return SPAWN_HOSTILE, label
            return None
        node = node.getparent()
    return None


# Per-bucket per-label breakdown of spawn counts. Outer key: bucket constant
# (SPAWN_HOSTILE / SPAWN_FRIENDLY / SPAWN_OBJECTIVE / SPAWN_UNKNOWN). Inner
# key: display label produced by ``classify_spawn_group``. Value: count.
SpawnBreakdown = dict[str, dict[str, int]]


def _empty_spawn_breakdown() -> SpawnBreakdown:
    return {
        SPAWN_HOSTILE: {},
        SPAWN_FRIENDLY: {},
        SPAWN_OBJECTIVE: {},
        SPAWN_UNKNOWN: {},
    }


def _add_spawn(breakdown: SpawnBreakdown, bucket: str, label: str, count: int) -> None:
    if count <= 0:
        return
    breakdown[bucket][label] = breakdown[bucket].get(label, 0) + count


def _extract_spawn_counts(element: ET.Element) -> SpawnBreakdown:
    """Extract a per-bucket per-label breakdown of spawn descriptions.

    Parses ``SpawnDescription_ShipGroup`` and ``SpawnDescription_NPC_Group``
    elements within the given XML element scope, classifies each by name via
    :func:`classify_spawn_group`, and aggregates counts per (bucket, label).

    Pre-1.4.1 this returned ``(num_waves, num_enemies, num_not_enemies)`` and
    bucketed everything unrecognized as hostile — see the keyword-table
    docstring for the misclassifications that surfaced.
    """
    breakdown = _empty_spawn_breakdown()

    for sg in element.findall(".//SpawnDescription_ShipGroup"):
        name = sg.get("Name", "")
        ships = sg.findall(".//SpawnDescription_Ship")
        total = sum(int(s.get("concurrentAmount", "0")) for s in ships)
        if total <= 0:
            continue
        # Turret ship-groups are reported separately by _extract_turret_info;
        # skipping them here keeps them off the Hostiles tally so the
        # MISSION DETAILS block doesn't double-count once as Hostiles and
        # once as Turrets.
        if "turret" in name.lower():
            continue
        bucket, label = classify_spawn_group(name, "ship")
        if bucket == SPAWN_UNKNOWN:
            fallback = _wrapper_hostile_fallback(sg)
            if fallback is not None:
                bucket, label = fallback
        _add_spawn(breakdown, bucket, label, total)

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
            m = re.search(r"x\s*(\d+)", name)
            if m:
                total_npcs = int(m.group(1))

        if total_npcs <= 0:
            continue

        bucket, label = classify_spawn_group(name, "npc")
        if bucket == SPAWN_UNKNOWN:
            fallback = _wrapper_hostile_fallback(ng)
            if fallback is not None:
                bucket, label = fallback
        _add_spawn(breakdown, bucket, label, total_npcs)

    return breakdown


def _format_spawn_lines(breakdown: SpawnBreakdown) -> list[str]:
    """Render a SpawnBreakdown as the MISSION DETAILS block lines.

    Emits at most four ``<EM4>...</EM4>`` lines: Hostiles, Friendlies,
    Objectives, Unknown. Each non-empty named bucket lists its types
    alphabetically as ``Label xN``; Unknown collapses to a single count.
    Empty buckets are omitted entirely.
    """
    lines: list[str] = []
    for bucket, header in (
        (SPAWN_HOSTILE,   "Hostiles"),
        (SPAWN_FRIENDLY,  "Friendlies"),
        (SPAWN_OBJECTIVE, "Objectives"),
    ):
        items = breakdown.get(bucket) or {}
        if not items:
            continue
        parts = [f"{lbl} x{cnt}" for lbl, cnt in sorted(items.items())]
        lines.append(f"<EM4>{header}:</EM4> {', '.join(parts)}")
    unknown = breakdown.get(SPAWN_UNKNOWN) or {}
    unknown_total = sum(unknown.values())
    if unknown_total > 0:
        lines.append(f"<EM4>Unknown:</EM4> {unknown_total}")
    return lines


def _merge_spawn_breakdowns_max(into: SpawnBreakdown, src: SpawnBreakdown) -> None:
    """Per-label MAX merge ``src`` into ``into``.

    Mirrors the pre-1.4.1 ``max(max_enemies, venemies)`` aggregation across
    desc-variant tiers: a single mission description can have easy / medium /
    hard variants with different spawn counts; we surface the worst case per
    type so a player sizing the mission sees the top-of-tier roster.
    """
    for bucket, items in src.items():
        target = into.setdefault(bucket, {})
        for label, count in items.items():
            if count > target.get(label, 0):
                target[label] = count


def _extract_turret_info(root: ET.Element) -> str | None:
    """Return a formatted ``count (hostility)`` for mission turrets, or None.

    Two CIG signal sources, used together:

    1. ``SpawnDescription_ShipGroup Name="Turrets"`` — the mission spawns
       turret entities at the location. ~119/2558 pu_missions in 4.7 use
       this. The ``concurrentAmount`` on each ``SpawnDescription_Ship``
       child gives the count.
    2. ``MissionProperty missionVariableName="OverrideTurretHosility_BP"``
       (note CIG's spelling — "Hosility", not "Hostility") with a Boolean
       value. ~8 missions set this. ``value="1"`` means the mission
       deliberately wants its turrets hostile to the player; only seen as
       ``"1"`` in the live 4.7 dataset, so a friendly explicit override is
       hypothetical until observed.

    Hostility default is "hostile" — when a mission spawns turrets without
    an explicit override, you're almost always going to a hostile location
    where the turrets are defending the target. Players answering "what
    should I expect" are best served by the conservative warning. Friendly
    turret cases will get a ``(friendly)`` qualifier if/when CIG ever ships
    one.

    Returns:
        ``"4 (hostile)"`` / ``"2 (friendly)"`` / ``"present (hostile)"``
        when a count is unavailable but the override flag was set, or
        ``None`` when the mission has no turret references at all.
    """
    turret_count = 0
    for sg in root.findall(".//SpawnDescription_ShipGroup"):
        name = sg.get("Name", "").lower()
        if "turret" not in name:
            continue
        ships = sg.findall(".//SpawnDescription_Ship")
        turret_count += sum(int(s.get("concurrentAmount", "0")) for s in ships)

    explicit_hostility: bool | None = None
    for prop in root.findall(".//MissionProperty"):
        if prop.get("missionVariableName") == "OverrideTurretHosility_BP":
            val_el = prop.find(".//MissionPropertyValue_Boolean")
            if val_el is not None:
                explicit_hostility = val_el.get("value") == "1"
            break

    if turret_count == 0 and explicit_hostility is None:
        return None

    count_str = str(turret_count) if turret_count > 0 else "present"

    if explicit_hostility is False:
        return f"{count_str} (friendly)"
    return f"{count_str} (hostile)"


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


def enhancements_mission(root: ET.Element, reputation_lookup: dict[str, int] | None = None,
                         rep_xp_label: str = _DEFAULT_REP_XP_LABEL) -> str:
    """Extract mission/contract reward stats (aUEC + Reputation XP) and flags.

    Extracts:
    - Engagement Type (FPS / Ship / FPS & Ship) from the mission loc_key
    - aUEC mission reward amount
    - Reputation XP from reward UUID references using the reputation_lookup table
    - Mission flags (Chain, Starter, Unique)
    """
    lines = []
    reputation_lookup = reputation_lookup or {}

    try:
        loc_key = _mission_loc_key(root) or _loc_key(root)
        lines.append(f"<EM4>Engagement Type:</EM4> {_classify_mission_engagement(loc_key)}")

        flags = _extract_mission_flags(root)
        lines.append(f"<EM4>Mission Type:</EM4> {', '.join(flags) if flags else 'Standard'}")

        difficulty = _extract_difficulty(root)
        if difficulty:
            lines.append(f"<EM4>Difficulty (1-7):</EM4> {difficulty}")

        total_rep_xp = _extract_mission_xp(root, reputation_lookup)
        if total_rep_xp > 0:
            lines.append(f"<EM4>{rep_xp_label}:</EM4> +{total_rep_xp:,}")

        # Extract spawn/wave counts — bucketed Hostiles / Friendlies /
        # Objectives / Unknown rather than the pre-1.4.1 single-tally
        # Enemies + Non-hostiles. Empty buckets are dropped by the formatter.
        lines.extend(_format_spawn_lines(_extract_spawn_counts(root)))

        # Turret presence — groups visually with the other hostile-entity
        # tallies so a player sizing up the mission sees enemies + turrets
        # adjacently in the MISSION DETAILS block.
        turret_info = _extract_turret_info(root)
        if turret_info:
            lines.append(f"<EM4>Turrets:</EM4> {turret_info}")

    except Exception:
        pass

    return "\\n".join(lines) if lines else ""


# Matches a leading CIG-baked size designator in an entity display name —
# "S0 Helix", "S00 Hofstede", "S1 …" etc. Mining heads and a handful of
# other entity classes carry the size as a prefix on the loc-name attribute
# itself (rather than in the description's Size: header field that
# `_component_name_tag` reads). When such a name appears in a blueprint
# reward list, the result sits next to entries the tagger DID classify
# (e.g. "Surveyor-Go [IND-S0-C]"), producing two different size-indicator
# conventions stacked together. Strip the prefix in blueprint-list output
# so the rendered list reads with one convention: bare name for items the
# tagger couldn't classify, "name [CLASS-Sx-grade]" for items it could.
# Anchor on word boundary so legitimate names starting with "S" + letters
# (Sasquatch, Slicer) aren't touched — the regex requires digits after S.
_CIG_SIZE_PREFIX_RE = re.compile(r"^S\d+\s+")


def _strip_cig_size_prefix(name: str) -> str:
    """Remove a leading 'S0 ' / 'S00 ' / 'S1 ' size prefix from a display name."""
    return _CIG_SIZE_PREFIX_RE.sub("", name, count=1)


# Rank-tier markers in blueprint pool filenames. CIG names progression-
# gated pools with a `RankN` or `RankNtoM` suffix (e.g. bp_rewards_shubinrank0to1
# / shubinrank2to3 / shubinrank4). Surfacing those as a sub-section label
# in POTENTIAL BLUEPRINTS lets a player tell at a glance which rewards
# correspond to which reputation tier — without the label, three tiers
# get merged into one wall of items and it's ambiguous which actually
# rolls for the player's current rank.
#
# Two patterns to recognise:
#   `RankNtoM` → "Rank N–M"   (e.g. Rank0to1 → "Rank 0–1")
#   `RankN`    → "Rank N"     (e.g. Rank4    → "Rank 4")
# Case-insensitive because filenames are lowercased; `(?i)` covers both
# "rank0to1" (raw filename) and "Rank0to1" (if anyone passes a __ref-cased
# name). Non-matching pool names return empty string and the sub-section
# falls back to the system-only header it had before this feature.
_POOL_RANK_RANGE_RE  = re.compile(r"(?i)rank(\d+)to(\d+)")
_POOL_RANK_SINGLE_RE = re.compile(r"(?i)rank(\d+)(?!\d|to)")


def _pool_rank_label(pool_name: str) -> str:
    """Derive a human-readable rank-tier label from a blueprint pool's filename.

    Examples:
      "bp_rewards_shubinrank0to1"  → "Rank 0–1"
      "bp_rewards_shubinrank4"     → "Rank 4"
      "bp_rewards_shubinrank2to3"  → "Rank 2–3"
      "bp_rewards_headhuntersmercenaryshipregionc" → ""  (region, not rank)

    Returns empty string when no rank token matches — callers should
    treat that as "no label" and render the sub-section header without
    a rank suffix.
    """
    if not pool_name:
        return ""
    m = _POOL_RANK_RANGE_RE.search(pool_name)
    if m:
        return f"Rank {m.group(1)}–{m.group(2)}"  # en-dash
    m = _POOL_RANK_SINGLE_RE.search(pool_name)
    if m:
        return f"Rank {m.group(1)}"
    return ""


def _merge_blueprint_pool(
    mission_blueprints: dict, title_key: str, system_name: str,
    pool_uuid: str, pool_items: list, pool_label: str,
) -> None:
    """Merge *pool_items* into mission_blueprints[title_key][system_name][pool_label],
    preserving order and de-duplicating across repeated calls."""
    per_system = mission_blueprints.setdefault(title_key, {})
    per_label = per_system.setdefault(system_name, {})
    existing_items = per_label.setdefault(pool_label, [])
    for item in pool_items:
        if item not in existing_items:
            existing_items.append(item)


def _name_from_blueprint_filename(bp_xml: Path) -> str:
    """Best-effort fallback display name from a blueprint XML's filename.

    Used when the blueprint's entityClass UUID isn't resolvable in the
    entity_names lookup (CIG sometimes ships blueprint references ahead
    of the entity definitions in PTU patches). The result isn't pretty
    but it's recognisable enough for users to know what reward category
    a mission pays — much better than dropping the whole BP tag.

    Examples:
        bp_craft_nozzle_fuelgiver_grin_nozzlefast.xml
            → "Nozzle Fuelgiver Grin Nozzlefast"
        bp_craft_salvage_modifier_scraper_large.xml
            → "Salvage Modifier Scraper Large"
        bp_rewards_eckhartsecuritykillnpcboss.xml
            → "Eckhartsecuritykillnpcboss"
    """
    stem = bp_xml.stem
    # Strip common prefixes — bp_craft_, bp_rewards_, bp_ — so the
    # surfaced part is the descriptive tail.
    for prefix in ("bp_craft_", "bp_rewards_", "bp_"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):]
            break
    # Replace separators with spaces and title-case.
    return stem.replace("_", " ").replace("-", " ").title()


def build_blueprint_pool_lookup(
    pool_dir: Path,
    bp_dir: Path,
    entity_names: dict[str, str],
    entity_names_by_filename: dict[str, str] | None = None,
    entity_name_tags: dict[str, str] | None = None,
    name_tag_placement: str = "prepend",
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Build mapping of blueprint pool UUID → list of craftable item display names.

    Resolution chain for each blueprint:
      1. Look up the blueprint's `entityClass` UUID in `entity_names`
         (first-class path; works for the bulk of items in stable patches).
      2. If 1 misses (CIG WIP — blueprint references an entityClass UUID
         that isn't __ref'd anywhere yet), look up the blueprint XML's
         filename stem (minus `bp_craft_` prefix) in
         `entity_names_by_filename`. CIG's authored layout puts the
         entity XML in `entities/scitem/...` with the same stem; the
         entity's localized Name attribute resolves cleanly even if the
         UUID linkage is broken. This recovers real product names like
         "Norfield" or "Harkin" instead of falling all the way through
         to filename-derived placeholders.
      3. If 2 also misses, derive a name from the blueprint XML's filename
         (`Nozzle Fuelgiver Grin Nozzlefast`-style — recognisable but
         not pretty). Set as a backstop so the BP tag still fires.

    When ``entity_name_tags`` is supplied AND the tier-1 (UUID) match
    hits, the matching ``[CLASS-Sx-grade]`` tag is woven into the
    display name — mirroring the tag the components pipeline writes
    onto stock component titles. ``name_tag_placement`` controls
    which side the tag lands on ("prepend" / "append") and is
    expected to match the components Tag Builder's placement so the
    POTENTIAL BLUEPRINTS list stays visually consistent with the
    component names on the strings tab. Tier-2 / tier-3 fallbacks
    intentionally skip the tag: the tag dict is keyed by entityClass
    UUID, which is exactly the linkage that's missing in those code
    paths, so there's nothing to look up. FPS gear / weapons / ships
    never get a tag entry, so they pass through bare even on a UUID hit.

    Args:
        pool_dir: Directory containing BlueprintPoolRecord XMLs.
        bp_dir: Directory containing CraftingBlueprintRecord XMLs.
        entity_names: UUID → display name (built from entities/scitem/).
        entity_names_by_filename: filename-stem → display name (same
            source). Optional — without it the resolver skips path 2.
        entity_name_tags: UUID → ``[CLASS-Sx-grade]`` tag. Optional —
            without it items render without the inline component tag.
        name_tag_placement: "prepend" (tag before the name, the
            default) or "append" (tag after). Mirrors the components
            Tag Builder placement so the blueprint list reads the
            same way as the strings tab.

    Returns:
        Tuple of:
          - pool_items: ``{pool __ref UUID: sorted list of item display names}``
          - pool_names: ``{pool __ref UUID: filename stem}``. The stem is the
            CIG-authored filename minus the ``bp_rewards_`` / ``bp_`` prefix
            (e.g. ``shubinrank0to1``). Downstream uses this to derive
            sub-section labels via ``_pool_rank_label`` so the rendered
            POTENTIAL BLUEPRINTS block can show ``[Stanton, Rank 0–1]``
            headers without re-reading the pool XMLs. Empty for any pool
            that didn't produce items (kept in lockstep with ``pool_items``).
    """
    entity_names_by_filename = entity_names_by_filename or {}
    entity_name_tags = entity_name_tags or {}
    if not pool_dir.exists() or not bp_dir.exists():
        return {}, {}

    # Index all blueprint files by __ref UUID → (entityClass UUID,
    # entity-stem-for-filename-lookup, filename-derived backstop name).
    # The resolver below tries entity_names[uuid] first, then
    # entity_names_by_filename[stem-without-bp_craft_], then the
    # filename-derived string as a last resort.
    bp_entity: dict[str, tuple[str, str, str]] = {}
    for xml_file in bp_dir.rglob("*.xml"):
        try:
            root = ET.parse(xml_file).getroot()
            ref = root.get("__ref", "")
            if not ref:
                continue
            entity_class = ""
            for elem in root.iter():
                if _poly_type(elem) == "CraftingProcess_Creation":
                    entity_class = elem.get("entityClass", "")
                    break
            # Derive the entity-stem from the bp filename for the
            # filename-fallback lookup. CIG's convention is
            # `bp_craft_<stem>.xml` for the blueprint and `<stem>.xml`
            # for the entity (e.g. bp_craft_nozzle_fuelgiver_grin_nozzlefast
            # ↔ nozzle_fuelgiver_grin_nozzlefast).
            stem = xml_file.stem
            for prefix in ("bp_craft_", "bp_rewards_", "bp_"):
                if stem.startswith(prefix):
                    stem = stem[len(prefix):]
                    break
            bp_entity[ref] = (entity_class, stem.lower(), _name_from_blueprint_filename(xml_file))
        except ET.ParseError:
            continue

    # Build pool UUID → item names AND pool UUID → filename stem.
    # The stem is stored in lowercase since downstream rank-label parsing
    # is case-insensitive and the filename casing is already lowercased
    # by CIG. Stripping the bp_rewards_ / bp_ prefix keeps the stem
    # focused on the meaningful part of the name.
    pool_items: dict[str, list[str]] = {}
    pool_names: dict[str, str] = {}
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
                    entity_ref, entity_stem, filename_fallback = bp_entity[bp_ref]
                    # Tier 1: UUID match (best — gives the localized
                    # display name from the entity's Localization Name
                    # attribute, e.g. "Norfield" / "Harkin" / "RN-7s").
                    if entity_ref in entity_names:
                        name = _strip_cig_size_prefix(entity_names[entity_ref])
                        # Mirror the components-pipeline annotation:
                        # ship components get an inline [CLASS-Sx-grade]
                        # tag (e.g. "Norfield [MIL-S1-A]"). FPS gear and
                        # other non-component blueprints have no tag
                        # entry and pass through bare.
                        tag = entity_name_tags.get(entity_ref)
                        if tag:
                            if name_tag_placement == "append":
                                name = f"{name} {tag}"
                            else:
                                name = f"{tag} {name}"
                    # Tier 2: filename-stem match. Recovers real product
                    # names when CIG ships the blueprint ahead of the
                    # entity-UUID linkage (PTU 4.8 fuel-nozzle pattern).
                    elif entity_stem in entity_names_by_filename:
                        name = _strip_cig_size_prefix(entity_names_by_filename[entity_stem])
                    # Tier 3: filename-derived placeholder. Ugly but
                    # ensures the BP tag still surfaces.
                    else:
                        name = filename_fallback
                    if name and name not in names:
                        names.append(name)
            if names:
                pool_items[pool_uuid] = sorted(names)
                stem = xml_file.stem.lower()
                for prefix in ("bp_rewards_", "bp_"):
                    if stem.startswith(prefix):
                        stem = stem[len(prefix):]
                        break
                pool_names[pool_uuid] = stem
        except ET.ParseError:
            continue

    logger.info(f"Blueprint pool lookup: {len(pool_items)} pools with items")
    return pool_items, pool_names


def _build_template_lookup(
    templates_dir: Path,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> dict[str, tuple[str, str]]:
    """Build mapping of contract template UUID → (title_loc_key, desc_loc_key).

    Some contracts don't have inline ContractStringParam elements and instead
    inherit title/description from their template via LocID elements.
    """
    lookup: dict[str, tuple[str, str]] = {}
    if not templates_dir.exists():
        return lookup

    _files = (
        _index_rglob(xml_path_index, templates_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else templates_dir.rglob("*.xml")
    )
    for xml_file in _files:
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
            tail = debug_name[len(prefix):]
            return tail.split("_", 1)[0]
    return debug_name.rsplit("_", 1)[-1]


def scan_contract_generators(
    contractgen_dir: Path,
    reputation_lookup: dict[str, int] | None = None,
    blueprint_pools: dict[str, list[str]] | None = None,
    entity_names: dict[str, str] | None = None,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
    pool_names: dict[str, str] | None = None,
    standings_lookup: dict[str, str] | None = None,
):
    """Scan contract generator XMLs for mission variants with different systems.

    Returns tuple of:
        - missions: dict mapping title_key → [(system_name, success_xp, failure_xp, desc_key, flags, spawns, difficulty, has_bp, bp_chance, bp_variant, rank_name), ...]
        - mission_blueprints: dict title_key → dict system_name → dict pool_label → list of craftable item display names.
          The pool_label dimension preserves rank-tier sub-grouping derived from the
          pool filename (e.g. ``Rank 0–1`` / ``Rank 2–3`` / ``Rank 4`` from Shubin
          progression pools). Empty string label is used for pools whose names don't
          encode a rank — those render with the original system-only header.
          Multiple system entries indicate per-region pools (e.g. Stanton vs Pyro
          Shubin HandMining); multiple label entries within a system indicate
          rank-tiered pools the same contract pulls from at different ranks.
        - mission_items: dict mapping title_key → list of reward item display names
    Sorted by system name for consistent output.
    """
    if not contractgen_dir.exists():
        return {}, {}, {}, {}

    reputation_lookup = reputation_lookup or {}
    blueprint_pools = blueprint_pools or {}
    entity_names = entity_names or {}
    pool_names = pool_names or {}
    standings_lookup = standings_lookup or {}
    # Variant tuple: (system_name, success_xp, failure_xp, desc_key, flags, spawns, difficulty, has_bp, bp_chance, bp_variant, rank_name)
    missions: dict[str, list[tuple[str, int, int, str, list[str], int, int]]] = {}
    # Per-system, per-pool-label item lists. The extra label dimension keeps
    # items from different rank-tier pools separate inside one system so the
    # renderer can show ``[Stanton, Rank 0–1]`` / ``[Stanton, Rank 2–3]`` /
    # ``[Stanton, Rank 4]`` instead of one merged blob. Pools whose names
    # don't carry a rank token use an empty-string label and render with
    # the original system-only header.
    mission_blueprints: dict[str, dict[str, dict[str, list[str]]]] = {}
    mission_bp_chance: dict[str, float] = {}
    mission_items: dict[str, list[str]] = {}

    # Build template lookup for contracts that inherit title/desc from templates
    templates_dir = contractgen_dir.parent / "contracttemplates"
    template_lookup = _build_template_lookup(templates_dir, xml_path_index=xml_path_index, records_dir=records_dir)

    _contractgen_files = (
        _index_rglob(xml_path_index, contractgen_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else contractgen_dir.rglob("*.xml")
    )
    try:
        for xml_file in _contractgen_files:
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
                    if handler.get("notForRelease") == "1":
                        continue
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

                    # Extract handler-level spawn breakdown (shared across
                    # contracts; per-contract overrides win when non-empty).
                    handler_spawns = _extract_spawn_counts(handler)

                    contracts = handler.findall(contract_xpath)

                    for contract in contracts:
                        try:
                            if contract.get("notForRelease") == "1":
                                continue

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
                            #
                            # A single contract can carry MULTIPLE
                            # ``BlueprintRewards`` elements pointing at
                            # distinct pools — e.g. the 4.8-era Adagio
                            # mining missions reward FPS gear via one pool
                            # AND ship components via another in the same
                            # contract. Earlier code used ``if system_name
                            # not in per_system: per_system[...] = pool_items``,
                            # which kept only the first pool and silently
                            # dropped the rest. Merge with order-preserving
                            # de-dup so every pool's items surface, while
                            # still suppressing duplicates when the same
                            # title_key is hit again later in the loop with
                            # the identical pool set.
                            contract_has_bp = False
                            contract_bp_chance = 0.0
                            contract_bp_variant = contract.get("debugName", "")
                            for bp_elem in contract.iter("BlueprintRewards"):
                                pool_uuid = bp_elem.get("blueprintPool", "")
                                null_uuid = "00000000-0000-0000-0000-000000000000"
                                if pool_uuid and pool_uuid != null_uuid and pool_uuid in blueprint_pools:
                                    contract_has_bp = True
                                    pool_items = blueprint_pools[pool_uuid]
                                    # Derive the rank-tier label from the pool's
                                    # filename. Pools without a rank token (most
                                    # one-off pools, plus region-based pools whose
                                    # geographic label is already covered by the
                                    # system_name dimension) produce empty string,
                                    # which keeps their sub-section header at the
                                    # bare ``[system_name]`` shape.
                                    pool_label = _pool_rank_label(pool_names.get(pool_uuid, ""))
                                    _merge_blueprint_pool(
                                        mission_blueprints, title_key, system_name,
                                        pool_uuid, pool_items, pool_label,
                                    )
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
                            min_standing = contract.get("minStanding", "")
                            null_uuid = "00000000-0000-0000-0000-000000000000"
                            # A contract with no standing requirement at handler intro level is a starter
                            # (detected by debugName containing "Intro" or being first in a career chain)
                            contract_debug = contract.get("debugName", "")
                            if "Intro" in contract_debug or "intro" in contract_debug:
                                if "Starter" not in contract_flags:
                                    contract_flags.append("Starter")

                            # Extract per-contract spawn breakdown; fall back
                            # to the handler-level breakdown when the contract
                            # node itself has no spawn descriptions of its own
                            # (a contract is empty when every bucket is empty).
                            contract_spawns = _extract_spawn_counts(contract)
                            spawns = (
                                contract_spawns
                                if any(contract_spawns.values())
                                else handler_spawns
                            )

                            # Extract per-contract difficulty
                            contract_difficulty = _extract_difficulty(contract)

                            # Resolve minStanding UUID to a reputation rank name
                            rank_name = standings_lookup.get(min_standing, "") if min_standing else ""

                            # Add all missions (not just those with XP/blueprint data)
                            if title_key not in missions:
                                missions[title_key] = []
                            missions[title_key].append((system_name, success_xp, failure_xp, desc_key, contract_flags, spawns, contract_difficulty, contract_has_bp, contract_bp_chance, contract_bp_variant, rank_name))

                            # Sub-contracts override title/desc but inherit
                            # everything else from the parent contract.
                            for sub in contract.findall(".//subContracts/SubContract"):
                                sub_title_p = sub.find(".//ContractStringParam[@param='Title']")
                                sub_desc_p = sub.find(".//ContractStringParam[@param='Description']")
                                sub_title = sub_title_p.get("value", "").lstrip("@") if sub_title_p is not None else ""
                                sub_desc = sub_desc_p.get("value", "").lstrip("@") if sub_desc_p is not None else ""
                                if not sub_title or sub_title in _SENTINEL_LOC_KEYS:
                                    continue
                                if sub_desc in _SENTINEL_LOC_KEYS:
                                    sub_desc = ""
                                if sub_title not in missions:
                                    missions[sub_title] = []
                                missions[sub_title].append((system_name, success_xp, failure_xp, sub_desc or desc_key, contract_flags, spawns, contract_difficulty, contract_has_bp, contract_bp_chance, contract_bp_variant, rank_name))
                                if contract_has_bp and sub_title != title_key:
                                    for bp_elem in contract.iter("BlueprintRewards"):
                                        sub_pool_uuid = bp_elem.get("blueprintPool", "")
                                        if sub_pool_uuid not in blueprint_pools:
                                            continue
                                        pool_label = _pool_rank_label(pool_names.get(sub_pool_uuid, ""))
                                        _merge_blueprint_pool(
                                            mission_blueprints, sub_title, system_name,
                                            sub_pool_uuid, blueprint_pools[sub_pool_uuid], pool_label,
                                        )
                                    if sub_title not in mission_bp_chance:
                                        mission_bp_chance[sub_title] = contract_bp_chance

                        except Exception as e:
                            logger.debug(f"Skipped contract {contract.get('debugName', '?')}: {e}")

        # Sort variants by system name for consistent output (Stanton first, then others alphabetically)
        for title_key in missions:
            missions[title_key].sort(key=lambda v: (v[0] != "Stanton", v[0]))

    except Exception as e:
        logger.warning(f"Error scanning contract generators: {e}")

    logger.info(f"Contract generators: {len(missions)} missions, {len(mission_blueprints)} with blueprints, {len(mission_items)} with items")
    return missions, mission_blueprints, mission_bp_chance, mission_items


def _resolve_resource_uuids(
    bp_dir: Path,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> set[str]:
    """Collect every material UUID a blueprint references — via both
    ``CraftingCost_Resource resource=...`` and ``CraftingCost_Item
    entityClass=...``.

    The two element types serve different blueprint slots:

    * ``CraftingCost_Resource`` points at an abstract resource-type UUID
      (e.g. the "agricium" resource pool); it appears INSIDE every
      carryable variant of that commodity as a tag reference, which is
      how the downstream resolver in :func:`_build_uuid_to_commodity`
      maps the UUID back to the commodity name. The FRAME slot in most
      laser-cannon blueprints uses this path.

    * ``CraftingCost_Item`` points directly at a carryable's own
      ``__ref`` UUID (the entity-class UUID). The EMITTER and APERTURE
      IRIS slots on the Omnisky III, for example, reference
      ``harvestable_mineral_1h_hadanite.xml`` and ``..._dolivine.xml``
      by their entity UUIDs. Pre-1.4.1 the scanner only picked up the
      Resource path, so every gem component (Hadanite/Aphorite/
      Dolivine/Janalite) was silently absent from the ``[CF]`` tag and
      Mining Compendium augmentation.

    Both UUID types share the same downstream resolution mechanism
    (substring search inside carryable XML content), so the caller gets
    a unified set.
    """
    uuids: set[str] = set()
    if not bp_dir.exists():
        return uuids
    _files = (
        _index_rglob(xml_path_index, bp_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else bp_dir.rglob("*.xml")
    )
    for xml_file in _files:
        try:
            root = ET.parse(xml_file).getroot()
            for elem in root.iter():
                ptype = _poly_type(elem)
                if ptype == "CraftingCost_Resource":
                    uid = elem.get("resource", "")
                elif ptype == "CraftingCost_Item":
                    uid = elem.get("entityClass", "")
                else:
                    continue
                if uid and uid != "00000000-0000-0000-0000-000000000000":
                    uuids.add(uid)
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
            n = n[len(prefix):]
    for suffix in ("_ore", "_raw", "_processed", "_refined"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


def _build_uuid_to_commodity(
    uuids: set[str],
    carryables_dir: Path,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> dict[str, str]:
    """Map resource UUIDs to commodity internal names by scanning carryable entity files."""
    uuid_names: dict[str, str] = {}
    if not carryables_dir.exists() or not uuids:
        return uuid_names
    _files = (
        _index_rglob(xml_path_index, carryables_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else carryables_dir.rglob("*.xml")
    )
    for xml_file in _files:
        try:
            content = xml_file.read_text(encoding="utf-8", errors="ignore")
            matched_uuids = [u for u in uuids if u in content]
            if not matched_uuids:
                continue
            fname = xml_file.stem
            # Two filename schemas cover all carryable variants:
            #   - bulk:       carryable_*_commodity_(metal|mineral|...)_<name>(_a..d)?
            #   - handheld:   harvestable_(mineral|metal|ore)_(1h|2h)_<name>
            # The handheld schema is where hand-mineable gems live
            # (Hadanite/Aphorite/Dolivine/Janalite); pre-1.4.1 only the
            # bulk schema was recognised, so blueprints referencing a gem
            # via ``CraftingCost_Item entityClass=<harvestable_uuid>`` had
            # no commodity name to map to and silently fell out.
            m = re.search(
                r"(?:commodity_(?:metal|mineral|minerals|nonmetal|gas)|"
                r"harvestable_(?:mineral|metal|ore)_\dh)_(\w+?)(?:_[a-d])?$",
                fname,
            )
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
                clean = re.sub(r'\s*"[^"]*"\s*', ' ', n).strip()
                clean = re.sub(r'\s+', ' ', clean)
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
                m2 = re.match(r'^([\w-]+(?:\s[\w-]+)?)\s+(?:Arms|Core|Legs|Helmet|Backpack|Suit|Armor)', n)
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
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
    tag_config: "TagConfig | None" = None,
    blueprint_data_header: str = "BLUEPRINT DATA",
    header_em_tag: str = "EM3",
) -> tuple[dict[str, str], dict[str, str]]:
    """Scan crafting blueprints and produce commodity + journal entries.

    Returns ``(commodity_out, journal_out)`` — two dicts of localization-key →
    augmented value. The commodity dict carries crafting material annotations
    on commodity names and descriptions; the journal dict carries the Mining
    Compendium augmentation. Both halves are always returned so the dispatcher
    in :func:`main` can unpack the result unconditionally, including when no
    crafting blueprints directory exists in the user's DataForge cache.
    """
    import os

    if not bp_dir.exists():
        logger.info("No crafting blueprints directory found")
        return {}, {}

    # Step 1: Collect resource UUIDs from blueprints
    resource_uuids = _resolve_resource_uuids(bp_dir, xml_path_index=xml_path_index, records_dir=records_dir)
    logger.info(f"Found {len(resource_uuids)} unique resource UUIDs in blueprints")

    # Step 2: Resolve UUIDs to commodity names via carryables
    uuid_names = _build_uuid_to_commodity(resource_uuids, carryables_dir, xml_path_index=xml_path_index, records_dir=records_dir)
    logger.info(f"Resolved {len(uuid_names)} resource UUIDs to commodity names")

    # Step 3: Parse blueprints to build commodity → crafted items map
    commodity_items: dict[str, list[tuple[str, str]]] = defaultdict(list)
    _bp_files = (
        sorted(_index_rglob(xml_path_index, bp_dir, records_dir))
        if xml_path_index is not None and records_dir is not None
        else sorted(bp_dir.rglob("*.xml"))
    )
    for xml_file in _bp_files:
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
                ptype = _poly_type(elem)
                if ptype == "CraftingCost_Resource":
                    uid = elem.get("resource", "")
                elif ptype == "CraftingCost_Item":
                    uid = elem.get("entityClass", "")
                else:
                    continue
                if uid in uuid_names:
                    materials.add(uuid_names[uid])
            for mat in materials:
                commodity_items[mat].append((category, item_name))
        except ET.ParseError:
            pass

    # Sanity-check that the localization dict actually carries commodity keys.
    # Hitting 0 here almost always means base.ini is stale (missing modern
    # commodity strings) — surfacing that in the log beats silently writing an
    # empty enhancements file.
    loc_commodity_key_count = sum(
        1 for k in loc if k.lower().startswith("items_commodities_")
    )
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
        enhancements_block = f"<{header_em_tag}>{blueprint_data_header}</{header_em_tag}>\\n{bp_block}"

        for name_key, desc_key in pairs:
            base_name = loc.get(name_key, "")
            if base_name and name_key not in out:
                cfg = tag_config or DEFAULT_TAG_CONFIGS.get("commodities")
                tag_str = render_tag(cfg, {"label": "Crafting"}) if cfg else "[CF]"
                if cfg and getattr(cfg, "placement", "append") == "prepend":
                    out[name_key] = f"<EM4>{tag_str}</EM4> {base_name}"
                else:
                    out[name_key] = f"{base_name} <EM4>{tag_str}</EM4>"

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

        # Build lookup keyed by every name a Compendium line might use:
        # the internal CIG name (american-spelling: ``aluminum_ore``) plus
        # the localized display name from loc (CIG mixes british spelling
        # in display text: ``Aluminium``). Adding the first-word stem
        # ("Aluminium" from "Aluminium Ore") catches Compendium lines that
        # use a bare mineral name even when loc only carries the +-Ore form.
        # Without this, minerals whose internal stem and display spelling
        # diverge (most prominently aluminum/aluminium) silently lose their
        # crafting block.
        mineral_crafting: dict[str, str] = {}
        for internal_name, items in commodity_items.items():
            condensed = _condense_crafted_items(items)
            if not condensed:
                continue
            crafting_text = ", ".join(condensed)
            lookup_keys: set[str] = {internal_name.lower()}
            for name_key, _desc_key in _discover_commodity_loc_pairs(internal_name, loc):
                display = loc.get(name_key, "").strip().lower()
                if not display:
                    continue
                lookup_keys.add(display)
                first_word = display.split()[0] if display.split() else ""
                if first_word:
                    lookup_keys.add(first_word)
            for k in lookup_keys:
                # setdefault — first writer wins on collisions (e.g. "iron"
                # arriving from both raw and ore variants), which is fine
                # since either crafting list is representative.
                mineral_crafting.setdefault(k, crafting_text)

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


def enhancements_weapon(root: ET.Element, ammo_lookup: dict[str, ET.Element],
                 loc: dict | None = None,
                 magazine_lookup: dict[str, tuple[str, str]] | None = None) -> str:
    """Ship or FPS weapon stats."""
    fr    = _fire_rate(root)
    modes = _fire_modes(root, loc)
    pwr   = _find_resource(root, "Power")

    # Component health / signatures / heat
    comp_hp  = _attr(root, "SHealthComponentParams", "Health")
    em_sig   = _attr(root, "EMSignature", "nominalSignature")
    ir_sig   = _attr(root, "IRSignature", "nominalSignature")
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
            proj_speed = (ammo_root.get("speed") or
                         ammo_root.get("velocity") or
                         ammo_root.get("projectileSpeed") or
                         ammo_root.get("initialSpeed"))
            # Try multiple field names for lifetime
            proj_lifetime = (ammo_root.get("lifetime") or
                           ammo_root.get("projectileLifetime") or
                           ammo_root.get("maxLifetime"))
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
    regen    = _find(root, "SWeaponRegenConsumerParams")
    regen_rate = regen_cooldown = regen_cost = None
    if regen is not None:
        if not capacity:
            capacity = regen.get("maxAmmoLoad")
        regen_rate    = regen.get("requestedRegenPerSec")
        regen_cooldown = regen.get("regenerationCooldown")
        regen_cost    = regen.get("regenerationCostPerBullet")
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
        if regen_rate:    parts.append(f"Regen: {_fmt(regen_rate)}/s")
        if regen_cooldown: parts.append(f"Cooldown: {_fmt(regen_cooldown, 's', 1)}")
        if regen_cost:    parts.append(f"Cost/Shot: {_fmt(regen_cost)}")
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
        if em_sig is not None: parts.append(f"EM: {_fmt(em_sig)}")
        if ir_sig is not None: parts.append(f"IR: {_fmt(ir_sig)}")
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
    m = re.search(r'_S0*(\d+)_', cls)
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
    guns:    list[tuple[str, bool]] = []   # (size_str, filled)
    turrets: list[tuple[str, bool]] = []
    mracks:  list[tuple[str, bool]] = []
    shields: list[str] = []               # size strings for filled slots
    powers:  list[str] = []
    coolers: list[str] = []
    qd:      list[str] = []

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
        cls  = entry.get("entityClassName", "")

        if "controller" in port:
            continue

        # Size: _classN in port name (Avenger-style), or _S0N_ in entity class name
        sz = None
        m = re.search(r'_class_?(\d+)', port)
        if m:
            sz = f"S{int(m.group(1))}"
        elif cls:
            sz = _extract_item_size(cls)

        # Gimbal/fixed mount → counts as a gun slot; size from the mount entity (Mount_Gimbal_S3)
        if cls.startswith("Mount_Gimbal_") or cls.startswith("Mount_Fixed_"):
            guns.append((sz or "?", True))   # mount exists = slot is equipped
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
        ship_class = xml_file.stem[len("controller_flight_"):]
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
            p, e, d, t = (di.get(k) for k in
                ("DamagePhysical", "DamageEnergy", "DamageDistortion", "DamageThermal"))
            if any(v is not None for v in (p, e, d, t)):
                lines.append(
                    f"Dmg Mult: P {_fmt(p, 'x', 2)}  |  E {_fmt(e, 'x', 2)}"
                    f"  |  D {_fmt(d, 'x', 2)}  |  T {_fmt(t, 'x', 2)}"
                )

    ad = _find(armor_root, "armorDeflection")
    if ad is not None:
        dv = ad.find("deflectionValue")
        if dv is not None:
            p, e, d, t = (dv.get(k) for k in
                ("DamagePhysical", "DamageEnergy", "DamageDistortion", "DamageThermal"))
            if any(v is not None for v in (p, e, d, t)):
                lines.append(
                    f"Deflect: P {_fmt(p)}  |  E {_fmt(e)}  |  D {_fmt(d)}  |  T {_fmt(t)}"
                )

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
    role_key   = (vpc.get("vehicleRole")   or "").lstrip("@")
    career = (loc or {}).get(career_key) if career_key else None
    role   = (loc or {}).get(role_key)   if role_key   else None

    bbox   = vpc.find("maxBoundingBoxSize")
    length = bbox.get("y") if bbox is not None else None

    # Insurance — DataForge tag is lowercase 'shipInsuranceParams', __type is 'ShipInsuranceParams'
    ins         = _find(root, "shipInsuranceParams")
    ins_base    = ins.get("baseWaitTimeMinutes")      if ins is not None else None
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
            scm       = ifcs.get("scmSpeed")
            max_spd   = ifcs.get("maxSpeed")
            boost_fwd = ifcs.get("boostSpeedForward")
            boost_bwd = ifcs.get("boostSpeedBackward")
        sp = _find_by_type(controller_root, "SIFCSSpeedProfile")
        if sp is not None:
            av = sp.find("angularVelocity")
            if av is not None:
                pitch = av.get("x")   # pitch rate °/s
                roll  = av.get("y")   # roll rate  °/s
                yaw   = av.get("z")   # yaw rate   °/s

    lines = []

    if scm is not None or max_spd is not None:
        lines.append(f"SCM: {_fmt(scm, ' m/s')}  |  Max: {_fmt(max_spd, ' m/s')}")
    if boost_fwd is not None or boost_bwd is not None:
        lines.append(f"Boost: +{_fmt(boost_fwd, ' m/s')}  /  -{_fmt(boost_bwd, ' m/s')}")
    if pitch is not None:
        lines.append(
            f"Pitch: {_fmt(pitch, '°/s')}  |  Roll: {_fmt(roll, '°/s')}  |  Yaw: {_fmt(yaw, '°/s')}"
        )

    basics = []
    if crew_size is not None: basics.append(f"Crew: {_fmt(crew_size)}")
    if length    is not None: basics.append(f"Length: {_fmt(length, 'm', 1)}")
    if career    is not None: basics.append(f"Class: {career}")
    if role      is not None: basics.append(f"Role: {role}")
    if basics:
        lines.append("  |  ".join(basics))

    if weapons_line:
        lines.append(weapons_line)
    if core_line:
        lines.append(core_line)
    if armor_block:
        lines.append(armor_block)

    if ins_base is not None:
        lines.append(
            f"Insurance: {_fmt(ins_base, ' min', 2)} base  |  {_fmt(ins_express, ' min', 2)} express"
        )

    return "\\n".join(lines)


def scan_spaceships(
    spaceships_dir: Path,
    controller_lookup: dict,
    loc: dict,
    armor_lookup: dict | None = None,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> dict[str, str]:
    """Scan DataForge spaceship entities and generate ship stat descriptions."""
    out: dict[str, str] = {}
    matched = missed = skipped = discovered = 0

    if xml_path_index is not None and records_dir is not None:
        key = spaceships_dir.relative_to(records_dir).as_posix()
        xml_file_list = sorted(Path(p) for p in xml_path_index.get(key, []))
    else:
        xml_file_list = sorted(spaceships_dir.glob("*.xml"))
    for xml_file in xml_file_list:
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
        is_discovered = base_value is None
        if is_discovered:
            base_value = _synthesize_description(root, xml_file, loc_key)
            discovered += 1

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
        elif is_discovered:
            if loc_key not in out:
                out[loc_key] = base_value
            matched += 1
        else:
            missed += 1

    logger.info(f"Spaceships: {matched} matched, {discovered} discovered, {missed} no enhancements/key, {skipped} skipped (AI/templates)")
    return out


# ── Ammo lookup builder ───────────────────────────────────────────────────────

def build_ammo_lookup(
    ammo_dir: Path,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> dict[str, ET.Element]:
    """Parse all ammo XML files and index them by their __ref GUID.

    Falls back to root tag name if __ref is not available.
    """
    lookup: dict[str, ET.Element] = {}
    if not ammo_dir.exists():
        return lookup
    xml_files = (
        _index_rglob(xml_path_index, ammo_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else ammo_dir.rglob("*.xml")
    )
    for xml_file in xml_files:
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


# scitem entity subdir → component-type label (matches the keys in
# tag_builder.DEFAULT_COMPONENT_TYPE_MAPPING). Shared by the standalone
# component generator (_run_gen_components) and the entity_name_tags builder
# (build_scitem_lookups) so the type element renders identically on standalone
# component names AND on the component entries inside mission blueprint lists
# (issue #101 — the lookup builder previously omitted it).
_SUBDIR_TO_TYPE: dict[str, str] = {
    "shieldgenerator": "Shield Generator",
    "cooler":          "Cooler",
    "powerplant":      "Power Plant",
    "quantumdrive":    "Quantum Drive",
    "radar":           "Radar",
}


def build_scitem_lookups(
    scitem_dir: Path,
    loc: dict[str, str] | None = None,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
    tag_config: "TagConfig | None" = None,
) -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, str], dict[str, str]]:
    """Single-pass scan of scitem XMLs that produces four lookups:

    * mag_lookup: magazine entity class name → (ammoParamsRecord, maxAmmoCount)
      — derived from SAmmoContainerComponentParams elements.
    * entity_names: __ref UUID → display name (resolved via loc)
      — first @-prefixed Name attribute on any element.
    * entity_names_by_filename: XML filename stem → display name
      — same name as above but indexed by the XML filename instead of
      __ref UUID. Used as a second-tier fallback by
      build_blueprint_pool_lookup when the blueprint references an
      entityClass UUID that doesn't __ref any entity record (CIG WIP
      pattern in PTU patches — blueprints land before the entity UUID
      assignments are finalised). The blueprint's own filename minus
      its `bp_craft_` / `bp_rewards_` prefix matches the entity XML's
      filename in CIG's authored layout.
    * entity_name_tags: __ref UUID → ``[CLASS-Sx-grade]`` tag (e.g.
      ``[MIL-S1-A]``) when the entity is a ship component whose
      description carries the Size:/Grade:/Class: header trio.
      Only populated for components that ``_component_name_tag``
      can classify — FPS gear, weapons, ships, missiles, ammo, etc.
      get no entry. Used by blueprint pool resolution to apply the
      same annotation to blueprint reward names that the components
      pipeline applies to stock component titles, so a mission's
      "POTENTIAL BLUEPRINTS" list reads e.g. "Norfield [MIL-S1-A]"
      instead of bare "Norfield".

    Walking the scitem tree once instead of twice (magazines + entity names
    used to iterate independently) cuts ~30s off the run since there are
    ~20k files under entities/scitem/.
    """
    mag_lookup: dict[str, tuple[str, str]] = {}
    entity_names: dict[str, str] = {}
    entity_names_by_filename: dict[str, str] = {}
    entity_name_tags: dict[str, str] = {}
    loc = loc or {}
    if not scitem_dir.exists():
        return mag_lookup, entity_names, entity_names_by_filename, entity_name_tags

    null_uuid = "00000000-0000-0000-0000-000000000000"
    xml_files = (
        _index_rglob(xml_path_index, scitem_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else scitem_dir.rglob("*.xml")
    )
    for xml_file in xml_files:
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        ref = root.get("__ref", "")
        entity_name = root.tag.split(".")[-1] if "." in root.tag else xml_file.stem
        found_mag = False
        found_name = False
        found_desc = False
        resolved_display_name: str | None = None
        desc_loc_key: str | None = None

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
                    resolved_display_name = loc.get(loc_key, loc_key)
                    if ref:
                        entity_names[ref] = resolved_display_name
                    found_name = True
            if not found_desc:
                desc_attr = elem.get("Description", "")
                if desc_attr and desc_attr.startswith("@") and not _is_sentinel_loc_ref(desc_attr):
                    desc_loc_key = desc_attr.lstrip("@")
                    found_desc = True
            if found_mag and found_name and found_desc:
                break

        # Index by filename stem regardless of whether the entity has a
        # __ref — the filename fallback in BP resolution doesn't care
        # about the UUID, only the display name.
        if resolved_display_name:
            entity_names_by_filename[xml_file.stem.lower()] = resolved_display_name

        # Component name-tag derivation. ``_component_name_tag`` returns
        # None for anything other than a ship component with the Size:/
        # Grade:/Class: header trio, so non-component entities (FPS gear,
        # weapons, ships, ammo …) silently fall out here without polluting
        # the dict. Requires both a __ref to key on and a resolvable
        # description loc-key — the rendering side looks up by ref.
        if ref and desc_loc_key:
            desc_value = loc.get(desc_loc_key, "")
            if desc_value:
                # Derive the component type from the entity's subdir so the
                # blueprint-list tag carries the same Type element the
                # standalone component path emits (#101). Non-component
                # entities won't be under these subdirs (comp_type stays "")
                # and _component_name_tag returns None for them regardless.
                _parts = {p.lower() for p in xml_file.parts}
                comp_type = next(
                    (t for sd, t in _SUBDIR_TO_TYPE.items() if sd in _parts), ""
                )
                tag = _component_name_tag(
                    desc_value, root, config=tag_config, component_type=comp_type
                )
                if tag:
                    entity_name_tags[ref] = tag

    return mag_lookup, entity_names, entity_names_by_filename, entity_name_tags


def build_magazine_lookup(scitem_dir: Path) -> dict[str, tuple[str, str]]:
    """Back-compat wrapper around build_scitem_lookups — returns magazines only."""
    mag_lookup, _, _, _ = build_scitem_lookups(scitem_dir)
    return mag_lookup


# ── DataForge directory scanner ───────────────────────────────────────────────

def scan_entity_dir(
    entity_dir: Path,
    enhancement_fn,
    ammo_lookup: dict | None = None,
    loc: dict | None = None,
    loc_key_fn = None,
    generate_name_tags: bool = False,
    name_tag_fn = None,
    name_tag_placement: str = "prepend",
    separator: str = ENHANCEMENT_SEPARATOR,
    capture_all: bool = False,
    xml_path_index: dict | None = None,
    records_dir: Path | None = None,
) -> dict[str, str]:
    """
    Scan all XML files in entity_dir, extract localization key + enhancements,
    and return {loc_key: augmented_value}. For keys missing from `loc`, a
    synthetic description is built from XML attributes so discovered items
    still appear in the output.

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
    matched = missed = skipped = discovered = 0

    xml_files = (
        _index_rglob(xml_path_index, entity_dir, records_dir)
        if xml_path_index is not None and records_dir is not None
        else entity_dir.rglob("*.xml")
    )
    for xml_file in xml_files:
        try:
            root = ET.parse(xml_file).getroot()
        except ET.ParseError:
            continue

        key = loc_key_fn(root)
        if not key:
            skipped += 1
            continue

        base_value = (loc or {}).get(key)
        is_discovered = base_value is None
        if is_discovered:
            base_value = _synthesize_description(root, xml_file, key)
            discovered += 1

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
        elif capture_all or is_discovered:
            # Still emit the base value so all missions / discovered items are captured
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
                is_discovered_name = name_value is None
                if is_discovered_name:
                    # Synthesize name from XML file stem
                    name_value = _humanize_key(xml_file.stem)
                if name_value:
                    tagger = name_tag_fn or _component_name_tag
                    tag = tagger(base_value, root)
                    if tag:
                        # `placement` is the user-configurable choice on the
                        # Tag Builder; default "prepend" puts the tag in
                        # front of the name so it sorts/scans naturally
                        # next to its neighbors.
                        if name_tag_placement == "append":
                            out[name_key] = f"{name_value} {tag}"
                        else:
                            out[name_key] = f"{tag} {name_value}"
                        short_key = f"{name_key}_short"
                        short_value = loc.get(short_key)
                        if short_value:
                            if name_tag_placement == "append":
                                out[short_key] = f"{short_value} {tag}"
                            else:
                                out[short_key] = f"{tag} {short_value}"

    logger.info(f"{entity_dir.name}: {matched} matched, {discovered} discovered, {missed} no enhancements, {skipped} no loc key")
    return out


# ── Process-pool entry points ─────────────────────────────────────────────────
# Module-level (not closures) so they can be called cleanly from the thread pool
# and reasoned about in isolation without capturing main()'s local scope.
# Each receives the shared context dict built in main() and returns its output.
# Progress ticks are intentionally omitted here — the main process ticks once
# per future as it completes, keeping all Qt signal emission off subprocesses.

def _run_gen_components(ctx: dict) -> dict[str, str]:
    loc             = ctx["loc"]
    ships_scitem    = ctx["ships_scitem"]
    xml_path_index  = ctx.get("xml_path_index")
    records         = ctx["records"]
    tag_configs     = ctx.get("tag_configs") or {}
    comp_cfg        = tag_configs.get("components") or DEFAULT_TAG_CONFIGS.get("components")
    comp_placement  = getattr(comp_cfg, "placement", "prepend") if comp_cfg else "prepend"

    def _make_comp_tagger(comp_type: str):
        def _tagger(desc_value: str, root: ET.Element | None = None) -> str | None:
            return _component_name_tag(desc_value, root, config=comp_cfg, component_type=comp_type)
        return _tagger

    out: dict[str, str] = {}
    for subdir, fn in [
        ("shieldgenerator", enhancements_shield),
        ("cooler",          enhancements_cooler),
        ("powerplant",      enhancements_powerplant),
        ("quantumdrive",    enhancements_quantum_drive),
        ("bombcompartments", enhancements_bomb_rack),
    ]:
        tagger = _make_comp_tagger(_SUBDIR_TO_TYPE.get(subdir, ""))
        out.update(scan_entity_dir(ships_scitem / subdir, fn, loc=loc, generate_name_tags=True,
                                   name_tag_fn=tagger,
                                   name_tag_placement=comp_placement,
                                   xml_path_index=xml_path_index, records_dir=records))
    radar_dir = ships_scitem / "radar"
    if radar_dir.exists():
        tagger = _make_comp_tagger(_SUBDIR_TO_TYPE.get("radar", ""))
        out.update(scan_entity_dir(radar_dir, enhancements_radar, loc=loc, generate_name_tags=True,
                                   name_tag_fn=tagger,
                                   name_tag_placement=comp_placement,
                                   xml_path_index=xml_path_index, records_dir=records))

    comp_types = ("COOL", "SHLD", "POWR", "QDRV", "RADR")
    sibling_count = 0
    for key, value in list(out.items()):
        if not key.endswith("_SCItem"):
            continue
        base_key = key[:-len("_SCItem")]

        # Mirror to the bare-key variant (just strip ``_SCItem``). CIG
        # ships some components with BOTH ``item_DescX_SCItem`` and a bare
        # ``item_DescX`` holding the same stock description — e.g. the S3
        # Juno Starwerk and ARCCorp QDRVs on PTU 4.8 (Agni / Vesta /
        # Fissure / Impulse). The game can render either key, and without
        # this mirror the bare-key variant shows stock text with no
        # annotations / stats / [CLASS-Sx-grade] tag. Done BEFORE the
        # comp_types underscore-variant check below so both legacy
        # siblings get propagated if both exist in stock.
        if base_key in loc and base_key not in out:
            if base_key.startswith("item_Desc"):
                base_value = loc[base_key]
                if ENHANCEMENT_SEPARATOR in value:
                    out[base_key] = base_value + value[value.index(ENHANCEMENT_SEPARATOR):]
                else:
                    out[base_key] = value
            elif base_key.startswith("item_Name"):
                tag_match = re.search(r"\s(\[[A-Z0-9\-]+\])\s*$", value)
                if tag_match:
                    out[base_key] = f"{loc[base_key]} {tag_match.group(1)}"
                else:
                    out[base_key] = value
            else:
                out[base_key] = value
            sibling_count += 1

        for ct in comp_types:
            desc_prefix = f"item_Desc{ct}_"
            if base_key.startswith(desc_prefix):
                sibling = f"item_Desc_{ct}_{base_key[len(desc_prefix):]}"
                if sibling not in out and sibling in loc:
                    sibling_base = loc[sibling]
                    if ENHANCEMENT_SEPARATOR in value:
                        out[sibling] = sibling_base + value[value.index(ENHANCEMENT_SEPARATOR):]
                    else:
                        out[sibling] = value
                    sibling_count += 1
                break
            name_prefix = f"item_name{ct}_"
            if base_key.startswith(name_prefix):
                sibling = f"item_Name_{ct}_{base_key[len(name_prefix):]}"
                if sibling not in out and sibling in loc:
                    out[sibling] = value
                    sibling_count += 1
                break

    inv_sibling_count = 0
    for key, value in list(out.items()):
        for prefix_with, prefix_without in (
            ("item_Desc_", "item_Desc"),
            ("item_Name_", "item_Name"),
        ):
            if not key.startswith(prefix_with):
                continue
            rest = key[len(prefix_with):]
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
                if ENHANCEMENT_SEPARATOR in value:
                    out[legacy_sibling] = legacy_base + value[value.index(ENHANCEMENT_SEPARATOR):]
                else:
                    out[legacy_sibling] = value
            else:
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
    return out


def _run_gen_missiles(ctx: dict) -> dict[str, str]:
    loc            = ctx["loc"]
    ships_scitem   = ctx["ships_scitem"]
    xml_path_index = ctx.get("xml_path_index")
    records        = ctx["records"]
    tag_configs    = ctx.get("tag_configs") or {}
    missile_cfg    = tag_configs.get("missiles") or DEFAULT_TAG_CONFIGS.get("missiles")
    missile_placement = getattr(missile_cfg, "placement", "prepend") if missile_cfg else "prepend"
    def _missile_tagger(desc_value: str, root: ET.Element | None = None) -> str | None:
        return _missile_name_tag(desc_value, root, config=missile_cfg)

    out: dict[str, str] = {}
    weapons_dir = ships_scitem / "weapons"
    for missile_dir in [weapons_dir / "missiles", weapons_dir / "rocket_pods"]:
        if missile_dir.exists():
            out.update(scan_entity_dir(
                missile_dir, enhancements_missile,
                loc=loc, generate_name_tags=True, name_tag_fn=_missile_tagger,
                name_tag_placement=missile_placement,
                xml_path_index=xml_path_index, records_dir=records,
            ))
    return out


def _ship_weapon_dispatch(root: ET.Element, vehicle_ammo: dict, loc: dict) -> str:
    """Polymorphic dispatch for entities in ``ships/weapons/``.

    The directory mixes combat weapons (cannons, repeaters, scatterguns)
    with non-combat ship-mounted gear (mining lasers — and likely
    tractor / salvage beams in the future). Pick the right extractor
    based on a marker element present only on the specialised entity:

      - SEntityComponentMiningLaserParams → mining laser → enhancements_mining_laser
      - everything else                  → enhancements_weapon (combat)

    Keeps the single-pass scan_entity_dir wiring intact while letting
    each entity class get the stats most relevant to it.
    """
    if _find(root, "SEntityComponentMiningLaserParams") is not None:
        return enhancements_mining_laser(root)
    return enhancements_weapon(root, vehicle_ammo, loc)


def _fps_weapon_dispatch(root: ET.Element, fps_ammo: dict, loc: dict, mag_lookup: dict) -> str:
    """Polymorphic dispatch for entities in ``weapons/fps_weapons/``.

    Same shape as ``_ship_weapon_dispatch``: handheld salvage tools
    (Renovar XTR + multitool salvage mode) need a different extractor
    than combat FPS weapons, but they live in the same directory.
    """
    if _find(root, "SWeaponActionFireSalvageRepairParams") is not None:
        return enhancements_salvage_tool(root)
    return enhancements_weapon(root, fps_ammo, loc, mag_lookup)


def _run_gen_ship_weapons(ctx: dict) -> dict[str, str]:
    loc            = ctx["loc"]
    ships_scitem   = ctx["ships_scitem"]
    vehicle_ammo   = ctx["vehicle_ammo"]
    xml_path_index = ctx.get("xml_path_index")
    records        = ctx["records"]
    tag_configs    = ctx.get("tag_configs") or {}
    ship_weapon_cfg = tag_configs.get("ship_weapons") or DEFAULT_TAG_CONFIGS.get("ship_weapons")
    ship_weapon_placement = (
        getattr(ship_weapon_cfg, "placement", "prepend") if ship_weapon_cfg else "prepend"
    )
    # Ship weapons gain name tags in 1.3.x (issue #31). The factory captures
    # ammo_lookup so the tagger can resolve the dominant damage type.
    ship_weapon_tagger = _ship_weapon_name_tag_factory(vehicle_ammo, config=ship_weapon_cfg)

    out: dict[str, str] = {}
    weapons_dir = ships_scitem / "weapons"
    if weapons_dir.exists():
        out = scan_entity_dir(
            weapons_dir,
            lambda root: _ship_weapon_dispatch(root, vehicle_ammo, loc),
            loc=loc,
            generate_name_tags=True, name_tag_fn=ship_weapon_tagger,
            name_tag_placement=ship_weapon_placement,
            xml_path_index=xml_path_index, records_dir=records,
        )
    logger.info(f"Finished ship weapons ({len(out)} entries)")
    return out


def _run_gen_fps_weapons(ctx: dict) -> dict[str, str]:
    loc            = ctx["loc"]
    records        = ctx["records"]
    fps_ammo       = ctx["fps_ammo"]
    mag_lookup     = ctx["mag_lookup"]
    xml_path_index = ctx.get("xml_path_index")
    out: dict[str, str] = {}
    fps_dir = records / "entities" / "scitem" / "weapons" / "fps_weapons"
    if fps_dir.exists():
        out = scan_entity_dir(
            fps_dir,
            lambda root: _fps_weapon_dispatch(root, fps_ammo, loc, mag_lookup),
            loc=loc,
            xml_path_index=xml_path_index, records_dir=records,
        )
    logger.info(f"Finished FPS weapons ({len(out)} entries)")
    return out


def _run_gen_ships(ctx: dict) -> dict[str, str]:
    records           = ctx["records"]
    loc               = ctx["loc"]
    controller_lookup = ctx["controller_lookup"]
    armor_lookup      = ctx["armor_lookup"]
    xml_path_index    = ctx.get("xml_path_index")
    spaceships_dir = records / "entities" / "spaceships"
    out = scan_spaceships(spaceships_dir, controller_lookup, loc, armor_lookup,
                          xml_path_index=xml_path_index, records_dir=records)
    logger.info(f"Finished ships ({len(out)} entries)")
    return out


def _run_gen_missions(ctx: dict) -> dict[str, str]:
    records           = ctx["records"]
    forge_dir         = ctx["forge_dir"]
    loc               = ctx["loc"]
    entity_names      = ctx["entity_names"]
    entity_names_by_filename = ctx.get("entity_names_by_filename", {})
    entity_name_tags  = ctx.get("entity_name_tags", {})
    reputation_lookup = ctx["reputation_lookup"]
    standings_lookup  = ctx.get("standings_lookup") or {}
    rep_xp_label      = ctx.get("rep_xp_label") or _DEFAULT_REP_XP_LABEL
    mh                = ctx.get("mission_headers") or {}
    mh_em             = ctx.get("mission_header_em") or _DEFAULT_MISSION_HEADER_EM_TAG
    hdr_details       = mh.get("details", _DEFAULT_MISSION_HEADERS["details"])
    hdr_blueprints    = mh.get("blueprints", _DEFAULT_MISSION_HEADERS["blueprints"])
    hdr_items         = mh.get("items", _DEFAULT_MISSION_HEADERS["items"])
    xml_path_index    = ctx.get("xml_path_index")
    tag_configs       = ctx.get("tag_configs") or {}
    # User toggle (Enhancements tab) for the inline component annotation
    # in mission descriptions. Default True preserves v1.4.0 behavior. When
    # False, we pass an empty tag dict so build_blueprint_pool_lookup
    # produces bare names — same code path as the back-compat case
    # locked by test_blueprint_pool_omits_tag_when_dict_unset.
    annotate_descs    = ctx.get("annotate_mission_descs", True)
    effective_tags    = entity_name_tags if annotate_descs else {}
    # Mirror the components-pipeline placement onto the BP-pool tag
    # weave so a user who picks "append" sees the same shape in both
    # the components strings AND the POTENTIAL BLUEPRINTS lists inside
    # mission descriptions. Default falls back to the same "prepend"
    # default the rest of the generator uses.
    _comp_cfg         = tag_configs.get("components") or DEFAULT_TAG_CONFIGS.get("components")
    comp_placement    = getattr(_comp_cfg, "placement", "prepend") if _comp_cfg else "prepend"

    mission_sep = f"\\n\\n<{mh_em}>{hdr_details}</{mh_em}>\\n"

    out: dict[str, str] = {}
    pu_missions_dir = records / "missionbroker" / "pu_missions"

    if pu_missions_dir.exists():
        out.update(scan_entity_dir(
            pu_missions_dir,
            lambda root: enhancements_mission(root, reputation_lookup, rep_xp_label=rep_xp_label),
            loc=loc, loc_key_fn=_mission_loc_key,
            separator=mission_sep, capture_all=True,
            xml_path_index=xml_path_index, records_dir=records,
        ))

    for mission_dir in [
        records / "entities" / "missions",
        records / "entities" / "contracts",
        records / "entities" / "jobterminal",
    ]:
        if mission_dir.exists():
            out.update(scan_entity_dir(
                mission_dir,
                lambda root: enhancements_mission(root, reputation_lookup, rep_xp_label=rep_xp_label),
                loc=loc, separator=mission_sep, capture_all=True,
                xml_path_index=xml_path_index, records_dir=records,
            ))

    logger.info(f"Finished missions scan ({len(out)} entries)")

    # Walk the parent `blueprintrewards/` directory (not just
    # `blueprintmissionpools/`) so the rglob in build_blueprint_pool_lookup
    # picks up CIG's 4.8-era sibling pool dirs (`48blueprints/`,
    # `xenothreat2rewards/`, `collectorwikelo/`). Pre-fix, ~1,400 PTU
    # BlueprintRewards references silently failed UUID resolution.
    pool_dir = records / "crafting" / "blueprintrewards"
    bp_dir   = records / "crafting" / "blueprints" / "crafting"
    blueprint_pools, pool_names = _cached_lookup(
        forge_dir, "blueprint_pools",
        lambda: build_blueprint_pool_lookup(
            pool_dir, bp_dir, entity_names,
            entity_names_by_filename=entity_names_by_filename,
            entity_name_tags=effective_tags,
            name_tag_placement=comp_placement,
        ),
        # blueprint pool names bake in the components tag — fold the
        # components config key AND the annotate-toggle in so a user edit
        # (including placement OR turning annotation off entirely)
        # invalidates this cache alongside scitem_lookups (the source
        # of entity_name_tags). The full TagConfig.to_json() includes
        # placement so swapping prepend ↔ append still bursts the cache;
        # the annotate=0/1 suffix bursts it on the toggle.
        extra_key=f"{ctx.get('_components_cfg_key', '')}|annotate={int(annotate_descs)}",
    )

    contractgen_dir = records / "contracts" / "contractgenerator"
    contractgen_missions, mission_blueprints, mission_bp_chance, mission_items = scan_contract_generators(
        contractgen_dir, reputation_lookup, blueprint_pools, entity_names,
        xml_path_index=xml_path_index, records_dir=records,
        pool_names=pool_names,
        standings_lookup=standings_lookup,
    )
    logger.info(f"Processed {len(contractgen_missions)} contract generator mission variants")

    # Materialise the pu_missions file list early so the title-augment loop
    # can demote [BP] → [BP?] for titles whose pu_missions side spawns
    # descs the contractgenerator never sees (and therefore can't award
    # blueprints for — issue #31 Covalex repro: every contractgen variant
    # of `Covalex_HaulCargo_SingleToMulti_title` carries BP, but the same
    # title is referenced by 6 pu_missions XMLs whose desc tokens never
    # appear in any contractgen file, so those spawn paths run without BP).
    # The same file list is reused by the existing XP back-fill pass below.
    _pu_files: list[Path] = (
        _index_rglob(xml_path_index, pu_missions_dir, records)
        if xml_path_index is not None and pu_missions_dir.exists()
        else (list(pu_missions_dir.rglob("*.xml")) if pu_missions_dir.exists() else [])
    )
    pu_title_to_descs: dict[str, set[str]] = {}
    if pu_missions_dir.exists():
        for xml_file in _pu_files:
            try:
                root = ET.parse(xml_file).getroot()
                title_attr = root.get("title", "")
                desc_attr  = root.get("description", "")
                if not title_attr.startswith("@") or not desc_attr.startswith("@"):
                    continue
                if _is_sentinel_loc_ref(title_attr) or _is_sentinel_loc_ref(desc_attr):
                    continue
                title_key = title_attr.lstrip("@")
                desc_key  = desc_attr.lstrip("@")
                pu_title_to_descs.setdefault(title_key, set()).add(desc_key)
            except (ET.ParseError, Exception):
                continue

    mission_titles_augmented = 0
    for title_key, variants in contractgen_missions.items():
        base_title = (loc or {}).get(title_key)
        is_discovered_title = not base_title
        if is_discovered_title:
            base_title = _humanize_key(title_key)

        seen_tiers: list[tuple[int, int, str]] = []
        for _, sxp, fxp, _, _, _, _, _, _, _, rname in variants:
            tier = (sxp, fxp, rname)
            if tier not in seen_tiers:
                seen_tiers.append(tier)

        unique_xp = sorted(set(sxp for sxp, _, _ in seen_tiers))
        has_blueprints = title_key in mission_blueprints
        _bp_variants = [v[7] for v in variants]  # v[7] = contract_has_bp
        _all_have_bp = has_blueprints and all(_bp_variants)

        desc_bucket_has_bp: dict[str, bool] = {}
        desc_bucket_count: dict[str, int] = {}
        for v in variants:
            dk = v[3]
            if not dk:
                continue
            desc_bucket_has_bp[dk] = desc_bucket_has_bp.get(dk, False) or v[7]
            desc_bucket_count[dk] = desc_bucket_count.get(dk, 0) + 1
        _total_bucketed = sum(desc_bucket_count.values())
        _any_variant_has_bp = any(_bp_variants)
        _has_dominant_no_bp_bucket = _total_bucketed > 0 and any(
            not desc_bucket_has_bp[dk]
            and desc_bucket_count[dk] / _total_bucketed > 0.5
            for dk in desc_bucket_has_bp
        )
        _bp_partial = (
            has_blueprints and _any_variant_has_bp and not _has_dominant_no_bp_bucket
        )
        augmented_title = base_title
        if _all_have_bp:
            augmented_title += " <EM4>[BP]</EM4>"
        elif _bp_partial:
            augmented_title += " <EM4>[BP?]</EM4>"
        nonzero_xp = [x for x in unique_xp if x > 0]
        if len(nonzero_xp) == 1:
            augmented_title += f" <EM4>[{nonzero_xp[0]:,} {rep_xp_label}]</EM4>"
        elif len(nonzero_xp) > 1:
            augmented_title += f" <EM4>[{min(nonzero_xp):,}\u2013{max(nonzero_xp):,} {rep_xp_label}]</EM4>"
        out[title_key] = augmented_title
        mission_titles_augmented += 1

        unique_desc_keys: list[str] = []
        for v in variants:
            dk = v[3]
            if dk and dk not in unique_desc_keys:
                unique_desc_keys.append(dk)

        for desc_key in unique_desc_keys:
            desc_variants = [v for v in variants if v[3] == desc_key]
            base_desc = loc.get(desc_key)
            if base_desc is None:
                # Synthesize from contract debug name in variant tuple
                contract_debug = next(
                    (v[9] for v in desc_variants if v[9]), ""
                )
                if contract_debug:
                    base_desc = _humanize_key(contract_debug)
                else:
                    base_desc = _humanize_key(desc_key)
            all_flags: list[str] = []
            agg_spawns = _empty_spawn_breakdown()
            all_difficulties: list[str] = []
            bp_variant_names: list[str] = []
            all_variants_have_bp = True
            any_variant_has_bp = False
            variant_bp_chance = 0.0
            desc_seen_tiers: list[tuple[int, int, str]] = []
            for _, vsxp, vfxp, _, vflags, vspawns, vdiff, vhas_bp, vbp_chance, vbp_variant, vrname in desc_variants:
                for f in vflags:
                    if f not in all_flags:
                        all_flags.append(f)
                _merge_spawn_breakdowns_max(agg_spawns, vspawns)
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
                tier = (vsxp, vfxp, vrname)
                if tier not in desc_seen_tiers:
                    desc_seen_tiers.append(tier)

            details_lines = []
            details_lines.append(f"<EM4>Mission Type:</EM4> {', '.join(all_flags) if all_flags else 'Standard'}")
            if all_difficulties:
                details_lines.append(f"<EM4>Difficulty (1-7):</EM4> {all_difficulties[0]}")
            details_lines.extend(_format_spawn_lines(agg_spawns))
            nonzero_tiers = [(s, f, rn) for s, f, rn in desc_seen_tiers if s > 0]
            if len(nonzero_tiers) == 1:
                sxp, fxp, rn = nonzero_tiers[0]
                label = f"{rn}:" if rn else f"{rep_xp_label}:"
                details_lines.append(f"<EM4>{label}</EM4> +{sxp:,} XP")
                if fxp < 0:
                    details_lines.append(f"<EM4>Failure Penalty:</EM4> {fxp:,} XP")
            elif len(nonzero_tiers) > 1:
                for i, (sxp, fxp, rn) in enumerate(sorted(nonzero_tiers, key=lambda t: t[0]), 1):
                    label = rn if rn else f"Tier {i}"
                    line = f"<EM4>{label}:</EM4> +{sxp:,} XP"
                    if fxp < 0:
                        line += f" (Failure: {fxp:,})"
                    details_lines.append(line)

            sections: list[str] = [base_desc]
            if any_variant_has_bp and has_blueprints:
                chance_pct = int(variant_bp_chance * 100)
                if all_variants_have_bp:
                    bp_header = (
                        f"<EM4>Blueprint Reward:</EM4> {chance_pct}% chance"
                        if chance_pct < 100 else "<EM4>Blueprint Reward:</EM4> Guaranteed"
                    )
                else:
                    variant_note = ", ".join(bp_variant_names) if bp_variant_names else "select variants"
                    bp_header = f"<EM4>Blueprint Reward:</EM4> {chance_pct}% chance ({variant_note} only)"
                details_lines.append(bp_header)

                pools_by_system = mission_blueprints.get(title_key, {})
                desc_systems = {v[0] for v in desc_variants if v[7]}
                desc_pools = {s: by_label for s, by_label in pools_by_system.items() if s in desc_systems}
                if not desc_pools:
                    desc_pools = pools_by_system
                # Flatten the per-system, per-rank-label structure into one
                # row per (system, label) pair so equal-item-list pairs can
                # dedupe under one header (e.g. Stanton + Pyro both award the
                # same Rank0to1 pool → one "[Stanton, Pyro, Rank 0–1]" header
                # instead of two). The de-dup key is the item-list tuple as
                # before; only the header construction grows a label axis.
                unique_fps: dict = {}
                for sys_name, by_label in desc_pools.items():
                    for pool_label, items in by_label.items():
                        fp = tuple(items)
                        unique_fps.setdefault(fp, []).append((sys_name, pool_label))
                bp_body_parts: list[str] = []
                if len(unique_fps) == 1:
                    items = list(next(iter(unique_fps)))
                    only_keys = next(iter(unique_fps.values()))
                    only_labels = sorted({l for _, l in only_keys if l})
                    if only_labels:
                        only_systems = sorted({s for s, _ in only_keys})
                        header = f"{', '.join(only_systems)}, {', '.join(only_labels)}"
                        bp_body_parts.append(
                            f"<EM4>[{header}]</EM4>\\n" + "\\n".join(f"- {name}" for name in items)
                        )
                    else:
                        bp_body_parts.append("\\n".join(f"- {name}" for name in items))
                else:
                    for fp, keys in sorted(unique_fps.items(), key=lambda kv: sorted(kv[1])):
                        systems = sorted({s for s, _ in keys})
                        labels = sorted({l for _, l in keys if l})
                        sys_str = ", ".join(systems)
                        header = f"{sys_str}, {', '.join(labels)}" if labels else sys_str
                        bp_body_parts.append(
                            f"<EM4>[{header}]</EM4>\\n" + "\\n".join(f"- {name}" for name in fp)
                        )
                # Join regional sub-sections with a blank line between them
                # (two `\n` literals = one empty line in CIG's renderer) so
                # the eye can tell adjacent [Pyro RegionA] / [Pyro RegionB]
                # / … blocks apart instead of running them together as one
                # wall of bullets. Single-pool missions only ever produce
                # one body part, so the extra newline is a no-op there.
                bp_body_separator = "\\n\\n" if len(bp_body_parts) > 1 else "\\n"
                sections.append(f"<{mh_em}>{hdr_blueprints}</{mh_em}>\\n" + bp_body_separator.join(bp_body_parts))

            if title_key in mission_items:
                item_list = "\\n".join(f"- {name}" for name in mission_items[title_key])
                sections.append(f"<{mh_em}>{hdr_items}</{mh_em}>\\n{item_list}")

            details_block = "\\n".join(details_lines)
            if details_block:
                sections.append(f"<{mh_em}>{hdr_details}</{mh_em}>\\n{details_block}")

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
            new_has_bp = f"<{mh_em}>{hdr_blueprints}</{mh_em}>" in new_text
            existing = out.get(desc_key)
            if existing is None:
                out[desc_key] = new_text
            elif new_has_bp and f"<{mh_em}>{hdr_blueprints}</{mh_em}>" not in existing:
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

    # Orphan pu-only desc cleanup. CIG runs two parallel mission-generation
    # wrappers on the same title: modern ``CareerContract`` blocks (which
    # carry ``BlueprintRewards`` and feed ``mission_blueprints``) and older
    # ``ContractLegacy`` blocks (which point at pu_missions XMLs via
    # ``missionBrokerEntry`` and award no BP — every one of the 419
    # ContractLegacy entries in the dataset lacks the BlueprintRewards
    # element). When a single title has both, the pu_missions scan at the
    # top of this function emits a bare-MISSION-DETAILS desc for every
    # ContractLegacy-fronted pu_missions XML — including descs that the
    # contractgen loop never touches. Result: title carries [BP] (true for
    # all CC variants) but several of its descs show no POTENTIAL
    # BLUEPRINTS section, which reads to the user as a regression. Drop
    # those orphan descs entirely so the title's [BP] claim only attaches
    # to bodies that actually back it up. pu_only_descs for titles WITHOUT
    # BP are left alone — their desc body matching the title's silent
    # (no-BP) header is internally consistent.
    orphans_dropped = 0
    for _title_key, _variants in contractgen_missions.items():
        if _title_key not in mission_blueprints:
            continue
        _cg_descs = {v[3] for v in _variants if v[3]}
        for _orphan in pu_title_to_descs.get(_title_key, set()) - _cg_descs:
            if out.pop(_orphan, None) is not None:
                orphans_dropped += 1
    if orphans_dropped:
        logger.info(
            f"Dropped {orphans_dropped} pu-only orphan desc entries "
            "from BP-tagged titles (ContractLegacy spawn paths that don't award BP)"
        )

    # Second pu_missions pass: XP for titles contractgen couldn't cover.
    # _pu_files is already materialised above (alongside pu_title_to_descs);
    # the third diagnostic pass below also reuses it.
    pu_title_xps: dict[str, list[int]] = {}
    if pu_missions_dir.exists():
        for xml_file in _pu_files:
            try:
                root = ET.parse(xml_file).getroot()
                title_attr = root.get("title", "")
                desc_attr  = root.get("description", "")
                if not title_attr.startswith("@") or not desc_attr.startswith("@"):
                    continue
                if _is_sentinel_loc_ref(title_attr) or _is_sentinel_loc_ref(desc_attr):
                    continue
                title_key = title_attr.lstrip("@")
                xp = _extract_mission_xp(root, reputation_lookup)
                if xp > 0:
                    pu_title_xps.setdefault(title_key, []).append(xp)
            except (ET.ParseError, Exception):
                continue

    xp_tag_re = re.compile(r"<EM4>\[\d[\d,]*(?:[–\-]\d[\d,]*)?\s*\w+\]</EM4>")
    for title_key, xps in pu_title_xps.items():
        base_title = (loc or {}).get(title_key)
        if not base_title:
            base_title = _humanize_key(title_key)
        current = out.get(title_key, base_title)
        if xp_tag_re.search(current):
            continue
        unique_xp = sorted(set(xps))
        if len(unique_xp) == 1:
            current += f" <EM4>[{unique_xp[0]:,} {rep_xp_label}]</EM4>"
        else:
            current += f" <EM4>[{min(unique_xp):,}\u2013{max(unique_xp):,} {rep_xp_label}]</EM4>"
        out[title_key] = current
        mission_titles_augmented += 1

    logger.info(f"Augmented {mission_titles_augmented} mission titles with XP")

    titles_with_xp = {k for k in out if re.search(r'\[\d', out[k])}
    desc_keys = {k for k in out if k not in titles_with_xp}
    titles_skipped_no_xp = 0
    titles_skipped_reasons: dict[str, list[str]] = {
        "no_rep_data": [],
        "no_base_title": [],
    }
    if pu_missions_dir.exists():
        for xml_file in _pu_files:
            try:
                root = ET.parse(xml_file).getroot()
                title_attr = root.get("title", "")
                desc_attr = root.get("description", "")
                if not title_attr.startswith("@") or not desc_attr.startswith("@"):
                    continue
                title_key = title_attr.lstrip("@")
                if title_key in out:
                    continue
                if title_key in contractgen_missions:
                    continue
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

    return out


def _run_gen_commodity_journal(ctx: dict) -> tuple[dict[str, str], dict[str, str]]:
    records        = ctx["records"]
    scitem_dir     = ctx["scitem_dir"]
    entity_names   = ctx["entity_names"]
    loc            = ctx["loc"]
    xml_path_index = ctx.get("xml_path_index")
    tag_configs    = ctx.get("tag_configs") or {}
    mh             = ctx.get("mission_headers") or {}
    mh_em          = ctx.get("mission_header_em") or _DEFAULT_MISSION_HEADER_EM_TAG
    bp_dir         = records / "crafting" / "blueprints" / "crafting"
    carryables_dir = scitem_dir / "carryables"
    return scan_crafting_blueprints(bp_dir, carryables_dir, entity_names, loc,
                                    xml_path_index=xml_path_index, records_dir=records,
                                    tag_config=tag_configs.get("commodities"),
                                    blueprint_data_header=mh.get("blueprint_data", _DEFAULT_MISSION_HEADERS["blueprint_data"]),
                                    header_em_tag=mh_em)


# ── Main ──────────────────────────────────────────────────────────────────────

def main(base_ini_path: Path, forge_dir: Path | None = None,
         categories: set[str] | None = None,
         progress_callback: Optional[Callable[[int, int, str], None]] = None,
         max_workers: int = 6,
         patches_dir: Path | None = None,
         tag_configs: "dict | None" = None,
         annotate_mission_descs: bool = True,
         rep_xp_label: str = _DEFAULT_REP_XP_LABEL,
         mission_headers: dict[str, str] | None = None,
         mission_header_em_tag: str = _DEFAULT_MISSION_HEADER_EM_TAG) -> None:
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
            f"DataForge cache not found at {forge_dir}\n"
            "Run 'Extract DataForge' in the app first (Enhancements tab)."
        )

    # ── XML path index ────────────────────────────────────────────────────────
    # Single rglob of the entire records tree, cached per DataForge version.
    # All subsequent directory walks use _index_rglob() against this dict
    # instead of repeated OS rglob calls.
    xml_path_index: dict = _cached_lookup(
        forge_dir, "xml_path_index",
        lambda: _build_xml_path_index(records),
    )
    logger.info(f"XML path index: {sum(len(v) for v in xml_path_index.values()):,} files across {len(xml_path_index):,} dirs")
    _flush()

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
    entity_names_by_filename: dict[str, str] = {}
    entity_name_tags: dict[str, str] = {}
    controller_lookup: dict = {}
    armor_lookup: dict = {}
    reputation_lookup: dict[str, int] = {}
    standings_lookup: dict[str, str] = {}

    # Components Tag Builder config — drives the [CLASS-Sx-grade] tags that
    # get baked into both scitem_lookups (entity_name_tags) and the pickle
    # of blueprint_pools (POTENTIAL BLUEPRINTS list entries). Folding the
    # JSON form into both caches' extra_key invalidates them on user edit
    # so mission descriptions don't keep emitting the old style after a
    # config change. JSON is sort_keys=True so the string is stable.
    _components_cfg = (tag_configs or {}).get("components") or DEFAULT_TAG_CONFIGS.get("components")
    _components_cfg_key = _components_cfg.to_json() if _components_cfg else ""

    def _build_scitem_pair():
        return _cached_lookup(
            forge_dir, "scitem_lookups",
            lambda: build_scitem_lookups(
                records / "entities" / "scitem", loc,
                xml_path_index=xml_path_index, records_dir=records,
                tag_config=_components_cfg,
            ),
            extra_key=_components_cfg_key,
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
        lookup_jobs["vehicle_ammo"] = lambda: build_ammo_lookup(
            records / "ammoparams" / "vehicle", xml_path_index=xml_path_index, records_dir=records)
        lookup_jobs["fps_ammo"]     = lambda: build_ammo_lookup(
            records / "ammoparams" / "fps", xml_path_index=xml_path_index, records_dir=records)
    if need_mag or need_names:
        lookup_jobs["scitem"] = _build_scitem_pair
    if _want("ship_descs"):
        lookup_jobs["controller"] = lambda: build_controller_lookup(records / "entities" / "scitem" / "ships" / "controller")
        lookup_jobs["armor"]      = lambda: build_armor_lookup(records / "entities" / "scitem" / "ships" / "armor")
    if _want("mission_rewards"):
        lookup_jobs["reputation"] = _build_reputation

    def _build_standings():
        standings_dir = records / "reputation" / "standings"
        def _builder() -> dict[str, str]:
            out: dict[str, str] = {}
            if not standings_dir.exists():
                return out
            for xml_file in standings_dir.rglob("*.xml"):
                try:
                    root = ET.parse(xml_file).getroot()
                    uuid = root.get("__ref")
                    display_name = root.get("displayName", "")
                    if uuid and display_name.startswith("@"):
                        loc_key = display_name.lstrip("@")
                        resolved = (loc or {}).get(loc_key, "")
                        if resolved:
                            out[uuid] = resolved
                except ET.ParseError:
                    continue
            return out
        return _cached_lookup(forge_dir, "standings", _builder)

    if _want("mission_rewards"):
        lookup_jobs["standings"] = _build_standings

    if lookup_jobs:
        logger.info(f"Building {len(lookup_jobs)} lookups in parallel (workers={min(max_workers, len(lookup_jobs))})…")
        _flush()
        with ThreadPoolExecutor(max_workers=min(max_workers, len(lookup_jobs)),
                                thread_name_prefix="lookup") as pool:
            futures = {name: pool.submit(fn) for name, fn in lookup_jobs.items()}
            results = {name: fut.result() for name, fut in futures.items()}

        if "vehicle_ammo" in results:
            vehicle_ammo = results["vehicle_ammo"]
            fps_ammo     = results["fps_ammo"]
            logger.info(f"Vehicle ammo: {len(vehicle_ammo)} records, FPS ammo: {len(fps_ammo)} records")
            _tick("Built ammo lookups")
        if "scitem" in results:
            mag_lookup, entity_names, entity_names_by_filename, entity_name_tags = results["scitem"]
            logger.info(
                f"Magazine lookup: {len(mag_lookup)} entries, "
                f"Entity names: {len(entity_names)} entries, "
                f"Entity-name-by-filename fallback: {len(entity_names_by_filename)} entries, "
                f"Entity name-tags: {len(entity_name_tags)} entries"
            )
            _tick("Built scitem lookups")
        if "controller" in results:
            controller_lookup = results["controller"]
            armor_lookup      = results["armor"]
            logger.info(f"Controllers: {len(controller_lookup)}, Armors: {len(armor_lookup)}")
            _tick("Built ship controller + armor lookups")
        if "reputation" in results:
            reputation_lookup = results["reputation"]
            logger.info(f"Loaded {len(reputation_lookup)} reputation reward definitions")
            _tick("Built reputation lookup")
        if "standings" in results:
            standings_lookup = results["standings"]
            logger.info(f"Loaded {len(standings_lookup)} reputation standing definitions")
            _tick("Built standings lookup")

    # ── Output-file generators (parallel wave) ────────────────────────────────
    # Generators run in a ThreadPoolExecutor. Each is a module-level function
    # (not a closure) receiving shared read-only state via a context dict.
    # Internal sub-phases within each generator stay serial since each step
    # consumes the prior step's in-memory result. Across generators there is
    # no shared mutable state, so they run safely on independent threads.
    ships_scitem = records / "entities" / "scitem" / "ships"
    scitem_dir   = records / "entities" / "scitem"

    ctx = {
        "records":           records,
        "forge_dir":         forge_dir,
        "scitem_dir":        scitem_dir,
        "ships_scitem":      ships_scitem,
        "loc":               loc,
        "entity_names":      entity_names,
        "entity_names_by_filename": entity_names_by_filename,
        "entity_name_tags":  entity_name_tags,
        "mag_lookup":        mag_lookup,
        "vehicle_ammo":      vehicle_ammo,
        "fps_ammo":          fps_ammo,
        "controller_lookup": controller_lookup,
        "armor_lookup":      armor_lookup,
        "reputation_lookup": reputation_lookup,
        "standings_lookup":  standings_lookup,
        "xml_path_index":    xml_path_index,
        "tag_configs":       tag_configs or {},
        "_components_cfg_key": _components_cfg_key,
        "annotate_mission_descs": bool(annotate_mission_descs),
        "rep_xp_label":      rep_xp_label or _DEFAULT_REP_XP_LABEL,
        "mission_headers":   mission_headers or dict(_DEFAULT_MISSION_HEADERS),
        "mission_header_em": mission_header_em_tag or _DEFAULT_MISSION_HEADER_EM_TAG,
    }

    gen_jobs: dict[str, Callable] = {}
    if _want("component_descs"):      gen_jobs["components"]        = _run_gen_components
    if _want("missile_enhancements"): gen_jobs["missiles"]          = _run_gen_missiles
    if _want("ship_weapon_descs"):    gen_jobs["ship_weapons"]      = _run_gen_ship_weapons
    if _want("fps_weapon_descs"):     gen_jobs["fps_weapons"]       = _run_gen_fps_weapons
    if _want("ship_descs"):           gen_jobs["ships"]             = _run_gen_ships
    if _want("mission_rewards"):      gen_jobs["missions"]          = _run_gen_missions
    if _want("commodity_crafting") or _want("journal"):
                                      gen_jobs["commodity_journal"] = _run_gen_commodity_journal

    out_components:  dict[str, str] = {}
    out_missiles:    dict[str, str] = {}
    out_ship_weapons: dict[str, str] = {}
    out_fps_weapons: dict[str, str] = {}
    out_ships:       dict[str, str] = {}
    out_missions:    dict[str, str] = {}
    out_commodities: dict[str, str] = {}
    out_journal:     dict[str, str] = {}

    if gen_jobs:
        n_workers = min(max_workers, len(gen_jobs))
        logger.info(f"Running {len(gen_jobs)} output generators in parallel (workers={n_workers}, pool=thread)…")
        _flush()
        with ThreadPoolExecutor(max_workers=n_workers,
                                thread_name_prefix="gen") as pool:
            futs = {name: pool.submit(fn, ctx) for name, fn in gen_jobs.items()}
            for name, fut in futs.items():
                result = fut.result()
                _tick(f"Finished {name}")
                if name == "components":          out_components   = result
                elif name == "missiles":          out_missiles     = result
                elif name == "ship_weapons":      out_ship_weapons = result
                elif name == "fps_weapons":       out_fps_weapons  = result
                elif name == "ships":             out_ships        = result
                elif name == "missions":          out_missions     = result
                elif name == "commodity_journal": out_commodities, out_journal = result

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
                load_locstring_workarounds,
                apply_locstring_workarounds,
            )
            workarounds = load_locstring_workarounds(patches_dir)
            if workarounds:
                total_applied = 0
                for out_dict in (out_missions, out_components, out_ship_weapons,
                                 out_fps_weapons, out_ships, out_missiles,
                                 out_commodities, out_journal):
                    total_applied += apply_locstring_workarounds(out_dict, workarounds)
                logger.info(
                    f"Loc-string workarounds: {total_applied}/{len(workarounds)} applied"
                )
                _flush()
        except ImportError:
            logger.debug("src.utils.dataforge_patcher unavailable; skipping workarounds")

    # ── Write output ──────────────────────────────────────────────────────────
    logger.info("Writing output files…")
    _flush()
    if _want("ship_descs"):
        write_ini(output_dir / "ships_desc_enhancements.ini",       out_ships)
    if _want("component_descs"):
        write_ini(output_dir / "components_desc_enhancements.ini",  out_components)
    if _want("ship_weapon_descs"):
        write_ini(output_dir / "ship_weapons_desc_enhancements.ini",out_ship_weapons)
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

    total = (len(out_ships) + len(out_components) + len(out_ship_weapons) +
             len(out_fps_weapons) + len(out_missions) + len(out_commodities) +
             len(out_journal) + len(out_missiles))
    logger.info(f"Done — {total:,} total stat entries written to {output_dir}")
    _tick("Wrote all output files")
    if _sink is not None:
        _sink.flush()


if __name__ == "__main__":
    base_ini  = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_BASE_INI
    forge_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_FORGE_DIR
    main(base_ini, forge_dir)
