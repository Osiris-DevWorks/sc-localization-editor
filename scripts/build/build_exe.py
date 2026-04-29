"""
Build script for creating Smart Citizen executable

Usage:
    python build_exe.py                        # build only
    python build_exe.py --sign                 # build and sign the app exe
    python build_exe.py --sign-file PATH       # sign an existing file (skip build)

Code-signing env vars (all optional — signing is skipped when absent):
    SC_SIGN_CERT      Path to a PFX certificate file
    SC_SIGN_PASSWORD  Password for the PFX file (omit for password-less certs)
    SC_SIGN_THUMB     SHA-1 thumbprint of a cert already in the Windows cert store
                      (takes priority over SC_SIGN_CERT when both are set)
    SIGNTOOL_PATH     Full path to signtool.exe (auto-detected from Windows SDK if unset)
"""

import argparse
import glob
import importlib.util
import os
import shutil
import subprocess
import sys

import PyInstaller.__main__

# ---------------------------------------------------------------------------
# Code-signing helpers
# ---------------------------------------------------------------------------


def find_signtool() -> str | None:
    """Return path to signtool.exe, checking PATH then common Windows SDK locations."""
    found = shutil.which("signtool")
    if found:
        return found
    env_path = os.environ.get("SIGNTOOL_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    # Search Windows SDK bin dirs, newest version first
    patterns = [
        r"C:\Program Files (x86)\Windows Kits\10\bin\10.*\x64\signtool.exe",
        r"C:\Program Files\Windows Kits\10\bin\10.*\x64\signtool.exe",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    candidates.sort(reverse=True)
    return candidates[0] if candidates else None


def sign_file(signtool: str, file_path: str) -> None:
    """Sign a PE binary using cert configured via environment variables.

    Supports two cert sources (thumbprint takes priority):
        SC_SIGN_THUMB    — SHA-1 thumbprint of a cert already in Windows cert store
        SC_SIGN_CERT     — path to a PFX file (SC_SIGN_PASSWORD for its password)

    Always uses SHA-256 digest + DigiCert RFC 3161 timestamp.
    """
    thumb = os.environ.get("SC_SIGN_THUMB", "").strip()
    cert = os.environ.get("SC_SIGN_CERT", "").strip()
    password = os.environ.get("SC_SIGN_PASSWORD", "").strip()

    if not thumb and not cert:
        raise OSError(
            "Signing requested but no certificate configured.\n"
            "  Set SC_SIGN_THUMB (cert-store thumbprint), or\n"
            "  set SC_SIGN_CERT (path to .pfx) and optionally SC_SIGN_PASSWORD."
        )

    cmd = [
        signtool,
        "sign",
        "/fd",
        "SHA256",
        "/tr",
        "http://timestamp.digicert.com",
        "/td",
        "SHA256",
        "/d",
        "Smart Citizen",
        "/du",
        "https://github.com/Osiris-DevWorks/smart-citizen",
    ]
    if thumb:
        cmd += ["/sha1", thumb]
    else:
        cmd += ["/f", cert]
        if password:
            cmd += ["/p", password]
    cmd.append(file_path)

    print(f"  Signing: {os.path.basename(file_path)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"signtool failed:\n{detail}")
    print("  - Signed OK")


def run_signing(file_path: str) -> None:
    """Locate signtool and sign *file_path*; exits with code 1 on any failure."""
    signtool = find_signtool()
    if not signtool:
        print(
            "ERROR: signtool.exe not found.\n"
            "  Install the Windows 10/11 SDK, add signtool to PATH, or set SIGNTOOL_PATH."
        )
        sys.exit(1)
    try:
        sign_file(signtool, file_path)
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Build Smart Citizen executable.")
parser.add_argument(
    "--sign",
    action="store_true",
    help="Sign the built executable after PyInstaller completes.",
)
parser.add_argument(
    "--sign-file",
    metavar="PATH",
    help="Sign an existing file and exit (skips the build step).",
)
args = parser.parse_args()

# --sign-file: sign only, no build
if args.sign_file:
    if not os.path.isfile(args.sign_file):
        print(f"ERROR: file not found: {args.sign_file}")
        sys.exit(1)
    print(f"\nSigning {args.sign_file} ...")
    run_signing(args.sign_file)
    sys.exit(0)

# ---------------------------------------------------------------------------
# Project paths
# ---------------------------------------------------------------------------

# Get the project directory
project_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(os.path.dirname(project_dir))

# Add src to path for imports
sys.path.insert(0, os.path.join(root_dir, "src"))

# Get version from VERSION.TXT
version_file = os.path.join(root_dir, "VERSION.TXT")
with open(version_file) as f:
    current_version = f.read().strip()

print(f"\n{'=' * 60}")
print(f"Building version: {current_version}")
print(f"{'=' * 60}\n")

# Clean previous builds
print("Cleaning old builds...")
for folder in ["build", "dist"]:
    path = os.path.join(root_dir, folder)
    if os.path.exists(path):
        shutil.rmtree(path)
        print(f"  - Removed {folder}/")

print()

# Build using spec file from repo root
print("Building --onedir version (for installer)...")
print()

os.chdir(root_dir)

# Generate PE version resource
gen_script = os.path.join(project_dir, "gen_version_info.py")
spec = importlib.util.spec_from_file_location("gen_version_info", gen_script)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
mod.generate(root_dir)
print("  - version_info.txt generated")
print()

try:
    PyInstaller.__main__.run(["SmartCitizen.spec"])
    print(f"\n{'=' * 60}")
    print("Build successful!")
    print(f"{'=' * 60}")
    print(f"Installer dir: dist/SmartCitizen-v{current_version}/")
    print()
except Exception as e:
    print(f"\nError building executable: {e}")
    sys.exit(1)

if args.sign:
    print("Signing executable...")
    exe_path = os.path.join(root_dir, "dist", "SmartCitizen", "SmartCitizen.exe")
    if not os.path.isfile(exe_path):
        print(f"ERROR: built exe not found at {exe_path}")
        sys.exit(1)
    run_signing(exe_path)
    print()
