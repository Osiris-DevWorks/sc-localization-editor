# Open Strings Roadmap

> Upstream Smart Citizen history (0.1.x – 1.0.0) is in [UPSTREAM-HISTORY.md](UPSTREAM-HISTORY.md).

## 1.1.0 — Initial Fork Release

- [x] Fork from Smart Citizen 1.0.0 (Osiris DevWorks)
- [x] Rebrand to Open Strings — app name, window title, About/Help documentation, data directory (`Documents\Smart Citizen\` → `Documents\Open Strings\`)
- [x] Remove Smart Citizen / Osiris DevWorks branding, donation links, and ODW Discord references
- [x] Remove unused upstream splash image
- [x] Add Check for Updates — checks `jonigirl/open-strings` GitHub releases on startup (6-hour interval) and via toolbar button
- [x] Change journal annotation tag from `[SmC]` to `[OS]`

## 1.1.1 — Maintenance

- [ ] Test and verify compatibility with Star Citizen 4.8
- [ ] Review and update localization tag handling for any 4.8 changes
- [ ] General app testing and fixes as needed

### Testing infrastructure (completed during 1.1.0 → 1.1.1)

- [x] Pytest config consolidated into `pyproject.toml`; `tests/pytest.ini` removed
- [x] Coverage floor enforced at 65%; GUI files excluded from measurement
- [x] GitHub Actions CI: lint on ubuntu, tests on windows; uv caching; coverage.xml artifact
- [x] `StringTableModel` covered by 85 automated tests via `pytest-qt`; two Qt compliance bugs found and fixed
- [x] `ini_parser.py` coverage raised from 54% to 93% with 13 new tests
- [x] Overall non-GUI coverage: 88% across 413 tests
