"""Export/import owned blueprints as JSON or CSV.

Qt-free (file dialogs and QMessageBox summaries live in
blueprint_tracker_tab.py) so the format handling and name-matching logic can
be unit-tested directly.

The JSON shape structurally matches SCMDB's own export (version / exportedAt
/ missions / blueprints[]) for compatibility with tools that already read
that format, but Smart Citizen has no real value for SCMDB's per-item "tag"
/ "url" fields (those are SCMDB's own item identifiers), so they're omitted
rather than faked. "missions" stays an empty list -- Smart Citizen tracks
blueprint ownership, not mission completion, so there's nothing real to put
there either.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

from src.utils.owned_items import normalize_item_name

_FORMAT_VERSION = 1


class InvalidImportFileError(ValueError):
    """Raised when an import file isn't a JSON or CSV blueprint export."""


def export_owned_blueprints_json(owned: "set[str]", blueprint_meta: dict) -> str:
    """Return a JSON string listing every owned blueprint.

    *blueprint_meta* is ``{name: BlueprintItem}`` (see blueprint_meta.py) --
    only used here to prefer each item's tagged display name over the bare
    match key, matching what the Blueprint Tracker itself shows.
    """
    blueprints = []
    for name in sorted(owned, key=str.lower):
        item = blueprint_meta.get(name)
        display_name = item.tagged_name if item and item.tagged_name else name
        blueprints.append({
            "name": display_name,
            "completed": True,
            "favorite": False,
        })
    payload = {
        "version": _FORMAT_VERSION,
        "exportedAt": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "missions": [],
        "blueprints": blueprints,
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def export_owned_blueprints_csv(owned: "set[str]", blueprint_meta: dict) -> str:
    """Return a CSV string (name, type) listing every owned blueprint."""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["name", "type"])
    for name in sorted(owned, key=str.lower):
        item = blueprint_meta.get(name)
        display_name = item.tagged_name if item and item.tagged_name else name
        item_type = item.type if item else ""
        writer.writerow([display_name, item_type])
    return buf.getvalue()


def parse_import_names(
    path: "str | Path", enclosings=None
) -> "set[str]":
    """Return the normalized item names listed in a JSON or CSV import file.

    Accepts both our own export shape and a genuine SCMDB export (both key
    each entry's display name as "name"), plus a plain CSV with a "name"
    column. Raises InvalidImportFileError for anything else (wrong
    extension, malformed JSON, missing "name" column, or a CSV that isn't
    valid UTF-8 -- plausible for a file saved from Excel on Windows, which
    defaults to cp1252/Latin-1) so the caller can show one clear error
    rather than a confusing traceback.

    ``enclosings`` is forwarded to ``normalize_item_name`` (#352) -- the set
    of (open, close) Tag Builder delimiter pairs to recognize. Defaults to
    Square only when omitted, matching this function's original behavior.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_import_names_json(path, enclosings)
    if suffix == ".csv":
        return _parse_import_names_csv(path, enclosings)
    raise InvalidImportFileError(f"Unsupported file type: {suffix or '(none)'}")


def _parse_import_names_json(path: Path, enclosings=None) -> "set[str]":
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise InvalidImportFileError(f"Could not read JSON file: {e}") from e
    blueprints = data.get("blueprints") if isinstance(data, dict) else None
    if not isinstance(blueprints, list):
        raise InvalidImportFileError('JSON file has no "blueprints" array')
    names: set[str] = set()
    for entry in blueprints:
        if not isinstance(entry, dict):
            continue
        nm = normalize_item_name(str(entry.get("name") or ""), enclosings)
        if nm:
            names.add(nm)
    return names


def _parse_import_names_csv(path: Path, enclosings=None) -> "set[str]":
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or "name" not in reader.fieldnames:
                raise InvalidImportFileError('CSV file has no "name" column')
            names: set[str] = set()
            for row in reader:
                nm = normalize_item_name(row.get("name") or "", enclosings)
                if nm:
                    names.add(nm)
    except (OSError, UnicodeDecodeError) as e:
        raise InvalidImportFileError(f"Could not read CSV file: {e}") from e
    return names


def match_import_names(
    imported: "set[str]", known: "set[str]", enclosings=None
) -> "tuple[set[str], set[str]]":
    """Split *imported* into (matched, unmatched) against *known* item names.

    *imported* is already normalized (parse_import_names runs every name
    through normalize_item_name). *known* -- the Blueprint Tracker's own
    dict keys -- is not, so this normalizes a working copy of *known* here
    rather than assuming the caller already did (a bare set intersection
    would silently break normalize_item_name's own documented invariant:
    "both sides... so the folding is symmetric and can never introduce a
    one-sided mismatch"). Currently a no-op for every real blueprint name
    in the data (none contain brackets, tags, or annotations that
    normalize_item_name would strip), but the asymmetry is real and cheap
    to close, so there's no reason to leave it latent.

    *matched* returns *known*'s original (unnormalized) names, not the
    normalized form used for comparison -- callers persist these into the
    Owned set, which must stay keyed exactly as the Blueprint Tracker's own
    dict, or a subsequent blueprint_meta.get(name) lookup (e.g. in export)
    would silently miss.

    ``enclosings`` is forwarded to ``normalize_item_name`` (#352), same
    default as :func:`parse_import_names`.
    """
    known_by_normalized: dict = {}
    for name in known:
        known_by_normalized.setdefault(normalize_item_name(name, enclosings), name)
    matched = {known_by_normalized[nm] for nm in imported if nm in known_by_normalized}
    unmatched = imported - known_by_normalized.keys()
    return matched, unmatched
