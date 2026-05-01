"""Filter StringEntry lists by user-selected criteria.

Extracted from MainWindow._filtered_entry_indices so this logic can be
tested independently of Qt.
"""

import logging

from src.models.string_model import StringEntry

logger = logging.getLogger(__name__)

# Number of columns in the row_values list built inside filter_entry_indices.
# Category / Key / Default Value / Original Value / Fav-star / Custom Value / Status
_NUM_FILTER_COLUMNS = 7


def filter_entry_indices(
    entries: list[StringEntry],
    default_values: dict[str, str],
    column_filters: list[str],
    category_filter: str,
    status_filter: str,
    hide_unmodified: bool,
    favorites_only: bool,
    favorite_prefix: str,
) -> list[int]:
    """Return indices of entries that pass all active filters.

    Args:
        entries: The full list of StringEntry objects.
        default_values: Mapping of key → stock base.ini value (for the
            Default Value column filter).
        column_filters: Per-column filter texts in column order.
            Empty strings mean "no filter for this column".
        category_filter: Category name to filter by, or "All".
        status_filter: Status name to filter by, or "All".
        hide_unmodified: When True, entries with status "Unmodified" are hidden.
        favorites_only: When True, only entries whose custom_value starts with
            favorite_prefix are shown.
        favorite_prefix: The prefix that marks a row as a favourite.

    Returns:
        Ordered list of integer indices into *entries* for rows that should
        be visible.
    """
    active_col_filters = [(i, t) for i, t in enumerate(column_filters) if t]

    # Validate column indices once, before the hot per-entry loop.
    # Stale filters (e.g. after a column layout change) would cause IndexError
    # inside the loop; drop them here and log once instead.
    valid_col_filters = [(i, t) for i, t in active_col_filters if i < _NUM_FILTER_COLUMNS]
    if len(valid_col_filters) != len(active_col_filters):
        bad_indices = [i for i, _ in active_col_filters if i >= _NUM_FILTER_COLUMNS]
        logger.warning(
            "Column filter indices out of range for %d-column table — skipped: %s",
            _NUM_FILTER_COLUMNS,
            bad_indices,
        )
        active_col_filters = valid_col_filters

    # Pre-resolve each active column filter to a (value_getter, text) pair.
    # Built once per call, amortised over all ~87k entries: the per-entry loop
    # then calls only the getters for columns that are actually filtered rather
    # than constructing a full 7-element list for every entry.
    # Getters close over default_values / favorite_prefix — safe because both
    # are parameters, not loop variables.
    if active_col_filters:
        _col_getters: tuple = (
            lambda e: e.category.lower(),
            lambda e: e.key.lower(),
            lambda e: default_values.get(e.key, "").lower(),
            lambda e: e.original_value.lower(),
            lambda e: "★" if e.custom_value.startswith(favorite_prefix) else "",
            lambda e: e.custom_value.lower(),
            lambda e: e.status.lower(),
        )
        active_filter_fns: list = [(_col_getters[i], t) for i, t in active_col_filters]
    else:
        active_filter_fns = []

    result: list[int] = []

    for idx, entry in enumerate(entries):
        show = True

        if hide_unmodified and entry.status == "Unmodified":
            show = False
        elif category_filter != "All" and entry.category != category_filter:
            show = False
        elif status_filter != "All" and entry.status != status_filter:
            show = False
        elif favorites_only and not entry.custom_value.startswith(favorite_prefix):
            show = False
        elif active_filter_fns:
            for get_val, filter_text in active_filter_fns:
                if filter_text not in get_val(entry):
                    show = False
                    break

        if show:
            result.append(idx)

    return result
