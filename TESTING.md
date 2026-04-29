# Testing Guide — Open Strings

This guide explains how to run both manual and automated tests.

---

## Quick Start

### Manual Testing

Run the app (`uv run python src/main.py`) and work through the manual workflow in the section below.

### Automated Testing

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/ -v

# Run only critical tests
uv run pytest tests/ -v -m critical

# Run only unit tests (fast)
uv run pytest tests/ -v -m unit

# Run with coverage
uv run pytest tests/ --cov=src --cov-report=html
```

---

## Test Structure

### Unit Tests (`tests/test_core.py`)

**Coverage**: Core functionality that doesn't require GUI or external tools

**Test Classes**:

- `TestIniParsing` - INI file parsing, encoding handling, edge cases
- `TestMerging` - Multi-source merge logic, hierarchy order, priority
- `TestStringEntry` - Data model, category extraction, status determination
- `TestUserIniManagement` - Saving/loading custom edits to user.ini
- `TestErrorHandling` - Error handling, graceful failures
- `TestStatsIntegration` - Enhancement entry merging

**Run these tests**:

```bash
pytest tests/test_core.py -v

# Quick smoke test (use after code changes)
uv run pytest tests/test_core.py -v -m unit
```

### P4K Extraction Tests (`tests/test_pak_extraction.py`)

**Coverage**: P4K extraction pipeline, DataForge cache, filtered-copy helper

**Test Classes**:

- `TestDataForgeCache` - Cache freshness detection
- `TestDataForgeExtraction` - Pipeline error handling (mocked subprocess)
- `TestDataForgeKeepList` - Keep-list / generator read-path contract (regression)
- `TestCopyFilteredRecords` - Filtered cache copy helper

**Run these tests**:

```bash
uv run pytest tests/test_pak_extraction.py -v

# Run with logging to see what's being tested
uv run pytest tests/test_pak_extraction.py -v -s
```

---

## Running Tests by Category

### Critical Path Tests (must pass before release)

```bash
uv run pytest tests/ -v -m critical
```

Tests:

- Data loading (ini_parser)
- Multi-source merging (ini_merger)
- Category extraction (string_model)
- Stats generation & integration
- Overrides persistence
- Error handling

### Quick Smoke Test (run after small changes)

```bash
uv run pytest tests/test_core.py::TestIniParsing -v
uv run pytest tests/test_core.py::TestMerging -v
uv run pytest tests/test_core.py::TestStringEntry -v
```

### Full Test Suite (run before major releases)

```bash
uv run pytest tests/ -v --tb=short
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

## Test Coverage Goals

| Component              | Target Coverage | Current |
| ---------------------- | --------------- | ------- |
| `ini_parser.py`        | 95%             | \_      |
| `ini_merger.py`        | 95%             | \_      |
| `string_model.py`      | 90%             | \_      |
| `overrides_manager.py` | 90%             | \_      |
| `pak_extractor.py`     | 80%             | \_      |
| `updater.py`           | 70%             | \_      |
| GUI (`main_window.py`) | Manual only     | ✓       |

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
3. **Check Windows Registry** for corrupted settings:
   ```
   regedit → HKEY_CURRENT_USER\Software\Joni Hayes\Open Strings
   ```
4. **Check user data** in `Documents\Open Strings\<channel>\`
5. **Check backup files** to see what was written to game

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

**Solution**: Run pytest from project root:

```bash
cd C:\Users\aabou\PycharmProjects\sc-localization-editor
pytest tests/ -v
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

## Adding New Tests

When adding new features, add tests:

1. **Decide: Unit or Integration?**
   - Unit: No file I/O, no external tools, fast (<100ms)
   - Integration: Uses real files, external tools, slower

2. **Add to appropriate file**:
   - Core logic → `test_core.py`
   - P4K/stats → `test_pak_extraction.py`
   - GUI → Manual testing checklist (for now)

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
**Passed**: **  
**Failed**: **

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

## CI/CD Integration (Future)

To integrate tests into GitHub Actions:

1. Create `.github/workflows/test.yml`
2. Run pytest on every push
3. Generate coverage reports
4. Comment on PRs with results

Example workflow:
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt pytest pytest-mock
      - run: pytest tests/ -v --tb=short
````

---

## Questions?

- **Can't run tests?** Check `pytest --version` and ensure it's installed
- **Test import errors?** Verify `src/` path is correct in `pytest.ini`
- **Need help writing tests?** Look at existing tests in `test_core.py` for examples
- **Found a bug?** Add a regression test that reproduces it, then fix the bug

---

**Last Updated**: 2026-04-09  
**For Version**: 0.6.0 and later
