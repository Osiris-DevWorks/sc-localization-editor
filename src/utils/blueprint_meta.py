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

from src.models.string_model import (
    CATEGORY_MISSIONS,
    _ARMOR_GEAR_WORDS,
    _FPS_WEAPON_WORDS,
    _SHIP_WEAPON_SIZE_RE,
)

# Extra armour-piece key tokens beyond string_model's set (which is tuned for
# the strings-table category, not blueprint classification). Armour blueprints
# are keyed by piece (backpack / undersuit / ...) with no "armor" token, so
# without these they fell into the "Other" type bucket (#195). "_core" (with
# the leading underscore) covers the torso-platform piece of newer
# manufacturer-prefixed FPS armor sets (e.g.
# item_Name_qrt_specialist_heavy_core_01_01_01 -> "Antium Core",
# item_Name_kap_combat_light_core_01_01_01 -> "Geist Armor Core") whose keys
# carry no "armor" token either — CIG's older sets do (cds_armor_heavy_core_*),
# so this was inconsistent rather than universally missing. Every armor key
# this targets carries the underscore form (..._core_01_...), so "_core"
# matches everything the bare word would while ruling out "score"-shaped
# collisions (bare "core" is a substring of "score") and any future CamelCase
# component name ("SomethingCore") whose prefix code isn't in the component
# map yet — same underscore-guard shape already used for "_legs"/"_arms".
# Ship components sharing the "core" word (LuxCore, CoolCore, ThermalCore)
# were never actually at risk either way: they carry a component-type-code
# prefix (POWR_/COOL_) resolved earlier by component_type_from_key, which
# always wins first.
#
# "gys_jacket" / "gys_pants" cover the Carnifex set's torso/leg pieces
# (item_Name_gys_jacket_01_01_01 -> "Carnifex Armor Core",
# item_Name_gys_pants_01_01_01 -> "Carnifex Armor Legs") — yet another
# manufacturer-specific naming scheme with no "armor" token. Scoped to the
# "gys_" prefix rather than bare "jacket"/"pants": those bare words match
# hundreds of unrelated civilian wardrobe items (987/ALB/CTL/DMC fashion
# lines) elsewhere in item_Name space, none of which are ever real blueprint
# rewards today — but there's no need to gamble on that staying true.
_ARMOR_EXTRA_WORDS = (
    "backpack", "undersuit", "flightsuit", "torso", "_legs", "_arms", "_core",
    "gys_jacket", "gys_pants",
)
from src.utils.owned_items import (
    BULLET_NAME_ALIASES,
    extract_bp_item_names,
    has_bp_section,
    normalize_item_name,
)
from src.utils.tag_builder import DEFAULT_COMPONENT_CLASS_MAPPING

# The Class facet should read as a full word ("Military") regardless of the
# Tag Builder style the tag was actually rendered in (Short "M" / Medium
# "MIL" / Long "Military" — user-configurable per #157's parse_component_tag
# limitation notwithstanding). Built from the same table the Tag Builder's
# default component class mapping uses, so it stays in sync automatically.
_CLASS_ABBREV_TO_FULL: dict[str, str] = {}
for _full, (_short, _med, _long) in DEFAULT_COMPONENT_CLASS_MAPPING.items():
    _CLASS_ABBREV_TO_FULL[_short.upper()] = _long
    _CLASS_ABBREV_TO_FULL[_med.upper()] = _long
    _CLASS_ABBREV_TO_FULL[_long.upper()] = _long
del _full, _short, _med, _long


def expand_class_full_word(cls: Optional[str]) -> Optional[str]:
    """Map a class token (any Tag Builder length) to its full word.

    Falls through unchanged for anything not in the default component class
    table (e.g. a user's custom class_mapping label) — best-effort, not a
    hard requirement, matching parse_component_tag's own best-effort framing.
    """
    if not cls:
        return cls
    return _CLASS_ABBREV_TO_FULL.get(cls.upper(), cls)


def strip_size_prefix(size: Optional[str]) -> Optional[str]:
    """Drop the leading "S" from a size token ("S3" -> "3") for display.

    size_from_key / parse_component_tag keep the "S" prefix for their own
    contract (it round-trips into loc-key lookups elsewhere); this is purely
    the Size facet's own preference to show a bare number.
    """
    if not size:
        return size
    return size[1:] if size[:1].upper() == "S" else size

# Loc-key prefix for item names; ship-weapon detection slices it off to
# inspect the manufacturer token that follows.
_ITEM_NAME_PREFIX = "item_Name"

# Coarse type buckets for non-component blueprint items.
_TYPE_FPS_WEAPON = "FPS Weapon"
_TYPE_SHIP_WEAPON = "Ship Weapon"
_TYPE_ARMOR = "Armor"
_TYPE_AMMO = "Ammo"
_TYPE_OTHER = "Other"

# Ammo/magazine loc keys always end in "_mag" (optionally "_empty"/"_filled",
# e.g. the salvage canister pair item_Name..._salvage_mag_empty /
# ..._salvage_mag_filled) (#249). Anchored to the end of the key rather than a
# bare "_mag" substring match: several weapon keys carry "_rifle_"/"_pistol_"/
# etc tokens that would otherwise win the FPS Weapon bucket first (e.g.
# item_Namebehr_rifle_ballistic_01_mag -> "P4-AR Magazine"), and an end anchor
# also rules out unrelated items that merely contain "mag" mid-key (e.g.
# item_NameFlair_Poster_SM_Mag_Cover, a physical magazine poster, not ammo).
_AMMO_KEY_SUFFIXES = ("_mag", "_mag_empty", "_mag_filled")

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

# Blueprints that exist in-game but were never advertised via a mission's
# POTENTIAL BLUEPRINTS text (#267) -- CIG announced these purely on their own
# website/socials for a limited-time event, so there's no loc-string source to
# scan them out of. Keyed by the bare item name a "Received Blueprint: ..."
# log line or a bullet would carry (no component tag). Extend this tuple for
# any future item reported missing the same way.
_MANUAL_MISSION_LABEL = "Limited time event reward"
MANUAL_BLUEPRINT_ITEMS: tuple[tuple[str, str], ...] = (
    # XenoThreat "Purgatory Camo" armor sets
    ("Chiron Arms Purgatory Camo", _TYPE_ARMOR),
    ("Chiron Backpack Purgatory Camo", _TYPE_ARMOR),
    ("Chiron Core Purgatory Camo", _TYPE_ARMOR),
    ("Chiron Helmet Purgatory Camo", _TYPE_ARMOR),
    ("Chiron Legs Purgatory Camo", _TYPE_ARMOR),
    ("Testudo Arms Purgatory Camo", _TYPE_ARMOR),
    ("Testudo Backpack Purgatory Camo", _TYPE_ARMOR),
    ("Testudo Core Purgatory Camo", _TYPE_ARMOR),
    ("Testudo Helmet Purgatory Camo", _TYPE_ARMOR),
    ("Testudo Legs Purgatory Camo", _TYPE_ARMOR),
    ("Monde Arms Purgatory Camo", _TYPE_ARMOR),
    ("Monde Core Purgatory Camo", _TYPE_ARMOR),
    ("Monde Helmet Purgatory Camo", _TYPE_ARMOR),
    ("Monde Legs Purgatory Camo", _TYPE_ARMOR),
    ("Warden Backpack Purgatory Camo", _TYPE_ARMOR),
    # XenoThreat "Purgatory Camo" FPS weapons
    ('Demeco "Purgatory Camo" LMG', _TYPE_FPS_WEAPON),
    ('S71 "Purgatory Camo" Rifle', _TYPE_FPS_WEAPON),
    ('BR-2 "Purgatory Camo" Shotgun', _TYPE_FPS_WEAPON),
    # XenoThreat ship components
    ("QuadraCell", _TYPE_LABELS["POWR"]),
    ("QuadraCell MT", _TYPE_LABELS["POWR"]),
    ("FR-66", _TYPE_LABELS["SHLD"]),
    ("FR-76", _TYPE_LABELS["SHLD"]),
    ("NDB-26 Repeater", _TYPE_SHIP_WEAPON),
    ("NDB-28 Repeater", _TYPE_SHIP_WEAPON),
    ("NDB-30 Repeater", _TYPE_SHIP_WEAPON),
)


def _key_slug(key: str) -> str:
    """Title-case each underscore-separated segment of a loc key (after
    dropping a trailing "_Name" segment, if present) and join with spaces
    -- e.g. ``Nozzle_FuelGiver_GRIN_NozzleVeryFast_Name`` -> ``Nozzle
    Fuelgiver Grin Nozzleveryfast``.

    Reproduces a real CIG bug: some mission POTENTIAL BLUEPRINTS bullets
    list this exact de-slugified KEY instead of the item's actual
    localized name (confirmed via a live mission body reporting "Nozzle
    Fuelgiver Grin Nozzleveryfast" as a blueprint reward -- the real item
    is "Lindstrom", key ``Nozzle_FuelGiver_GRIN_NozzleVeryFast_Name``).
    Deterministic and reversible, so rather than hardcoding aliases per
    affected item, every bullet name that doesn't match a real item
    directly is checked against this transform of every known Name key.
    """
    segments = key.split("_")
    if segments and segments[-1].lower() == "name":
        segments = segments[:-1]
    return " ".join(seg.capitalize() for seg in segments)


# Bullet-name aliases now live in owned_items.BULLET_NAME_ALIASES so the
# owned-tag matching folds through the same table (#346); this module
# keeps using it for the resolution chain in build_blueprint_metadata.
_BULLET_NAME_ALIASES = BULLET_NAME_ALIASES

# Prefixes CIG strips off a blueprint XML's filename before the descriptive
# part. Shared with generate_enhancements_ini.py's _name_from_blueprint_filename
# (imported from here, same deferred-import pattern as tag_builder/win_paths)
# so the two don't hand-maintain separate copies of the same transform.
RAW_BLUEPRINT_FILENAME_PREFIXES = ("bp_craft_", "bp_rewards_", "bp_")


def strip_raw_blueprint_filename_prefix(stem: str) -> "tuple[str, bool]":
    """Strip a known bp_* filename prefix (case-insensitively) from *stem*.

    Returns ``(remainder, True)`` if a prefix matched, or ``(stem, False)``
    unchanged if it didn't -- deliberately leaves "no prefix matched" for the
    caller to interpret, since the two current callers disagree on what that
    means: :func:`_raw_blueprint_filename_slug` below takes it as "this bullet
    isn't shaped like a raw blueprint filename at all," while
    generate_enhancements_ini.py's ``_name_from_blueprint_filename`` still
    transforms the untouched stem (its caller already knows it's a genuine
    blueprint XML path, so there's no "is this one at all" question to ask).
    """
    lowered = stem.lower()
    for prefix in RAW_BLUEPRINT_FILENAME_PREFIXES:
        if lowered.startswith(prefix):
            return stem[len(prefix):], True
    return stem, False


def _raw_blueprint_filename_slug(raw_nm: str) -> "str | None":
    """Recover a real display name from a raw blueprint-XML-filename-shaped
    bullet, or None if *raw_nm* doesn't look like one.

    Some mission text ships the raw blueprint filename stem verbatim instead
    of a resolved display name -- confirmed via a live "URGENT REFUEL
    REQUEST" mission body listing "bp_craft_nozzle_fuelgiver_grin_
    nozzleverysecure" for what should be "Harkin". This is a different root
    cause than _key_slug's garbled-KEY bug above: the bullet here is the
    blueprint's own filename, not a de-slugified loc key, so it needs its
    own prefix-strip + title-case transform before _BULLET_NAME_ALIASES can
    recognize it -- once transformed it lands on the exact same alias-table
    entries the key-slug bug already uses (both bugs happen to produce the
    same title-cased string for the fuel-nozzle family), so no new aliases
    are needed, just the extra normalization step to reach them.
    """
    stem, matched = strip_raw_blueprint_filename_prefix(raw_nm)
    if not matched:
        return None
    return stem.replace("_", " ").replace("-", " ").title()


# Extra Name-key conventions for #266's bare-type components, which don't
# follow the item_Name<code> / vehicle_Name prefix every other component
# uses. Fuel nozzles ship under two different manufacturer-specific
# prefixes (MISC's item_fuelnozzle_* vs Greycat/Shubin's
# Nozzle_FuelGiver_*); mining lasers share one prefix across all
# manufacturers but carry no "_Name" marker at all -- the bare key IS the
# name entry. Without these, Pass 1 never recognised these keys as Name
# entries at all, so the _key_slug fallback and the explicit aliases above
# had nothing to resolve against, and the Blueprint Tracker's tagged_name
# fell back to the untagged bare name even though the String Editor showed
# the real tag correctly.
# Extend this alongside _BARE_TYPE_NAMES in generate_enhancements_ini.py
# whenever a new bare-type category ships (fuel tank, mining module, ...).
_EXTRA_NAME_KEY_PREFIXES = (
    "item_fuelnozzle_",
    "nozzle_fuelgiver_",
    "item_mining_mininglaser_",
)

# The bracketed component tag, e.g. "[MIL-S3-B]" or the user-reconfigured
# "[CMP.S1.B.PW]". Parsed by tokenizing the contents rather than a fixed
# pattern, because the tag's separator, element order, and which elements
# appear are all Tag-Builder-configurable (see parse_component_tag). Matched
# leading OR trailing since the category's placement setting can put it on
# either side (mirrors normalize_item_name's leading/trailing handling).
_TAG_BRACKET_RE = re.compile(r"^\s*\[([^\]]+)\]")
_TRAILING_TAG_BRACKET_RE = re.compile(r"\[([^\]]+)\]\s*$")
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
    # The item's own item_Name value, tag and all (e.g. "Norfield [MIL-S1-A]"
    # or "10-Series Greatsword Cannon [Physical-S2]") — whatever the Tag
    # Builder actually rendered, leading or trailing per the category's
    # placement setting. Falls back to the bare `name` when the item never
    # resolved to a loc key (landed in "Other"). `name` stays the stable,
    # tag-free identity used for matching/filtering/Owned-tracking; this is
    # purely for the optional "show tags" display toggle.
    tagged_name: str = ""


def parse_component_tag(value: str):
    """Best-effort ``(class, size, grade)`` from a component tag.

    Robust to the Tag Builder's configurable separator / element order / which
    elements are shown, so it handles the default ``[MIL-S3-B]`` and a
    reconfigured ``[CMP.S1.B.PW]`` alike. Also robust to the category's
    placement setting: the tag is matched leading (``[MIL-S3-B] Norfield``,
    prepend) or trailing (``Norfield [MIL-S3-B]``, append) — a category
    configured to append lost Class/Grade extraction entirely until this
    matched normalize_item_name's leading/trailing symmetry. The tokens
    inside the ``[...]`` are split on any non-alphanumeric separator and
    classified: an ``S?<digits>`` token is the size, a lone A-F letter is the
    grade, and the first multi-letter token is the class (type codes like
    ``PW`` come after the class in the tag, so they don't win). Missing
    pieces are ``None``.

    Limitation: a single-letter (Short-style) class code can't be told apart from
    a grade letter, so class may be missed under a Short class style — size still
    comes from the loc key and grade still resolves.

    Limitation: the class token itself is unvalidated against any known class
    list, so a stock component name that happens to end in a bracket that
    isn't actually a tag (e.g. a name literally ending in "[Prototype]")
    would parse a bogus class facet now that trailing brackets are matched
    too, not just leading ones. The call-site gate (only components actually
    routed through the Tag Builder reach this function) makes it unlikely in
    practice; the leading-only version of this regex had the same weakness.
    """
    m = _TAG_BRACKET_RE.match(value or "") or _TRAILING_TAG_BRACKET_RE.search(value or "")
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
    if kl.endswith(_AMMO_KEY_SUFFIXES):
        return _TYPE_AMMO
    if any(w in kl for w in _FPS_WEAPON_WORDS):
        return _TYPE_FPS_WEAPON
    if any(w in kl for w in _ARMOR_GEAR_WORDS) or any(w in kl for w in _ARMOR_EXTRA_WORDS):
        return _TYPE_ARMOR
    # Ship-mounted mining lasers share CIG's generic "Mining_Head" entity-model
    # key shape across every real variant (item_NameMining_Head_S00_Arbor_SCItem,
    # ..._Helix_SCItem, ..._Hofstede_SCItem, ..._Klein_SCItem): "Mining" starts
    # with an uppercase letter like a manufacturer code, and "_S00" is the
    # head's own size-0 designator -- both signals the ship-weapon heuristic
    # below looks for, so every one of them satisfies it by coincidence and
    # misclassifies as "Ship Weapon". None of these are combat ship weapons;
    # carve the family out before that check so they land in "Other", same as
    # any mining laser CIG ships under a different key shape.
    if "mining_head" in kl:
        return None
    # Ship weapons (#212): an uppercase-manufacturer ship item (item_Name<UPPER>…)
    # carrying a weapon size designator (_S2 / _XL / _L-2) but no recognized
    # subsystem code — the same signal string_model uses to route ship weapons
    # into "Ship Items". Without this they fell into the "Other" bucket and had
    # no entry in the Blueprints tracker's Type filter.
    if kl.startswith(_ITEM_NAME_PREFIX.lower()):
        after = key[len(_ITEM_NAME_PREFIX):]
        if after[:1].isupper() and _SHIP_WEAPON_SIZE_RE.search(key):
            return _TYPE_SHIP_WEAPON
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


def build_blueprint_metadata(
    entries, bp_header: "str | None" = None
) -> dict:
    """Scan loaded strings once and return ``{name: BlueprintItem}``.

    *entries* is any iterable of objects exposing ``key`` / ``original_value``
    / ``category``. The result is keyed by the same normalized item names the
    owned set and ``StringTableModel`` use, so it drops straight into the
    Blueprints shuttle.

    ``bp_header``, when given, is the user's actual configured "blueprints"
    mission header (#353) -- e.g. ``AppSettings.get_mission_headers()
    ["blueprints"]``. Without it, a renamed header is never recognized as a
    blueprint-bearing section at all, so the Pass 1 gate below silently
    skips every mission, not just mis-tags one. See
    ``owned_items.has_bp_section``'s docstring.
    """
    # Pass 1: name->key map (for type), component tag attrs, mission titles,
    # and the blueprint-bearing desc values.
    name_to_key: dict = {}      # normalized display name -> its loc key
    name_to_value: dict = {}    # normalized display name -> its raw item_Name value (tag intact)
    attrs: dict = {}            # normalized name -> (cls, size, grade)
    titles: dict = {}           # (base_lower, num) -> cleaned mission name
    bp_descs: list = []         # (pair_key | None, value)
    keyslug_to_name: dict = {}  # _key_slug(key) -> normalized display name

    for e in entries:
        key = getattr(e, "key", "") or ""
        val = getattr(e, "original_value", "") or ""
        cat = getattr(e, "category", "") or ""
        kl = key.lower()

        if (kl.startswith("item_name") or kl.startswith("vehicle_name")
                or kl.startswith(_EXTRA_NAME_KEY_PREFIXES)):
            nm = normalize_item_name(val)
            if nm:
                keyslug_to_name[_key_slug(key)] = nm
                # Prefer the longest value when multiple distinct keys
                # normalize to the same display name — e.g. two ship weapons
                # with different manufacturer codes/sizes that happen to
                # share an identical stock display name, one of them an
                # untagged/unenhanced duplicate CIG ships alongside the real,
                # tagged entity. A bare first-wins pick could lock in the
                # untagged one, leaving the Blueprint Tracker showing no tag
                # and no Class/Size/Grade facets for an item that IS tagged
                # elsewhere. Recompute attrs alongside the winning value so
                # the two never fall out of sync with each other.
                existing_val = name_to_value.get(nm)
                if existing_val is None or len(val.strip()) > len(existing_val):
                    name_to_key[nm] = key
                    name_to_value[nm] = val.strip()
                    # Class/size/grade only for recognized component types
                    # (Shield, Quantum Drive, ...); ship weapons etc. carry a
                    # different tag shape (e.g. [E-S2], no grade) that would
                    # pollute the facets.
                    if cat == "Ship Items" and component_type_from_key(key):
                        cls, tag_size, grade = parse_component_tag(val)
                        cls = expand_class_full_word(cls)
                        size = strip_size_prefix(size_from_key(key) or tag_size)
                        if cls or size or grade:
                            attrs[nm] = (cls, size, grade)
                        elif nm in attrs:
                            del attrs[nm]

        tm = _TITLE_KEY_RE.match(key)
        if tm:
            titles[_title_pair_key(tm.group("base"), tm.group("num"))] = \
                clean_mission_title(val)

        # #354: gated to Missions entries only. A POTENTIAL BLUEPRINTS
        # section only ever legitimately exists in a mission's Desc text --
        # without this gate, has_bp_section runs on every entry's value
        # unconditionally, so if a user's independently-configurable
        # "Blueprint Data" mission-commodity header (settings.py's
        # MISSION_HEADER_BLUEPRINT_DATA) happens to collide with the
        # "blueprints" header text, a commodity's crafting-material-usage
        # summary ("- Power Plants: 10 items", "- Quantum Drives: 3 items
        # (S1-S3)", one per raw material) gets scanned as if it were a real
        # mission's blueprint reward list -- fabricating fake, unownable
        # "items" that show up identically in both Available and Owned
        # (reported as the tracker "stacking" components).
        if cat == CATEGORY_MISSIONS and has_bp_section(val, bp_header):
            dm = _DESC_KEY_RE.match(key)
            pair = _title_pair_key(dm.group("base"), dm.group("num")) if dm else None
            bp_descs.append((pair, val))

    # Pass 2: gather each blueprint item's missions, then attach type + attrs.
    # A bullet name that doesn't match any real item directly is checked
    # against the known one-off aliases, then against the key-slug fallback
    # (see _BULLET_NAME_ALIASES / _key_slug), then against the raw-filename
    # fallback (see _raw_blueprint_filename_slug) before falling back to
    # itself, so a mismatched bullet still joins the real, tagged item
    # instead of creating a separate untagged "Other" entry.
    missions_by_name: dict = {}
    for pair, val in bp_descs:
        title = titles.get(pair) if pair else None
        for raw_nm in extract_bp_item_names(val, bp_header):
            if raw_nm in name_to_value:
                nm = raw_nm
            elif raw_nm in _BULLET_NAME_ALIASES:
                nm = _BULLET_NAME_ALIASES[raw_nm]
            elif raw_nm in keyslug_to_name:
                nm = keyslug_to_name[raw_nm]
            else:
                slug = _raw_blueprint_filename_slug(raw_nm)
                nm = _BULLET_NAME_ALIASES.get(slug, raw_nm) if slug else raw_nm
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
            tagged_name=name_to_value.get(nm) or nm,
        )

    # Pass 3: fold in manually-declared items no mission ever advertised
    # (#267). Prefer real data from Pass 1 if this install's loaded strings
    # happen to carry a matching item_Name/vehicle_Name entry (picks up the
    # real tag/class/size/grade); otherwise fall back to a bare entry so the
    # item still shows up rather than being silently dropped. Never
    # overwrites an item a mission already supplied.
    for raw_name, manual_type in MANUAL_BLUEPRINT_ITEMS:
        nm = normalize_item_name(raw_name)
        if not nm or nm in result:
            continue
        key = name_to_key.get(nm)
        cls, size, grade = attrs.get(nm, (None, None, None))
        result[nm] = BlueprintItem(
            name=nm,
            missions=frozenset({_MANUAL_MISSION_LABEL}),
            type=(blueprint_type_from_key(key) or manual_type),
            cls=cls,
            size=size,
            grade=grade,
            tagged_name=name_to_value.get(nm) or nm,
        )
    return result
