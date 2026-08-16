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
from functools import lru_cache

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


@lru_cache(maxsize=8)
def _build_bp_header_re(custom_header: "str | None"):
    """Compiled header-matching regex, optionally widened to ALSO recognize
    *custom_header* -- the user's actual configured "blueprints" mission
    header (AppSettings.get_mission_headers()["blueprints"]), which the
    generator writes verbatim into mission text instead of the hardcoded
    default when the user has renamed it (#353). Without this, has_bp_section
    /_bp_section_span never matched a renamed header at all, so the Blueprint
    Tracker silently stopped scanning every mission -- not just mis-tagging
    one, the whole feature going dark for anyone who renamed this header.

    Anchored to an ``<EM3>``/``<EM4>`` wrapper (matching open/close tag
    number, like _SECTION_HEADER_RE below), not a bare substring search: the
    generator always writes the header as ``f"<{em}>{header}</{em}>"``
    (generate_enhancements_ini.py), so requiring that wrapper here too rules
    out an unrelated, coincidental occurrence of the header text elsewhere in
    the SAME mission's own prose. This matters far more once the header is
    user-renameable -- "POTENTIAL BLUEPRINTS" is distinctive enough to never
    collide with real flavor text by accident, but a user-chosen replacement
    (a real report: renamed to "stuff") can easily be an ordinary word CIG's
    own mission dialogue already uses elsewhere in the same body, which the
    old bare-substring match would treat as the section start and sweep every
    stray "\\n- <word>" prose bullet between that false match and the real
    header (or next section) into the item set as if they were blueprints.

    *custom_header* is skipped (falls back to the module-level default-only
    pattern) when empty or already equal to one of the built-in headers, so
    the common "never renamed it" case doesn't pay for an extra regex build.
    Cached because this can be called once per entry across a full rescan.
    """
    parts = [BP_SECTION_HEADER, _ALT_BP_SECTION_HEADER]
    if custom_header:
        custom_header = custom_header.strip()
        if custom_header and custom_header.upper() not in {p.upper() for p in parts}:
            parts.append(custom_header)
    alt = "|".join(re.escape(p) for p in parts)
    # A trailing parenthesised qualifier is part of the header, not a
    # different header. CIG ships several: "Potential Blueprints (Repeat
    # Only)", "(BitZeros Only)", "(Nyx Only)", "(Pyro IV/V Area Only)", and
    # "Multiple Blueprint Pools (Yormandi Eye Only)" -- 20 lines across the
    # 292 header-bearing lines in tests/fixtures/kraken_global_latest.ini.
    # Requiring the wrapper to hold *only* the header text dropped every one
    # of them, which is the same "mission silently absent from the tracker"
    # failure this function exists to fix, just for a different subset. The
    # group stays optional and bounded to one parenthesised run, so it still
    # rejects unrelated text: "<EM3>stuffed animals</EM3>" does not match a
    # header renamed to "stuff".
    return re.compile(
        r"<EM([34])>\s*(?:" + alt + r")(?:\s*\([^)]*\))?\s*</EM\1>",
        re.IGNORECASE,
    )


def has_bp_section(value: str, bp_header: "str | None" = None) -> bool:
    """True if *value* contains a recognised blueprint-section header.

    Single source of truth for the "is this a blueprint-bearing mission
    body" gate used by blueprint_meta.py (before collecting a Desc for
    bullet scanning) and entry_filter.py (the String Editor's "BP
    Descriptions" checkbox) -- both used to do their own raw ``BP_SECTION_
    HEADER in value.upper()`` substring check, which missed the
    "MULTIPLE BLUEPRINT POOLS" header entirely.

    ``bp_header``, when given, is the user's actual configured "blueprints"
    mission header (#353) -- see :func:`_build_bp_header_re`. Defaults to
    matching only the built-in headers when omitted, matching this
    function's original hardcoded behavior exactly.
    """
    return bool(_build_bp_header_re(bp_header).search(value or ""))


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


def _bp_section_span(value: str, bp_header: "str | None" = None):
    """Return (start, end) spanning just the blueprint section's bullet
    content — from right after its header (POTENTIAL BLUEPRINTS or MULTIPLE
    BLUEPRINT POOLS, or the user's renamed header -- see :func:`has_bp_
    section`) up to the next real section header (or end of string). ``None``
    when there's no such section.

    Bounding the scan this way matters: CIG mission bodies sometimes carry a
    stray "\\n- <word>" line in the flavor-text prose *before* the header
    (e.g. "\\n- Stows\\n"), and a body with both a blueprint section and a
    later ITEM REWARDS section (e.g. "\\n- Council Scrip") puts a real
    bullet-shaped line after it too. Un-scoped bullet matching swept both
    into the blueprint item set. Bullets across ALL pools/tiers within one
    section are pooled into a single set -- this module doesn't track which
    specific pool/tier a bullet belongs to, matching the pre-existing
    region-label behaviour.

    The END boundary doesn't need ``bp_header`` awareness even if the user
    also renamed "MISSION DETAILS"/"ITEM REWARDS"/etc: the loop below treats
    ANY other ``<EM3>``/``<EM4>`` tag as the next section's start regardless
    of its specific text, so a renamed header there is already handled.
    """
    m = _build_bp_header_re(bp_header).search(value)
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


def extract_bp_item_names(value: str, bp_header: "str | None" = None) -> set[str]:
    """Return the normalized item names in *value*'s POTENTIAL BLUEPRINTS list.

    Empty when the value has no such section. Scoped to just that section's
    span (see :func:`_bp_section_span`) so a stray prose bullet before the
    header or a real bullet in a later section (ITEM REWARDS, ...) isn't
    picked up as a blueprint item. ``bp_header`` is forwarded to
    :func:`_bp_section_span` -- see :func:`has_bp_section`'s docstring (#353).
    """
    if not value:
        return set()
    span = _bp_section_span(value, bp_header)
    if span is None:
        return set()
    start, end = span
    return {normalize_item_name(m.group(1))
            for m in _BULLET_RE.finditer(value, start, end)
            if normalize_item_name(m.group(1))}


def apply_owned_to_value(
    value: str, owned: set[str], bp_header: "str | None" = None
) -> str:
    """Return *value* with ``[Owned]`` on bullets whose item is in *owned*.

    Idempotent: any existing ``[Owned]`` tag is removed first, so the result is
    a pure function of (value, owned) and re-running never doubles the tag.
    Values without a POTENTIAL BLUEPRINTS section are returned unchanged (after
    stripping stale owned tags, in case an item was just un-owned). Retagging
    is scoped to just that section's span (see :func:`_bp_section_span`) so a
    stray prose bullet before the header or a bullet in a later section can
    never be mistaken for a blueprint item. ``bp_header`` is forwarded to
    :func:`_bp_section_span` -- see :func:`has_bp_section`'s docstring (#353).
    """
    if not value:
        return value
    # Strip any prior owned tags first (handles un-owning + idempotency).
    value = _OWNED_STRIP_RE.sub("", value)
    if not owned:
        return value
    span = _bp_section_span(value, bp_header)
    if span is None:
        return value
    start, end = span

    def _retag(m: re.Match) -> str:
        raw = m.group(1)
        if normalize_item_name(raw) in owned:
            return f"{_NL}- {raw}{_OWNED_TAG}"
        return m.group(0)

    return value[:start] + _BULLET_RE.sub(_retag, value[start:end]) + value[end:]
