# Open Strings Roadmap

> Upstream Smart Citizen history (0.1.x – 1.0.0) is in [UPSTREAM-HISTORY.md](UPSTREAM-HISTORY.md).

## 1.1.0 — Initial Fork Release

- [x] Fork from Smart Citizen 1.0.0 (Osiris DevWorks)
- [x] Rebrand to Open Strings — app name, window title, About/Help documentation, data directory (`Documents\Smart Citizen\` → `Documents\Open Strings\`)
- [x] Remove Smart Citizen / Osiris DevWorks branding, donation links, and ODW Discord references
- [x] Remove unused upstream splash image
- [x] Add Check for Updates — checks `jonigirl/open-strings` GitHub releases on startup (6-hour interval) and via toolbar button
- [x] Change journal annotation tag from `[SmC]` to `[OS]`

## 1.1.1 — Attribution and legal patch

- [x] Add MIT attribution for bundled unp4k / unforge tools to NOTICE.md
- [x] Add RSI / Data.p4k disclaimer to README
- [x] Install LICENSE and NOTICE.md alongside app via installer

## 1.1.2 — Upstream fixes port + maintenance

- [x] Port radar name tags from upstream 1.1.0: `[CLASS-S{size}-{grade}]` annotations for radar components, matching the existing pattern for shields, power plants, coolers, and quantum drives
- [x] Port radar sibling-key propagation from upstream 1.1.0: `"RADR"` added to `comp_types` so radar stat blocks propagate from `_SCItem` keys to their non-SCItem siblings
- [x] Fix Custom Value cell editor losing content on double-click: `EditRole` now returns `entry.custom_value` in `StringTableModel.data()`, preventing the delegate from receiving `None` and erasing unsaved text
- [x] Fix Generate Enhancements and source reload wiping pending edits: snapshot/restore mechanism preserves un-Applied in-memory edits across all `_on_loading_finished` and `perform_merge_and_reload` paths
- [ ] Test and verify compatibility with Star Citizen 4.8
- [ ] Review and update localization tag handling for any 4.8 changes

### Testing infrastructure (completed during 1.1.0 → 1.1.1)

- [x] Pytest config consolidated into `pyproject.toml`; `tests/pytest.ini` removed
- [x] Coverage floor enforced at 65%; GUI files excluded from measurement
- [x] GitHub Actions CI: lint on ubuntu, tests on windows; uv caching; coverage.xml artifact
- [x] `StringTableModel` covered by 85 automated tests via `pytest-qt`; two Qt compliance bugs found and fixed
- [x] `ini_parser.py` coverage raised from 54% to 93% with 13 new tests
- [x] Overall non-GUI coverage: 88% across 413 tests
