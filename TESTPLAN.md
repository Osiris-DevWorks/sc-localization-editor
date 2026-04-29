# Open Strings 1.0 Pre-Release Test Plan

Focused on the UX and integration paths `pytest` can't reach. Automated coverage already exists for parsing/merging/missions/patcher/pak-filtering/channel layout/progress — don't duplicate.

**Before starting:** `pytest tests/ -n auto` must pass green. Build a fresh `OpenStrings-1.0.0-Setup.exe` and drive the tests below against that installer (not the dev checkout).

---

## 1. Install & upgrade matrix

Run against the built `dist/OpenStrings-1.0.0-Setup.exe`.

- [ ] **Fresh install** on a machine that has never had Smart Citizen or SC Localization Editor — app launches, tutorial fires on first show, no legacy registry nodes present
- [ ] **Upgrade from 0.8.x** (legacy registry `SC Localization Editor`, legacy folder `Documents\SC Localization Editor\`) — `migrate_registry_appname` runs, marker `_migrated_from_legacy_appname` appears under new node, old subtree deleted; folder auto-migrated to `Documents\Smart Citizen\`; `overrides.ini` → `user.ini` rename works; paths/favorites/theme preserved
- [ ] **Upgrade from 0.9.2** (flat `Documents\Smart Citizen\` layout) — `migrate_game_path_to_channel_layout` splits `GAME_INSTALL_PATH` into `SC_INSTALL_ROOT` + `ACTIVE_CHANNEL`; flat cache/backups/user.ini move into `LIVE/`; marker gates idempotence on relaunch
- [ ] **Upgrade 0.9.3 → 1.0** (reinstall) — no duplicate migrations, no data loss, no zombie uninstall entry
- [ ] **OneDrive-redirected Documents** — installer's `IsDocsOnOneDrive` page fires; user redirects to local path; `USER_DATA_DIR` override written; app respects it
- [ ] **OneDrive + override already set** — installer skips the redirect page (`HasDataDirOverride`)
- [ ] **Uninstall → reinstall** — preserves `backups/`, registry settings, and `user.ini` across the cycle
- [ ] **Uninstall** does NOT delete `Documents\Open Strings\backups\`

## 2. Per-channel end-to-end

For **each channel you have installed** (minimum: LIVE; ideally also PTU):

- [ ] Config tab shows a Channel combo; selecting persists; `channel_changed` triggers table reload without restart
- [ ] Channels without `{root}\{channel}\Data.p4k` are disabled with tooltip
- [ ] `Channel: {NAME}` shown in status bar; SC-version string carries suffix (e.g. `SC v4.7.176-PTU`)
- [ ] Switching channels triggers the enhancement-categories prompt **every** switch (not just first)
- [ ] Switching to an **un-extracted** channel prompts to extract, doesn't load stale data
- [ ] `Documents\Open Strings\{channel}\` has its own `cache/`, `backups/`, `dataforge/`, `user.ini` — zero cross-contamination
- [ ] **PTU DataForge extraction succeeds** (validates bundled `unforge.exe` v4.0.83 PTU DCB fix)
- [ ] `⚠` hint appears when the stored active channel's P4K is missing

## 3. Core workflow — golden path

Per active channel:

- [ ] **Extract from Data.p4k** — determinate progress bar, shows unp4k → unforge → cache filter phases, completes without Log tab errors
- [ ] Cache size sanity: `cache\dataforge\` ≈ 1.3 GB / ≈ 28k files (not the old 2.4 GB / 58k). Larger = `_copy_filtered_records` regressed
- [ ] **Generate Enhancements** — determinate progress, no "Ready" mid-run, all 7 output INIs produced
- [ ] **Post-extract auto-reload** — strings load into the table automatically when Extract finishes; table populates instantly, no freeze on 87k+ rows
- [ ] **Edit a string** — autosaves to `user.ini`, Modified status appears, survives app restart
- [ ] **Apply to Game** — timestamped backup created; 5-backup cap enforced; written file validates against stock keys
- [ ] **Restore Backup** — last backup restores cleanly
- [ ] **Clear Localization** — reverts game to vanilla without touching `user.ini`; reminds user to re-Apply
- [ ] **Open Localization Dir** — opens the active-channel `english/` folder

## 4. In-game rendering smoke checks

Boot SC (LIVE) after an Apply. Spot-check each category:

- [ ] **Ship description** shows `--- STATS ---` block with SCM/fuel/cargo/weapon loadout/armor
- [ ] **Component description** shows plain-text stats (no raw `<EM3>` tags)
- [ ] **Ship weapon / FPS weapon** descriptions render stats block
- [ ] **Missile** name tagged `[S{n}-CS/EM/IR]`; bomb `[S{n}]`
- [ ] **Mission title** shows `[BP]` / `[BP*]` only where a BP pool exists; no `[BP?]` on bounty missions
- [ ] **Mission description** shows `MISSION DETAILS`, `POTENTIAL BLUEPRINTS` (with regional `[Stanton]` / `[Pyro RegionA, Pyro RegionB]` subheaders), and `ITEM REWARDS` under `<EM3>` — EM tags render
- [ ] **Commodity with `[CF]` tag** shows crafting cross-references — test **Aluminum** (verifies refined+ore pairing)
- [ ] **Jorrit Dossier P2M4** shows Icebox pool flavor (STARC-176797 loc-string workaround)
- [ ] **Jorrit Dossier P2M1** shows its own pool + labeled P2M4 appendix
- [ ] **No sentinel-loc leaks** (e.g. hauling contracts' primary objectives do not show another mission's reward block)
- [ ] **Wikelo/TheCollector ships** appear under Ships category in the app table, not Missions
- [ ] **Hex Shield Generator** shows name tag + stats (underscore/no-underscore inverse propagation)
- [ ] **Favorites** — star a ship, verify `*` prefix sorts it to top in ASOP

## 5. UI regression checks

- [ ] **Tutorial** fires on first fresh-install launch; Skip leaves completion flag unset (re-fires next launch); Finish records version (no re-fire); **Tutorial** toolbar button re-triggers; each coach-mark targets the correct widget; tab auto-switch works; spotlight follows on window resize/move
- [ ] **Help dock** — opens/closes via toolbar; floats; moves L/R; state persists across restart
- [ ] **Help content** — Markdown bold/italic/links render inline in paragraphs, list items, headers; inline `` `code` `` stays literal
- [ ] **Themes** — swap through SCLE / Light / Dark / ODW; verify progress bar animates with contrast; secondary text has contrast; tooltips styled; help panel re-renders
- [ ] **Tooltips** — hover any toolbar/filter/combo widget ≈ 800ms → tooltip appears; immediately hover an adjacent widget, next tooltip also takes 800ms (not instant)
- [ ] **Filter row** — per-column filters debounce; Clear Filters resets all
- [ ] **Log tab** — level filter works; auto-scroll works; export works
- [ ] **Status bar** — no stale "Ready" during extract/generate/load; Channel indicator always present; SC version carries channel suffix

## 6. Import INI workflow

- [ ] Import an external INI with overlapping keys; `ImportConflictDialog` offers keep / imported / append / prepend / custom; result lands in `user.ini`; merge order still respects user-as-last

## 7. Declarative patches & workarounds

- [ ] Delete `cache\dataforge\` and re-extract — patches under `patches/` apply idempotently
- [ ] Locstring workaround idempotence — regen enhancements twice; second run doesn't double-append to `P2M1_Repeat_desc`
- [ ] HELP.md "Known Issues" section renders; lists STARC-176797 with CIG Issue Council link

## 8. Edge cases to deliberately break

- [ ] Rename `cache\dataforge\` away → Extract prompts again; no crash
- [ ] Missing `Data.p4k` → clean error, no crash
- [ ] Point SC install at an invalid path → Config validation hint; Apply fails gracefully
- [ ] Delete `user.ini` → regenerates on next edit; legacy `overrides.ini` auto-renames on first read
- [ ] Corrupt `ACTIVE_CHANNEL` registry value → falls back cleanly
- [ ] Hold a file open in `cache\dataforge\` during Clear Cache → `_robust_rmtree` retries and succeeds, or surfaces a clear error

## 9. Documentation read-through (explicit 1.0 ROADMAP item)

- [ ] `README.md` — features, quick start, acknowledgments (unp4k included)
- [ ] `ABOUT.md` — renders in About tab; bulleted acks render correctly
- [ ] `HELP.md` — renders in Help dock; Config tab section matches current UI; Known Issues section current
- [ ] `CLAUDE.md` — no stale 0.8.x references

## 10. Release artifact sanity

Before tagging 1.0:

- [ ] `VERSION.TXT` bumped to `1.0.0`
- [ ] `pytest tests/ -n auto` passes clean
- [ ] Installer built from the `1.0.0` commit; SHA recorded
- [ ] Fresh-VM install test (section 1, row 1) on the final `1.0.0` installer
- [ ] GitHub release drafted; installer uploaded; Discord webhook fires
- [ ] Tag `v1.0.0` points at the built commit — do not repeat the 0.9.3 tag drift
