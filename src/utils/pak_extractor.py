"""Extracts files from Star Citizen's Data.p4k using bundled unp4k.exe."""
import gc
import logging
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from src.utils.perf import timed

from src.utils.dataforge_diff import update_manifest
from src.utils.i18n import tr
from src.utils.win_paths import win_long_path as _win_long_path

logger = logging.getLogger(__name__)

# DataForge-cache freshness stamps, written after extraction and read by
# dataforge_cache_is_fresh. Size is the primary signal (#209); mtime is the
# legacy fallback for caches written before the size stamp existed.
P4K_MTIME_STAMP = ".p4k_mtime"
P4K_SIZE_STAMP = ".p4k_size"

# ``shutil.rmtree`` replaced ``onerror`` with ``onexc`` in Python 3.12. The
# frozen build runs on 3.11, so passing ``onexc=`` raises TypeError there.
# Detect once at import.
_RMTREE_CB_KWARG = "onexc" if sys.version_info >= (3, 12) else "onerror"

# The RSI Launcher holds an exclusive lock on Data.p4k while it downloads or
# verifies a game update, so unp4k (which opens Data.p4k directly) dies with a
# .NET IOException whose message contains "being used by another process"
# (exit code 0xE0434352 = 3762504530, the generic managed-exception code — so
# the message text, not the code, is the reliable signal). Detect it and give
# the user a plain "your install is updating, wait and retry" hint instead of
# a raw stack trace.
_P4K_LOCKED_SIGNATURE = "being used by another process"


class P4kLockedError(RuntimeError):
    """Data.p4k is locked by another process (RSI Launcher updating/verifying).

    A RuntimeError subclass, not a plain RuntimeError, so P4kExtractWorker /
    DataForgeExtractWorker (workers.py) can tell this anticipated, already-
    friendly-messaged condition apart from a genuinely unexpected extraction
    failure — via isinstance(), not by re-sniffing the message text a second
    time. Both workers' blanket ``except Exception`` handlers otherwise call
    logger.exception() unconditionally, which independently satisfies
    MainWindow's global ErrorDialogHandler (error_dialog.py, triggers on any
    ERROR-level log record app-wide) — so downgrading only the log call
    inside _raise_unp4k_failure wasn't enough; the worker's own logging needed
    the same treatment, and needed a reliable way to recognize this case."""


class DataForgeTimeoutError(RuntimeError):
    """unforge.exe ran past its timeout converting the DataForge database.

    A RuntimeError subclass for the same reason as P4kLockedError above: an
    anticipated condition that carries its own friendly message, which
    DataForgeExtractWorker recognises via isinstance() so its blanket
    ``except Exception`` does not log at ERROR and fire the global
    ErrorDialogHandler on top of the dialog the ``error`` signal already
    shows.

    Overwhelmingly this means the game install is inconsistent rather than
    the machine being slow. Measured on a healthy 4.9.188.23497 install,
    unforge converts the 330 MB Game2.dcb in about 40 seconds against a
    1800 second budget. Issue #370 was a user whose Data.p4k carried a
    114 MB ``Game.dcb`` while their build_manifest.id was byte-for-byte
    identical to a working install's: a patch that never finished applying
    to the 160 GB archive. unforge sat on the mismatched database until the
    timeout while their memory climbed, and all the user saw was "DataForge
    extraction failed" with no mention of a timeout at all.
    """


def _raise_unp4k_failure(returncode: int, output: str) -> None:
    """Raise for a non-zero unp4k exit — P4kLockedError for a locked Data.p4k,
    plain RuntimeError otherwise.

    Upgrades the generic "exited with code N" message to a clear "Star Citizen
    is updating, wait and retry" hint when the failure is Data.p4k being locked
    by another process (the common case — the user launched an extract while
    the RSI Launcher was patching). Always logs the raw output first so the Log
    tab keeps the underlying technical detail even when the friendly message is
    shown. Never returns — always raises.

    Logged at WARNING, not ERROR, for the locked-file case specifically — see
    P4kLockedError's docstring for why. Any OTHER unp4k failure still logs at
    ERROR — those are genuinely unexpected and should still surface through
    the generic handler."""
    output = output or ""
    if _P4K_LOCKED_SIGNATURE in output.lower():
        logger.warning(
            f"unp4k.exe exited with code {returncode} — Data.p4k is locked "
            f"(game likely updating); output:\n{output[:2000]}"
        )
        raise P4kLockedError(tr("extract.p4k_locked"))
    logger.error(f"unp4k.exe exited with code {returncode}; output:\n{output[:2000]}")
    raise RuntimeError(f"unp4k.exe exited with code {returncode}.\n\n{output}")


def _unforge_timeout_error(exc, dcb_path: Path, dcb_mb: float,
                           p4k_path: Path) -> DataForgeTimeoutError:
    """Log everything the timeout knows and build the error to raise.

    Two things the previous bare propagation threw away.

    First, the diagnostics. On Windows ``subprocess.run`` kills the child and
    re-collects its output onto the exception (``exc.stdout``/``exc.stderr``)
    precisely so a timeout is not silent, but nothing caught the exception, so
    that output went in the bin. The normal success path logs unforge's output
    a few lines below; the one failure that most needs it logged nothing.

    Second, which database it was chewing on. The name and size are the whole
    diagnosis: a healthy install yields Game2.dcb at ~330 MB, and #370's
    stalled one yielded Game.dcb at 114 MB. Without both in the log there is
    no way to tell a mismatched install from a slow machine, and the two need
    opposite advice.

    Returns the exception rather than raising it, so the caller's `raise`
    is visible at the call site. Raising from in here would leave `result`
    statically possibly-unbound after the try block, resting on an implicit
    "this never returns" contract that a later edit could quietly break into
    a confusing NameError."""
    def _decode(v) -> str:
        if not v:
            return ""
        return v if isinstance(v, str) else v.decode("utf-8", "replace")

    out = _decode(getattr(exc, "stdout", None)).strip()
    err = _decode(getattr(exc, "stderr", None)).strip()
    logger.warning(
        f"unforge.exe timed out after {exc.timeout:.0f}s on {dcb_path.name} "
        f"({dcb_mb:.0f} MB). A healthy install converts in well under a "
        f"minute, so this usually means Data.p4k does not match the "
        f"installed build (see issue #370)."
    )
    if out:
        logger.warning(f"unforge partial stdout ({len(out)} bytes, truncated): {out[:2000]}")
    if err:
        logger.warning(f"unforge partial stderr ({len(err)} bytes, truncated): {err[:2000]}")
    return DataForgeTimeoutError(
        tr("extract.dataforge_timeout", dcb=dcb_path.name,
           size=f"{dcb_mb:.0f}", path=str(p4k_path))
    )


def robust_rmtree(path: Path, attempts: int = 6) -> None:
    """Delete *path* recursively, surviving transient Windows locks.

    On Windows — especially when the target lives under OneDrive — rmtree
    often trips over three things:

    1. Read-only attribute on files unp4k/unforge just wrote. Clearing the
       bit via ``os.chmod(.., stat.S_IWRITE)`` lets the retry succeed.
    2. A ghost handle from the just-exited ``unforge.exe`` child process
       (or Windows Defender / Search Indexer / OneDrive client) that
       releases a beat later. A short sleep-and-retry loop clears these.
    3. A non-empty directory whose children are mid-delete. Re-walking the
       tree on each attempt catches files added or unlocked between tries.

    Silently succeeds if *path* doesn't exist. Raises the last error if
    every attempt fails so callers can surface it to the user.
    """
    if not path.exists():
        return

    def _on_error(func, target, *_):
        # Compatible with both 3.11 ``onerror(func, path, excinfo)`` and
        # 3.12+ ``onexc(func, path, exc)`` callback signatures — we only
        # care about the failing path so the trailing arg is ignored.
        # Clear the read-only bit and retry the single failing file/dir;
        # for other errors (e.g. lingering handle), propagate so the
        # outer retry loop picks it up.
        try:
            os.chmod(target, stat.S_IWRITE)
        except OSError:
            pass
        try:
            func(target)
        except OSError:
            raise

    last_err: Exception | None = None
    for i in range(attempts):
        try:
            gc.collect()  # drop any lingering XML file handles we own
            shutil.rmtree(_win_long_path(path), **{_RMTREE_CB_KWARG: _on_error})
            return
        except OSError as e:
            last_err = e
            # Exponential-ish backoff: 0.2, 0.4, 0.8, 1.5, 3.0 seconds. Total
            # ceiling ~6s before we bail, enough to outlast most AV/indexer
            # scans without hanging the UI forever.
            delay = min(0.2 * (2 ** i), 3.0)
            logger.warning(
                f"rmtree {path} attempt {i + 1}/{attempts} failed ({e}); "
                f"retrying in {delay:.1f}s"
            )
            time.sleep(delay)

    raise last_err if last_err else OSError(f"Failed to remove {path}")

# Path of global.ini inside the p4k archive (unp4k preserves directory structure)
_GLOBAL_INI_RELATIVE = Path("data/Localization/english/global.ini")


# Subtrees of unforge's ``libs/foundry/records/`` that the enhancement
# generator actually reads. Everything else unforge produces is copied nowhere
# — the temp extraction is thrown away when the with-block exits.
#
# Keeping this list tight:
#   * halves the final cache's file count (~58k → ~28k) and disk footprint
#     (~2.4 GB → ~1.4 GB);
#   * cuts the temp → cache copy step to ~50% of its old wall-clock (OneDrive
#     / Defender / Indexer fire hooks per-file-close, which dominates copy
#     time on typical Windows installs);
#   * makes ``robust_rmtree`` on the old cache roughly 2x faster and less
#     prone to transient WinError 5 retries, since there are half as many
#     files for the AV/indexer stack to hold open briefly.
#
# unp4k and unforge themselves are unaffected — unforge has no filter flag,
# so we still produce the full DCB-expansion into the temp dir. The savings
# are on the persistent cache, not on the first-time CPU work.
#
# MAINTENANCE CONTRACT: paths here must cover everything ``scripts/
# generate_enhancements_ini.py`` reads via ``records / ...``. If a future
# generator feature reads a new subtree, add it here or the cache won't
# contain it and enhancements for that subtree will silently be empty.
# ``tests/test_pak_extraction.py`` has a regression test that diffs this
# list against a hardcoded copy of the generator's read-paths so drift is
# caught at test time.
DATAFORGE_KEEP_SUBPATHS: tuple[str, ...] = (
    "entities/scitem",
    "entities/spaceships",
    "entities/missions",
    "entities/contracts",
    "entities/jobterminal",
    "contracts/contractgenerator",
    "contracts/contracttemplates",
    "crafting/blueprintrewards",
    "crafting/blueprints/crafting",
    "missionbroker/pu_missions",
    "ammoparams/vehicle",
    "ammoparams/fps",
    "reputation/rewards/missionrewards_reputation",
    "reputation/standings",
)


def _copy_filtered_records(src_libs: Path, dst_libs: Path) -> tuple[int, int]:
    """Copy only the generator's required subtrees from *src_libs* → *dst_libs*.

    Both paths point at the ``libs/`` directory unforge writes (which in turn
    contains ``foundry/records/<subtree>/...``). Only subpaths listed in
    :data:`DATAFORGE_KEEP_SUBPATHS` are copied; anything else in the source
    is left in the temp dir and dropped when the surrounding TemporaryDirectory
    context exits.

    Returns ``(copied, skipped)`` — the number of keep-subpaths actually
    present and copied, and the number that weren't in this game build
    (common for ``entities/missions`` etc. which appear and disappear between
    patches — the generator already guards each read with ``if dir.exists()``).
    """
    records_src = src_libs / "foundry" / "records"
    records_dst = dst_libs / "foundry" / "records"

    if not records_src.exists():
        raise FileNotFoundError(
            f"unforge output missing expected 'foundry/records/' layout at {records_src}"
        )

    Path(_win_long_path(records_dst)).mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = 0
    for rel in DATAFORGE_KEEP_SUBPATHS:
        src = records_src / rel
        dst = records_dst / rel
        if not src.exists():
            # Not every build ships every subtree — e.g. entities/missions,
            # entities/contracts, entities/jobterminal came and went across
            # 4.x patches. Log at debug so the cold-path message in the Log
            # Tab stays uncluttered.
            logger.debug(f"DataForge keep-path not in this build, skipping: {rel}")
            skipped += 1
            continue
        Path(_win_long_path(dst.parent)).mkdir(parents=True, exist_ok=True)
        # Long-path-prefixed on both sides: the deepest entries under
        # entities/scitem/mission_entities/ routinely push the destination
        # past 260 chars once nested under a user's install dir (#221).
        shutil.copytree(_win_long_path(src), _win_long_path(dst))
        copied += 1

    return copied, skipped


def _get_subprocess_kwargs() -> dict:
    """Return subprocess kwargs to suppress window on Windows."""
    kwargs = {
        "capture_output": True,
        "text": True,
    }
    # On Windows, suppress the subprocess window completely
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000
    return kwargs


@timed
def extract_global_ini(
    p4k_path: Path,
    output_path: Path,
    unp4k_exe: Path,
    progress_callback=None,
    progress_pct_callback=None,
) -> bool:
    """Extract global.ini from Data.p4k and save it to output_path.

    Uses unp4k.exe with the filter "global.ini" to extract only the localization
    file, then copies it to output_path (overwriting any existing file).

    Args:
        p4k_path: Path to Star Citizen's Data.p4k file.
        output_path: Destination path (e.g. cache/base.ini).
        unp4k_exe: Path to the bundled unp4k.exe.
        progress_callback: Optional callable(str) for status messages.

    Returns:
        True on success.

    Raises:
        FileNotFoundError: If unp4k.exe or Data.p4k is missing, or the
            extracted file is not found after extraction.
        RuntimeError: If unp4k.exe exits with a non-zero return code.
    """
    if not unp4k_exe.exists():
        raise FileNotFoundError(f"unp4k.exe not found at: {unp4k_exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")

    TOTAL_PHASES = 2
    with tempfile.TemporaryDirectory() as tmp_dir:
        if progress_callback:
            progress_callback(tr("progress.unp4k_launch"))
        if progress_pct_callback:
            progress_pct_callback(0, TOTAL_PHASES, tr("progress.unp4k_launch_short"))

        logger.info(f"Running unp4k: {unp4k_exe} {p4k_path} global.ini (cwd={tmp_dir})")
        result = subprocess.run(
            [str(unp4k_exe), str(p4k_path), "global.ini"],
            cwd=tmp_dir,
            timeout=300,
            **_get_subprocess_kwargs()
        )

        if result.returncode != 0:
            _raise_unp4k_failure(result.returncode, result.stderr or result.stdout)

        extracted = Path(tmp_dir) / _GLOBAL_INI_RELATIVE
        if not extracted.exists():
            raise FileNotFoundError(
                f"unp4k ran successfully but global.ini was not found at the expected path:\n"
                f"{extracted}\n\n"
                f"stdout: {result.stdout[:500]}"
            )

        if progress_callback:
            progress_callback(tr("progress.copy_global"))
        if progress_pct_callback:
            progress_pct_callback(1, TOTAL_PHASES, tr("progress.copy_global_short"))

        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(extracted), str(output_path))
        logger.info(f"Extracted global.ini → {output_path}")

    if progress_pct_callback:
        progress_pct_callback(2, TOTAL_PHASES, "Done")
    return True


@timed
def extract_dataforge(
    p4k_path: Path,
    unp4k_exe: Path,
    unforge_exe: Path,
    dataforge_cache_dir: Path,
    progress_callback=None,
    progress_pct_callback=None,
) -> bool:
    """Extract DataForge entity XMLs from Data.p4k and cache them.

    Pipeline:
      1. unp4k.exe extracts Game2.dcb from the p4k into a temp directory.
      2. unforge.exe converts Game2.dcb → individual XML entity files.
      3. The full extraction is cached to dataforge_cache_dir for stats generation.

    This is slow the first time (~several minutes) but results are cached and
    only need to be re-run when the p4k file changes.

    Args:
        p4k_path: Path to Data.p4k.
        unp4k_exe: Path to bundled unp4k.exe.
        unforge_exe: Path to bundled unforge.exe.
        dataforge_cache_dir: Destination directory for the cached entity XMLs.
        progress_callback: Optional callable(str) for status messages.

    Returns:
        True on success.

    Raises:
        FileNotFoundError: If required executables or Data.p4k are missing.
        RuntimeError: If either subprocess fails.
    """
    for exe, name in [(unp4k_exe, "unp4k.exe"), (unforge_exe, "unforge.exe")]:
        if not exe.exists():
            raise FileNotFoundError(f"{name} not found at: {exe}")
    if not p4k_path.exists():
        raise FileNotFoundError(f"Data.p4k not found at: {p4k_path}")

    # Wrap once here so every use below (mkdir, exists checks, and whatever
    # this function hands to _copy_filtered_records/update_manifest) inherits
    # long-path safety — see win_paths.win_long_path (#221).
    dataforge_cache_dir = Path(_win_long_path(dataforge_cache_dir))

    TOTAL_PHASES = 3
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)

        # ── Step 1: Extract Game2.dcb ─────────────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.extract_dcb"))
        if progress_pct_callback:
            progress_pct_callback(0, TOTAL_PHASES, tr("progress.extract_dcb"))
        logger.info(f"Running unp4k to extract .dcb: {unp4k_exe} {p4k_path} .dcb")
        result = subprocess.run(
            [str(unp4k_exe), str(p4k_path), ".dcb"],
            cwd=tmp_dir,
            timeout=600,
            **_get_subprocess_kwargs()
        )
        if result.returncode != 0:
            _raise_unp4k_failure(result.returncode, result.stderr or result.stdout)

        # Explicit cleanup: ensure subprocess is fully released
        del result
        gc.collect()
        time.sleep(0.1)  # Brief pause for file system to release locks

        # unp4k preserves archive structure: Data/Game2.dcb
        dcb_candidates = list(tmp.glob("Data/Game*.dcb"))
        if not dcb_candidates:
            raise FileNotFoundError("Game*.dcb not found in p4k output — check game install path.")
        dcb_path = dcb_candidates[0]
        logger.info(f"Found DCB: {dcb_path} ({dcb_path.stat().st_size / 1_048_576:.0f} MB)")

        # ── Step 2: Run unforge to produce entity XMLs ────────────────────────
        if progress_callback:
            progress_callback(tr("progress.unforge"))
        if progress_pct_callback:
            progress_pct_callback(1, TOTAL_PHASES, tr("progress.unforge_short"))
        # Size is captured before the run so the timeout handler can name it:
        # "Game.dcb (114 MB)" versus a healthy "Game2.dcb (330 MB)" is the
        # entire diagnosis when this stalls (#370).
        dcb_mb = dcb_path.stat().st_size / 1_048_576
        logger.info(f"Running unforge: {unforge_exe} {dcb_path}")
        try:
            result = subprocess.run(
                [str(unforge_exe), str(dcb_path)],
                timeout=1800,   # 30 minutes max
                **_get_subprocess_kwargs()
            )
        except subprocess.TimeoutExpired as e:
            raise _unforge_timeout_error(e, dcb_path, dcb_mb, p4k_path) from e
        # Always log unforge's output at INFO (truncated). A zero-length
        # stdout + sub-second runtime is typically a silent failure — e.g.
        # missing .NET runtime, the user's AV quarantining a temp file, or
        # unforge choking on a new DCB schema. Without this log the
        # downstream "libs/ directory was not created" error gives no clue
        # what went wrong.
        _stdout = (result.stdout or "").strip()
        _stderr = (result.stderr or "").strip()
        if _stdout:
            logger.info(f"unforge stdout ({len(_stdout)} bytes, truncated): {_stdout[:2000]}")
        if _stderr:
            logger.info(f"unforge stderr ({len(_stderr)} bytes, truncated): {_stderr[:2000]}")
        if result.returncode != 0:
            raise RuntimeError(f"unforge.exe failed (code {result.returncode}):\n{_stderr or _stdout or '(no output)'}")

        # Explicit cleanup: ensure subprocess is fully released
        del result
        gc.collect()
        time.sleep(0.1)  # Brief pause for file system to release locks

        # unforge writes entity XMLs into a libs/ subdirectory next to the
        # dcb file. When it's missing we surface whatever we captured from
        # unforge's stdout/stderr in the exception so the user (and the Log
        # Tab) can see what went wrong.
        libs_dir = dcb_path.parent
        if not (libs_dir / "libs").exists():
            diagnostic = ""
            if _stdout or _stderr:
                diagnostic = (
                    f"\n\nunforge stdout:\n{_stdout[:1500] or '(empty)'}"
                    f"\n\nunforge stderr:\n{_stderr[:1500] or '(empty)'}"
                )
            else:
                # Nothing on either stream and no libs/ — classic "missing
                # .NET runtime" signature on Windows. unforge is a .NET
                # executable and quietly exits 0 when the CLR fails to load.
                diagnostic = (
                    "\n\nNo output from unforge and no libs/ directory produced. "
                    "This typically means .NET Framework 4.x isn't installed or "
                    "is blocked by antivirus. Install the latest .NET Framework "
                    "runtime from Microsoft and try again."
                )
            raise FileNotFoundError(
                "unforge ran but libs/ directory was not created — unexpected output structure."
                + diagnostic
            )

        # ── Step 3: Cache the full extraction ─────────────────────────────────
        if progress_callback:
            progress_callback(tr("progress.caching_entities"))
        if progress_pct_callback:
            progress_pct_callback(2, TOTAL_PHASES, tr("progress.caching_entities"))

        # Ensure all file handles from extraction are released before copying
        gc.collect()
        time.sleep(0.1)

        # Blow away any prior cache. Uses a retry loop because on Windows
        # (particularly under OneDrive) a transient handle from the
        # just-exited unforge.exe or from the OneDrive/Defender/indexer
        # stack can reject the first few rmdir attempts with WinError 5.
        if dataforge_cache_dir.exists():
            robust_rmtree(dataforge_cache_dir)
        dataforge_cache_dir.mkdir(parents=True, exist_ok=True)

        # Cache only the subtrees the enhancement generator actually reads.
        # See DATAFORGE_KEEP_SUBPATHS for the list and rationale — dropping
        # the unused ~30k/~1 GB worth of entries halves cache file count and
        # makes every re-extract + clear-cache noticeably faster on the
        # OneDrive/Defender/Indexer-burdened Windows paths our users live in.
        raw_dir = dataforge_cache_dir / "raw"
        logger.info(f"Saving DataForge extraction to {raw_dir}…")
        copied, skipped = _copy_filtered_records(libs_dir / "libs", raw_dir / "libs")
        logger.info(
            f"DataForge cache written: {copied}/{len(DATAFORGE_KEEP_SUBPATHS)} "
            f"keep-subpaths copied ({skipped} not present in this build)"
        )

        # Stamp the source Data.p4k's mtime AND size so a later launch can tell
        # whether this cache is still current. Size is the reliable signal —
        # see dataforge_cache_is_fresh — because the RSI launcher's file
        # verification bumps Data.p4k's mtime on game launches without changing
        # its content, and a multi-GB re-extract on every such benign touch is
        # exactly the needless work issue #209 reported.
        p4k_stat = p4k_path.stat()
        (dataforge_cache_dir / P4K_MTIME_STAMP).write_text(str(p4k_stat.st_mtime))
        (dataforge_cache_dir / P4K_SIZE_STAMP).write_text(str(p4k_stat.st_size))
        logger.info(f"DataForge cache written to {dataforge_cache_dir}")
        # Snapshot the new cache so the next run can diff against it.
        # SHA-256 over ~28k files is multi-minute serial; we surface it
        # to the progress bar (and parallelize it inside update_manifest)
        # so the UI doesn't appear frozen.
        logger.info("Snapshotting DataForge cache for diff manifest…")
        if progress_callback:
            progress_callback(tr("progress.snapshot_diff"))
        update_manifest(raw_dir / "libs", progress_callback=progress_pct_callback)
        logger.info("Diff manifest written")

    # Ensure all file handles are released before returning
    gc.collect()
    if progress_pct_callback:
        progress_pct_callback(3, TOTAL_PHASES, "Done")
    return True


@timed
def dataforge_cache_is_fresh(p4k_path: Path, dataforge_cache_dir: Path) -> bool:
    """Return True if the cached DataForge XMLs are up-to-date with the p4k.

    Requires a stamp AND actual XML content in the cache so a stamp-only
    remnant from a failed/partial extraction returns False.

    Freshness is keyed off the source Data.p4k's **byte size**, not its mtime
    (issue #209). The RSI launcher's file verification bumps Data.p4k's mtime
    on ordinary game launches without changing its content, so an mtime-only
    check declared the cache stale after any game launch and forced a needless
    multi-minute re-extract on the next app start. A real game patch always
    changes the ~100 GB archive's size, so size is the reliable "did the
    content change" signal. Caches written before the ``.p4k_size`` stamp
    existed (upgrades) fall back to the legacy mtime comparison until the next
    extraction writes the size stamp.
    """
    dataforge_cache_dir = Path(_win_long_path(dataforge_cache_dir))
    stamp = dataforge_cache_dir / P4K_MTIME_STAMP
    size_stamp = dataforge_cache_dir / P4K_SIZE_STAMP
    libs_dir = dataforge_cache_dir / "raw" / "libs"
    if not stamp.exists() or not libs_dir.exists():
        return False
    # Verify there is at least one XML file — guards against empty extractions
    if not any(libs_dir.rglob("*.xml")):
        return False
    try:
        p4k_stat = p4k_path.stat()
    except OSError:
        return False
    # Primary signal: unchanged size means unchanged content → fresh,
    # regardless of any benign mtime drift.
    try:
        cached_size = int(size_stamp.read_text().strip())
        return cached_size == p4k_stat.st_size
    except (OSError, ValueError):
        pass
    # Legacy fallback (no size stamp yet): the pre-#209 mtime comparison.
    try:
        cached_mtime = float(stamp.read_text().strip())
        return cached_mtime >= p4k_stat.st_mtime
    except (OSError, ValueError):
        return False
