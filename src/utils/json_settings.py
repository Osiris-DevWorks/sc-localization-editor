"""JSON-file backend mirroring the QSettings API surface AppSettings uses.

PR-A in the standalone-build series. Lands the backend abstraction with
zero behavior change to the registry path: AppSettings continues to
return a QSettings by default. The JsonSettings backend defined here is
the foundation for a portable build that writes to a JSON file alongside
the .exe instead of HKEY_CURRENT_USER. PR-B wires the path-routing,
PR-C wires the build flag.

Why a custom backend instead of just QSettings(IniFormat)?
- QSettings(IniFormat, "/path/to/file.ini") IS a built-in option. We're
  not using it because:
    (a) QSettings's INI writer mangles slash-prefixed keys (it treats
        them as path separators producing nested groups, then can't
        round-trip them) — and AppSettings uses keys like
        ``enhancements/categories/foo/enabled``.
    (b) JSON is easier for users to inspect / hand-edit when something
        goes wrong, and easier for us to write deterministic tests
        against.
- The full QSettings API is huge; AppSettings only uses 4 methods
  (``value`` / ``setValue`` / ``remove`` / ``sync``), so a focused shim
  is small and obvious.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Sentinel for "no default provided" so we can distinguish
# ``value(key)`` (returns None on miss) from ``value(key, "")``
# (returns "" on miss). QSettings's behavior is the same.
_MISSING = object()


class JsonSettings:
    """File-backed key-value store with QSettings-compatible semantics.

    Thread-safe: all read/write paths take a lock. AppSettings is called
    from both the main thread and worker threads, so this matters even
    in the typical single-process portable scenario.

    Persists immediately on every ``setValue`` / ``remove`` (no batching)
    so a crash mid-session doesn't lose user-visible settings. The cost
    is one file write per setting change — fine for a settings store
    (writes are infrequent, <1KB typical).
    """

    def __init__(self, file_path: Path):
        self._path = Path(file_path)
        self._lock = threading.RLock()
        self._data: dict[str, Any] = {}
        self._load()

    # ── Loading + persistence ────────────────────────────────────────

    def _load(self) -> None:
        """Read the JSON file into ``self._data``. Missing / unreadable
        files start empty — same forgiving semantics as QSettings on a
        registry tree that doesn't exist yet."""
        if not self._path.exists():
            return
        try:
            with self._path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
            else:
                logger.warning(
                    "JsonSettings file %s did not contain a JSON object "
                    "(got %s); starting empty",
                    self._path, type(loaded).__name__,
                )
        except (OSError, ValueError) as e:
            # ValueError, not just JSONDecodeError: a settings.json whose
            # bytes are corrupt raises UnicodeDecodeError during the read —
            # a ValueError but NOT a JSONDecodeError — which previously
            # escaped this guard and crashed the portable app at startup
            # (#251 bug class). JSONDecodeError is itself a ValueError, so
            # this catches both.
            logger.warning(
                "JsonSettings could not load %s (%s); starting empty",
                self._path, e,
            )

    def _persist(self) -> None:
        """Write ``self._data`` to disk. Atomic via tmp + rename so a
        crash mid-write doesn't truncate the file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, sort_keys=True, ensure_ascii=False)
            tmp.replace(self._path)
        except (OSError, TypeError, ValueError) as e:
            # OSError: disk/IO. TypeError/ValueError: a non-JSON-serialisable
            # value reached the store (e.g. a QByteArray). Degrade to "not
            # persisted" with a warning rather than crashing the app — a write
            # on close must never take the process down (#141). The real file
            # is left untouched because the rename only happens after a clean
            # dump, so the store stays consistent.
            logger.warning("JsonSettings could not write %s: %s", self._path, e)
            # Best-effort cleanup of the tmp file.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # ── QSettings-compatible API ─────────────────────────────────────

    def value(self, key: str, default: Any = _MISSING, type: type | None = None) -> Any:  # noqa: A002 — name matches QSettings
        """Read a value. Mirrors ``QSettings.value(key, default, type=...)``.

        When ``type`` is provided, the stored value is coerced to that
        type. Currently only ``bool`` and ``str`` are needed by
        AppSettings (verified via grep over settings.py). Other types
        fall through with a best-effort ``type()`` call.

        Bool coercion specifically must handle the QSettings quirk
        where stored booleans round-trip as the strings "true" / "false"
        through some serialization paths — JSON natively stores True /
        False, but the type=bool flag should still produce a Python
        bool from a string sentinel for parity.
        """
        with self._lock:
            if key in self._data:
                raw = self._data[key]
            elif default is _MISSING:
                return None
            else:
                raw = default

        if type is None:
            return raw
        if type is bool:
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, str):
                return raw.strip().lower() in ("true", "1", "yes", "on")
            return bool(raw)
        if type is str:
            return "" if raw is None else str(raw)
        # Best-effort fallback for any other requested type.
        try:
            return type(raw)
        except (TypeError, ValueError):
            return raw

    def setValue(self, key: str, value: Any) -> None:  # noqa: N802 — name matches QSettings
        """Set + persist a value. JSON-serialisable values only — Python
        primitives, lists, dicts. AppSettings stores str / bool / int
        exclusively (verified via grep), so this is fine in practice."""
        with self._lock:
            self._data[key] = value
            self._persist()

    def remove(self, key: str) -> None:
        """Delete a key. Silent no-op if not present (QSettings parity)."""
        with self._lock:
            if key in self._data:
                del self._data[key]
                self._persist()

    def sync(self) -> None:
        """Flush pending writes. We persist on every setValue / remove,
        so this is a no-op — kept for API parity with QSettings since
        AppSettings calls it after batched mutations."""
        # No batching, so nothing to flush.
        pass

    # ── Test / debug helpers (not part of the QSettings API) ─────────

    def file_path(self) -> Path:
        """Return the on-disk path. Useful for log messages and tests."""
        return self._path

    def keys(self) -> list[str]:
        """Snapshot of stored keys. Used by tests; not part of the
        AppSettings call surface."""
        with self._lock:
            return list(self._data.keys())
