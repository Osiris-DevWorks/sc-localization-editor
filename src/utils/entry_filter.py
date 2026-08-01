"""Filter StringEntry lists by user-selected criteria.

Extracted from MainWindow._filtered_entry_indices so this logic can be
tested independently of Qt.
"""

import logging

from src.gui.string_table_model import NUM_COLUMNS
from src.models.string_model import StringEntry, is_favoritable_ship
from src.utils.owned_items import has_bp_section
from src.utils.ship_sort_prefix import get_order

logger = logging.getLogger(__name__)


def filter_entry_indices(
    entries: list[StringEntry],
    default_values: dict[str, str],
    column_filters: list[str],
    category_filter: str,
    status_filter: str,
    hide_unmodified: bool,
    favorites_only: bool,
    favorite_prefix: str,
    bp_titles_only: bool = False,
    bp_descs_only: bool = False,
    ship_vehicle_names_only: bool = False,
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
        favorites_only: When True, only favourited ship/vehicle NAME rows are
            shown -- i.e. a row must satisfy is_favoritable_ship AND carry
            favorite_prefix on its custom_value. The ship-row half was added
            in #329: previously any row whose custom_value merely started
            with the prefix passed, so a non-Ships row a user had happened
            to start with "*" showed up as a "favourite" it could never
            actually have been (the star column never rendered for it, and
            neither the star click nor the context menu would toggle it).
        favorite_prefix: The prefix that marks a row as a favourite.
        bp_titles_only: When True, keep mission-title rows carrying the
            [BP] / [BP?] blueprint tag (#156).
        bp_descs_only: When True, keep mission-description rows containing the
            POTENTIAL BLUEPRINTS section (#156). When both bp_* flags are set
            the row passes if it matches EITHER (blueprint titles OR bodies).
        ship_vehicle_names_only: When True, show ONLY ship/vehicle name rows
            (vehicle_Name*, Wikelo *_VehicleName) -- every other row is
            hidden, including ship description rows and every non-Ships
            category (#329). Narrows the table to exactly the rows the
            favorite / ASOP sort-order mechanism reads.

    Returns:
        Ordered list of integer indices into *entries* for rows that should
        be visible.
    """
    # Validate column indices once. Stale filters (e.g. after a column layout
    # change) would cause IndexError inside the per-entry loop below; drop
    # them here and log once instead.
    valid_col_filters: list[tuple[int, str]] = []
    bad_indices: list[int] = []
    for i, t in enumerate(column_filters):
        if not t:
            continue
        if i < NUM_COLUMNS:
            valid_col_filters.append((i, t))
        else:
            bad_indices.append(i)
    if bad_indices:
        logger.warning(
            "Column filter indices out of range for %d-column table — skipped: %s",
            NUM_COLUMNS,
            bad_indices,
        )

    # Per-column value getters. Indices match the COL_* constants in
    # string_table_model. Closures over default_values / favorite_prefix —
    # safe because both are parameters, not loop variables.
    _col_getters = (
        lambda e: e.category.lower(),
        lambda e: e.key.lower(),
        lambda e: default_values.get(e.key, "").lower(),
        lambda e: e.original_value.lower(),
        lambda e: (
            "★"
            if is_favoritable_ship(e) and e.custom_value.startswith(favorite_prefix)
            else ""
        ),
        lambda e: (
            get_order(e.custom_value, favorite_prefix)
            if is_favoritable_ship(e) else ""
        ),
        lambda e: e.custom_value.lower(),
        lambda e: e.status.lower(),
        # COL_OWNED (#157): the owned star isn't text-filterable from here (the
        # owned set lives on the model), so this getter just keeps the tuple
        # aligned with NUM_COLUMNS for the drift guard. Blueprint filtering is
        # covered by the dedicated BP filters (#156).
        lambda e: "",
    )
    active_filter_fns = [(_col_getters[i], t) for i, t in valid_col_filters]

    result: list[int] = []
    for idx, entry in enumerate(entries):
        if hide_unmodified and entry.status == "Unmodified":
            continue
        if category_filter != "All" and entry.category != category_filter:
            continue
        if status_filter != "All" and entry.status != status_filter:
            continue
        if ship_vehicle_names_only and not is_favoritable_ship(entry):
            continue
        if favorites_only and not (
            is_favoritable_ship(entry)
            and entry.custom_value.startswith(favorite_prefix)
        ):
            continue
        # #156: blueprint-mission isolation. [BP]/[BP?] tags live on title
        # rows; the POTENTIAL BLUEPRINTS header lives on description rows. The
        # effective value (user override if any, else the merged baseline that
        # carries the enhancement) is what's shown, so test that.
        if bp_titles_only or bp_descs_only:
            val = entry.custom_value or entry.original_value
            is_bp_title = bp_titles_only and "[BP" in val
            is_bp_desc = bp_descs_only and has_bp_section(val)
            if not (is_bp_title or is_bp_desc):
                continue
        if active_filter_fns:
            skip = False
            for get_val, filter_text in active_filter_fns:
                if filter_text not in get_val(entry):
                    skip = True
                    break
            if skip:
                continue
        result.append(idx)

    return result
