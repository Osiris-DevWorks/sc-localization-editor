# Testing Guide — Open Strings

This guide explains how to run both manual and automated tests.

---

## Quick Start

### Manual Testing

Run the app (`uv run python src/main.py`) and work through the manual workflow in the section below.

### Automated Testing

```bash
# Install dependencies (includes dev group with pytest, pytest-qt, pytest-cov, etc.)
uv sync --all-groups

# Run all tests
uv run pytest tests/

# Run only critical tests
uv run pytest tests/ -m critical

# Run only unit tests (fast)
uv run pytest tests/ -m unit

# Run with HTML coverage report
uv run pytest tests/ --cov-report=html
```

All pytest settings (timeout, coverage, markers) are configured in `pyproject.toml` under `[tool.pytest.ini_options]`. No separate `pytest.ini` is needed.

---

## Test Structure

### Test files

| File                                    | What it covers                                                                               |
| --------------------------------------- | -------------------------------------------------------------------------------------------- |
| `test_core.py`                          | INI parsing, merging, StringEntry model, user INI management, stats integration              |
| `test_ini_parser.py`                    | Full `ini_parser.py` coverage: source loading, `load_sources_from_settings`, exception paths |
| `test_string_table_model.py`            | `StringTableModel`: data roles, flags, sort, filter, signals, Qt model compliance            |
| `test_channel_layout.py`                | Per-channel directory layout and isolation                                                   |
| `test_dataforge_patcher.py`             | DataForge enhancement patching logic                                                         |
| `test_entry_filter.py`                  | Entry filter matching                                                                        |
| `test_extracted_modules.py`             | Extracted module integration                                                                 |
| `test_ini_parser.py`                    | INI parser edge cases                                                                        |
| `test_missions.py`                      | Mission key handling and prefix detection                                                    |
| `test_pak_extraction.py`                | P4K extraction pipeline, DataForge cache, filtered-copy helper                               |
| `test_perf.py`                          | Performance utility helpers                                                                  |
| `test_progress_sink.py`                 | Progress reporting                                                                           |
| `test_retired_url_sources_migration.py` | Legacy URL source migration                                                                  |
| `test_settings.py`                      | AppSettings persistence and defaults                                                         |
| `test_updater.py`                       | Auto-update version checking                                                                 |
| `test_user_cfg.py`                      | User config file handling                                                                    |
| `test_user_ini_manager.py`              | User INI read/write                                                                          |
| `test_version.py`                       | Version string parsing                                                                       |
| `test_workers.py`                       | Qt worker thread signal contracts                                                            |

### Markers

```bash
uv run pytest tests/ -m unit        # Fast, isolated unit tests
uv run pytest tests/ -m critical    # Must-pass before release
uv run pytest tests/ -m integration # File I/O and external tool tests
uv run pytest tests/ -m slow        # P4K extraction (large file ops)
uv run pytest tests/ -m regression  # Tests for previously found bugs
```

---

## Running Tests by Category

### Critical Path Tests (must pass before release)

```bash
uv run pytest tests/ -m critical
```

### Quick Smoke Test (run after small changes)

```bash
uv run pytest tests/test_core.py tests/test_ini_parser.py tests/test_string_table_model.py
```

### Full Test Suite (run before major releases)

```bash
uv run pytest tests/ --tb=short
```

---

## Manual Testing Workflow

### 1. First Run Test (ensure no crashes on startup)

```bash
uv run python src/main.py
```

**Expected**: App launches cleanly, loads base file, displays table.

### 2. Core Features Test

- Load base file
- Verify ~80,000 entries in table
- Filter by category (Ships, Gear, Missions)
- Search for key (e.g., "shield")
- Edit an entry
- Apply to game
- Verify backup created
- Restart app and verify edit persists

**Time**: ~15 minutes

### 3. Enhancement Generation Test

1. Set game path in Config tab
2. Click "Extract DataForge from P4K" in the Enhancements tab
3. Wait for extraction to complete (~30 seconds - 2 minutes depending on system)
4. Verify enhancement INI files in `Documents\Open Strings\<channel>\cache\`:
   - `ships_desc_enhancements.ini`
   - `components_desc_enhancements.ini`
   - `ship_weapons_desc_enhancements.ini`
   - `fps_weapons_desc_enhancements.ini`
   - `mission_rewards_enhancements.ini`
5. Search for `vehicle_Desc` and verify entries show stats (e.g., "Max Speed: 210 m/s")

**Time**: ~5-10 minutes

### 4. Multi-Source & Merge Test

1. Config tab: Verify all sources are configured (Global, Contracts, Ships, Commodities, Gear)
2. Drag a source to reorder hierarchy (e.g., move Contracts above Global)
3. Click "Save Configuration & Merge"
4. Verify table updates with new merge order

**Time**: ~5 minutes

### 5. Error Handling Test

1. Set a source URL to invalid path (e.g., `https://invalid.url/file.ini`)
2. Click "Save Configuration & Merge"
3. Verify error dialog appears with helpful message
4. Click "Skip source"
5. Verify merge continues with remaining sources

**Time**: ~5 minutes

### 6. Extended Stability Test

- Keep app open for 15+ minutes
- Perform multiple edits (at least 5)
- Filter, search, apply multiple times
- Monitor console for errors (none should appear)
- Restart app and verify all edits persisted

**Time**: ~20 minutes

---

## Test Coverage

Coverage is measured automatically on every test run. GUI files (`main_window.py`, `config_tab.py`, etc.) are excluded — they are covered by the manual test plan in `TESTPLAN.md`.

### Current coverage (as of v1.1.2)

| Component               | Coverage | Notes                                                         |
| ----------------------- | -------- | ------------------------------------------------------------- |
| `ini_parser.py`         | 93%      | Lines 127–134 are dead code (category filter never triggered) |
| `ini_merger.py`         | 97%      |                                                               |
| `string_model.py`       | 75%      |                                                               |
| `string_table_model.py` | 99%      |                                                               |
| `overrides_manager.py`  | 100%     |                                                               |
| `pak_extractor.py`      | 55%      | GUI-driven extraction paths not reachable without a real P4K  |
| `updater.py`            | 97%      |                                                               |
| **Overall (non-GUI)**   | **84%**  | Floor enforced at 65% via `--cov-fail-under`; 446 tests       |

Coverage is uploaded as a `coverage.xml` artifact on every CI run (30-day retention).

---

## Debugging Failed Tests

### If a unit test fails:

1. **Read the error message** - it usually tells you exactly what's wrong

   ```bash
   pytest tests/test_core.py::TestMerging::test_merge_multiple_sources_respects_order -v
   ```

2. **Check the assertion** - look at the line number in the traceback

   ```python
   # Example: assert result['key2'] == 'contracts_value2' failed
   # Means the merge order wasn't respected
   ```

3. **Add debugging output**:

   ```bash
   pytest tests/test_core.py -v -s  # -s shows print() output
   ```

4. **Run just one test class**:
   ```bash
   pytest tests/test_core.py::TestMerging -v
   ```

### If a manual test fails:

1. **Note exact reproduction steps**
   - Check Log Tab for error messages or exceptions
2. **Check Windows Registry** for corrupted settings:
   ```
   regedit → HKEY_CURRENT_USER\Software\Joni Hayes\Open Strings
   ```
3. **Check user data** in `Documents\Open Strings\<channel>\`
4. **Check backup files** to see what was written to game

---

## Continuous Testing

### Before Each Commit

```bash
# Quick validation
pytest tests/test_core.py -v --tb=short
```

### Before Each Release

```bash
# Full suite + coverage
pytest tests/ -v --cov=src --cov-report=html --cov-report=term
```

---

## Known Issues & Workarounds

### Issue: "ModuleNotFoundError: No module named 'src'"

**Solution**: Run pytest from the project root using `uv run`:

```bash
cd C:\path\to\open-strings
uv run pytest tests/
```

### Issue: "ImportError: cannot import name 'StringEntry'"

**Solution**: Ensure `src/` is in Python path:

```bash
# pytest.ini already sets this, but if running manually:
set PYTHONPATH=%CD%\src
pytest tests/ -v
```

### Issue: P4K extraction tests fail (tools not in assets/)

**Solution**: These tests are mocked and don't require real tools. If you see:

```
FileNotFoundError: unp4k.exe not found
```

This is expected and tested in `TestDataForgeExtraction::test_extract_dataforge_handles_missing_tools`.

### Issue: Tests timeout

**Solution**: Some P4K extraction tests can be slow. Skip them:

```bash
pytest tests/ -v -m "not slow"
```

---

## Patch Testing — After Each Star Citizen Update

After CIG releases a patch, run this workflow to catch any enhancements breakage before users report it.

### 1. Extract and regenerate

1. Open the app → Enhancements tab → **Extract DataForge from P4K** (wait for completion)
2. Click **Generate Enhancements** and watch the log for `WARNING` lines

A warning like:

```
cooler: 0 enhancements generated despite 42 loc-key matches — DataForge XML structure may have changed
```

means CIG restructured that component's XML. The relevant `enhancements_*` function in
`scripts/generate_enhancements_ini.py` needs updating.

### 2. Audit attribute changes

Run the audit script to diff DataForge XML attributes against the previous patch snapshot:

```powershell
# First patch after adding the script — no previous snapshot yet:
uv run python scripts/audit_dataforge_attrs.py

# Subsequent patches — diff against the previous version's snapshot:
uv run python scripts/audit_dataforge_attrs.py --diff "$env:USERPROFILE\Documents\Open Strings\cache\dataforge_attrs_<prev_version>.txt"
```

Output flags:

- `← NOT YET HANDLED — review needed`: CIG added a new attribute. Open the relevant `enhancements_*` function and decide whether to surface it as a stat line.
- `← was being read` + listed under **REMOVED**: the XML was restructured and your parser is silently reading nothing. Fix immediately.
- `← already handled`: no action needed.

Snapshots are written to `Documents\Open Strings\cache\dataforge_attrs_<version>.txt` and `dataforge_attrs_latest.txt`.

### 3. Spot-check in the app

For any component category that had changes:

1. Search for a known item (e.g., `item_DescQDRV_ARCC_S03_Echo`) in the table
2. Verify the stats block is present and the numbers look plausible
3. Check the log tab for any `sync_key_variants: conflict` warnings on enhancement keys — these indicate a new `_SCItem` variant pattern that may need investigation

### 4. Run the automated suite

```bash
uv run pytest tests/ --tb=short
```

All 446 tests must pass before considering the patch verified.

---

## Adding New Tests

When adding new features, add tests:

1. **Decide: Unit or Integration?**
   - Unit: No file I/O, no external tools, fast (<100ms)
   - Integration: Uses real files, external tools, slower

2. **Add to appropriate file**:
   - Core logic → `test_core.py`
   - INI parser paths → `test_ini_parser.py`
   - P4K/stats → `test_pak_extraction.py`
   - `StringTableModel` (data roles, sort, filter, signals) → `test_string_table_model.py`
   - New GUI widget → create `tests/test_<widget_name>.py`, use `qtbot` and `qtmodeltester` fixtures from `pytest-qt`

3. **Follow the pattern**:

   ```python
   class TestNewFeature:
       @pytest.mark.unit
       def test_something_works(self):
           """Test description"""
           # Arrange
           input_data = {"key": "value"}

           # Act
           result = some_function(input_data)

           # Assert
           assert result == expected_value
   ```

4. **Run and verify**:
   ```bash
   pytest tests/test_core.py::TestNewFeature -v
   ```

---

## Test Results Template

Use this template to document test runs:

````markdown
# Test Results - v0.6.0 - [DATE]

**Tester**: [Name]  
**Environment**: Windows 10/11, Python 3.10, PyQt6

## Automated Tests

```bash
pytest tests/ -v --tb=short
```
````

**Results**:

- Total: \_\_ tests
- Passed: \_\_ ✓
- Failed: \_\_ ✗
- Skipped: \_\_

**Failed Tests**:
(List any failures with reproduction steps)

## Manual Tests

**Checklist**: TESTING_CHECKLIST_v0.6.0.md  
**Total Checks**: 120+  
**Passed**: \*\*  
**Failed**: \*\*

## Critical Path Tests

- [x] Application startup
- [x] Data loading
- [x] Multi-source merge
- [x] Stats generation
- [x] Apply to game
- [x] Backup/restore
- [ ] Clear localization

## Summary

- **Overall Status**: ✓ PASS / ✗ FAIL
- **Ready for Release**: YES / NO
- **Notes**:

````

---

## CI/CD

Tests run automatically on every push via GitHub Actions (`.github/workflows/ci.yml`):

- **Lint job** (`ubuntu-latest`): ruff lint + format check, mypy type check
- **Test job** (`windows-latest`): full pytest suite with coverage; uploads `coverage.xml` artifact (30-day retention)

Both jobs use uv caching (`uv.lock`) to keep run times fast.

To reproduce a CI failure locally:

```bash
# Lint (what CI runs)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run mypy src/

# Tests (what CI runs)
uv run pytest tests/ --cov=src --cov-report=xml
```

---

## Questions?

- **Can't run tests?** Check `pytest --version` and ensure it's installed
- **Test import errors?** Verify `src/` path is correct in `pytest.ini`
- **Need help writing tests?** Look at existing tests in `test_core.py` for examples
- **Found a bug?** Add a regression test that reproduces it, then fix the bug

---

**Last Updated**: 2026-04-09
**For Version**: 0.6.0 and later
````
