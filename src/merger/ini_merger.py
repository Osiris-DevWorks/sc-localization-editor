"""INI file merger for combining base and custom strings."""

import logging
from collections import defaultdict
from functools import cache
from pathlib import Path

from src.utils.perf import timed

logger = logging.getLogger(__name__)

# Component type codes used to canonicalize item_name*/item_desc* key variants.
# Hoisted to module scope so _get_canonical_key doesn't rebuild this list on
# each of its ~87k calls per merge. Kept as a tuple for both the C-level
# ``any(code in …)`` membership check and the sequential ``.replace()`` pass
# (order-sensitive by design — see the function comment).
_COMPONENT_CODES = ("shld", "powr", "cool", "qdrv", "jump", "misl", "gmisl", "bomb")


@timed
def merge_sources_by_hierarchy(
    sources_dict: dict[str, dict[str, str]], hierarchy: list[str], user_overrides: dict[str, str] | None = None
) -> dict[str, str]:
    """Merge multiple INI sources in specified hierarchy order.

    Sources earlier in hierarchy have lower priority. Sources later in hierarchy
    overwrite earlier ones. User overrides (if provided) always have highest priority
    and are applied last.

    Syncs values across key variants (e.g., item_Name_QDRV_RSI_S02_Hemera and
    item_nameQDRV_RSI_S02_Hemera_SCItem get the same value).

    Args:
        sources_dict: Dictionary mapping source name to its key-value pairs.
                     e.g., {"global": {"key1": "val1", ...}, "contracts": {...}}
        hierarchy: Ordered list of source names to merge in order.
                  e.g., ["global", "contracts", "components"]
                  Earlier = lower priority, later = higher priority
        user_overrides: Optional dict of user edits (highest priority).
                       Applied last, overwrites all other sources.

    Returns:
        Merged dictionary with final values from all sources applied in order,
        with variant keys synced to have matching values.

    Example:
        >>> sources = {
        ...     "global": {"key1": "base_val", "key2": "val2"},
        ...     "contracts": {"key1": "override_val", "key3": "val3"},
        ...     "components": {"key4": "val4"}
        ... }
        >>> hierarchy = ["global", "contracts", "components"]
        >>> user = {"key1": "user_val"}
        >>> result = merge_sources_by_hierarchy(sources, hierarchy, user)
        >>> result["key1"]
        'user_val'  # User override always wins
        >>> result["key3"]
        'val3'      # From contracts (overrides global)
        >>> result["key2"]
        'val2'      # From global (only source for this key)
    """
    result: dict[str, str] = {}

    # dict.update() is a C-level bulk copy — semantically identical to the
    # previous Python loop (later sources overwrite earlier ones) but
    # significantly faster for the ~87k-key base.ini on each Load / Apply.
    for source_name in hierarchy:
        if source_name in sources_dict:
            result.update(sources_dict[source_name])

    # Apply user overrides last (highest priority)
    if user_overrides:
        result.update(user_overrides)

    # Sync values across key variants (e.g., item_Name_QDRV vs item_nameQDRV_SCItem)
    sync_key_variants(result)

    return result


@cache
def _get_canonical_key(key: str) -> str:
    """Get the canonical form of a key for variant matching.

    Variant keys like:
      - item_Name_QDRV_RSI_S02_Hemera
      - item_nameQDRV_RSI_S02_Hemera_SCItem

    Both normalize to: item_name_qdrv_rsi_s02_hemera

    Steps:
    1. Remove _SCItem suffix (case-insensitive)
    2. Lowercase
    3. Remove underscores
    4. Insert underscores only before SHLD/POWR/COOL/QDRV/JUMP/MISL/GMISL/BOMB component codes

    Fast paths:
    - Cached via lru_cache — Load populates it, Apply reuses it for the
      same merged dict.
    - ~98% of keys in a real base.ini contain no component code at all, so
      the 8 sequential replaces + the split/join cleanup are skipped after
      the underscore strip. The remaining ~2% take the full canonicalization
      pass with identical semantics to the original (order-sensitive replace
      preserved).
    """
    # Remove _SCItem suffix (case-insensitive). Avoid the ``key.lower()`` call
    # on the happy path where the suffix isn't present by checking length +
    # the common uppercase variant first.
    if len(key) >= 7 and key[-7:].lower() == "_scitem":
        key = key[:-7]

    key = key.lower()
    key_no_underscore = key.replace("_", "")

    # Fast path: check for component codes AFTER underscore stripping — a code
    # can hide across an underscore boundary in the original (e.g.
    # ``powpow_reaction`` → after strip ``powpowreaction`` which contains
    # ``powr``). The happy path is ~98% of real keys; in that case the
    # sequential replace loop is a no-op and the final split/join is just an
    # identity on a string that has no remaining underscores.
    if not any(c in key_no_underscore for c in _COMPONENT_CODES):
        return key_no_underscore

    for comp in _COMPONENT_CODES:
        key_no_underscore = key_no_underscore.replace(comp, f"_{comp}")

    # Clean up: replace multiple underscores with single, strip leading underscore
    return "_".join(p for p in key_no_underscore.split("_") if p)


@timed
def sync_key_variants(merged_dict: dict[str, str]) -> None:
    """Sync values across key variants in a merged dictionary.

    If item_Name_QDRV_RSI_S02_Hemera has value X, then
    item_nameQDRV_RSI_S02_Hemera_SCItem also gets value X.

    The non-_SCItem variant is treated as authoritative. If variants carry
    different values (unexpected after a clean hierarchy merge), a warning is
    logged so the discrepancy is visible rather than silently discarded.

    This modifies merged_dict in-place.

    Args:
        merged_dict: Dictionary of keys to values from merged sources
    """
    # Build canonical → [actual_keys] map.
    # defaultdict avoids the double-lookup (check + set) of the manual approach.
    # Iterate merged_dict directly — no need for list() copy since we're only reading keys here.
    canonical_keys: dict[str, list[str]] = defaultdict(list)
    for key in merged_dict:
        canonical_keys[_get_canonical_key(key)].append(key)

    for canonical, variants in canonical_keys.items():
        if len(variants) <= 1:
            continue

        # Prefer non-_SCItem variant as the authoritative value;
        # fall back to first variant if all have the _SCItem suffix.
        preferred_key = next(
            (v for v in variants if not v.lower().endswith("_scitem")),
            variants[0],
        )
        synced_value = merged_dict[preferred_key]

        # Detect conflicts — after a clean hierarchy merge all variants should
        # already agree. Log a warning when they don't so the discrepancy is
        # visible in the log tab rather than silently lost.
        if any(merged_dict[v] != synced_value for v in variants):
            details = "; ".join(f"{v!r}={merged_dict[v]!r}" for v in variants)
            logger.warning(
                "Variant value conflict for canonical key %r — choosing %r=%r. All variants: %s",
                canonical,
                preferred_key,
                synced_value,
                details,
            )

        for var in variants:
            merged_dict[var] = synced_value


@timed
def merge_ini_files(source_path: str | Path, overrides_dict: dict[str, str], output_path: str | Path) -> None:
    """Merge source INI with overrides, preserving all lines.

    Reads source file line-by-line, replaces values for matching keys,
    and writes to output as UTF-8. Strips comma-based metadata suffixes
    (e.g., "key,P") from keys to match normalized override keys.

    Note: Variant key syncing happens in merge_sources_by_hierarchy(), so
    the overrides_dict already has synced values when this is called.

    Args:
        source_path: Path to base file (base.ini or game's global.ini)
        overrides_dict: Dictionary of key-value overrides (with clean keys, already synced)
        output_path: Path to write merged output
    """
    source_path = Path(source_path)
    output_path = Path(output_path)

    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(source_path, encoding="utf-8") as infile, open(output_path, "w", encoding="utf-8") as outfile:
            for line in infile:
                # Preserve line ending style, but work with stripped version
                line_rstrip = line.rstrip("\n\r")
                original_ending = line[len(line_rstrip) :]

                # Skip processing for comments and empty lines
                if not line_rstrip.strip() or line_rstrip.strip().startswith(";"):
                    outfile.write(line)
                    continue

                # Try to split on first '='
                if "=" not in line_rstrip:
                    outfile.write(line)
                    continue

                key, value = line_rstrip.split("=", 1)
                key_stripped = key.strip()

                # Strip comma-based metadata suffix (e.g., "key,P" → "key")
                # This ensures keys from different sources match up correctly
                clean_key = key_stripped.split(",")[0].strip()

                # Check if we have an override for this key (using clean key)
                if clean_key in overrides_dict:
                    # Replace value with override, using clean key without metadata
                    new_value = overrides_dict[clean_key]
                    new_line = f"{clean_key}={new_value}{original_ending}"
                    outfile.write(new_line)
                else:
                    # Keep original line (but with clean key, no metadata)
                    new_line = f"{clean_key}={value}{original_ending}"
                    outfile.write(new_line)

    except Exception as e:
        raise OSError(f"Error merging INI files: {e}")
