"""
Build script for creating Smart Citizen executable

Usage:
    python build_exe.py
"""

import importlib.util
import os
import shutil
import sys

import PyInstaller.__main__

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
