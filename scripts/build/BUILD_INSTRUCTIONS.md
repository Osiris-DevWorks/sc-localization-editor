# Build Instructions for Smart Citizen

## Quick Start

**Build executable (recommended):**

```bash
uv run python scripts/build/build_exe.py
```

**Build everything (executable + installer):**

```bash
cd scripts/build
build_all.bat
```

---

## Prerequisites

### Required Software

1. **Python 3.12+** and **UV** (`https://docs.astral.sh/uv/getting-started/installation/`) — required
2. **PyInstaller** — installed automatically by `uv sync`

### Download Inno Setup (Optional)

For creating the installer, download from: https://jrsoftware.org/isdl.php

- Install the Unicode version
- Default installation is fine

---

## Step 0 (Optional): Clean Cache for Distribution

If distributing to users, optionally clean the DataForge cache to reduce user data size:

```bash
uv run python scripts/build/clean_cache_for_distribution.py
```

This removes the `raw/` DataForge extraction (keeping the filtered `libs/` which has all necessary stats data).
Users can regenerate raw/ if needed by re-extracting their P4K.

**Note:** The executable doesn't bundle user cache data - it's created at runtime. This script is only
useful if you've manually included cache in any distribution package.

---

## Step 1: Build the Executable

Run the build script from the project root:

```bash
uv run python scripts/build/build_exe.py
```

This will:

- Clean previous builds
- Package the application into an onedir bundle
- Include all necessary data files
- Create `dist/SmartCitizen-{VERSION}/SmartCitizen.exe`

**Testing the build:**

```bash
dist\SmartCitizen-{VERSION}\SmartCitizen.exe
```

---

## Step 2: Create the Installer (Recommended)

### Option A: Using build_all.bat (Automated)

```bash
cd scripts/build
build_all.bat
```

This runs both build_exe.py and Inno Setup automatically.

### Option B: Using Inno Setup GUI

1. Open Inno Setup Compiler
2. File → Open → Select `installer.iss` (in project root)
3. Build → Compile
4. The installer will be created in project root

### Option C: Using Command Line

```bash
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```

The installer will be created in the project root as:

```
SmartCitizen-v0.1.0-Setup.exe
```

---

## Step 3: Test the Installer

1. Run the installer: `SmartCitizen-{VERSION}-Setup.exe`
2. Follow the installation wizard
3. Test the installed application:
   - Launch the app
   - Click "Extract DataForge from P4K" to load data
   - Edit some strings
   - Apply to game
   - Check that files are in the right location

---

## Code Signing (Optional)

Signing requires a Windows code-signing certificate. Without one, the build still works — Windows will show an "Unknown Publisher" SmartScreen warning when users run the installer.

There are three signing modes; all are optional and off by default.

### Option 1 — Self-sign (no cert required)

Creates a temporary self-signed certificate in your Windows cert store and signs both binaries with it. The SmartScreen warning still appears ("Unknown Publisher"), but the binary is cryptographically signed — useful for testing the signing pipeline before buying a cert, or for internal/dev builds.

```powershell
# Interactive build — prompted at the end of the build
uv run python scripts/build/build_exe.py

# Non-interactive
uv run python scripts/build/build_exe.py --self-sign

# Via build_all.bat
$env:SC_SELF_SIGN = "1"
scripts\build\build_all.bat
```

### Option 2 — CA-issued certificate (removes SmartScreen warning)

| Cert type               | Cost         | Notes                                                |
| ----------------------- | ------------ | ---------------------------------------------------- |
| **SignPath Foundation** | Free (OSS)   | Apply at signpath.io — approval takes a few days     |
| **Sectigo / Comodo OV** | ~€80–150/yr  | Standard OV cert, issued in a few hours              |
| **EV cert**             | ~€300–500/yr | Immediately removes SmartScreen warning on first run |

Set environment variables before building. Only one cert source is needed:

```powershell
# Option A — PFX file
$env:SC_SIGN_CERT     = "C:\path\to\cert.pfx"
$env:SC_SIGN_PASSWORD = "your-pfx-password"   # omit if the PFX has no password

# Option B — cert already installed in Windows cert store
$env:SC_SIGN_THUMB = "AABBCCDDEEFF..."        # SHA-1 thumbprint from certmgr.msc

# Optional: override signtool.exe path (auto-detected from Windows SDK if unset)
$env:SIGNTOOL_PATH = "C:\path\to\signtool.exe"
```

`build_all.bat` detects these vars automatically and signs both binaries. When the vars are not set, signing is silently skipped (or you will be prompted if running in a terminal).

### Option 3 — Interactive prompt

When `build_exe.py` is run from a terminal without `--sign` / `--self-sign` and without signing env vars set, it asks at the end of the build:

```
  1) Skip — leave unsigned
  2) Self-sign — sign with a new temporary self-signed cert
  3) Sign now — enter a cert-store thumbprint or PFX path
```

Skipped automatically in CI / non-TTY environments.

### Manual signing

```powershell
# Sign using env vars (CA cert)
uv run python scripts/build/build_exe.py --sign

# Self-sign
uv run python scripts/build/build_exe.py --self-sign

# Sign any arbitrary file (CA cert)
uv run python scripts/build/build_exe.py --sign-file dist\SmartCitizen-1.0.0-Setup.exe

# Sign any arbitrary file (self-signed)
uv run python scripts/build/build_exe.py --self-sign --sign-file dist\SmartCitizen-1.0.0-Setup.exe
```

### What gets signed

- `dist/SmartCitizen/SmartCitizen.exe` — the PyInstaller app (signed before installer is built)
- `dist/SmartCitizen-{version}-Setup.exe` — the Inno Setup installer

---

The installer includes:

- ✅ Main executable (`SmartCitizen.exe`)
- ✅ Data files (default global.ini)
- ✅ Start menu shortcuts
- ✅ User config setup

---

## File Sizes (Approximate)

- **Executable**: ~60-100 MB (includes Python runtime, PyQt6, and all dependencies)
- **Installer**: ~30-50 MB (compressed)

---

## Version Update Checklist

For future versions:

1. Update version in:
   - `VERSION.TXT` (e.g., `1.1.0`) — this is the single source of truth; `installer.iss` reads it via ISPP

2. Rebuild:

   ```bash
   cd scripts/build
   build_all.bat
   ```

3. Test installer and executable

4. Create release notes

5. Tag in git:

   ```bash
   git tag -a v0.2.0 -m "Release v0.2.0"
   git push origin v0.2.0
   ```

6. Create GitHub release with:
   - Release notes
   - Installer executable
   - Standalone executable

---

## Troubleshooting

### "PyInstaller not found"

```bash
.venv\Scripts\pip install pyinstaller
```

### "Module not found" errors

Make sure all dependencies are installed:

```bash
.venv\Scripts\pip install -r requirements.txt
```

### Executable is too large

This is normal for PyQt6 applications. PyInstaller bundles the entire Python runtime and all libraries (60-100MB is standard).

### Inno Setup not found

Install from: https://jrsoftware.org/isdl.php

Or compile the installer manually by:

1. Opening `installer.iss` in Inno Setup Compiler
2. Clicking Build → Compile

---

**Ready to build!** Run `build_all.bat` or follow the steps above.
