# scripts/CLAUDE.md

Standalone CLI scripts and the build pipeline. See the root `CLAUDE.md` for project context.

## Files

- `generate_enhancements_ini.py` — reads DataForge entity XMLs (no external JSON) → enhancement INI files in cache (ships, components, ship weapons, FPS weapons descriptions).
- `extract_components.py` — diffs base.ini against stock vanilla to produce components.ini.
- `gen_commodity_crafting.py` — generates `commodity_crafting_enhancements.ini` with crafting blueprint usage from DataForge XMLs.
- `compare_kraken_fixture.py` — research/reporting: diffs the `kraken_4.7.ini` ground-truth fixture against the generated `mission_rewards_enhancements.ini` to validate blueprint list output. Read-only.
- `diff_bp_kraken.py`, `diff_bp_annotations.py`, `diff_bp_csv_fixture.py` — read-only diagnostics for `[BP]` / `[BP?]` blueprint annotations on mission rewards. Each compares `mission_rewards_enhancements.ini` against a different ground truth (kraken fixture, applied LIVE `global.ini`, `missions_4.7.177.csv` per-variant fixture). Use when blueprint tags regress.
- `diff_base_ini_channels.py` — read-only: diffs cached `base.ini` between two SC channels (e.g. `LIVE` vs `PTU`) and reports added / removed / changed loc keys as a category-bucket summary plus optional full machine-readable list. Defaults to `%USERPROFILE%\Documents\Smart Citizen`; `--user-data` overrides for OneDrive-redirected installs.
- `diff_mission_rewards_channels.py` — companion to `diff_base_ini_channels.py` for the generated `mission_rewards_enhancements.ini`: diffs mission entries between channels and reports adds / removes / changes. Use to verify a CIG balance pass or new mission archetype propagated through the enhancements pipeline across `LIVE` / `PTU`.
- `discord_notify.py` — GitHub Actions release webhook.
- `build/build_exe.py`, `build/build_all.bat`, `build/clean_cache_for_distribution.py` — build pipeline; see `scripts/build/BUILD_INSTRUCTIONS.md`.

## Design decisions

### Mining-laser and handheld-salvage stat enhancements
`generate_enhancements_ini.py` exposes `enhancements_mining_laser` and `enhancements_salvage_tool` (new in 1.4.0) alongside the ship-weapon / FPS-weapon / component generators. The mining-laser generator reads ship-mounted mining heads under `ships/weapons/mining_laser_*.xml` and emits per-mode (Fracture / Extraction) beam stats plus `SEntityComponentMiningLaserParams` modifier overlays. The salvage generator reads `weapons/fps_weapons/grin_*salvage_repair*.xml` and emits per-mode (Repair / Salvage) rate / efficiency / ramp / energy / heat / wear. Both exclude data that needs a `globalParams` UUID resolved into a base entity (base mining-laser power/range, ship-mounted salvage equipment); the scope cut is documented at the function level and locked by `tests/test_mining_salvage_stats.py`.

### Medical consumables (CureLife pens) — a static, non-DataForge category
`enhancements_medical_consumables` (2.2.0) is the one enhancement generator with no DataForge XML dependency. Every other category derives its added text from entity XML stats; the CureLife pens' stock `item_Desc` is pure lore and never states what the item actually does, so there's no stat to extract. `MEDICAL_CONSUMABLE_EFFECTS` is a fixed dict of curated "Effect: …" copy keyed directly off the 7 known loc keys already in base.ini (the base AdrenaPen/CorticoPen/DeconPen/DetoxPen/MedPen/OpioPen/OxyPen — deliberately not the Xtra variants, BoostPen, or VitalityPen). Because it only reads `loc`, it's exempt from `CATEGORY_SUBTREES` (`dataforge_diff.py`) and `DATAFORGE_KEEP_SUBPATHS` (`pak_extractor.py`) — there's no XML subtree whose freshness would matter. It still needs its own checkbox: `ENHANCEMENTS_FILES` / `ENHANCEMENT_LABELS` / `ENHANCEMENT_CATEGORY_FILES` entries in `settings.py` under the key `medical_consumables`, output file `medical_consumables_enhancements.ini`. Locked by `tests/test_medical_consumables.py`.
