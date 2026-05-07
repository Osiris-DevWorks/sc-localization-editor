# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.2] - 2026-05-07

### Added

- Atkinson Hyperlegible as default body font with OpenDyslexic opt-in via Appearance settings
- Configurable data folder setting
- Atkinson Hyperlegible OFL attribution in NOTICE.md

### Fixed

- Header repaint stuck after layout pass
- Upgrade uninstall race condition
- QD stats loss; dynamic `comp_types`; zero-match warning
- Zip path traversal and tool gate re-entry issues
- Installer: `CurFinished` → `CurStepChanged`, `ScaleX/Y`, dead code removal
- Uninstall dialog: correct `CreateCustomForm` signature, remove `TBevel`
- Inno Setup batch parser error (goto labels instead of parenthesised else block)
- `TProgressBarStyle` → `TNewProgressBarStyle` in installer Pascal script

### Changed

- Preserve pending edits across Generate Enhancements and source reload
- Radar name tags and sibling-key propagation ported from upstream 1.1.0

## [1.1.1] - 2026-03-01

### Added

- Checkbox uninstall dialog for tools and edits cleanup
- `--no-prompt` flag to `build_exe.py`

### Changed

- Download unp4k/unforge at runtime instead of bundling binaries
- Bundled unp4k.exe updated to v4.0.83
- Signing prompt moved to start of `build_all.bat`
- Improved first-launch experience: auto-detect SC path, no error dialog on missing base.ini

### Fixed

- SC auto-detect reverted to standard paths only (removed unreliable drive scan)
- Concurrent.futures missing from PyInstaller bundle

## [1.1.0] - 2026-01-15

### Added

- Multi-channel support (LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW) with isolated workspaces
- Localization sourced directly from Data.p4k; no community mirrors required
- Inline editing with live preview rendering loc-tokens as styled HTML
- Auto-generated enhancements for ships, components, weapons, missions, journal, and commodities
- Safe apply with timestamped backups and automatic rollback on mismatch
- Check for Updates feature
- Test suite with CI coverage enforcement

[1.1.2]: https://github.com/jonigirl/open-strings/releases/tag/v1.1.2
[1.1.1]: https://github.com/jonigirl/open-strings/releases/tag/v1.1.1
[1.1.0]: https://github.com/jonigirl/open-strings/releases/tag/v1.1.0
