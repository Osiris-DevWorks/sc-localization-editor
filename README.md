# Smart Citizen

_Smarter Strings for Star Citizen_

A Windows desktop app for customizing Star Citizen's localization strings. Layer auto-generated stat and crafting enhancements on top of stock text, edit any in-game string in a sortable filterable table, and apply the result to your game install with a single click and an automatic backup.

> [!NOTE]
> This project was originally inspired by [ExoAE's ScCompLangPack](https://github.com/ExoAE/ScCompLangPack) and the merge concepts from [MrKraken's ASOP terminal enhancements](https://www.youtube.com/@MrKraken). Smart Citizen evolved into a standalone desktop app sourcing its data directly from your installed `Data.p4k`.

## Features

- **Multi-Channel Star Citizen Support**: LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW each get their own isolated workspace — independent `user.ini`, cache, backups, DataForge extraction, and enhancement INIs. Switch channels from the Config tab without restarting.
- **Multi-Source Merge System**: Configurable sources (stock, contracts, components, ships, commodities, gear, user) merge in a drag-and-drop priority order, with user overrides always applied last so your edits never get overwritten.
- **Sourced from Data.p4k**: All stock localization and DataForge entity data is extracted directly from your installed game — no community mirrors, no version drift, no network required after install.
- **Inline Editing & Live Preview**: Double-click any cell in the _Custom Value_ column to edit. A preview pane next to the toolbar renders the selected string with the game's loc-tokens (line breaks, EM3/EM4 emphasis, mission placeholders) translated to styled HTML so you see roughly how it will appear in-game.
- **Persistent Edits**: Your customizations are saved to `user.ini` per channel and automatically re-applied across game updates.
- **Auto-Generated Enhancements**: Stat overlays for ships, ship components, ship weapons, FPS weapons, missions (with `[BP]`/`[BP?]` blueprint reward tags + structured detail blocks), journal entries, and commodity crafting cross-references — all togglable per category in the Enhancements tab.
- **Declarative CIG Data-Bug Patches**: A patch system applies fixes to known DataForge bugs at extraction time so the in-game text reads correctly without waiting on CIG.
- **Search & Filter**: Free-text search, category filter (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other), modified/unmodified status, plus per-column filter rows under every header.
- **Ship Favorites**: Star a ship to prepend a configurable prefix (default `*`) so your favorites sort to the top of the in-game ASOP terminal.
- **Apply to Game**: Writes the merged result to your `global.ini`, takes a timestamped backup first, and validates the output against the stock key set — auto-rolls back on any mismatch.
- **Backup & Restore**: Up to 5 automatic backups per channel, oldest auto-pruned. One-click restore from any of them.
- **Clear Localization**: Revert your game to vanilla text without losing your saved overrides.
- **Guided Tutorial**: A coach-mark tour walks new users through the workflow on first launch of each version. Replayable any time from the Tutorial button.
- **In-App Log Viewer**: Real-time application log with level filter, auto-scroll, and an Export button for bug reports.
- **Auto-Update Notifier**: Smart Citizen checks GitHub Releases every 6 hours and surfaces a non-blocking notification when a newer installer is available.
- **Themes**: Four built-in themes — SCLE (default deep-navy mobiGlas), Light, Dark, and ODW (Osiris DevWorks signature).

## Quick Start

### Using the Release

Grab the latest release here: [Smart Citizen Releases](https://github.com/Osiris-DevWorks/smart-citizen/releases)

Download the **`SmartCitizen-{VERSION}-Setup.exe`** installer and run it. The app auto-detects your Star Citizen installation.

### For Developers

**Prerequisites**:

- Python 3.12+
- [UV](https://docs.astral.sh/uv/getting-started/installation/)
- Windows 10/11 (the app uses Windows Registry and is Win32-only)

**Installation**:

1. **Clone the repository**

   ```bash
   git clone https://github.com/Osiris-DevWorks/smart-citizen.git
   cd smart-citizen
   ```

2. **Install dependencies and run**

   ```bash
   uv sync
   uv run python src/main.py
   ```

## Usage

### First Run

1. The app creates `Documents\Smart Citizen\<channel>\` (one subdir per Star Citizen channel) for user data — cache, backups, `user.ini`.
2. Open the Config tab and click **Extract from Data.p4k** to unpack stock localization plus DataForge entity data from your installed game. When extraction finishes, sources merge by hierarchy and the strings load into the table automatically.
3. The guided tutorial auto-runs the first time you launch a new version, walking you through the rest.

### Standard Workflow

1. **Find & Edit**:
   - Use the **Search** box to find strings, the **Category** filter to narrow by domain (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other), and per-column filter boxes for fine-grained narrowing.
   - Double-click the **Custom Value** column to edit. The preview pane shows the rendered result.
2. **Apply Changes**: Click **Apply to Game**. Your edits are persisted to `user.ini`, the merged file is written to your game's `global.ini`, and a timestamped backup is created automatically.
3. **Restore** (if needed): Click **Restore Backup** to revert to a previous version.

### After Star Citizen Updates

1. Re-run **Extract from Data.p4k** in the Config tab to pull fresh stock strings and DataForge entity data from the patched game. The table reloads automatically and your customizations re-apply on top.
2. Click **Apply to Game** to push the updated merge into the new build.

## Configuration

All settings are stored in Windows Registry under:

- **Organization**: Osiris DevWorks
- **Application**: Smart Citizen

The Config tab lets you set:

- **Star Citizen install path** (the SC root folder containing `LIVE/`, `PTU/`, etc. — auto-detected at install time)
- **Active channel** (LIVE / PTU / EPTU / HOTFIX / TECH-PREVIEW)
- **Theme**
- **Data sources**: enable/disable, drag-drop merge priority
- **Import INI**: fold an external `.ini` into your overrides

The Enhancements tab lets you toggle each enhancement category (ship stats, weapon stats, mission tags, etc.) and configure the ship favorite prefix character.

### Data Storage

All per-user data lives under `Documents\Smart Citizen\<channel>\`, where `<channel>` is one of `LIVE`, `PTU`, `EPTU`, `HOTFIX`, `TECH-PREVIEW`:

- **Your edits**: `user.ini`
- **Cached sources & extracted DataForge**: `cache\` (`base.ini`, `cache\dataforge\`, and the generated `*_enhancements.ini` files)
- **Backups**: `backups\` (max 5, oldest auto-deleted)

Each channel is fully isolated — you can run a different customization set on PTU than on LIVE without one bleeding into the other.

## Building & Release

### Development Run

```bash
uv run python src/main.py
```

### Create Executable

```bash
uv run python scripts/build/build_exe.py
```

This creates a PyInstaller onedir at `dist/SmartCitizen-v{VERSION}\` containing `SmartCitizen-v{VERSION}.exe`. VERSION comes from `VERSION.TXT`.

### Create Installer (Windows)

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php):

```bash
powershell -NoProfile -Command "& 'C:\Users\<you>\AppData\Local\Programs\Inno Setup 6\ISCC.exe' installer.iss"
```

Outputs:

- `dist/SmartCitizen-v{VERSION}\` — Standalone executable (onedir, distributed via the installer)
- `dist/SmartCitizen-{VERSION}-Setup.exe` — Installer (this is what users download)

The installer preserves user data — `user.ini` and `backups/` survive both upgrades and uninstalls; only the regeneratable cache is removed on uninstall.

## Project Structure

```
src/
├── main.py                       # Application entry point
├── gui/                          # PyQt6 widgets and dialogs
├── models/                       # StringEntry dataclass, category extraction
├── parser/                       # INI parsing + source loading
├── merger/                       # Source merge engine
└── utils/                        # Settings, paths, P4K extraction, patcher,
                                  # version, updater, app_updater, progress sink

scripts/
├── generate_enhancements_ini.py  # DataForge XML → enhancement INI files
├── extract_components.py         # base.ini delta extraction
├── gen_commodity_crafting.py     # Commodity crafting cross-reference INI
├── diff_*.py                     # Diagnostic / research tools
└── build/                        # PyInstaller build script + helpers

patches/                          # Declarative DataForge patches (JSON)
tests/                            # pytest suite
assets/                           # Bundled resources (unp4k, fonts, icon, tutorial)
```

For a deeper guide to architecture and conventions, see `CLAUDE.md` at the repo root.

## Game Installation Path

After applying localization, the relevant path inside your Star Citizen install looks like:

```
StarCitizen/
└── LIVE/                    (or PTU/, EPTU/, HOTFIX/, TECH-PREVIEW/)
    ├── user.cfg
    └── data/
        └── Localization/
            └── english/
                └── global.ini
```

## Legal

> [!IMPORTANT]
> **Made by the Community** — This is an unofficial Star Citizen fan project, not affiliated with the Cloud Imperium group of companies. All content in this repository not authored by its host or users is the property of its respective owners.

- The ability to customize your localization using extracted `global.ini` files is **authorized by CIG** to support community translations until officially integrated.
  - _[Star Citizen: Community Localization Update](https://robertsspaceindustries.com/spectrum/community/SC/forum/1/thread/star-citizen-community-localization-update) 2023-10-11_
- Use at your own discretion as a third-party contribution.
- [RSI Terms of Service](https://robertsspaceindustries.com/en/tos)
- [Translation & Fan Localization Statement](https://support.robertsspaceindustries.com/hc/en-us/articles/360006895793-Star-Citizen-Fankit-and-Fandom-FAQ#h_01JNKSPM7MRSB1WNBW6FGD2H98)

## Acknowledgments

- **Boogie Man, Tichro, Perseus, Flat Earth, Lord Valium** — testers who helped shape Smart Citizen across the 0.x cycle
- [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k) — Bundled `unp4k.exe` / `unforge.exe` used to unpack `Data.p4k` and convert DataForge to XML
- [**ExoAE**](https://github.com/ExoAE/ScCompLangPack) — Original ScCompLangPack concept and merge logic that inspired Smart Citizen's foundation
- [**MrKraken**](https://github.com/MrKraken/StarStrings) — ASOP terminal enhancements, workflow improvements, and mission contract localization work
- The **Star Citizen community** — for endless feedback, testing, and ideas

## License

Smart Citizen is licensed under the **[GNU General Public License v3.0](LICENSE)** (GPL-3.0-only).

This is required for compatibility with [PyQt6](https://riverbankcomputing.com/software/pyqt/), which is GPL-3.0-only. You are free to use, modify, and distribute this software under the same terms.

Bundled third-party components:

- **unp4k / unforge** ([dolkensp/unp4k](https://github.com/dolkensp/unp4k)) — MIT License

## Support & Community

### Feedback, Bugs & Feature Voting

All bug reports, feature requests, and prioritization happen in the dedicated `#smart-citizen` channel on the Osiris DevWorks Discord. Reactions and polls drive what lands next.

- **[Discord Server Invite](https://discord.gg/BNzRegKZ7k)** — join the server first, then jump into the [Smart Citizen feedback channel](https://discord.com/channels/1438175448420057323/1472394204347895890).
- When reporting a bug, attach the log (Log tab → **Export**) and mention the SC version you're on.

### Support the Project

Smart Citizen is a free, open-source project. If you find it useful and want to support development:

- [PayPal Donation](https://paypal.me/RighteousKill)
- [Venmo Donation](https://venmo.com/u/Amr-Abouelleil)

---

**Fly safe, Citizen!** o7
