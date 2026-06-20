"""Pure helpers for ship-name sort prefixes (favorite marker + sort-order number).

Smart Citizen lets a user mark a ship as a favorite (a configurable prefix,
default ``*``) and assign it a two-digit sort-order number. Both ride in the
ship's ``custom_value`` so they prepend to the in-game display name and control
ASOP ordering: the favorite prefix comes first, then the zero-padded number, a
``-`` separator, and the name (e.g. ``*05-Avenger``). The number is zero-padded
to two digits so ASOP's lexicographic sort orders ``01 < 02 < ... < 10``
correctly (issue #142).

Why the ``-`` separator: many Star Citizen ships have names that *start with
two digits* (300i, 600i, 890 Jump, 100i, 85X, 990, 125a, ...). Without a
separator, the parser cannot tell a user-assigned sort number from a ship whose
name simply begins with digits, so ``300i`` was misread as order ``30`` and
editing that order chopped the leading digits off the real name (``*300i`` ->
``*0i``). Requiring the order token to be ``two digits + "-"`` makes the value
self-describing: a bare numeric name has no separator, so it is never read as an
order, and its digits are never stripped.

Qt-free so it can be unit-tested without a QApplication.
"""
from __future__ import annotations

import re

# Separator between the sort-order number and the rest of the name. Visible
# in-game (e.g. ``05-Avenger``); chosen so a ship name that starts with digits
# can't be mistaken for an order token.
SEPARATOR = "-"

# A sort-order token is exactly two leading digits FOLLOWED BY the separator,
# sitting after any favorite prefix. A name like "300i" or "890 Jump" has no
# separator after its leading digits, so it is correctly read as "no order".
_ORDER_RE = re.compile(r"(\d{2})" + re.escape(SEPARATOR))

# Validates/normalizes a raw order value supplied by the spin box (the number
# itself, with no separator).
_TWO_DIGITS = re.compile(r"\d{2}")

ORDER_NONE = ""


def get_order(custom_value: str, favorite_prefix: str) -> str:
    """Return the two-digit sort-order prefix on *custom_value*, or "".

    Skips a leading favorite prefix first, then reads a ``NN-`` order token.
    The separator is required, so a ship whose name starts with digits (300i,
    890 Jump) reports no order.
    """
    body = custom_value
    if favorite_prefix and body.startswith(favorite_prefix):
        body = body[len(favorite_prefix):]
    m = _ORDER_RE.match(body)
    return m.group(1) if m else ORDER_NONE


def set_order(
    custom_value: str,
    original_value: str,
    favorite_prefix: str,
    order: str,
) -> str:
    """Return *custom_value* with its sort-order set to *order* ("" clears it).

    The favorite prefix (when present) stays first; the order number and its
    ``-`` separator sit between it and the rest of the name, so we never produce
    ``01*Avenger`` or strip digits from a numeric ship name. Mirrors
    ``toggle_favorite``'s collapse rule: if the result is just the unmodified
    original name with no prefixes, return "" so the entry's status falls back
    to Unmodified.
    """
    # Split off a leading favorite prefix so the order lands behind it.
    has_fav = bool(favorite_prefix) and custom_value.startswith(favorite_prefix)
    body = custom_value[len(favorite_prefix):] if has_fav else custom_value

    # Strip an existing "NN-" order token from the front of the body. A bare
    # numeric name (no separator) doesn't match, so its digits are preserved.
    m = _ORDER_RE.match(body)
    if m:
        body = body[m.end():]

    # Anchor the prefixes to the user's custom name, or the stock value when
    # there's nothing custom left to carry them.
    base = body if body else original_value

    order = order or ""
    if order and not _TWO_DIGITS.fullmatch(order):
        # Normalize any stray input to a zero-padded two-digit string.
        order = f"{int(order):02d}"

    fav = favorite_prefix if has_fav else ""
    if order:
        result = f"{fav}{order}{SEPARATOR}{base}"
    else:
        result = f"{fav}{base}"

    # Collapse to empty when nothing distinguishes the result from the stock
    # value, so the row's status returns to Unmodified.
    return "" if result == original_value else result
