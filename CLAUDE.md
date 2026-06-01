# CLAUDE.md

This file guides Claude Code (claude.ai/code) when working in this repo.

> **Before editing files under `src/<dir>/`, `scripts/`, or `tests/`, read that directory's `CLAUDE.md` first.** See *Per-directory guides* below for the list.

## Communication style

- **Plain words, short sentences.** Cut adjectives, hedges, and throat-clearing. If a sentence isn't earning its weight, drop it.
- **One concept per message.** When the work involves several distinct concepts, present the first, stop, and ask the user before moving on. Do not stack ideas, decisions, or trade-offs in a wall of text.
- **Prompt at decision points.** When the next step needs the user's preference, judgment, or clarification, ask before proceeding. A one-line confirmation is cheaper than redoing work.

## Project Overview

Smart Citizen (formerly SC Localization Editor) is a Windows-only PyQt6 GUI for customizing Star Citizen localization strings. Tagline: *Smarter Strings for Star Citizen*. Users edit strings in a table backed by the `global` source (locally cached `base.ini` from Data.p4k) merged with per-channel `user.ini` overrides, then apply the result to their game with backup management.

**Branding**: User-facing strings, registry path (`Osiris DevWorks\Smart Citizen`), and the default data root (`Documents\Smart Citizen\`) use the new name. `AppSettings` keeps one-shot migrators for the legacy `Osiris DevWorks\SC Localization Editor` registry tree and `Documents\SC Localization Editor\` folder (rebrand was 0.9.0); keep them while pre-0.9 users may upgrade.

**Version**: `VERSION.TXT` is the sole source of truth. Now 1.5.0.

Build modes are covered in `src/utils/CLAUDE.md` under *Portable vs registry build mode*.

## Per-directory guides

Directory-specific docs (read the one for the layer you're touching):

- `src/gui/CLAUDE.md` — GUI layer (PyQt6 widgets, workers, table model).
- `src/utils/CLAUDE.md` — settings, build-mode flag, P4K extraction, enhancement helpers.
- `src/parser/CLAUDE.md` — INI parsing, status classification.
- `src/merger/CLAUDE.md` — source merge engine.
- `src/models/CLAUDE.md` — domain data models.
- `scripts/CLAUDE.md` — standalone CLI scripts and the build pipeline.
- `tests/CLAUDE.md` — test suite layout, pytest config.

Entry point: `src/main.py`.

## Quick Commands

```bash
# Setup
pip install -r requirements.txt           # production deps
pip install -r requirements-dev.txt       # plus pytest, flake8, black, mypy

# Run
python src/main.py

# Testing
pytest tests/                                                    # all
pytest tests/test_core.py                                        # one file
pytest tests/test_core.py::TestIniParsing                        # one class
pytest tests/test_core.py::TestIniParsing::test_parse_basic_ini  # one test
pytest tests/ -v                                                 # verbose
pytest tests/ --cov=src --cov-report=html                        # HTML coverage
pytest tests/ -n auto                                            # parallel (pytest-xdist)

# Code Quality
black src/ tests/ scripts/        # format
flake8 src/ tests/ scripts/       # lint
isort src/ tests/ scripts/        # sort imports
mypy src/                         # types

# Building
cd scripts/build && python build_exe.py             # registry build
cd scripts/build && python build_exe.py --portable  # portable build
cd scripts/build && build_all.bat                   # exe + installer (needs Inno Setup)

# Data Generation
python scripts/generate_enhancements_ini.py [base_ini_path [dataforge_cache_dir]]
python scripts/extract_components.py [--stock path] [--base path] [--output path] [--dry-run]
```

## Cross-cutting design decisions

Per-layer decisions live in the per-directory guides above. The ones below span layers.

### File naming: base.ini vs global.ini
The cached global source is saved as `base.ini` (not `global.ini`) to avoid confusion with the game's `global.ini` at `LIVE/data/Localization/english/global.ini`.

### Threading model
I/O-bound work (file loads, network, P4K extraction) runs in `QThread` workers in `src/gui/workers.py` (lone exception: `AppUpdateCheckWorker` in `src/utils/app_updater.py`, next to its companion logic). Workers emit `finished()`; cleanup needs `quit()` + `wait()`. Never block the main thread on file or network I/O. Wrap bulk table updates in `setUpdatesEnabled(False)`. `AppSettings` is thread-safe — use from main or worker. Worker logger names: `src.gui.workers` post-extraction (`src.gui.main_window` pre-extraction) — matters when grepping logs.

### Startup initialization
On first run, the app sets up user data dirs, validates the SC install path, and may show a startup dialog to guide config. Later runs check source freshness and apply any pending DataForge cache updates.

### DataForge extraction is a four-step pipeline
The "Extract DataForge from P4K" button triggers, in order:
1. Unpack Data.p4k → entity XMLs via `src/utils/pak_extractor.py`. The bundled unp4k is a parallelised fork (`odw-fast-unp4k`) using `ThreadPoolExecutor` for extraction and `lxml` for unforge.
2. Apply declarative patches from `patches/` via `src/utils/dataforge_patcher.py` to fix upstream CIG data bugs. Idempotent; runs on the extracted cache even when step 1 is skipped as fresh.
3. Run `scripts/generate_enhancements_ini.py` over the XMLs (only for categories the diff cache flags as dirty — see `src/utils/CLAUDE.md` → *DataForge diff cache*).
4. Reload all strings to refresh the table.

The progress dialog stays continuous across steps 1–3 so users see one bar from start to finish.

### Merge hierarchy
Sources merge in user-defined order. Later sources overwrite earlier ones; user overrides apply last and survive source updates. As of 1.0 the seeded default is just `[global, user]` — the URL sources (contracts/components/ships/commodities) and `gear` retired in 0.7.0 when extraction moved to local Data.p4k, and `migrate_remove_retired_url_sources()` removes them from upgrader registries. `load_sources_from_settings()` also injects a synthetic `enhancements` source at runtime when any enhancement category is enabled on the Enhancements tab — it is *not* a registry entry; don't add it to the hierarchy by hand.

### Favorites use value prefix
Favorites prepend a configurable prefix (default `*`) to `custom_value`. Stored via `AppSettings.FAVORITE_PREFIX`.

### Code deduplication (DRY)
Prefer one canonical implementation over copy-paste. Calibration:

- **Two occurrences**: usually fine — leave it.
- **Three or more**: extract. The third repeat is the signal.
- **Magic literals used in 2+ places**: extract a named constant immediately. Common offenders: settings keys, source names (`"global"`, `"user"`, `"enhancements"`), channel names (`"LIVE"`, `"PTU"`, `"EPTU"`, `"HOTFIX"`, `"TECH-PREVIEW"`), column indices, file extensions, path segments.
- **Near-duplicates differing in one literal or branch**: parameterize. Two functions that diverge on a single string or boolean are one function with an argument.

Anchor examples already in-tree: `COL_*` constants in `src/gui/string_table_model.py`, `_entry_index_for_row()` on `MainWindow`, `AppSettings` helpers (one backend abstraction, not mode-conditional call sites), `ProgressSink` (one shared progress channel for all parallel workers).

**Tolerated exception**: `CATEGORY_SUBTREES` (`src/utils/dataforge_diff.py`) ↔ `DATAFORGE_KEEP_SUBPATHS` (`src/utils/pak_extractor.py`) — two lists kept in sync deliberately; they serve different consumers and the contract is locked by tests.

**Don't over-abstract.** Three similar lines beats a premature abstraction. Single-use helpers, one-off config classes, and clever metaprogramming for code that runs in one place are worse than the inline version.

## PyInstaller specs

`SmartCitizen.spec` at the repo root is the live spec. The `SCLocalizationEditor-v*.spec` and `SmartCitizen-v0.9.*.spec` files are archival — do not edit for new builds.

## File Locations

| What | Where |
|------|-------|
| Settings (registry build) | Windows Registry: `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` |
| Settings (portable build) | `<user_data_dir>/config.json` via `JsonSettings` |
| User data root (registry build) | Configurable via `user_data_dir` (alias `UserDataDir` also read); default `Documents\Smart Citizen\` |
| User data root (portable build) | `<exe-dir>/data/` when frozen; `<repo-root>/portable_data/` unfrozen |
| **Per-channel data** | `{user_data_root}\{LIVE\|PTU\|EPTU\|HOTFIX\|TECH-PREVIEW}\` — 0.9.3+ nests user.ini / cache / backups / dataforge under the active channel so each SC channel is isolated. Migrator: `AppSettings.migrate_game_path_to_channel_layout()`. |
| User overrides | `{user_data_root}\{active_channel}\user.ini` (legacy `overrides.ini` auto-migrated) |
| Cached sources | `{user_data_root}\{active_channel}\cache\` — only `base.ini` post-1.0 (four legacy URL sources retired in 0.7.0); enhancement INIs live here too |
| DataForge cache | `%LOCALAPPDATA%\Smart Citizen\{active_channel}\cache\dataforge\` by default (entity XMLs from Data.p4k); overrideable independently of the user-data root via the `CACHE_DIR` registry key (1.4.1+ — `AppSettings.get_cache_dir_override()` / `set_cache_dir()`, wired to the Config tab's *DataForge Cache Folder*; the cache override does *not* fall back to the user-data override). Moved out of `Documents\` in 1.x — `migrate_dataforge_cache_to_local()` relocates the legacy `…\cache\dataforge\` tree on first launch. Resolved via `AppSettings.get_dataforge_cache_dir()`. |
| Crash dumps + log exports | `{user_data_root}\logs\` (NOT per-channel — a crash can fire before the channel context is established, e.g. during startup migrators). Resolved via `AppSettings.get_logs_dir()`; created lazily on first crash or export. |
| Enhancement INIs | `{user_data_root}\{active_channel}\cache\` (`ships_desc_enhancements.ini`, `components_desc_enhancements.ini`, `ship_weapons_desc_enhancements.ini`, `fps_weapons_desc_enhancements.ini`, `mission_rewards_enhancements.ini`, `commodity_crafting_enhancements.ini`) |
| Backups | `{user_data_root}\{active_channel}\backups\` (max 5, oldest auto-deleted) |
| Game file | `{sc_install_root}\{active_channel}\data\Localization\english\global.ini` — `AppSettings.get_global_ini_path()` |
| P4K tools | `assets/unp4k/` (`unp4k.exe`, `unforge.exe`) |
| DataForge patches | `patches/` (JSON files mirroring DataForge layout; applied post-extraction) |
| Help/About | `docs/HELP.md`, `docs/ABOUT.md` — bundled under `docs/` via `SmartCitizen.spec` (and `scripts/build/build_exe.py` for the CLI path); rendered in-app via `get_resource_path("docs/HELP.md")` so dev and frozen resolve symmetrically |
| Legal tab | `docs/LEGAL.md` — CIG community-content compliance, license summaries, privacy/data-handling disclosure, AI-use statement. Bundled via `SmartCitizen.spec` (source `docs/LEGAL.md`, dest `docs`); same markdown→HTML pipeline as About |
| Linux/Wine guide | `docs/LINUX.md` — user-facing Wine-prefix walkthrough; not loaded by the app |
| Release notes | `docs/{X.Y.Z}-RELEASE-NOTES.md`. Release workflow at `.github/workflows/release.yml` looks here first; falls back to repo root for pre-1.4.1 re-runs |

## Common Modification Points

| Task | File | Key Function |
|------|------|-------------|
| Add/change table columns | `src/gui/main_window.py`, `src/gui/string_table_model.py` | `setup_string_table()`, `NUM_COLUMNS` + `COL_*` constants (also referenced by `entry_filter.py`'s getter tuple) |
| Add/change filters (UI wiring) | `src/gui/main_window.py` | `apply_filters()`, `on_filter_changed()` |
| Change row-filter logic | `src/utils/entry_filter.py` | `filter_entry_indices()` (delegated to from `MainWindow._filtered_entry_indices`) |
| Change per-column filter widgets | `src/gui/filter_header.py` | `FilterHeaderView` |
| Change category extraction | `src/models/string_model.py` | `StringEntry.extract_category()` |
| Modify INI parsing | `src/parser/ini_parser.py` | `parse_ini_file()` |
| Change merge logic | `src/merger/ini_merger.py` | `merge_sources_by_hierarchy()` |
| Change overrides persistence | `src/utils/user_ini_manager.py` (save) / `src/parser/ini_parser.py` (load) | `save_user_ini()`, `load_overrides()` |
| Change user INI import behavior | `src/gui/import_dialog.py`, `src/utils/user_ini_manager.py` | `ImportConflictDialog` |
| Change table model | `src/gui/string_table_model.py`, `src/gui/main_window.py` | `StringTableModel`, `COL_*` constants, `setup_string_table()` |
| Modify auto-update | `src/utils/updater.py` | `check_for_updates()`, `download_base_file()` |
| Change backup behavior | `src/gui/main_window.py` | `manage_backups()` |
| Modify P4K extraction | `src/utils/pak_extractor.py` | `extract_dataforge()` |
| Change enhancements generation | `scripts/generate_enhancements_ini.py` | (standalone script) |
| Add performance profiling | `src/utils/perf.py` | `@timed` decorator |
| Change user data paths | `src/utils/settings.py` | `AppSettings.get_user_data_dir()` |
| Change DataForge freshness | `src/utils/settings.py`, `src/gui/main_window.py` | `dataforge_cache_is_fresh()` |
| Change stats/favorites UI | `src/gui/enhancements_tab.py` | `setup_ui()` |
| Manage Config tab UI | `src/gui/config_tab.py` | `setup_ui()`, drag-drop hierarchy |
| Manage Enhancements tab UI | `src/gui/enhancements_tab.py` | `setup_ui()`, stats toggle, favorites config |
| Change in-app logging | `src/gui/log_tab.py` | `LogTab`, `_QtLogHandler` |
| Change user.cfg behavior | `src/utils/user_cfg.py` | `ensure_user_cfg_language()` |
| Fix an upstream DataForge data bug | `patches/<category>/.../<name>.patch.json`, `src/utils/dataforge_patcher.py` | `apply_patches()` |
| Change parallel progress reporting | `src/utils/progress_sink.py` | `ProgressSink.advance()` |
| Change post-apply validation | `src/utils/applied_file_validator.py` | `validate_applied_file()` (wrapped by `MainWindow._validate_applied_file`) |
| Change About / Help markdown rendering | `src/gui/markdown_renderer.py` | `markdown_to_html()` (wrapped by `MainWindow.markdown_to_html`, which supplies palette colours) |
| Add or modify a background worker | `src/gui/workers.py` | The relevant `*Worker` class (subclass of `QThread`) |
| Change resource-path resolution (bundle vs dev) | `src/utils/resource_path.py` | `get_resource_path()`, `resolve_patches_dir()` |
| Toggle portable vs registry build mode | `scripts/build/build_exe.py`, `src/utils/build_mode.py` | `--portable` flag, `IS_PORTABLE` |
| Change portable-mode settings backend | `src/utils/json_settings.py`, `src/utils/settings.py` | `JsonSettings`, `AppSettings._backend` |
| Skip clean enhancement categories on re-extract | `src/utils/dataforge_diff.py`, `src/utils/pak_extractor.py` | `update_manifest()`, `dirty_categories()`, `CATEGORY_SUBTREES` (mirrors `DATAFORGE_KEEP_SUBPATHS`) |
| Change Export Loc-Pack zip behavior | `src/utils/locpack_exporter.py` | `default_locpack_filename()`, `write_locpack_zip()` |
| Change apply-time launcher watermark | `src/gui/main_window.py` | `_stamp_frontend_version()`, `_FRONTEND_VERSION_KEY`, `_FRONTEND_VERSION_STAMP_RE` |
| Change Modified/Enhanced/Unmodified/New status logic | `src/parser/ini_parser.py` | `_determine_status_from_source()` |
| Adjust close-time user.ini autosave guard | `src/utils/user_ini_manager.py` | `should_autosave_user_ini()` |
| Change "Reset user.ini" tool behavior | `src/utils/user_ini_manager.py`, `src/gui/config_tab.py` | `reset_user_ini()` (+ Config-tab button wiring) |
| Move DataForge XML cache out of Documents | `src/utils/settings.py` | `migrate_dataforge_cache_to_local()`, `get_dataforge_cache_dir()` |
| Add a tag-builder element/style/category | `src/utils/tag_builder.py` | `CATEGORY_ELEMENT_KINDS`, `STYLES_BY_KIND`, `DEFAULT_TAG_CONFIGS`, `render_tag()` |
| Change Tag Builder UI / live preview | `src/gui/enhancements_tab.py`, `src/gui/tag_mapping_dialog.py` | `_PREVIEW_VALUES`, `TagMappingDialog` |
| Persist/load tag configs | `src/utils/settings.py` | `AppSettings.get_tag_config()`, `set_tag_config()`, `get_all_tag_configs()` |
| Add a new stats-enhancement generator (e.g. mining/salvage analogue) | `scripts/generate_enhancements_ini.py` | `enhancements_mining_laser`, `enhancements_salvage_tool` (reference pattern); register in `CATEGORY_SUBTREES` + `DATAFORGE_KEEP_SUBPATHS` |
| Change crash-dump behavior | `src/utils/crash_handler.py`, `src/main.py` | `install_crash_handler()`; install site is the early `main()` setup, before the QApplication is constructed |
| Change error-dialog cooldown / coalescing | `src/gui/main_window.py`, `src/gui/error_dialog.py` | `MainWindow._show_error_dialog()` (cooldown / spam protection lives on the slot, not the `ErrorDialogHandler`) |
| Move the DataForge cache off the default path | `src/utils/settings.py`, `src/gui/config_tab.py` | `AppSettings.get_cache_dir_override()` / `set_cache_dir()` (1.4.1+; independent of the user-data override) |

## Version & Release

### Branching model

Smart Citizen uses **long-lived release branches as integration targets**, not feature-branch-into-main.

- After a release ships, the next `release/X.Y.Z` branch opens off `main` and `VERSION.TXT` bumps on it. That branch becomes the integration target until it ships.
- **The version in the branch name signals scope.** A patch bump (e.g. `release/1.4.1`) is reserved for **bug fixes and minor polish** — anything bigger waits for the next minor or major. Use the branch version as a scope filter when reviewing or proposing changes: don't land a new feature on a patch branch without flagging the mismatch.
- **PRs target the active `release/X.Y.Z`, not `main`.** `main` only receives the release-branch merge.
- When the integration branch is feature-complete and stable, **the user adds the `build-installer` label to a PR** to produce a tester installer artifact (see *Tester pre-release installers*). Tests run against those artifacts before any merge to `main`.
- **Merging `release/X.Y.Z` → `main` is the release trigger.** That merge runs the per-release checklist below (tag, GitHub release, Discord webhook). Until then, no commit on the release branch is "released."

Don't propose tagging, drafting release notes, or merging to `main` mid-integration — the user drives that handoff. During integration, normal work is just landing PRs on the release branch.

### Release checklist (release/X.Y.Z → main)
1. `VERSION.TXT` should already match the branch name from when it opened — confirm (sole source of truth; `installer.iss` reads it via ISPP at compile time).
2. Build the PyInstaller onedir: `.venv/Scripts/python.exe scripts/build/build_exe.py`
3. Compile the installer (Inno Setup is per-user; invoke via PowerShell): `powershell -NoProfile -Command "& 'C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"`
4. Test the installer from `dist/SmartCitizen-{VERSION}-Setup.exe`
5. Merge `release/X.Y.Z` into `main`, then tag on `main` (`git tag -a vX.Y.Z -m "Release vX.Y.Z"`), push branch + tag.
6. Create the GitHub release and attach `dist/SmartCitizen-{VERSION}-Setup.exe` (installer only; portable onefile exe is retired).
7. Open the next `release/X.Y.(Z+1)` off `main` and bump `VERSION.TXT` — the new integration target.

Discord notification fires via GitHub Actions (`scripts/discord_notify.py`) when `DISCORD_RELEASE_WEBHOOK_URL` secret is set.

**Tester pre-release installers**: `.github/workflows/installer-preview.yml` builds a downloadable `SmartCitizen-{VERSION}-Setup.exe` artifact outside the standard release flow. Triggers: (1) `workflow_dispatch` from the Actions tab against any branch, (2) adding the `build-installer` label to a PR (later pushes to the labeled PR rebuild via `synchronize`; remove the label to stop rebuilds). In the integration-branch model this is the *primary* signal that a release is near test sign-off — when the user adds the label, treat the active release branch as approaching ship. Artifact: `smartcitizen-installer-{SHA}`, 30-day retention (testers need lead time vs. CI's 7). The `concurrency` group cancels in-flight builds when a newer commit lands on the same PR / branch.

**Tester pre-release portable builds**: `.github/workflows/portable-preview.yml` is the sibling of installer-preview for the portable variant. Same triggers and gate, but keyed off the `build-portable` label and `workflow_dispatch`; it runs `build_exe.py --portable` and uploads the `SmartCitizen-Portable-v{VERSION}.zip` (a no-install onedir — unzip, run the `.exe`, portable mode writes `data/` next to it). Artifact: `smartcitizen-portable-{SHA}`, 30-day retention, same concurrency cancel behavior. Use it when a tester wants to run without installing or to smoke-test portable-mode behavior (no registry) before a release.

**Preview artifact cleanup**: `installer-preview-cleanup.yml` (workflow name "Preview Artifact Cleanup") deletes the tester-build artifacts on PR merge so storage doesn't accumulate stale builds. It cleans *both* preview workflows (installer + portable) — its `WORKFLOWS` list must stay in sync with any new `*-preview.yml` that uploads per-PR artifacts.

## Debugging

- **Registry**: `regedit` → `HKEY_CURRENT_USER\Software\Osiris DevWorks\Smart Citizen` (live tree). Pre-0.9 installs leave a parallel `Osiris DevWorks\SC Localization Editor` tree the in-app migrator drains on next launch.
- **User data path**: if `Documents` is redirected (OneDrive), Registry stores the override under `user_data_dir` (legacy/manual alias `UserDataDir` also honored); delete that value to reset and auto-detect on next run.
- **Threading hangs**: check `worker.quit()` + `worker.wait()` in finished slots. Watch the Log Tab.
- **File encoding**: parser expects UTF-8; BOM or other encodings fail silently. Ensure cache files are UTF-8 no-BOM.
- **GitHub API rate limit**: unauthenticated, 60 req/hr per IP. Check updater logs if auto-update stalls.
- **Overrides not loading**: verify `{user_data_root}\{active_channel}\user.ini` exists with `key=value` format (no sections). A legacy `Documents\SC Localization Editor\overrides.ini` triggers both the rename (`overrides.ini` → `user.ini`) and the channel-nesting migration lazily on next launch.
- **Performance**: use `@timed` on slow functions and check elapsed times in DEBUG logs.

## Dependencies

- **PyQt6** (>=6.10.0) — GUI framework
- **pyinstaller** (>=6.3.0) — executable builder
- **pyperclip** (>=1.8.2) — clipboard
- **lxml** (>=5.0) — XML parsing for DataForge entity XMLs (`src/utils/dataforge_patcher.py`, mission classifiers in `scripts/generate_enhancements_ini.py`)

Windows-only by default (Windows Registry via QSettings in the standard build; portable builds skip the registry and write a JSON file next to the `.exe`). Python 3.9+, 3.10+ recommended.
