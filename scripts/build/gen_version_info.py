"""
Generate a PyInstaller PE version resource file (version_info.txt)
from the project's VERSION.TXT.

Also asserts that pyproject.toml version matches VERSION.TXT so they
cannot silently drift before a build.

Usage (from repo root):
    python scripts/build/gen_version_info.py
"""

import datetime
import os
import re


def _parse_version(version_str):
    """Return a 4-tuple of ints from a dotted version string."""
    parts = [int(x) for x in version_str.strip().split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def _check_pyproject_version(root_dir: str, version_str: str) -> None:
    """Assert pyproject.toml version matches VERSION.TXT. Aborts the build if not."""
    pyproject_path = os.path.join(root_dir, "pyproject.toml")
    if not os.path.exists(pyproject_path):
        return
    with open(pyproject_path, encoding="utf-8") as f:
        content = f.read()
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if not match:
        print("WARNING: Could not find version in pyproject.toml — skipping sync check.")
        return
    pyproject_ver = match.group(1)
    if pyproject_ver != version_str:
        raise SystemExit(
            f"\nVersion mismatch — build aborted.\n"
            f"  VERSION.TXT  : {version_str}\n"
            f"  pyproject.toml: {pyproject_ver}\n"
            "Update both files to the same version before building."
        )


def generate(root_dir):
    version_file = os.path.join(root_dir, "VERSION.TXT")
    with open(version_file, encoding="utf-8") as f:
        version_str = f.read().strip()

    _check_pyproject_version(root_dir, version_str)

    v = _parse_version(version_str)
    file_version_str = "{}.{}.{}.{}".format(*v)
    year = datetime.date.today().year

    content = f"""\
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v[0]}, {v[1]}, {v[2]}, {v[3]}),
    prodvers=({v[0]}, {v[1]}, {v[2]}, {v[3]}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [StringTable(
        u'040904B0',
        [StringStruct(u'CompanyName', u'Joni Hayes'),
         StringStruct(u'FileDescription', u'Open Strings - Star Citizen Localization Editor'),
         StringStruct(u'FileVersion', u'{file_version_str}'),
         StringStruct(u'InternalName', u'OpenStrings'),
         StringStruct(u'LegalCopyright', u'Copyright {year} Joni Hayes. Portions Copyright 2024-{year} Osiris DevWorks. GPL-3.0-only.'),
         StringStruct(u'OriginalFilename', u'OpenStrings.exe'),
         StringStruct(u'ProductName', u'Open Strings'),
         StringStruct(u'ProductVersion', u'{file_version_str}')]
      )]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"""

    out_path = os.path.join(root_dir, "version_info.txt")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)

    return out_path


if __name__ == "__main__":
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(os.path.dirname(script_dir))
    out = generate(root_dir)
    print(f"Written: {out}")
