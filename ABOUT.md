# Smart Citizen

*Smarter Strings for Star Citizen*

## About This Project

**Smart Citizen** is a powerful, user-friendly tool for Star Citizen players to customize their game's localization strings. Load, edit, and apply localization changes with full persistence, automatic backups, and seamless support for game updates.

Developed by **Osiris DevWorks**, a one-man development studio dedicated to creating valuable tools for the gaming community.

## The Osiris DevWorks Promise

All Osiris DevWorks tools will be either **completely free** or have a **free tier**. We believe in creating value for gamers without paywalls or mandatory subscriptions.

## Acknowledgements

Thanks to the testers and contributors who helped shape Smart Citizen with their feedback:

- **Boogie Man**
- **Perseuscz**
- **Tichro**
- **Flat Earth**
- **Lord Valium**
- **Zero**

Smart Citizen also bundles upstream tooling from:

- [**dolkensp/unp4k**](https://github.com/dolkensp/unp4k) — `unp4k.exe` and `unforge.exe`, used to unpack `Data.p4k` and convert DataForge to XML

## Key Features

### 🎯 Core Features
- **Load & Edit**: Load global.ini from your Star Citizen installation and customize strings in an intuitive table view
- **Mission Contracts**: Edit mission contract and briefing text from the dedicated Missions category
- **Smart Filtering**: Search strings, filter by category (Ships, Ship Items, Missions, Gear, Commodities, Journal, Other), or modification status
- **Per-Column Filters**: Type directly into filter boxes below each column header for fine-grained searching
- **Safe Application**: Automatic timestamped backups before applying changes to prevent data loss
- **Restore Backups**: Keep up to 5 backup versions — revert changes anytime with one click
- **Import INI**: Import an existing INI file and resolve conflicts key-by-key with the built-in conflict dialog

### 🔄 Data Sourcing & Persistence
- **Sourced from Data.p4k**: All stock localization and DataForge entity data is unpacked directly from your installed `Data.p4k` — no downloads, no community mirrors, always in sync with your actual game version
- **Persistent Edits**: Your customizations are automatically saved and reloaded in every session
- **Seamless Migration**: When Star Citizen updates, re-extract from the patched `Data.p4k` — your saved edits re-apply to the new base strings automatically
- **Clean UI**: High-performance table view with filters, in-line editing, keyboard shortcuts, and a modern interface

### 📊 Enhancements
- **Ship Stats**: SCM speed, hydrogen fuel, quantum fuel, cargo capacity, and weapon loadouts appended to ship descriptions
- **Component Stats**: Shield HP, power draw, cooling rate, and other stats for ship components
- **Weapon Stats**: DPS, fire rate, range, and damage stats for ship weapons and FPS weapons
- **Mission Annotations**: `[BP]` / `[BP?]` blueprint reward tags on titles, plus structured *MISSION DETAILS*, *POTENTIAL BLUEPRINTS*, and *ITEM REWARDS* blocks in descriptions
- **Selective Categories**: Enable or disable each enhancement category independently from the Enhancements tab

### 🎨 Themes
- **Default**: Deep-navy cyber theme inspired by Star Citizen's mobiGlas UI
- **Light / Dark**: Classic UI themes
- **ODW**: Osiris DevWorks signature theme — navy charcoal with antique gold

### 🛡️ Data Management
- **Automatic Backups**: Timestamped backups created before applying changes to your game
- **Registry Persistence**: All paths and preferences saved securely in Windows Registry
- **Documents Storage**: Your custom edits stored per-channel in `Documents\Smart Citizen\<channel>\` for safe persistence across sessions and game channels
- **Per-Channel Isolation**: Each Star Citizen channel (LIVE, PTU, EPTU) gets its own cache, user overrides, and backups

## Quick Start

1. **First Launch**: App auto-detects your Star Citizen installation (editable in the **Config** tab)
2. **Extract**: Click **Extract from Data.p4k** in the Config tab to unpack stock localization + DataForge entity data from your installed game — the strings load into the table automatically when extraction finishes
3. **Edit Strings**: Use the search and filter tools, then double-click any Custom Value cell to customize text
4. **Apply**: Click **Apply to Game** — your changes are saved and applied with an automatic backup
5. **Enhancements (Optional)**: Open the Enhancements tab to enable stat overlays for ships, components, weapons, and mission rewards
6. **After Game Updates**: Re-run Extract from Data.p4k — your edits reapply automatically

## Community & Support

### Join Us
- 💬 [Discord Community](https://discord.gg/BNzRegKZ7k) - Get support, share configs, request features
- 🐛 [Smart Citizen Feedback, Bugs, & Feature Voting](https://discord.com/channels/1438175448420057323/1472394204347895890) - Dedicated channel for bug reports, feedback, and voting on upcoming features (join the server first via the invite above)

### Support This Project
Smart Citizen is completely free. If you find it valuable:
- 💳 [Donate via PayPal](https://paypal.me/RighteousKill)
- 💰 [Donate via Venmo](https://venmo.com/u/Amr-Abouelleil)

## Other Tools by Osiris DevWorks

- **[Battlestations](https://battlestations.osiris-devworks.com/)** - Manage and share Star Citizen hangar battlestation builds
- **[SC Profile Editor](https://github.com/Osiris-DevWorks/sc-profile-editor)** - Import, edit, and export Star Citizen control profiles
- **[Extended AFK](https://github.com/Osiris-RK/extended-afk)** - AFK tool to prevent idle timeouts

## Built On

Built with **PyQt6** and inspired by the Star Citizen community's localization work.

**GitHub**: https://github.com/Osiris-DevWorks/smart-citizen

## Licence

Smart Citizen is distributed under the **GPL-3.0-only** licence.
