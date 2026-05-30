# Plan: cargo missions missing mission information (#102)

Status: **investigation + plan** (not yet implemented). Unlike the other
1.5.0 fix PRs, this one captures the root-cause analysis and the intended fix
so the implementation can be done and validated against real data with care.
Producing *wrong* mission XP/rep is worse than the current missing-info state,
so this deserves a deliberate, fixture-backed implementation rather than a
rushed change.

## Symptom

Most Cargo / delivery missions show no mission-information block (rep tier, XP,
etc.) in their description. Reporter (Narull) saw details on ~3 of 39 cargo
missions. Confirmed still present on 1.4.2.

## What we already know

- Cargo/delivery missions are defined in `missionbroker/pu_missions`
  (~1,311 of 2,558 reference cargo/haul/delivery/freight), **not** in
  `contracts/contractgenerator`. Only a handful have a contractgenerator
  entry, which is why only those few get enriched. (This is the #95/#102
  split finding.)
- The mission XP/rep block is added by the pu_missions augmentation pass in
  `_run_gen_missions` (`scripts/generate_enhancements_ini.py`). A mission is
  **skipped** when `_extract_mission_xp(root, reputation_lookup) <= 0`
  (the `no_rep_data` bucket — the generator log shows ~645 skipped).
- The cargo missions **do** carry rep data inline, e.g.:
  ```xml
  <SReputationAmountParams factionReputation="…" reputationScope="…"
                           reward="36d5786c-5258-48ca-a3b8-fefb5838e143" />
  ```
  The `reward` attribute is a UUID reference (not a direct amount).
- `_extract_mission_xp` resolves that UUID via `reputation_lookup[uuid]`.
- The referenced reward definition **exists** in the very dir the lookup
  builder scans:
  `reputation/rewards/missionrewards_reputation/reputationrewardamount_positive_xs.xml`
  → `<SReputationRewardAmount … reputationAmount="500"
     __ref="36d5786c-5258-48ca-a3b8-fefb5838e143" />`
- Yet `_build_reputation` reports only **54** definitions loaded, and 645
  missions still skip. So the gap is: **the reward UUIDs these cargo missions
  reference are not ending up in `reputation_lookup`.**

## The open question to answer first

Determine *why* the cargo missions' reward UUIDs miss `reputation_lookup`.
Two candidate causes (confirm with the LIVE cache before coding):

1. **Coverage:** `_build_reputation` (line ~5196) keys/filters reward records
   in a way that drops the `reputationrewardamount_*` family (e.g. only a
   subset of `__type`/editorName, or a different sub-path), so the cargo
   reward UUIDs never enter the lookup even though the files are scanned.
2. **Indirection:** the cargo `reward` UUID points at an intermediate record
   (a per-scope wrapper) that itself references the `reputationrewardamount_*`
   leaf, so a single-hop lookup misses it and a second resolve hop is needed.

A 20-minute sweep of the LIVE cache (map the 645 skipped missions' reward
UUIDs → which records define them → whether `_build_reputation` includes those
records) settles which cause it is.

## Proposed fix

- Extend `_build_reputation` so every `SReputationRewardAmount` under
  `missionrewards_reputation` (keyed by `__ref` → `reputationAmount`) is in the
  lookup, plus any one-hop indirection the cargo rewards use.
- With the lookup complete, `_extract_mission_xp` returns a positive value for
  the cargo missions, the `no_rep_data` skip no longer fires, and the existing
  augmentation emits their mission-information block. **No change to the
  per-mission output format** — only lookup coverage.

## Validation (must-have before merge)

- The existing ground-truth diagnostics already exist for exactly this:
  `scripts/diff_mission_rewards_channels.py`, `scripts/diff_bp_*` and the
  `kraken_*` / `missions_*.csv` fixtures. Use them to confirm:
  - the ~645 previously-skipped cargo missions now carry XP/rep,
  - the XP values match known-good missions (no regression to the 54 that
    already resolved),
  - no mission that should stay un-augmented suddenly gains a bogus value.
- Add a unit test that feeds a fabricated cargo mission XML (inline
  `missionResultReputationRewards` → reward UUID) plus a minimal reward-def
  set through `_extract_mission_xp` / the augmentation and asserts the
  mission is no longer skipped.

## Why this is a separate, careful change

The fix is small in code but high-blast-radius in output: it changes the
mission-rewards INI for hundreds of missions. It must be validated against the
ground-truth fixtures so we don't ship incorrect XP/rep, which would be a worse
regression than the missing block this issue reports.
