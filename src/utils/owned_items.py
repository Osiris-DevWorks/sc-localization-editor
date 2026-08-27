"""Owned-blueprint tagging (#157).

Users mark blueprint items they already own; an ``[Owned]`` tag is then woven
onto that item wherever it appears in a mission reward POTENTIAL BLUEPRINTS
list. Keyed by item *display name* (issue #157 option a) because the GUI table
never sees item UUIDs — it works purely from localization keys and values.

Qt-free and settings-free so it can be unit-tested with plain strings. The
transform is idempotent: it strips any existing ``[Owned]`` tags before
re-applying, so it can run on every load and on every toggle without doubling.

Values use a literal ``\\n`` (backslash-n) line separator — the in-INI encoding
the parser and game both read — so all matching here is on the two-character
sequence, not a real newline.
"""
from __future__ import annotations

import re
import unicodedata

# The bullet line separator inside a stored INI value (literal backslash-n).
_NL = "\\n"
# A POTENTIAL BLUEPRINTS bullet: "\n- <name>". Names can carry a leading
# component tag ("[Mil-S1-A] Norfield") and we keep everything up to the next
# separator.
_BULLET_RE = re.compile(re.escape(_NL) + r"- ([^\\]+)")
# The owned tag we weave in. EM4 renders blue in-game — the visibility the
# request asked for ("so it's in blue").
_OWNED_TAG = " <EM4>[Owned]</EM4>"
# Strip a previously-applied owned tag (with or without the leading space).
_OWNED_STRIP_RE = re.compile(r"\s*<EM4>\[Owned\]</EM4>")
# A leading bracketed component tag on a bullet name, e.g. "[Mil-S1-A] ".
_LEADING_TAG_RE = re.compile(r"^\[[^\]]*\]\s*")
# A trailing bracketed tag, e.g. "10-Series Greatsword Cannon [B-S2-A]". The
# Tag Builder's placement setting is per-category and user-configurable
# (prepend/append), so the same class/size/grade tag can land on either side
# of the name depending on which category (components vs. ship_weapons vs.
# missiles) it came from. Stripping both sides keeps matching independent of
# that setting instead of only handling the default leading placement.
_TRAILING_TAG_RE = re.compile(r"\s*\[[^\]]*\]\s*$")
# Collapse any run of whitespace to a single space. Runs after NFKC folds a
# non-breaking space (U+00A0, seen in log names like "Lynx\xa0Legs") into a
# plain space, so the same item from a log and from loc data normalize alike.
_WS_RE = re.compile(r"\s+")

# CIG's own POTENTIAL BLUEPRINTS bullet text appends a category annotation to
# some items -- "Bendix (Fuel Nozzle)", "Arbor MH1 Mining Laser (Mining
# Laser)", "5CA 'Akura' (Shield)", "Trawler Scraper Module (Salvage Mod)" --
# that never appears on the item's own item_Name value. Left unstripped, the
# bullet-extracted name never matches the real (tagged) item, so it shows up
# as a separate, untagged "Other"-type entry in the Blueprint Tracker instead
# of joining with the real one (confirmed via tests/fixtures/kraken_global_
# latest.ini across at least these 8 categories -- almost certainly a
# systemic gap, not specific to any one item type). A small explicit
# allow-list rather than "strip any trailing (...)": some items carry a
# parenthetical that IS part of their real distinguishing name (e.g. "Artimex
# Arms (Modified)"), and blindly stripping those would collide two actually
# different items into one.
_BULLET_CATEGORY_ANNOTATIONS = frozenset({
    "Cooler", "Fuel Nozzle", "Mining Laser", "Powerplant", "Quantum Drive",
    "Radar", "Salvage Mod", "Shield",
})
_TRAILING_CATEGORY_RE = re.compile(
    r"\s*\((" + "|".join(re.escape(w) for w in _BULLET_CATEGORY_ANNOTATIONS) + r")\)\s*$"
)

# Known one-off mismatches between a mission bullet's name and the item's real
# localized display name that AREN'T explained by a key-slug or filename
# fallback -- the mission author simply wrote a short/informal name, or the
# generator deliberately strips a leading CIG size prefix from blueprint-list
# output (_strip_cig_size_prefix in generate_enhancements_ini.py) so the list
# reads with one size convention.
#
# Applied inside normalize_item_name, so BOTH sides of every comparison fold
# to the real name. That symmetry is the point: this table used to live in
# blueprint_meta.py, where it resolved bullets for the Blueprint Tracker's
# item list only. The owned-set matching in apply_owned_to_value never saw it,
# so a mission bullet reading "Hofstede" was compared against an owned entry
# stored as "S00 Hofstede" and never matched -- the item showed as owned in
# the tracker but its bullet never got an [Owned] tag in game (#346).
#
# Keys are what a bullet says; values are the item's real display name.
# Extend for any other reported mismatch that isn't a key-slug case.
BULLET_NAME_ALIASES: dict[str, str] = {
    "Arbor": "S0 Arbor",
    "Helix": "S0 Helix",
    "Hofstede": "S00 Hofstede",
    "Klein": "Lawson Mining Laser",
    # Fuel nozzles (#266 follow-up): most manufacturer variants resolve
    # generically via the key-slug fallback (their real key follows
    # Nozzle_FuelGiver_<MFR>_Nozzle<Variant>_Name), but these three still
    # showed up ungarbled/untagged after that fix -- their real underlying
    # key must not match that exact pattern.
    "Nozzle Fuelgiver Grin Nozzlefast": "Norfield",
    "Nozzle Fuelgiver Grin Nozzleverysecure": "Harkin",
    "Nozzle Fuelgiver Misc Nozzlestandard": "RN-7s",
}

# Marks the start of a blueprint-bearing section. The header text is
# user-configurable (AppSettings.MISSION_HEADER_DEFAULTS["blueprints"]) but the
# default is BP_SECTION_HEADER; we match that default case-insensitively. This
# module stays settings-free by design, so it owns the default literal rather
# than importing AppSettings, and the settings default is kept in sync with it.
# blueprint_meta.py and entry_filter.py import BP_SECTION_HEADER from here so
# the three matchers share one source of truth. A value with no such header has
# no bullets to tag, so it passes through untouched.
#
# CIG uses a SECOND, entirely different header for missions that offer more
# than one blueprint pool (confirmed via tests/fixtures/kraken_global_
# latest.ini: "MULTIPLE BLUEPRINT POOLS" appears on 35 missions in the
# fixture, vs. 237 using "POTENTIAL BLUEPRINTS" -- e.g. the mining-laser
# purchase-order contracts that award a weapon/armor Pool 1 alongside a
# mining-laser/radar Pool 2). Missions using this header were entirely
# unscanned before this fix -- not just untagged, absent from the Blueprint
# Tracker altogether, regardless of any per-item fix.
_ALT_BP_SECTION_HEADER = "MULTIPLE BLUEPRINT POOLS"
BP_SECTION_HEADER = "POTENTIAL BLUEPRINTS"
_BP_HEADER_RE = re.compile(
    "(?:" + re.escape(BP_SECTION_HEADER) + "|" + re.escape(_ALT_BP_SECTION_HEADER) + ")",
    re.IGNORECASE,
)


def has_bp_section(value: str) -> bool:
    """True if *value* contains a recognised blueprint-section header.

    Single source of truth for the "is this a blueprint-bearing mission
    body" gate used by blueprint_meta.py (before collecting a Desc for
    bullet scanning) and entry_filter.py (the String Editor's "BP
    Descriptions" checkbox) -- both used to do their own raw ``BP_SECTION_
    HEADER in value.upper()`` substring check, which missed the
    "MULTIPLE BLUEPRINT POOLS" header entirely.
    """
    return bool(_BP_HEADER_RE.search(value or ""))


# A tag that MIGHT be a genuine section header (POTENTIAL BLUEPRINTS, ITEM
# REWARDS, MISSION DETAILS, BLUEPRINT DATA, ...) — filtered further in
# _bp_section_span against the known non-header sub-header shapes: region
# labels (<EM4>[Nyx]</EM4>), reputation-tier labels (<EM4>Awarded from
# Contractor level variants</EM4>), and blueprint-pool labels (<EM4>Pool
# 1</EM4>, <EM4>Pool 2</EM4> -- appear under a MULTIPLE BLUEPRINT POOLS
# header, grouping that mission's several independent bullet lists).
_SECTION_HEADER_RE = re.compile(r"<EM([34])>([^<]*)</EM\1>")
# Reputation-tiered contracts (Adagio Industrial salvage, Bounty Hunters
# Guild, Security, ...) group their blueprint bullets under one of these
# per-tier sub-headers *inside* the section — e.g. "Awarded from Contractor
# level variants" followed by that tier's bullet list, sometimes repeated
# for multiple tiers in one mission body. None of these are section
# boundaries; treating them as one silently truncated the span before any
# bullets were ever reached, so items awarded this way (Scraper Modules —
# Trawler/Cinch/Abrade — among others) never surfaced in the Blueprint
# Tracker at all, tag or no tag.
_AWARDED_FROM_RE = re.compile(r"^awarded from .+ variants$", re.IGNORECASE)
# "Pool 1", "Pool 2", ... under a MULTIPLE BLUEPRINT POOLS header.
_POOL_LABEL_RE = re.compile(r"^pool \d+$", re.IGNORECASE)


def _bp_section_span(value: str):
    """Return (start, end) spanning just the blueprint section's bullet
    content — from right after its header (POTENTIAL BLUEPRINTS or MULTIPLE
    BLUEPRINT POOLS) up to the next real section header (or end of string).
    ``None`` when there's no such section.

    Bounding the scan this way matters: CIG mission bodies sometimes carry a
    stray "\\n- <word>" line in the flavor-text prose *before* the header
    (e.g. "\\n- Stows\\n"), and a body with both a blueprint section and a
    later ITEM REWARDS section (e.g. "\\n- Council Scrip") puts a real
    bullet-shaped line after it too. Un-scoped bullet matching swept both
    into the blueprint item set. Bullets across ALL pools/tiers within one
    section are pooled into a single set -- this module doesn't track which
    specific pool/tier a bullet belongs to, matching the pre-existing
    region-label behaviour.
    """
    m = _BP_HEADER_RE.search(value)
    if not m:
        return None
    start = m.end()
    end = len(value)
    for hm in _SECTION_HEADER_RE.finditer(value, start):
        text = hm.group(2).strip()
        if text.startswith("[") or _AWARDED_FROM_RE.match(text) or _POOL_LABEL_RE.match(text):
            continue
        end = hm.start()
        break
    return start, end


def normalize_item_name(name: str) -> str:
    """Reduce a bullet/name to a stable identity for matching.

    Applies, in order: NFKC unicode folding (so a non-breaking space becomes a
    plain space), removal of any ``[Owned]`` tag, removal of a leading *and* a
    trailing bracketed component tag (``[Mil-S1-A] Norfield`` and
    ``Norfield [Mil-S1-A]`` both reduce to the bare name), removal of a
    trailing bullet-only category annotation (``Bendix (Fuel Nozzle)`` ->
    ``Bendix``), whitespace collapse, and finally a BULLET_NAME_ALIASES
    lookup that folds a known short bullet name onto the item's real display
    name (``Hofstede`` -> ``S00 Hofstede``). Used for both the owned set and
    bullet matching, so a tagged bullet, a log-imported name, and a bare item
    row all resolve to one key.

    The alias fold runs last, after the tag/annotation strips, so a decorated
    bullet (``[Mining Laser-S0] Hofstede``) reduces to the bare name first and
    then resolves like any other.

    Both sides of every comparison pass through here (the owned-set entries and
    the mission bullets in ``apply_owned_to_value``), so the folding is
    symmetric and can never introduce a one-sided mismatch. The category-
    annotation strip is safe on both sides even though it's bullet-specific:
    the allow-listed words never appear as a real item_Name's own trailing
    parenthetical, so it's a no-op wherever it doesn't apply.
    """
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name)
    s = _OWNED_STRIP_RE.sub("", s)
    s = _LEADING_TAG_RE.sub("", s)
    s = _TRAILING_TAG_RE.sub("", s)
    s = _TRAILING_CATEGORY_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return BULLET_NAME_ALIASES.get(s, s)


# Characters that can sit between a foreign tool's tag and the real item name.
# A recovered name must start right after one of these (or fill the whole
# string), so a known item can never be matched mid-word: "Colossus" must not
# resolve out of a hypothetical "MegaColossus". Covers every separator seen in
# the wild (space, StarStrings' "/", generic "-_)}>") plus "." and ":" for a
# tool that hasn't been seen yet but uses either as its tag/name divider.
_FOREIGN_TAG_BOUNDARY = frozenset(" ]/-_)}>.:")


def resolve_against_catalogue(
    name: str, catalogue: "set[str]"
) -> "str | None":
    """Recover the real item a foreign-formatted *name* refers to, or None.

    Star Citizen writes whatever name it was DISPLAYING into Game.log, so a
    player who previously ran another localization editor has that tool's
    naming permanently baked into their old logs. Smart Citizen then scans
    those logs and stores names it can never match against its own item list.
    Reported in #372: a user who had run StarStrings had owned entries reading
    ``Ind/1/B Colossus`` while every other side of the app called the same item
    ``Colossus``, so their blueprints never showed as owned. Deleting and
    regenerating did not help, because the bad names are in the LOGS, not in
    anything Smart Citizen writes.

    Deliberately not a pattern-match against any particular tool's format.
    Matching ``Ind/1/B`` would fix StarStrings and nothing else, and would need
    extending for every editor anyone has ever used. Instead this anchors on
    the one thing we know is true: *catalogue* is the set of real, normalized
    item names built from the current localization data. If a scanned name ends
    in a known real item name, on a word boundary, that is what it refers to,
    whatever decoration precedes it. That works for any tool, including ones
    that do not exist yet.

    Suffix rather than prefix because these tools prepend their tag and leave
    the real name at the end -- StarStrings does, and so does Smart Citizen's
    own default placement.

    Returns None when nothing in *catalogue* is a matching suffix. The longest
    match wins when more than one catalogue entry qualifies, so
    ``Mil/1/B Fierell Cascade`` resolves to ``Fierell Cascade`` and not to the
    equally-real but shorter ``Cascade`` -- two catalogue entries can never
    tie at the same length, since a fixed-length trailing slice of *n* has
    exactly one possible value, so at most one member of a set can equal it.

    Callers pass names that already failed a direct catalogue lookup, so this
    only ever runs on strings that are otherwise unusable. *catalogue* should
    be every real item name this install currently knows about (see
    ``blueprint_meta.known_item_names``), not a narrower "eligible right now"
    subset -- a name absent from *catalogue* only because it means "not a
    known real item", never "known but temporarily unlisted", or a real
    owned item can resolve into an unrelated shorter one and be lost. See
    ``repair_foreign_owned_names``'s docstring for the incident this caused.
    """
    n = normalize_item_name(name)
    if not n:
        return None
    best: "str | None" = None
    best_len = -1
    for known in catalogue:
        if not known or len(known) > len(n) or len(known) <= best_len:
            continue
        if not n.endswith(known):
            continue
        if len(n) != len(known) and n[-len(known) - 1] not in _FOREIGN_TAG_BOUNDARY:
            continue
        best, best_len = known, len(known)
    return best


def repair_foreign_owned_names(
    owned: "set[str]", catalogue: "set[str]"
) -> "tuple[set[str], dict[str, str | None]]":
    """Recover/clean *owned* names left by another editor (#372) against
    *catalogue*, returning ``(repaired, renamed)``.

    Pure Qt-free/settings-free core of ``MainWindow._repair_foreign_owned_
    names`` -- that method only owns the ``AppSettings`` read/write and the
    one-shot-on-load timing; this owns the actual decision logic so it is
    directly testable without Qt or a live settings backend.

    ``renamed`` maps every *owned* entry that changed to what it became:
    the recovered real name, or ``None`` when the entry was dropped outright
    because the same real item was already separately present in *owned*
    (a foreign-formatted duplicate of an already-correct entry). An empty
    ``renamed`` means *owned* was already clean and the caller should skip
    writing anything back.

    ``catalogue`` MUST be every real item name currently known -- see
    ``blueprint_meta.known_item_names`` -- not the narrower Blueprint
    Tracker "eligible right now" set (``build_blueprint_metadata``'s keys).
    That narrower set only contains names with an active mission reward or a
    fixed manual entry, so any real item CIG has rotated out of every
    mission's reward pool this patch -- an expected, recurring state, not a
    rare one -- would read as "unmatched" against it. ``resolve_against_
    catalogue`` would then be free to fold that unmatched-but-real name into
    an unrelated shorter owned item's name and this function would discard it
    as a "duplicate", permanently deleting a real ownership record with
    nothing to show for it -- the exact class of silent data loss #372 itself
    was filed over, reintroduced by this repair step under a different
    trigger. Using the wider catalogue means a name is only ever "unmatched"
    when it genuinely isn't a real item this install knows about, which is
    the only case recovery should touch.
    """
    if not catalogue:
        return set(owned), {}
    unmatched = owned - catalogue
    if not unmatched:
        return set(owned), {}
    repaired = set(owned)
    renamed: "dict[str, str | None]" = {}
    for nm in sorted(unmatched):
        real = resolve_against_catalogue(nm, catalogue)
        if real is None:
            continue
        repaired.discard(nm)
        if real in repaired:
            renamed[nm] = None
        else:
            repaired.add(real)
            renamed[nm] = real
    return repaired, renamed


def extract_bp_item_names(value: str) -> set[str]:
    """Return the normalized item names in *value*'s POTENTIAL BLUEPRINTS list.

    Empty when the value has no such section. Scoped to just that section's
    span (see :func:`_bp_section_span`) so a stray prose bullet before the
    header or a real bullet in a later section (ITEM REWARDS, ...) isn't
    picked up as a blueprint item.
    """
    if not value:
        return set()
    span = _bp_section_span(value)
    if span is None:
        return set()
    start, end = span
    return {normalize_item_name(m.group(1))
            for m in _BULLET_RE.finditer(value, start, end)
            if normalize_item_name(m.group(1))}


def apply_owned_to_value(value: str, owned: set[str]) -> str:
    """Return *value* with ``[Owned]`` on bullets whose item is in *owned*.

    Idempotent: any existing ``[Owned]`` tag is removed first, so the result is
    a pure function of (value, owned) and re-running never doubles the tag.
    Values without a POTENTIAL BLUEPRINTS section are returned unchanged (after
    stripping stale owned tags, in case an item was just un-owned). Retagging
    is scoped to just that section's span (see :func:`_bp_section_span`) so a
    stray prose bullet before the header or a bullet in a later section can
    never be mistaken for a blueprint item.
    """
    if not value:
        return value
    # Strip any prior owned tags first (handles un-owning + idempotency).
    value = _OWNED_STRIP_RE.sub("", value)
    if not owned:
        return value
    span = _bp_section_span(value)
    if span is None:
        return value
    start, end = span

    def _retag(m: re.Match) -> str:
        raw = m.group(1)
        if normalize_item_name(raw) in owned:
            return f"{_NL}- {raw}{_OWNED_TAG}"
        return m.group(0)

    return value[:start] + _BULLET_RE.sub(_retag, value[start:end]) + value[end:]
