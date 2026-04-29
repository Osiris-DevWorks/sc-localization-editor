# Open Strings

*Customize Star Citizen's localization strings.*

## Fork notice

Open Strings is a fork of [Smart Citizen](https://github.com/Osiris-DevWorks/smart-citizen) by Osiris DevWorks, modified by Joni Hayes. Distributed under GPL-3.0-only.

## About This Project

**Open Strings** is a tool for Star Citizen players to customize their game's localization strings. Load, edit, and apply localization changes with full persistence, automatic backups, and seamless support for game updates.

## Acknowledgements

Thanks to the testers and contributors who helped shape the upstream Smart Citizen project with their feedback:

- **Boogie Man**
- **Perseuscz**
- **Tichro**
- **Flat Earth**
- **Lord Valium**
- **Zero**

Open Strings also bundles upstream tooling from:

- [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k) — `unp4k.exe` and `unforge.exe`, used to unpack `Data.p4k` and convert DataForge to XML

## Key Features

### Core Features
- **Load & Edit**: Load global.ini from your Star Citizen installation and customize strings in an intuitive table view
- **Mission Contracts**: Edit mission contract and briefing text from the dedicated Missions category
- **Smart Filtering**: Search strings, filter by category (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other), or modification status
- **Per-Column Filters**: Type directly into filter boxes below each column header for fine-grained searching
- **Safe Application**: Automatic timestamped backups before applying changes to prevent data loss
- **Restore Backups**: Keep up to 5 backup versions — revert changes anytime with one click
- **Import INI**: Import an existing INI file and resolve conflicts key-by-key with the built-in conflict dialog

### Data Sourcing & Persistence
- **Sourced from Data.p4k**: All stock localization and DataForge entity data is unpacked directly from your installed `Data.p4k` — no downloads, no community mirrors, always in sync with your actual game version
- **Persistent Edits**: Your customizations are automatically saved and reloaded in every session
- **Seamless Migration**: When Star Citizen updates, re-extract from the patched `Data.p4k` — your saved edits re-apply to the new base strings automatically
- **Clean UI**: High-performance table view with filters, in-line editing, keyboard shortcuts, and a modern interface

### Enhancements
- **Ship Stats**: SCM speed, hydrogen fuel, quantum fuel, cargo capacity, and weapon loadouts appended to ship descriptions
- **Component Stats**: Shield HP, power draw, cooling rate, and other stats for ship components
- **Weapon Stats**: DPS, fire rate, range, and damage stats for ship weapons and FPS weapons
- **Mission Annotations**: `[BP]` / `[BP?]` blueprint reward tags on titles, plus structured *MISSION DETAILS*, *POTENTIAL BLUEPRINTS*, and *ITEM REWARDS* blocks in descriptions
- **Selective Categories**: Enable or disable each enhancement category independently from the Enhancements tab

### Themes
- **Default**: Deep-navy cyber theme inspired by Star Citizen's mobiGlas UI
- **Light / Dark**: Classic UI themes

### Data Management
- **Automatic Backups**: Timestamped backups created before applying changes to your game
- **Registry Persistence**: All paths and preferences saved in Windows Registry
- **Documents Storage**: Your custom edits stored per-channel in `Documents\Open Strings\<channel>\` for safe persistence across sessions and game channels
- **Per-Channel Isolation**: Each Star Citizen channel (LIVE, PTU, EPTU) gets its own cache, user overrides, and backups

## Quick Start

1. **First Launch**: App auto-detects your Star Citizen installation (editable in the **Config** tab)
2. **Extract**: Click **Extract from Data.p4k** in the Config tab to unpack stock localization + DataForge entity data from your installed game — the strings load into the table automatically when extraction finishes
3. **Edit Strings**: Use the search and filter tools, then double-click any Custom Value cell to customize text
4. **Apply**: Click **Apply to Game** — your changes are saved and applied with an automatic backup
5. **Enhancements (Optional)**: Open the Enhancements tab to enable stat overlays for ships, components, weapons, and mission rewards
6. **After Game Updates**: Re-run Extract from Data.p4k — your edits reapply automatically

## Built On

Built with **PyQt6**.

## Licence

Open Strings is distributed under the **GPL-3.0-only** licence.
