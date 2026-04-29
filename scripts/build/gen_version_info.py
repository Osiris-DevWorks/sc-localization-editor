"""
Generate a PyInstaller PE version resource file (version_info.txt)
from the project's VERSION.TXT.

Usage (from repo root):
    python scripts/build/gen_version_info.py
"""

import os


def _parse_version(version_str):
    """Return a 4-tuple of ints from a dotted version string."""
    parts = [int(x) for x in version_str.strip().split(".")]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])


def generate(root_dir):
    version_file = os.path.join(root_dir, "VERSION.TXT")
    with open(version_file, encoding="utf-8") as f:
        version_str = f.read().strip()

    v = _parse_version(version_str)
    file_version_str = "{}.{}.{}.{}".format(*v)

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
        [StringStruct(u'CompanyName', u'Osiris DevWorks'),
         StringStruct(u'FileDescription', u'Smart Citizen - Star Citizen Localization Editor'),
         StringStruct(u'FileVersion', u'{file_version_str}'),
         StringStruct(u'InternalName', u'SmartCitizen'),
         StringStruct(u'LegalCopyright', u'Copyright 2024-2026 Osiris DevWorks'),
         StringStruct(u'OriginalFilename', u'SmartCitizen.exe'),
         StringStruct(u'ProductName', u'Smart Citizen'),
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
