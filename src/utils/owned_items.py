"""Owned-blueprint tagging (#157).

Users mark blueprint items they already own; an ``[Owned]`` tag is then woven
onto that item wherever it appears in a mission reward POTENTIAL BLUEPRINTS
list. Keyed by item *display name* (issue #157 option a) because the GUI table
never sees item UUIDs — it works purely from localization keys and values.

Qt-free and settings-free so it can be unit-tested with plain strings: the
Tag Builder's enclosing style is per-category, user-configurable, live
QSettings state, so it's never read here directly. Callers who need
non-default-enclosing matching (#352) resolve the user's live Tag Builder
config themselves (see ``enclosings_from_tag_configs`` below, which is the
one place this module references ``tag_builder``'s plain data tables — not
settings) and hand this module a plain ``enclosings`` tuple. The transform is
idempotent: it strips any existing ``[Owned]`` tags before re-applying, so it
can run on every load and on every toggle without doubling.

Values use a literal ``\\n`` (backslash-n) line separator — the in-INI encoding
the parser and game both read — so all matching here is on the two-character
sequence, not a real newline.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from typing import Sequence

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
# Default (open, close) pairs to strip when a caller doesn't pass its own —
# today's original hardcoded Square-only behavior, preserved exactly so every
# existing caller that doesn't know about #352 is unaffected.
_DEFAULT_ENCLOSINGS: tuple[tuple[str, str], ...] = (("[", "]"),)
# The Tag Builder's "None (space only)" style, which renders no delimiter at
# all. It travels in an ``enclosings`` tuple like any other configured pair;
# _build_tag_patterns has nothing to build from it and skips it, while
# normalize_item_name reads its presence as "the space-only heuristic is worth
# running here". Not in _DEFAULT_ENCLOSINGS, so a caller that hasn't resolved
# the user's real config never pays for a style nobody asked for.
NONE_STYLE_ENCLOSING: tuple[str, str] = ("", "")


def strip_via_stock_diff(tagged: str, stock: str) -> "str | None":
    """Recover the tag text by diffing *tagged* against *stock* -- the
    item's known pre-Tag-Builder value for the same loc key -- rather than
    guessing the tag/name boundary from *tagged* alone (#352). Authoritative,
    not a heuristic: works for every enclosing style, including "None (space
    only)", since it never has to examine the tag's own shape -- it only
    needs to know what ISN'T the name.

    Returns the leftover tag text (possibly ``""`` if *tagged* already equals
    *stock*, i.e. not actually tagged), or ``None`` if *stock* isn't a prefix
    or suffix of *tagged* (nothing to recover -- caller falls back to
    bracket/heuristic stripping). Both sides are NFKC-folded and
    whitespace-trimmed before comparing, matching normalize_item_name's own
    folding, so a stray non-breaking space can't defeat the match.

    Only usable where a caller actually knows the item's stock value for the
    same key (build_blueprint_metadata's Pass 1, the Owned-star column) --
    mission bullet text, the hardcoded MANUAL_BLUEPRINT_ITEMS names, SCMDB
    imports, and Game.log-scanned names have no associated key, so they fall
    back to :func:`_looks_like_none_style_tag_word` instead.
    """
    stock_n = unicodedata.normalize("NFKC", stock or "").strip()
    if not stock_n:
        return None
    tagged_n = unicodedata.normalize("NFKC", tagged or "")
    if tagged_n.strip() == stock_n:
        return ""
    if tagged_n.endswith(stock_n):
        return tagged_n[: -len(stock_n)].strip()
    if tagged_n.startswith(stock_n):
        return tagged_n[len(stock_n):].strip()
    return None


# Conservative "does this look like a None-enclosing tag word" fallback for
# contexts with no stock value to diff against (mission bullets, manual
# items, SCMDB imports, Game.log names -- see strip_via_stock_diff's
# docstring). Deliberately narrow: an earlier, looser version (any
# multi-letter word not shaped like a size token) misfired on ordinary
# multi-word real names -- "10-Series Greatsword Cannon" has a real,
# hyphenated leading word ("10-Series") that a loose bare-digit size check
# would misclassify as a tag. Requiring BOTH an embedded Tag-Builder
# separator char (hyphen/underscore/dot/slash/pipe -- i.e. the tag's
# elements are actually joined together, not just an ordinary word) AND a
# strict "S"-prefixed size token or lone A-F grade letter inside it closes
# that hole: "10-Series" has a separator but no "S<digits>"/lone-letter
# sub-token, so it's correctly left alone, while "MIL-S1-A"/"E-S2" still
# match. Still probabilistic -- it can miss a real tag (space-separated
# elements, e.g. "Military S2 A", have no separator char to key off) or, in
# principle, mis-strip an unlucky real name shaped exactly like a tag one
# never occurred in testing but can't be ruled out entirely. Accepted
# trade-off for contexts where the fully-reliable diff isn't available.
_NONE_STYLE_SEPARATOR_CHARS = frozenset("-_./|")
_NONE_STYLE_SIZE_RE = re.compile(r"^S\d{1,2}$", re.IGNORECASE)
_NONE_STYLE_GRADE_RE = re.compile(r"^[A-F]$", re.IGNORECASE)
# Every bracket char any ENCLOSINGS style renders with. A word wrapped in one
# of these (e.g. "[Mil-S1-A]" when the caller's configured `enclosings` is
# Round only, not Square) belongs to the bracket-based stripping logic, not
# this heuristic -- without this guard, a bracketed tag from a style that's
# simply not in the currently-active set would get incorrectly swept up here
# instead of being left alone as intended.
_BRACKET_CHARS = frozenset("[](){}<>")


def _looks_like_none_style_tag_word(word: str) -> bool:
    if not word or not any(ch in word for ch in _NONE_STYLE_SEPARATOR_CHARS):
        return False
    if word[0] in _BRACKET_CHARS or word[-1] in _BRACKET_CHARS:
        return False
    toks = [t for t in re.split(r"[^A-Za-z0-9]+", word) if t]
    return any(_NONE_STYLE_SIZE_RE.match(t) or _NONE_STYLE_GRADE_RE.match(t) for t in toks)


def find_none_style_tag_word(s: str) -> "tuple[str, str] | None":
    """Find a leading or trailing "None (space only)" tag-shaped word in *s*.

    Returns ``(tag_word, remainder)`` if found, else ``None``. Shared by
    :func:`strip_none_style_tag_heuristic` (owned_items' own callers only
    want the remainder, i.e. the bare name) and blueprint_meta.
    parse_component_tag (wants the tag word itself, to classify class/size/
    grade out of it) so both stay in sync with one matching rule -- see
    :func:`_looks_like_none_style_tag_word` for that rule and its known
    limitations.
    """
    parts = s.split(" ", 1)
    if len(parts) == 2 and _looks_like_none_style_tag_word(parts[0]):
        return parts[0], parts[1]
    parts = s.rsplit(" ", 1)
    if len(parts) == 2 and _looks_like_none_style_tag_word(parts[1]):
        return parts[1], parts[0]
    return None


def strip_none_style_tag_heuristic(s: str) -> str:
    """Best-effort leading/trailing tag-word strip for "None" enclosing when
    no stock value is available to diff against -- see
    :func:`find_none_style_tag_word`."""
    found = find_none_style_tag_word(s)
    return found[1] if found else s


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


@lru_cache(maxsize=16)
def _build_tag_patterns(enclosings: tuple[tuple[str, str], ...]):
    """Compiled (leading_re, trailing_re) for the given (open, close) pairs.

    Matches a Tag Builder tag on either side of a name -- "[Mil-S1-A] Norfield"
    (prepend) or "Norfield [Mil-S1-A]" (append), since the category's
    placement setting can put it on either side (#352). ``enclosings`` must be
    a tuple of 2-tuples (hashable, so this cache works) -- a plain caller-built
    list will raise from deep inside lru_cache, a confusing place to debug, so
    callers should always hand over a tuple. Returns (None, None) when no pair
    has both a non-empty open and close (e.g. an empty tuple, or the "None
    (space only)" style, which has no delimiter and so can never be reversed
    by a regex -- a permanent limitation, not a bug to fix later).
    """
    alts = "|".join(
        re.escape(o) + r"[^" + re.escape(c) + r"]*" + re.escape(c)
        for o, c in enclosings if o and c
    )
    if not alts:
        return None, None
    return (
        re.compile(r"^(?:" + alts + r")\s*"),
        re.compile(r"\s*(?:" + alts + r")$"),
    )


def enclosings_from_tag_configs(
    tag_configs: dict,
    categories: tuple[str, ...] = ("components", "missiles", "ship_weapons"),
) -> tuple[tuple[str, str], ...]:
    """Reduce a ``{category: TagConfig}`` dict (from ``AppSettings.get_all_tag_
    configs()``) to the deduplicated set of (open, close) enclosing pairs
    actually in play, for callers who need to match a tag back off a name.

    Only the 3 categories that ever tag an item/vehicle name appearing in a
    POTENTIAL BLUEPRINTS bullet are considered by default -- ``commodities``
    tags non-ownable trade goods and ``mission_titles`` tags mission title
    text via a separate mechanism (see blueprint_meta._TITLE_TAG_RE); neither
    is relevant to Blueprint Tracker matching.

    Square is always included, regardless of what's actually configured:
    enhancements.ini is a generated artifact that may still carry
    yesterday's Square-tagged values if the user hasn't regenerated since
    changing a setting, and Square never collides with a real Star Citizen
    item name (unlike Round/Curly/Angle, which sometimes do) -- so keeping it
    costs nothing and closes that transition-window gap.
    """
    from src.utils.tag_builder import _ENCLOSING_BY_KEY

    pairs = {("[", "]")}
    for cat in categories:
        cfg = tag_configs.get(cat)
        if cfg is None:
            continue
        o, c = _ENCLOSING_BY_KEY.get(cfg.enclosing, ("[", "]"))
        # The "None (space only)" style is ("", "") -- a real configured
        # enclosing with no delimiter, so it's reported like any other rather
        # than dropped. _build_tag_patterns skips it (there's nothing to build
        # a regex from) and normalize_item_name reads its presence as
        # permission to run the space-only heuristic. Dropping it here is what
        # made that heuristic unconditional: with no way to tell whether any
        # category actually uses None, it had to run for everybody, so every
        # user carried its mis-strip risk while only None users could benefit.
        pairs.add((o, c))
    return tuple(sorted(pairs))


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


def normalize_item_name(
    name: str,
    enclosings: "Sequence[tuple[str, str]] | None" = None,
    stock: "str | None" = None,
) -> str:
    """Reduce a bullet/name to a stable identity for matching.

    Applies, in order: NFKC unicode folding (so a non-breaking space becomes a
    plain space), removal of any ``[Owned]`` tag, removal of a leading *and* a
    trailing Tag Builder tag (``[Mil-S1-A] Norfield`` and ``Norfield
    [Mil-S1-A]`` both reduce to the bare name), removal of a trailing
    bullet-only category annotation (``Bendix (Fuel Nozzle)`` -> ``Bendix``),
    whitespace collapse, and finally a BULLET_NAME_ALIASES lookup that folds a
    known short bullet name onto the item's real display name (``Hofstede``
    -> ``S00 Hofstede``). Used for both the owned set and bullet matching, so
    a tagged bullet, a log-imported name, and a bare item row all resolve to
    one key.

    ``stock``, when given, is the item's known pre-Tag-Builder value for the
    same loc key (#352) -- e.g. ``main_window.py``'s ``self.default_values``,
    the un-enhanced English ``base.ini`` value. When present, it takes
    priority over every other strip below via :func:`strip_via_stock_diff`:
    diffing against a known value is authoritative (works for every enclosing
    style, including "None (space only)", which has no delimiter char to
    guess by) rather than a guess. Only pass this when the caller actually
    has key context (build_blueprint_metadata's Pass 1, the Owned-star
    column) -- bare strings with no associated key (mission bullets, manual
    items, SCMDB imports, Game.log names) have nothing to diff against and
    fall through to the enclosing/heuristic strips below.

    ``enclosings`` is the set of (open, close) delimiter pairs to try
    stripping, e.g. ``(("[", "]"), ("(", ")"))``. Defaults to Square only
    (``[ ]``) when omitted, matching this function's original hardcoded
    behavior exactly -- every caller that hasn't been taught about the Tag
    Builder's configurable enclosing style is unaffected. This module stays
    Qt-free/settings-free: it never reads the user's live Tag Builder config
    itself. A caller that needs the real, currently-configured style resolves
    it via ``enclosings_from_tag_configs(AppSettings.get_all_tag_configs())``
    and passes the result down.

    When neither ``stock`` nor a bracket match resolves anything, a
    conservative fallback (:func:`_looks_like_none_style_tag_word`) tries to
    strip a "None (space only)"-shaped leading/trailing word -- best-effort,
    since there's no delimiter and no known value to confirm it against.

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
    if stock:
        diff = strip_via_stock_diff(s, stock)
        if diff is not None:
            stock_s = unicodedata.normalize("NFKC", stock).strip()
            stock_s = _WS_RE.sub(" ", stock_s).strip()
            return BULLET_NAME_ALIASES.get(stock_s, stock_s)
    resolved = tuple(enclosings) if enclosings is not None else _DEFAULT_ENCLOSINGS
    leading_re, trailing_re = _build_tag_patterns(resolved)
    if leading_re is not None:
        s = leading_re.sub("", s)
        s = trailing_re.sub("", s)
    # The "None (space only)" heuristic runs only when a category is actually
    # configured that way -- enclosings_from_tag_configs reports that style as
    # the delimiter-less ("", "") pair. It used to run unconditionally, which
    # meant every user paid its risk for a feature only None users could use:
    # it strips a leading/trailing word containing a separator char plus an
    # "S<digits>" or lone A-F token, and real item names can take that shape
    # ("F-4 Blaster" reduces to "Blaster"). No such name is known in today's
    # data -- the real hyphenated names all carry 2-3 letter prefixes (FR-66,
    # NDB-26 Repeater, RN-7s) and are safe -- but CIG adds items constantly,
    # and two names colliding on one key is a wrong [Owned] tag on an item the
    # user does not own. Gating keeps that exposure with the setting that
    # needs it.
    if NONE_STYLE_ENCLOSING in resolved:
        s = strip_none_style_tag_heuristic(s)
    s = _TRAILING_CATEGORY_RE.sub("", s)
    s = _WS_RE.sub(" ", s).strip()
    return BULLET_NAME_ALIASES.get(s, s)


def extract_bp_item_names(
    value: str, enclosings: "Sequence[tuple[str, str]] | None" = None
) -> set[str]:
    """Return the normalized item names in *value*'s POTENTIAL BLUEPRINTS list.

    Empty when the value has no such section. Scoped to just that section's
    span (see :func:`_bp_section_span`) so a stray prose bullet before the
    header or a real bullet in a later section (ITEM REWARDS, ...) isn't
    picked up as a blueprint item. ``enclosings`` is forwarded to
    :func:`normalize_item_name` -- see its docstring.
    """
    if not value:
        return set()
    span = _bp_section_span(value)
    if span is None:
        return set()
    start, end = span
    # Normalize once per bullet, not twice. The set comprehension used to call
    # normalize_item_name in both the value and the condition; that was cheap
    # when it was two regex subs, but it now walks up to four bracket
    # alternatives, an lru_cache lookup and (when configured) the space-only
    # heuristic, on every bullet of every mission in a full rescan.
    names = (normalize_item_name(m.group(1), enclosings)
             for m in _BULLET_RE.finditer(value, start, end))
    return {n for n in names if n}


def apply_owned_to_value(
    value: str, owned: set[str], enclosings: "Sequence[tuple[str, str]] | None" = None
) -> str:
    """Return *value* with ``[Owned]`` on bullets whose item is in *owned*.

    Idempotent: any existing ``[Owned]`` tag is removed first, so the result is
    a pure function of (value, owned) and re-running never doubles the tag.
    Values without a POTENTIAL BLUEPRINTS section are returned unchanged (after
    stripping stale owned tags, in case an item was just un-owned). Retagging
    is scoped to just that section's span (see :func:`_bp_section_span`) so a
    stray prose bullet before the header or a bullet in a later section can
    never be mistaken for a blueprint item. ``enclosings`` is forwarded to
    :func:`normalize_item_name` -- see its docstring.
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
        if normalize_item_name(raw, enclosings) in owned:
            return f"{_NL}- {raw}{_OWNED_TAG}"
        return m.group(0)

    return value[:start] + _BULLET_RE.sub(_retag, value[start:end]) + value[end:]
