# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Smart Citizen (formerly SC Localization Editor) is a Windows-only PyQt6 GUI application for customizing Star Citizen localization strings. Tagline: _Smarter Strings for Star Citizen_. Users configure multiple data sources (Global, Contracts, Components, Ships, Commodities, Gear, User) with a drag-and-drop merge hierarchy, edit strings in a table, and apply changes to their game installation with automatic backup management.

**Rebrand status**: As of 0.9.0, user-facing strings, registry path (`Osiris DevWorks\Smart Citizen`), and the user data root (`Documents\Smart Citizen\`) all use the new name. `AppSettings` still contains one-shot migrators for the legacy `Osiris DevWorks\SC Localization Editor` registry tree and `Documents\SC Localization Editor\` directory; do not remove them while users on pre-0.9 builds may still upgrade.

**Current Version**: Read from `VERSION.TXT` (single source of truth). Project is at 1.0 as of this writing.

## Quick Commands

```bash
# Setup (install all deps including dev)
uv sync

# Run
uv run python src/main.py

# Testing
uv run pytest tests/                                    # Run all tests
uv run pytest tests/test_core.py                       # Run single file
uv run pytest tests/test_core.py::TestIniParsing       # Run single class
uv run pytest tests/ -v                                # Verbose output
uv run pytest tests/ --cov=src --cov-report=html      # Coverage report (HTML)
uv run pytest tests/ -n auto                           # Parallel execution (pytest-xdist)

# Code Quality
uv run ruff check src/ tests/ scripts/                 # Lint
uv run ruff format src/ tests/ scripts/                # Format
uv run mypy src/                                       # Type checking

# Building
uv run python scripts/build/build_exe.py               # Build exe (PyInstaller)
cd scripts/build && build_all.bat                      # Build exe + installer (requires Inno Setup)

# Data Generation
python scripts/generate_enhancements_ini.py [base_ini_path [dataforge_cache_dir]]
python scripts/extract_components.py [--stock path] [--base path] [--output path] [--dry-run]
```

## Testing Strategy

**Unit Tests** (`tests/`): Split by domain — `test_core.py` (INI parsing/merging/category extraction), `test_missions.py` (mission rewards pipeline), `test_pak_extraction.py` (P4K/DataForge), `test_progress_sink.py` (thread-safe progress coalescing), `test_dataforge_patcher.py` (declarative XML patching), `test_app_updater.py` (GitHub Releases version-check worker), `test_channel_layout.py` (per-channel directory migration). Pytest config lives in `tests/pytest.ini` (sets `pythonpath = src`, registers markers: `unit`, `integration`, `slow`, `critical`, `regression`).

**GUI Testing**: Manual. Run app (`python src/main.py`), load base file, edit a value, apply to game, restart to verify persistence. Use the Log Tab to watch for errors during load/merge/apply cycles.

## Architecture

Entry point: `src/main.py`. The app has two main layers:

**GUI layer** (`src/gui/`):

- `main_window.py` — Main window with table, toolbar, filters, backup/restore, threading workers, DataForge extraction. This is the largest file (~2000+ lines). Manages the primary workflow: load, merge, edit, apply.
- `config_tab.py` — **Config Tab**: Data source management (add/edit/remove sources), drag-drop merge hierarchy, Star Citizen install path, and DataForge extraction trigger.
- `enhancements_tab.py` — **Enhancements Tab**: Toggle stats overlays, configure ship favorites prefix, trigger DataForge extraction. Emits `merge_requested` and `stats_pipeline_requested` signals.
- `log_tab.py` — **Log Tab**: In-app real-time log viewer. Bridges Python `logging` to Qt text widget via `_LogEmitter` signal (thread-safe). Supports level filtering, auto-scroll, and log export.
- `filter_header.py` — `FilterHeaderView` QHeaderView subclass adding per-column QLineEdit filter row below header labels, with debounced filtering.
- `string_table_model.py` — `QAbstractTableModel` backing the strings `QTableView`. Replaces the old `QTableWidget.populate_table()` approach; renders visible rows on demand and sorts in Python (via `sort()` override) rather than per-comparison `lessThan()`. Column index constants (`COL_CATEGORY`, `COL_KEY`, `COL_DEFAULT`, `COL_CURRENT`, `COL_STAR`, `COL_CUSTOM`, `COL_STATUS`) live here.
- `import_dialog.py` — `ImportConflictDialog` for resolving conflicts when importing INI files into user overrides. Allows per-key resolution strategies (keep current, use imported, append, prepend, or custom).
- `theme.py` — Palette swap on `QApplication` + branded font loading (`load_application_fonts()` registers the Orbitron TTF (OFL-1.1) from `assets/fonts/`). Theme-aware widgets rely on palette `WindowText`/`Text` roles; dim/secondary labels mark themselves with `setProperty("role", "secondary")` and the app-level QSS rule installed by `apply_theme()` recolors them on live theme swap. Progress-bar contrast is controlled via the palette's `Highlight` role (Fusion's native chunk color) — do not add `QProgressBar::chunk` QSS, it switches Qt to a styled path that stops animating in indeterminate mode.
- `coach_mark.py` — `CoachMarkOverlay` + `TutorialTour` for the in-app guided tour. Self-contained: the main window builds a list of `CoachMarkStep` records (target widget, title, description, optional pre-action) and calls `tour.start()`. Overlay dims the window, spotlights the target, and floats a callout with Back / Next / Skip; emits `finished(completed: bool)` when done.

**Data layer** (`src/models/`, `src/parser/`, `src/merger/`, `src/utils/`):

- `string_model.py` — `StringEntry` dataclass with category extraction from key prefixes.
- `ini_parser.py` — Line-by-line INI parsing (splits on first `=`), source loading via `load_sources_from_settings()`, and `load_overrides(target_path)` for reading `user.ini` back as a `dict[str, str]`.
- `ini_merger.py` — Merge engine: `merge_sources_by_hierarchy(sources_dict, hierarchy, user_overrides)`. Sources merge sequentially; user overrides always win.
- `settings.py` — `AppSettings` class wrapping QSettings (Windows Registry). All user data stored under `Documents\Smart Citizen\{active_channel}\`. Critical: Registry is the single source of truth for all paths and preferences. Also owns canonical paths (`get_user_data_dir()`, `get_cache_dir()`, `get_user_ini_path()`, `get_backups_dir()`) and handles automatic migrations: legacy `overrides.ini` → `user.ini`, `AppData\Roaming\...` → `Documents\...`, and the 0.9.3+ flat layout → per-channel layout (`migrate_game_path_to_channel_layout()`).
- `updater.py` — Per-source GitHub downloads. Drives the auto-update workers that refresh each cached source INI (`base.ini`, `contracts.ini`, etc.) from its configured GitHub URL.
- `app_updater.py` — _Separate_ from `updater.py`. Polls `GET /repos/Osiris-DevWorks/smart-citizen/releases/latest` and compares `tag_name` to the local `VERSION.TXT` to surface a "new installer available" prompt. Runs on a `QThread`; `MainWindow` caps auto-checks to once per 6 hours via a registry timestamp to stay under GitHub's 60-req/hr unauthenticated limit.
- `pak_extractor.py` — P4K extraction pipeline: `unp4k.exe` (extracts Game2.dcb) → `unforge.exe` (converts to entity XMLs). After unforge writes the full DataForge tree to a temp dir, `_copy_filtered_records()` copies only the subtrees in `DATAFORGE_KEEP_SUBPATHS` (the ones the generator actually reads) to the persistent cache — halves cache file count and cuts copy/rmtree wall time. Adding a new read path in the generator requires adding it to `DATAFORGE_KEEP_SUBPATHS`; `tests/test_pak_extraction.py::TestDataForgeKeepList` locks the contract.
- `user_ini_manager.py` — Saves user-modified entries to `user.ini` (plain `key=value`, no sections) via `save_user_ini(entries, path)`; coordinates with `ImportConflictDialog` when importing external INIs.
- `user_cfg.py` — Manages Star Citizen's `user.cfg` file; ensures `g_language = english` is set in the LIVE directory.
- `version.py` — Reads version string from `VERSION.TXT`, handling both normal and PyInstaller-frozen execution.
- `perf.py` — `@timed` decorator for debug-level performance profiling. No-op when DEBUG logging disabled.
- `progress_sink.py` — `ProgressSink` coalesces `advance()` calls from many worker threads into throttled `(completed, total, message)` callbacks. Used by the parallelized lookup builders and enhancement generators to drive determinate progress bars without flooding the Qt event loop.
- `dataforge_patcher.py` — Applies declarative JSON patches from `patches/` to the DataForge XML cache immediately after extraction. Fixes upstream CIG data bugs (e.g. mission records pointing at wrong loc-keys) so downstream consumers see corrected data. Patches mirror the DataForge layout under `patches/<category>/.../<name>.patch.json`.

**Scripts** (`scripts/`):

- `generate_enhancements_ini.py` — Reads DataForge entity XMLs only (no external JSON) → outputs enhancement INI files to cache (ships, components, ship weapons, FPS weapons descriptions).
- `extract_components.py` — Diffs base.ini against stock vanilla to produce components.ini.
- `gen_commodity_crafting.py` — Generates `commodity_crafting_enhancements.ini` with crafting blueprint usage data from DataForge XMLs.
- `compare_kraken_fixture.py` — Research/reporting tool: diffs the `kraken_4.7.ini` ground-truth fixture against our generated `mission_rewards_enhancements.ini` to validate blueprint list output. Read-only.
- `diff_bp_kraken.py`, `diff_bp_annotations.py`, `diff_bp_csv_fixture.py` — Read-only diagnostic scripts validating `[BP]` / `[BP?]` blueprint annotations on mission rewards. Each compares our `mission_rewards_enhancements.ini` output against a different ground-truth source (kraken fixture, an applied LIVE `global.ini`, and the `missions_4.7.177.csv` per-variant fixture, respectively). Use these when blueprint tags regress.
- `discord_notify.py` — GitHub Actions release webhook notifier.
- `build/build_exe.py`, `build/build_all.bat`, `build/clean_cache_for_distribution.py` — Build pipeline; see `scripts/build/BUILD_INSTRUCTIONS.md`.

**PyInstaller specs**: `SmartCitizen.spec` at the repo root is the live spec used by the current build. The `SCLocalizationEditor-v*.spec` and `SmartCitizen-v0.9.*.spec` files are archival snapshots from prior releases — do not edit them for new builds.

## Critical Design Decisions

### Sortable columns require indirect row lookup

The table is a `QTableView` backed by `StringTableModel` (`src/gui/string_table_model.py`), which maintains a filtered/sorted list of indices into `self.entries`. Row index != entry index when columns are sorted or filtered. **All row→entry lookups must use `_entry_index_for_row(row)`** on `MainWindow` (which delegates to `self._model.entry_index_for_row(row)`). Direct indexing into `self.entries` by row number will produce wrong results. When adding code that reads from the table, use the `COL_*` constants from `string_table_model.py` rather than hard-coded column numbers.

### File naming: base.ini vs global.ini

The cached global source is saved as `base.ini` (not `global.ini`) to avoid confusion with the game's `global.ini` at `LIVE/data/Localization/english/global.ini`.

### Threading model

All I/O-bound operations (file loads, network requests, P4K extraction) run in `QThread` workers. Workers emit `finished()` signals; cleanup requires `quit()` + `wait()`. Never block the main thread with file or network operations. Bulk table updates wrap in `setUpdatesEnabled(False)`. Registry access (via `AppSettings`) is thread-safe; use it freely from main or worker threads.

### Startup initialization

On first run, the app initializes user data directories, validates Star Citizen install path, and may show a startup dialog to guide configuration. Subsequent runs check source freshness and auto-apply any pending DataForge cache updates.

### DataForge extraction is a four-step pipeline

The "Extract DataForge from P4K" button triggers: (1) unpack Data.p4k → entity XMLs via `pak_extractor.py`, (2) apply declarative patches from `patches/` via `dataforge_patcher.py` to fix upstream CIG data bugs, (3) run `generate_enhancements_ini.py` to produce enhancement INI files from the XMLs, (4) reload all strings to refresh the table. All steps run sequentially from a single button click. The patch step is idempotent and always runs on the extracted cache, even when extraction is skipped as fresh.

### Parallel pipelines report progress via ProgressSink

Lookup builders and enhancement output generators run in parallel worker threads (see `scripts/generate_enhancements_ini.py`). They share a single `ProgressSink` (`src/utils/progress_sink.py`) so the UI shows one determinate progress bar. Never call `QProgressBar.setValue()` directly from workers — go through the sink so updates are coalesced and throttled on the main thread.

### Merge hierarchy

Sources merge in user-defined order (default: global → contracts → components → ships → commodities → gear → user). Later sources overwrite earlier ones. User overrides are always applied last and never lost during source updates.

### Favorites use value prefix

Favorites prepend a configurable prefix (default `*`) to `custom_value`. The prefix is stored in Registry via `AppSettings.FAVORITE_PREFIX`.

## File Locations

| What                 | Where                                                                                                                                                                                                                                                                       |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --- | ---- | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Settings             | Windows Registry: `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen`                                                                                                                                                                                                |
| User data root       | `Documents\Smart Citizen\` (resolved via registry for OneDrive support)                                                                                                                                                                                                     |
| **Per-channel data** | `Documents\Smart Citizen\{LIVE                                                                                                                                                                                                                                              | PTU | EPTU | HOTFIX | TECH-PREVIEW}\` — 0.9.3+ nests user.ini / cache / backups / dataforge under the active channel so each SC channel is isolated. Migrator: `AppSettings.migrate_game_path_to_channel_layout()`. |
| User overrides       | `Documents\Smart Citizen\{active_channel}\user.ini` (legacy `overrides.ini`, auto-migrated)                                                                                                                                                                                 |
| Cached sources       | `Documents\Smart Citizen\{active_channel}\cache\` (`base.ini`, `contracts.ini`, etc.)                                                                                                                                                                                       |
| DataForge cache      | `Documents\Smart Citizen\{active_channel}\cache\dataforge\` (entity XMLs from Data.p4k)                                                                                                                                                                                     |
| Enhancement INIs     | `Documents\Smart Citizen\{active_channel}\cache\` (`ships_desc_enhancements.ini`, `components_desc_enhancements.ini`, `ship_weapons_desc_enhancements.ini`, `fps_weapons_desc_enhancements.ini`, `mission_rewards_enhancements.ini`, `commodity_crafting_enhancements.ini`) |
| Backups              | `Documents\Smart Citizen\{active_channel}\backups\` (max 5, oldest auto-deleted)                                                                                                                                                                                            |
| Game file            | `{sc_install_root}\{active_channel}\data\Localization\english\global.ini` — resolved via `AppSettings.get_global_ini_path()`                                                                                                                                                |
| P4K tools            | `assets/unp4k/` (`unp4k.exe`, `unforge.exe`)                                                                                                                                                                                                                                |
| DataForge patches    | `patches/` (JSON files mirroring DataForge layout; applied post-extraction)                                                                                                                                                                                                 |
| Help/About content   | `HELP.md`, `ABOUT.md` at repo root — rendered inside the in-app help panel                                                                                                                                                                                                  |

## Common Modification Points

| Task                               | File                                                               | Key Function                                                  |
| ---------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------- |
| Add/change table columns           | `main_window.py`                                                   | `setup_string_table()`                                        |
| Add/change filters                 | `main_window.py`                                                   | `apply_filters()`, `on_filter_changed()`                      |
| Change per-column filters          | `filter_header.py`                                                 | `FilterHeaderView`                                            |
| Change category extraction         | `string_model.py`                                                  | `StringEntry.extract_category()`                              |
| Modify INI parsing                 | `ini_parser.py`                                                    | `parse_ini_file()`                                            |
| Change merge logic                 | `ini_merger.py`                                                    | `merge_sources_by_hierarchy()`                                |
| Change overrides persistence       | `user_ini_manager.py` (save) / `ini_parser.py` (load)              | `save_user_ini()`, `load_overrides()`                         |
| Change user INI import behavior    | `import_dialog.py`, `user_ini_manager.py`                          | `ImportConflictDialog`                                        |
| Change table columns / model       | `string_table_model.py`, `main_window.py`                          | `StringTableModel`, `COL_*` constants, `setup_string_table()` |
| Modify auto-update                 | `updater.py`                                                       | `check_for_updates()`, `download_base_file()`                 |
| Change backup behavior             | `main_window.py`                                                   | `manage_backups()`                                            |
| Modify P4K extraction              | `pak_extractor.py`                                                 | `extract_dataforge()`                                         |
| Change enhancements generation     | `scripts/generate_enhancements_ini.py`                             | (standalone script)                                           |
| Add performance profiling          | `perf.py`                                                          | `@timed` decorator                                            |
| Change user data paths             | `settings.py`                                                      | `AppSettings.get_user_data_dir()`                             |
| Change DataForge freshness         | `settings.py`, `main_window.py`                                    | `dataforge_cache_is_fresh()`                                  |
| Change stats/favorites UI          | `enhancements_tab.py`                                              | `setup_ui()`                                                  |
| Manage Config tab UI               | `config_tab.py`                                                    | `setup_ui()`, drag-drop hierarchy setup                       |
| Manage Enhancements tab UI         | `enhancements_tab.py`                                              | `setup_ui()`, stats toggle, favorites config                  |
| Change in-app logging              | `log_tab.py`                                                       | `LogTab`, `_QtLogHandler`                                     |
| Change user.cfg behavior           | `user_cfg.py`                                                      | `ensure_user_cfg_language()`                                  |
| Fix an upstream DataForge data bug | `patches/<category>/.../<name>.patch.json`, `dataforge_patcher.py` | `apply_patches()`                                             |
| Change parallel progress reporting | `progress_sink.py`                                                 | `ProgressSink.advance()`                                      |

## Version & Release

**Version update workflow:**

1. Edit `VERSION.TXT` to new version (sole source of truth — `installer.iss` reads it via ISPP at compile time)
2. Build the PyInstaller onedir: `.venv/Scripts/python.exe scripts/build/build_exe.py`
3. Compile the installer (Inno Setup is a per-user install, invoke via PowerShell): `powershell -NoProfile -Command "& 'C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"`
4. Test installer from `dist/SmartCitizen-{VERSION}-Setup.exe`
5. Commit (include VERSION.TXT bump), tag (`git tag -a v0.X.Y -m "Release v0.X.Y"`), push branch + tag
6. Create GitHub release and attach `dist/SmartCitizen-{VERSION}-Setup.exe` (installer only; portable onefile exe has been retired)

Discord notification is automatic via GitHub Actions (`scripts/discord_notify.py`) if `DISCORD_RELEASE_WEBHOOK_URL` secret is configured.

## Debugging

- **Registry**: `regedit` → `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` (live tree). Pre-0.9 installs leave a parallel `Osiris DevWorks\SC Localization Editor` tree that the in-app migrator drains on next launch.
- **User data path**: If `Documents` is redirected (OneDrive), Registry stores the resolved path under `UserDataDir`; delete that value to reset and auto-detect on next run.
- **Threading hangs**: Check `worker.quit()` + `worker.wait()` are called in finished slots. Use Log Tab to watch for blockages.
- **File encoding**: Parser expects UTF-8; BOM or other encodings fail silently. Ensure cache files are UTF-8 no-BOM.
- **GitHub API rate limit**: Unauthenticated, 60 requests/hour per IP. Check updater logs if auto-update stalls.
- **Overrides not loading**: Verify `Documents\Smart Citizen\{active_channel}\user.ini` exists with `key=value` format (no sections). If you find a legacy `Documents\SC Localization Editor\overrides.ini`, both the rename (`overrides.ini` → `user.ini`) and the channel-nesting migration are handled lazily by `AppSettings` — launching the app once should drain them.
- **Performance**: Use `@timed` decorator on slow functions and check elapsed times in DEBUG logs.
- **Test isolation**: Each test should not depend on Registry state; mock `AppSettings` or use conftest fixtures.

## Dependencies

- **PyQt6** (>=6.10.0) — GUI framework
- **pyinstaller** (>=6.3.0) — Executable builder

Windows-only (uses Windows Registry via QSettings). Python 3.9+, recommended 3.10+.
