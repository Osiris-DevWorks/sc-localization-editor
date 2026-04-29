"""Filter StringEntry lists by user-selected criteria.

Extracted from MainWindow._filtered_entry_indices so this logic can be
tested independently of Qt.
"""

from src.models.string_model import StringEntry


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
        elif active_col_filters:
            row_values = [
                entry.category.lower(),
                entry.key.lower(),
                default_values.get(entry.key, "").lower(),
                entry.original_value.lower(),
                "★" if entry.custom_value.startswith(favorite_prefix) else "",
                entry.custom_value.lower(),
                entry.status.lower(),
            ]
            for col, filter_text in active_col_filters:
                if filter_text not in row_values[col]:
                    show = False
                    break

        if show:
            result.append(idx)

    return result
