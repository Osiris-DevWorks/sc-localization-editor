"""
Build script for creating Open Strings executable

Usage:
    python build_exe.py                        # build only; prompts for signing if TTY
    python build_exe.py --no-prompt            # build only; skip signing prompt (used by build_all.bat)
    python build_exe.py --sign                 # build and sign using env vars / prompt
    python build_exe.py --self-sign            # build and self-sign with a temp cert
    python build_exe.py --sign-file PATH       # sign an existing file (skip build)

Code-signing env vars (all optional — signing is skipped when absent and non-interactive):
    SC_SIGN_CERT      Path to a PFX certificate file
    SC_SIGN_PASSWORD  Password for the PFX file (omit for password-less certs)
    SC_SIGN_THUMB     SHA-1 thumbprint of a cert already in the Windows cert store
                      (takes priority over SC_SIGN_CERT when both are set)
    SIGNTOOL_PATH     Full path to signtool.exe (auto-detected from Windows SDK if unset)

Self-signed certs produced by --self-sign are NOT trusted by Windows SmartScreen.
    They provide integrity verification only ("Unknown Publisher" warning remains).
    Use a CA-issued cert to eliminate SmartScreen warnings.
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
        "Open Strings",
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
# Self-signing helpers
# ---------------------------------------------------------------------------

_SELF_SIGN_SUBJECT = "CN=Open Strings (Self-Signed Build)"
_SELF_SIGN_STORE = "Cert:\\CurrentUser\\My"


def create_self_signed_cert(export_pfx_path: str | None = None) -> tuple[str, str | None]:
    """Create a code-signing cert in the current user's cert store via PowerShell.

    Returns (thumbprint, pfx_path_or_None).  The cert is valid for 2 years.
    *export_pfx_path* — if given, the cert is exported to that path (no password).
    """
    print("  Creating self-signed certificate...")
    ps_create = (
        f"$cert = New-SelfSignedCertificate "
        f"-Type CodeSigningCert "
        f"-Subject '{_SELF_SIGN_SUBJECT}' "
        f"-CertStoreLocation '{_SELF_SIGN_STORE}' "
        f"-NotAfter (Get-Date).AddYears(2) "
        f"-HashAlgorithm SHA256; "
        f"Write-Output $cert.Thumbprint"
    )
    # Use pwsh (PowerShell 7).
    ps_exe = "pwsh"
    result = subprocess.run(
        [ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps_create],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"New-SelfSignedCertificate failed:\n{detail}")

    lines = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    if not lines:
        detail = result.stderr.strip()
        raise RuntimeError(
            "New-SelfSignedCertificate produced no output."
            + (f"\n{detail}" if detail else "")
            + "\nThis usually means the current user lacks permission to write to the "
            "certificate store. Try running the build as Administrator, or use "
            "--sign with a PFX file instead."
        )
    thumb = lines[-1]
    if not thumb:
        raise RuntimeError("Could not read thumbprint from New-SelfSignedCertificate output.")
    print(f"  - Certificate created (thumbprint: {thumb[:16]}...)")

    pfx_out: str | None = None
    if export_pfx_path:
        ps_export = (
            f"$cert = Get-Item '{_SELF_SIGN_STORE}\\{thumb}'; "
            f"Export-PfxCertificate -Cert $cert "
            f"-FilePath '{export_pfx_path}' "
            f"-ProtectTo $env:USERNAME"
        )
        exp = subprocess.run(
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps_export],
            capture_output=True,
            text=True,
        )
        if exp.returncode == 0:
            pfx_out = export_pfx_path
            print(f"  - Certificate exported to {export_pfx_path}")
        else:
            # Non-fatal — the cert is already in the store; export is optional
            print(f"  - WARNING: export skipped ({exp.stderr.strip()[:120]})")

    return thumb, pfx_out


def run_self_sign(file_path: str, export_pfx_path: str | None = None) -> None:
    """Create a self-signed cert and sign *file_path*; exits with code 1 on failure."""
    signtool = find_signtool()
    if not signtool:
        print(
            "ERROR: signtool.exe not found.\n"
            "  Install the Windows 10/11 SDK, add signtool to PATH, or set SIGNTOOL_PATH."
        )
        sys.exit(1)
    try:
        thumb, _ = create_self_signed_cert(export_pfx_path)
        # Temporarily inject thumbprint so sign_file() picks it up
        os.environ["SC_SIGN_THUMB"] = thumb
        # Self-signed certs have no trusted timestamp authority — sign without /tr
        cmd = [
            signtool,
            "sign",
            "/sha1",
            thumb,
            "/fd",
            "SHA256",
            "/d",
            "Open Strings",
            file_path,
        ]
        print(f"  Signing (self-signed): {os.path.basename(file_path)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            detail = (res.stdout + res.stderr).strip()
            raise RuntimeError(f"signtool failed:\n{detail}")
        print("  - Signed OK (self-signed — SmartScreen warning will still appear)")
    except (OSError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Interactive signing prompt (TTY only)
# ---------------------------------------------------------------------------

_SIGNING_CONFIGURED = bool(os.environ.get("SC_SIGN_THUMB") or os.environ.get("SC_SIGN_CERT"))


def _is_tty() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def prompt_signing(files: list[str]) -> None:
    """Ask the user how they want to sign *files* when running interactively.

    Called after a successful build when --sign / --self-sign were not passed
    and no signing env vars are set.  Silently skipped in non-TTY environments.
    """
    if not _is_tty():
        return

    print()
    print("=" * 60)
    print("  Code signing")
    print("=" * 60)
    print("  The build is unsigned. Choose an option:")
    print()
    print("  1) Skip — leave unsigned (SmartScreen 'Unknown Publisher' warning)")
    print("  2) Self-sign — sign with a new temporary self-signed cert")
    print("     (integrity only; SmartScreen warning remains; no CA required)")
    print("  3) Sign now — enter a cert-store thumbprint or PFX path")
    print()
    choice = input("  Choice [1/2/3] (default 1): ").strip() or "1"

    if choice == "2":
        print()
        for f in files:
            run_self_sign(f)
    elif choice == "3":
        print()
        print("  Thumbprint (SHA-1 from certmgr.msc), or blank to enter PFX path:")
        thumb = input("  Thumbprint: ").strip()
        if thumb:
            os.environ["SC_SIGN_THUMB"] = thumb
        else:
            pfx = input("  PFX path: ").strip()
            if not pfx or not os.path.isfile(pfx):
                print("  ERROR: PFX file not found — skipping signing.")
                return
            os.environ["SC_SIGN_CERT"] = pfx
            pwd = input("  PFX password (blank if none): ")
            if pwd:
                os.environ["SC_SIGN_PASSWORD"] = pwd
        print()
        for f in files:
            run_signing(f)
    else:
        print("  Skipping signing.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

parser = argparse.ArgumentParser(description="Build Open Strings executable.")
parser.add_argument(
    "--sign",
    action="store_true",
    help="Sign the built executable after PyInstaller completes (uses env vars or prompts).",
)
parser.add_argument(
    "--self-sign",
    action="store_true",
    help="Build and self-sign with a new temporary self-signed cert (no CA required).",
)
parser.add_argument(
    "--sign-file",
    metavar="PATH",
    help="Sign an existing file and exit (skips the build step).",
)
parser.add_argument(
    "--no-prompt",
    action="store_true",
    help="Skip the interactive signing prompt and leave the build unsigned (used by build_all.bat).",
)
args = parser.parse_args()

# --sign-file: sign only, no build
if args.sign_file:
    if not os.path.isfile(args.sign_file):
        print(f"ERROR: file not found: {args.sign_file}")
        sys.exit(1)
    print(f"\nSigning {args.sign_file} ...")
    if args.self_sign:
        run_self_sign(args.sign_file)
    else:
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
    PyInstaller.__main__.run(["OpenStrings.spec"])
    print(f"\n{'=' * 60}")
    print("Build successful!")
    print(f"{'=' * 60}")
    print("Executable: dist/OpenStrings/OpenStrings.exe")
    print()
except Exception as e:
    print(f"\nError building executable: {e}")
    sys.exit(1)

exe_path = os.path.join(root_dir, "dist", "OpenStrings", "OpenStrings.exe")
if not os.path.isfile(exe_path):
    print(f"WARNING: built exe not found at expected path: {exe_path}")
else:
    if args.self_sign:
        print("Self-signing executable...")
        run_self_sign(exe_path)
        print()
    elif args.sign:
        print("Signing executable...")
        run_signing(exe_path)
        print()
    else:
        # Interactive: prompt when running in a terminal and no signing is configured
        if not _SIGNING_CONFIGURED and not args.no_prompt:
            prompt_signing([exe_path])
