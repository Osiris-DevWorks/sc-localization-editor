# Open Strings — Quick Start Guide

## First Time Setup

On launch, Open Strings reloads any customizations from your previous session and checks for your Star Citizen installation — the installer pre-fills this path, but you can change it in the **Config** tab. All stock localization and DataForge data is sourced **directly from your installed `Data.p4k`** (no downloads, no community mirrors), so extracting once is a required first step after install or after any game patch.

## 1. Extract Base Localization from Data.p4k

Open the **Config** tab and click **Extract from Data.p4k**. This unpacks stock `global.ini` plus the DataForge entity XMLs used by the enhancement generator — ships, components, weapons, missions, blueprints, etc.

> **First extraction only:** Open Strings needs two small extraction tools (unp4k and unforge, ~130 MB total) which are downloaded automatically from the upstream GitHub release the first time you extract. The download is a one-time step; the tools are cached locally and reused for all future extractions.

When extraction finishes, the extracted `base.ini` is loaded into the table automatically — merged with any enhancement files and your saved `user.ini` overrides.

## 2. Edit Localization Strings

- Double-click any **Custom Value** cell to edit text.
- **Default Value** — original text from `Data.p4k`-extracted `base.ini`.
- **Current Value** — the effective value before your override (base + any imported INI layers).
- **Custom Value** — your personal edit. Saved automatically on every change and persisted to `<data folder>\<channel>\user.ini` (the data folder defaults to `Documents\Open Strings`; each Star Citizen channel — LIVE, PTU, EPTU, HOTFIX, TECH-PREVIEW — has its own isolated overrides).
- Edits are highlighted with a **Modified** status (green).

## 3. Preview Pane

The **preview pane** in the top-right shows the rendered text of whatever row is currently selected. The game's loc-string tokens are translated into styled HTML so you see roughly how your string will read in-game:

- `\n` → line break
- `<EM3>...</EM3>` → underlined section heading
- `<EM4>...</EM4>` → bold blue inline emphasis (typically stat values)
- `~mission(Name)` → greyed `[Name]` placeholder (the game substitutes the actual value at runtime)

The pane stays visible across all tabs and reflects the last row you selected in the **String Editor** — useful for checking how a long mission description or journal entry will format before you apply.

## 4. Categories

Use the **Category** filter to focus on one domain:

- **Ships** — Ship names and descriptions (`vehicle_Name*`, `vehicle_Desc*`, plus Wikelo/Collector mods).
- **Ship Items** — Shields, power plants, coolers, quantum drives, jump drives, ship weapons, missiles, bombs, turrets.
- **Missions** — Mission briefings, contract text, reward descriptions.
- **Gear** — FPS weapons, armor, helmets, suits, optics.
- **Commodities** — Trade goods and crafting materials.
- **Journal** — In-game journal / Galactapedia-style entries.
- **Other** — Everything else.

## 5. Search & Filter

- Use the **search box** to find strings by key or text content.
- Combine with **Category** and **Status** (Modified / Unmodified / New) filters.
- Check **Hide Unmodified** to focus on your own edits only.
- The **per-column filter boxes** under each header narrow further within the table.
- Click any column header to sort by that column. Click the **★** header to sort favorites to the top.

## 6. Ship Favorites

- Click the **★** column on any Ship row to mark it as a favorite.
- Favorited ships get a configurable prefix prepended to their name, sorting them to the top of the in-game ship list.
- Change the prefix character in the **Enhancements** tab (default: `*`).

## 7. Apply Changes to Game

Click **Apply to Game** to write your edits to the game installation. A timestamped backup of the current `global.ini` is created in `<data folder>\<channel>\backups\` before anything is overwritten.

## 8. Restore a Backup

Click **Restore Backup** to revert to a previous version. Open Strings keeps up to **5 automatic backups** — the oldest is pruned as new ones are created.

## 9. Clear Localization

Click **Clear Localization** to delete the custom `global.ini` from the game directory, reverting the game to its default (vanilla) text. Your saved overrides in `<data folder>\<channel>\user.ini` are untouched and can be re-applied anytime.

## 10. Import INI

Use **Import INI** in the **Config** tab to fold an existing INI file into your overrides. A conflict-resolution dialog lets you decide, per key, whether to **keep current**, **use imported**, **append**, **prepend**, or provide a **custom** value.

## 11. After Game Updates

When Star Citizen updates, your edits are preserved in `<data folder>\<channel>\user.ini`. Re-run **Extract from Data.p4k** to pull fresh stock strings from the patched game — the table reloads automatically and your customizations re-apply on top.

## Enhancements Tab

- Toggle stat overlays that append numerical stats to descriptions — SCM speed, shield HP, DPS, cargo capacity, blueprint pools, mission XP, and more.
- Enable or disable each enhancement category independently.
- Configure the ship favorites prefix character.
- Click **Generate Enhancements** to extract DataForge data from `Data.p4k` and rebuild the enhancement INI files. Declarative patches under `patches/` are re-applied idempotently on every regen so known CIG data bugs stay fixed without waiting for a game patch.

## Config Tab

- **Appearance** — pick the app theme (see below).
- **Star Citizen Installation** — path to your LIVE directory; auto-detected at install time, editable here.
- **Open Strings Data** — folder for `user.ini`, caches, DataForge extraction, enhancement INIs, and backups. Defaults to `Documents\Open Strings`; move it off OneDrive-synced Documents if extraction or cache cleanup is slow.
- **Base Localization (P4K Extraction)** — click **Extract from Data.p4k** to unpack stock localization plus DataForge entity data directly from your installed game. This is the sole source for base strings and enhancement data.
- **Import INI** — fold an existing INI file into your overrides via the conflict-resolution dialog.

## Log Tab

- Real-time application log.
- Filter by log level, auto-scroll to latest entries, and **Export** the log for troubleshooting or bug reports.

## Themes

Pick a theme in the **Config tab → Appearance** section:

- **Default** — a deep-navy cyber theme inspired by Star Citizen's mobiGlas UI.
- **Light / Dark** — classic UI themes.

## Status Bar

Shows the count of loaded / modified entries and the state of any running background worker (extract, generate, apply).

## Guided Tour

Click the **Tutorial** button on the toolbar at any time to replay the guided tour — a step-by-step walkthrough of the core workflow with on-screen callouts pointing at each control. The tour also runs automatically the first time you launch a new version, so a fresh install never lands cold. Hit **Skip** any time to dismiss it.

## Keyboard Shortcuts

- **Ctrl+Shift+C** — Copy filtered rows to clipboard (key=value format).

## Troubleshooting

- **Nothing in the table** — Make sure **Extract from Data.p4k** has completed and the post-extract reload has finished, then check the **Log Tab** for parse errors.
- **Enhancements empty or missing items** — Run **Generate Enhancements** from the Enhancements tab; it needs a DataForge cache (click **Extract from Data.p4k** first if you haven't).
- **Apply to Game fails** — Confirm the Star Citizen install path in the **Config Tab** and that the game isn't running.
- **Stale data after game update** — Re-run **Extract from Data.p4k**, then regenerate enhancements.

## Known Issues

Some mission text anomalies originate in Star Citizen's own data (wrong loc-key references in CIG's contract records). The game reads contracts from its own `Data.p4k` at runtime, so Open Strings can't change which loc-key the game looks up — it can only edit the _text_ under each loc-key. Where practical, we work around these by merging the intended content into the loc key the game actually reads.

- **Jorrit Dossier — "Updated Power Usage Data" shows Energy Anomaly text** — CIG Issue Council [STARC-176797](https://issue-council.robertsspaceindustries.com/projects/STAR-CITIZEN/issues/STARC-176797). CIG's `Hockrow_FacilityDelve_P2M4-Stanton4_Repeat` contract points its `Description` parameter at `@Hockrow_FacilityDelve_P2M1_Repeat_desc` instead of its own `P2M4_Repeat_desc`, so in-game players see P2M1's Energy Anomaly flavor text for a mission titled "Power Usage Data". Open Strings works around this in two steps, both declared in `patches/contracts/contractgenerator/mercenary_guild/hockrowagency/hockrowagency_facilitydelve.patch.json`:
  1. A DataForge XML edit so our enhancement generator attaches the correct P2M4 blueprint pool (Corbel Smolder, Geist Rogue/Whiteout) to `P2M4_Repeat_desc` instead of collapsing onto P2M1's.
  2. A loc-string workaround that appends `P2M4_Repeat_desc`'s full content (its flavor text plus its own blueprint pool) onto `P2M1_Repeat_desc`, separated by a labeled divider. Because the game reads the bugged pointer and looks up `P2M1_Repeat_desc` for both contracts, the P2M4 contract now displays its intended content. P2M1 players see the P2M4 block as a labeled appendix after their own description — noisier, but both contracts now show the right blueprint pool and the right flavor text.

  When CIG corrects STARC-176797, the whole patch file can be deleted and the next regenerate produces clean split descriptions again.
