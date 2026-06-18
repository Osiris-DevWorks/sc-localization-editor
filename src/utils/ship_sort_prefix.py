"""Pure helpers for ship-name sort prefixes (favorite marker + sort-order number).

Smart Citizen lets a user mark a ship as a favorite (a configurable prefix,
default ``*``) and assign it a two-digit sort-order number. Both ride in the
ship's ``custom_value`` so they prepend to the in-game display name and control
ASOP ordering: the favorite prefix comes first, then the zero-padded number
(e.g. ``*01Avenger``). The number is zero-padded to two digits so ASOP's
lexicographic sort orders ``01 < 02 < ... < 10`` correctly (issue #142).

Qt-free so it can be unit-tested without a QApplication.
"""
from __future__ import annotations

import re

# A sort-order token is exactly two leading digits, sitting after any favorite
# prefix. Single digits, three+ digit runs, and non-digits are "no order".
_ORDER_RE = re.compile(r"\d{2}")

ORDER_NONE = ""


def get_order(custom_value: str, favorite_prefix: str) -> str:
    """Return the two-digit sort-order prefix on *custom_value*, or "".

    Skips a leading favorite prefix first, then reads a two-digit run.
    """
    body = custom_value
    if favorite_prefix and body.startswith(favorite_prefix):
        body = body[len(favorite_prefix):]
    m = _ORDER_RE.match(body)
    return m.group(0) if m else ORDER_NONE


def set_order(
    custom_value: str,
    original_value: str,
    favorite_prefix: str,
    order: str,
) -> str:
    """Return *custom_value* with its sort-order set to *order* ("" clears it).

    The favorite prefix (when present) stays first; the order number sits
    between it and the rest of the name, so we never produce ``01*Avenger``.
    Mirrors ``toggle_favorite``'s collapse rule: if the result is just the
    unmodified original name with no prefixes, return "" so the entry's status
    falls back to Unmodified.
    """
    # Split off a leading favorite prefix so the order lands behind it.
    has_fav = bool(favorite_prefix) and custom_value.startswith(favorite_prefix)
    body = custom_value[len(favorite_prefix):] if has_fav else custom_value

    # Strip an existing two-digit order from the front of the body.
    m = _ORDER_RE.match(body)
    if m:
        body = body[m.end():]

    # Anchor the prefixes to the user's custom name, or the stock value when
    # there's nothing custom left to carry them.
    base = body if body else original_value

    order = order or ""
    if order and not _ORDER_RE.fullmatch(order):
        # Normalize any stray input to a zero-padded two-digit string.
        order = f"{int(order):02d}"

    fav = favorite_prefix if has_fav else ""
    result = f"{fav}{order}{base}"

    # Collapse to empty when nothing distinguishes the result from the stock
    # value, so the row's status returns to Unmodified.
    return "" if result == original_value else result
