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

# Marks the start of a POTENTIAL BLUEPRINTS section. The header text is
# user-configurable (AppSettings.MISSION_HEADER_DEFAULTS["blueprints"]) but the
# default is BP_SECTION_HEADER; we match that default case-insensitively. This
# module stays settings-free by design, so it owns the default literal rather
# than importing AppSettings, and the settings default is kept in sync with it.
# blueprint_meta.py and entry_filter.py import BP_SECTION_HEADER from here so
# the three matchers share one source of truth. A value with no such header has
# no bullets to tag, so it passes through untouched.
BP_SECTION_HEADER = "POTENTIAL BLUEPRINTS"
_BP_HEADER_RE = re.compile(BP_SECTION_HEADER, re.IGNORECASE)


def normalize_item_name(name: str) -> str:
    """Reduce a bullet/name to a stable identity for matching.

    Strips a leading component tag (``[Mil-S1-A] Norfield`` -> ``Norfield``),
    any ``[Owned]`` tag, and surrounding whitespace. Used for both the owned
    set and bullet matching so a tagged bullet matches its bare item row.
    """
    if not name:
        return ""
    s = _OWNED_STRIP_RE.sub("", name)
    s = _LEADING_TAG_RE.sub("", s)
    return s.strip()


def extract_bp_item_names(value: str) -> set[str]:
    """Return the normalized item names in *value*'s POTENTIAL BLUEPRINTS list.

    Empty when the value has no such section.
    """
    if not value or not _BP_HEADER_RE.search(value):
        return set()
    return {normalize_item_name(m.group(1)) for m in _BULLET_RE.finditer(value)
            if normalize_item_name(m.group(1))}


def apply_owned_to_value(value: str, owned: set[str]) -> str:
    """Return *value* with ``[Owned]`` on bullets whose item is in *owned*.

    Idempotent: any existing ``[Owned]`` tag is removed first, so the result is
    a pure function of (value, owned) and re-running never doubles the tag.
    Values without a POTENTIAL BLUEPRINTS section are returned unchanged (after
    stripping stale owned tags, in case an item was just un-owned).
    """
    if not value:
        return value
    # Strip any prior owned tags first (handles un-owning + idempotency).
    value = _OWNED_STRIP_RE.sub("", value)
    if not owned or not _BP_HEADER_RE.search(value):
        return value

    def _retag(m: re.Match) -> str:
        raw = m.group(1)
        if normalize_item_name(raw) in owned:
            return f"{_NL}- {raw}{_OWNED_TAG}"
        return m.group(0)

    return _BULLET_RE.sub(_retag, value)
