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

# Extra armour-piece key tokens beyond string_model's set (which is tuned for
# the strings-table category, not blueprint classification). Armour blueprints
# are keyed by piece (backpack / undersuit / ...) with no "armor" token, so
# without these they fell into the "Other" type bucket (#195).
_ARMOR_EXTRA_WORDS = ("backpack", "undersuit", "flightsuit", "torso", "_legs", "_arms")
from src.utils.owned_items import (
    BP_SECTION_HEADER,
    extract_bp_item_names,
    normalize_item_name,
)

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

# The leading bracketed tag on a component name, e.g. "[MIL-S3-B]" or the
# user-reconfigured "[CMP.S1.B.PW]". Parsed by tokenizing the contents rather
# than a fixed pattern, because the tag's separator, element order, and which
# elements appear are all Tag-Builder-configurable (see parse_component_tag).
_TAG_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]")
_SIZE_TOKEN_RE = re.compile(r"^S?(\d+)$", re.IGNORECASE)
# Size straight from the loc key (stable regardless of tag config):
# item_NamePOWR_ACOM_S01_StarHeart -> S1.
_KEY_SIZE_RE = re.compile(r"_S0*(\d+)(?:_|$)", re.IGNORECASE)

# A component name entry key: item_Name<code>... or item_Name_<code>...
_NAME_CODE_RE = re.compile(r"^item_name_?([a-z]+)", re.IGNORECASE)

# Mission title / desc key pairing: <base>_Title[_NNN] <-> <base>_Desc[_NNN].
_TITLE_KEY_RE = re.compile(r"^(?P<base>.*)_Title(?:_(?P<num>\d+))?$", re.IGNORECASE)
_DESC_KEY_RE = re.compile(r"^(?P<base>.*)_Desc(?:_(?P<num>\d+))?$", re.IGNORECASE)

# Trailing reward tags on a title, e.g. "<EM4>[BP]</EM4> <EM4>[150 REP]</EM4>".
_TITLE_TAG_RE = re.compile(r"(?:\s*<EM\d>\[[^\]]*\]</EM\d>)+\s*$")


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
    """Best-effort ``(class, size, grade)`` from a leading component tag.

    Robust to the Tag Builder's configurable separator / element order / which
    elements are shown, so it handles the default ``[MIL-S3-B]`` and a
    reconfigured ``[CMP.S1.B.PW]`` alike. The tokens inside the leading ``[...]``
    are split on any non-alphanumeric separator and classified: an ``S?<digits>``
    token is the size, a lone A-F letter is the grade, and the first multi-letter
    token is the class (type codes like ``PW`` come after the class in the tag,
    so they don't win). Missing pieces are ``None``.

    Limitation: a single-letter (Short-style) class code can't be told apart from
    a grade letter, so class may be missed under a Short class style — size still
    comes from the loc key and grade still resolves.
    """
    m = _TAG_BRACKET_RE.match(value or "")
    if not m:
        return (None, None, None)
    cls = size = grade = None
    for tok in re.split(r"[^A-Za-z0-9]+", m.group(1)):
        if not tok:
            continue
        sm = _SIZE_TOKEN_RE.match(tok)
        if sm and size is None:
            size = "S" + str(int(sm.group(1)))  # strip zero-padding (S02 -> S2)
        elif len(tok) == 1 and tok.upper() in "ABCDEF" and grade is None:
            grade = tok.upper()
        elif len(tok) >= 2 and cls is None and not sm:
            cls = tok.upper()
    return (cls, size, grade)


def size_from_key(key: str):
    """Component size straight from the loc key (``..._S01_...`` -> ``S1``), or
    None. More reliable than the tag, which the user can reformat."""
    m = _KEY_SIZE_RE.search(key or "")
    return "S" + str(int(m.group(1))) if m else None


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
    if any(w in kl for w in _ARMOR_GEAR_WORDS) or any(w in kl for w in _ARMOR_EXTRA_WORDS):
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
            # Class/size/grade only for recognized component types (Shield,
            # Quantum Drive, ...); ship weapons etc. carry a different tag shape
            # (e.g. [E-S2], no grade) that would pollute the facets.
            if cat == "Ship Items" and component_type_from_key(key):
                cls, tag_size, grade = parse_component_tag(val)
                size = size_from_key(key) or tag_size
                if (cls or size or grade) and nm and nm not in attrs:
                    attrs[nm] = (cls, size, grade)

        tm = _TITLE_KEY_RE.match(key)
        if tm:
            titles[_title_pair_key(tm.group("base"), tm.group("num"))] = \
                clean_mission_title(val)

        if BP_SECTION_HEADER in val.upper():
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
