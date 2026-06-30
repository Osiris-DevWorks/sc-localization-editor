"""Per-blueprint-item metadata for the Blueprints shuttle filters (#157 follow-up).

The Blueprints ownership section lets users filter the blueprint catalogue by
the mission it drops from and by ship-component attributes (type / class /
size / grade). Those attributes are not reliably on a mission's blueprint
bullets: the ``[CLASS-Sx-grade]`` tag only appears inline when the "annotate
components in mission descriptions" toggle is on. The robust source is each
component's own ``item_Name*`` entry, which stays tagged whenever the
components enhancement is generated and whose loc key encodes the component
type (QDRV / SHLD / COOL / RADR / ...). We join the blueprint bullet display
names to those component entries by normalized name (an exact match after the
leading tag is stripped).

Mission names come from pairing each blueprint-bearing ``..._Desc_NNN`` entry
with its sibling ``..._Title_NNN`` entry.

Qt-free so it unit-tests with plain entry stand-ins (anything exposing
``key`` / ``original_value`` / ``category``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from src.models.string_model import _ARMOR_GEAR_WORDS, _FPS_WEAPON_WORDS
from src.utils.owned_items import extract_bp_item_names, normalize_item_name

# Coarse type buckets for non-component blueprint items.
_TYPE_FPS_WEAPON = "FPS Weapon"
_TYPE_ARMOR = "Armor"
_TYPE_OTHER = "Other"

# Friendly labels for the component type codes that appear right after
# ``item_Name`` / ``item_Name_`` in a component loc key. Codes not in this map
# (a few manufacturer-prefixed names like AEGS_Eclipse_BombRack) resolve to no
# type, so the Type facet stays a clean list of real component kinds.
_TYPE_LABELS = {
    "SHLD": "Shield",
    "POWR": "Power Plant",
    "COOL": "Cooler",
    "QDRV": "Quantum Drive",
    "QRDV": "Quantum Drive",   # CIG key typo seen in live data
    "JUMP": "Jump Drive",
    "RADR": "Radar",
    "MISL": "Missile",
    "GMISL": "Guided Missile",
    "BOMB": "Bomb",
}

# A leading component tag like "[MIL-S3-B]" -> (class, size, grade). Lenient on
# the class code and size digits; grade is a single letter. This is the Tag
# Builder default shape; a reconfigured tag that doesn't match simply yields no
# attributes (the item then filters by mission + keyword only).
_TAG_RE = re.compile(r"^\[([A-Za-z0-9]+)-S(\d+)-([A-Za-z])\]", re.IGNORECASE)

# A component name entry key: item_Name<code>... or item_Name_<code>...
_NAME_CODE_RE = re.compile(r"^item_name_?([a-z]+)", re.IGNORECASE)

# Mission title / desc key pairing: <base>_Title[_NNN] <-> <base>_Desc[_NNN].
_TITLE_KEY_RE = re.compile(r"^(?P<base>.*)_Title(?:_(?P<num>\d+))?$", re.IGNORECASE)
_DESC_KEY_RE = re.compile(r"^(?P<base>.*)_Desc(?:_(?P<num>\d+))?$", re.IGNORECASE)

# Trailing reward tags on a title, e.g. "<EM4>[BP]</EM4> <EM4>[150 REP]</EM4>".
_TITLE_TAG_RE = re.compile(r"(?:\s*<EM\d>\[[^\]]*\]</EM\d>)+\s*$")

_BP_HEADER = "POTENTIAL BLUEPRINTS"


@dataclass(frozen=True)
class BlueprintItem:
    """One ownable blueprint item with the metadata the shuttle filters on."""
    name: str
    missions: frozenset = frozenset()
    type: Optional[str] = None
    cls: Optional[str] = None
    size: Optional[str] = None
    grade: Optional[str] = None


def parse_component_tag(value: str):
    """Return ``(class, size, grade)`` from a leading ``[MIL-S3-B]`` tag.

    All three are ``None`` when the value carries no recognizable tag.
    """
    m = _TAG_RE.match(value or "")
    if not m:
        return (None, None, None)
    return (m.group(1).upper(), "S" + m.group(2), m.group(3).upper())


def component_type_from_key(key: str):
    """Friendly component type for a component name key, or ``None``."""
    m = _NAME_CODE_RE.match(key or "")
    if not m:
        return None
    return _TYPE_LABELS.get(m.group(1).upper())


def blueprint_type_from_key(key: str):
    """Coarse type bucket for a blueprint item from its matched name key.

    A recognized ship-component code wins (Shield / Quantum Drive / ...), then
    FPS weapon and armor by key tokens. Returns ``None`` for anything else, so
    the caller can fold it into the "Other" bucket. ``None`` key (the bullet
    name matched no loaded name entry) is also ``None`` -> "Other".
    """
    if not key:
        return None
    t = component_type_from_key(key)
    if t:
        return t
    kl = key.lower()
    if any(w in kl for w in _FPS_WEAPON_WORDS):
        return _TYPE_FPS_WEAPON
    if any(w in kl for w in _ARMOR_GEAR_WORDS):
        return _TYPE_ARMOR
    return None


def clean_mission_title(value: str) -> str:
    """Recover the human mission name from a title entry value.

    Takes the first line and strips trailing ``[BP]`` / ``[REP]`` reward tags.
    """
    if not value:
        return ""
    head = value.split("\\n", 1)[0]
    return _TITLE_TAG_RE.sub("", head).strip()


def _title_pair_key(base: str, num) -> tuple:
    return (base.lower(), num or "")


def build_blueprint_metadata(entries) -> dict:
    """Scan loaded strings once and return ``{name: BlueprintItem}``.

    *entries* is any iterable of objects exposing ``key`` / ``original_value``
    / ``category``. The result is keyed by the same normalized item names the
    owned set and ``StringTableModel`` use, so it drops straight into the
    Blueprints shuttle.
    """
    # Pass 1: name->key map (for type), component tag attrs, mission titles,
    # and the blueprint-bearing desc values.
    name_to_key: dict = {}      # normalized display name -> its loc key
    attrs: dict = {}            # normalized name -> (cls, size, grade)
    titles: dict = {}           # (base_lower, num) -> cleaned mission name
    bp_descs: list = []         # (pair_key | None, value)

    for e in entries:
        key = getattr(e, "key", "") or ""
        val = getattr(e, "original_value", "") or ""
        cat = getattr(e, "category", "") or ""
        kl = key.lower()

        if kl.startswith("item_name") or kl.startswith("vehicle_name"):
            nm = normalize_item_name(val)
            if nm and nm not in name_to_key:
                name_to_key[nm] = key
            if cat == "Ship Items":
                cls, size, grade = parse_component_tag(val)
                if (cls or size or grade) and nm and nm not in attrs:
                    attrs[nm] = (cls, size, grade)

        tm = _TITLE_KEY_RE.match(key)
        if tm:
            titles[_title_pair_key(tm.group("base"), tm.group("num"))] = \
                clean_mission_title(val)

        if _BP_HEADER in val.upper():
            dm = _DESC_KEY_RE.match(key)
            pair = _title_pair_key(dm.group("base"), dm.group("num")) if dm else None
            bp_descs.append((pair, val))

    # Pass 2: gather each blueprint item's missions, then attach type + attrs.
    missions_by_name: dict = {}
    for pair, val in bp_descs:
        title = titles.get(pair) if pair else None
        for nm in extract_bp_item_names(val):
            bucket = missions_by_name.setdefault(nm, set())
            if title:
                bucket.add(title)

    result: dict = {}
    for nm, missions in missions_by_name.items():
        type_ = blueprint_type_from_key(name_to_key.get(nm)) or _TYPE_OTHER
        cls, size, grade = attrs.get(nm, (None, None, None))
        result[nm] = BlueprintItem(
            name=nm,
            missions=frozenset(missions),
            type=type_,
            cls=cls,
            size=size,
            grade=grade,
        )
    return result
