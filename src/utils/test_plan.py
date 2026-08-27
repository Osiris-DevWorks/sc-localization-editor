"""The tester test-plan: content, progress math, and report formatting (#144).

Smart Citizen ships a "Test Plan" panel so testers on a pre-release build can
work through what changed in the release and check items off as they verify
them. This module is the Qt-free core: the plan content itself, the
progress/key helpers, and the markdown report a tester submits. The Qt panel
(`src/gui/test_plan_panel.py`) and the Discord-submit worker
(`TestPlanSubmitWorker` in `src/gui/workers.py`) build on these.

The content tracks the diff that the active release branch carries over its
integration base, so each release's plan covers exactly what's new. Update
TEST_SECTIONS when a release's scope changes; `plan_hash()` changes with it, so
a tester's stale check-marks are dropped rather than silently mislabelled.
"""
from __future__ import annotations

import hashlib
import json

# Each section is a title plus a flat list of one-line test items. Keep items
# imperative and self-contained ("do X, confirm Y") so a tester needs no other
# doc. This plan covers Smart Citizen 2.3.1 (the diff over its 2.3.0 base).
#
# Keep each item under ~190 characters. tests/test_test_plan.py chunks the
# submitted report at a 200-char limit and asserts every line survives intact,
# so a longer item fails that test rather than just wrapping awkwardly.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Config tab: extract DataForge from Data.p4k; the progress bar runs start to finish and the table reloads.",
            "Generate Enhancements, edit a string's Custom Value, then Apply to Game; confirm the change shows in-game.",
            "Restore Backup (More menu): a previous global.ini is offered and restores cleanly.",
        ],
    },
    {
        "title": "Tag Builder enclosing styles (#352)",
        "items": [
            "Tag Builder > Ship Weapons: set Enclosing to Angle, Save Tag Changes, Generate Enhancements.",
            "Blueprint Tracker: NDB-26 Repeater shows its tag in <angle> brackets, and its Type/Class/Size/Grade are filled in, not blank.",
            "Set the Class filter to Military: the Available list narrows to <MIL-...> items only, and hovering one shows its facets in the tooltip.",
            "Repeat with Round and Curly on Components: QuadraCell, QuadraCell MT, FR-66 and FR-76 all keep their tag and their facets.",
            "Set Enclosing to None (space only) and regenerate: those same items still resolve their tag and facets rather than going blank.",
            "Set every category back to Square and regenerate: everything still resolves, exactly as in 2.3.0.",
        ],
    },
    {
        "title": "Renamed blueprints mission header (#353)",
        "items": [
            "Config > Mission Labels: rename the blueprints header (e.g. to \"LOOT\"), then Generate Enhancements.",
            "Blueprint Tracker still populates; it does not go empty.",
            "String Editor: the BP Descriptions filter still finds those mission bodies under the renamed header.",
            "Mark an item owned and Apply Owned Tags: the [Owned] tag still lands on its bullet under the renamed header in game.",
            "Set the header back to the default and regenerate: everything still works.",
        ],
    },
    {
        "title": "Blueprint names from another editor (#372)",
        "items": [
            "If you have ever run another localization editor (e.g. StarStrings), open Blueprint Tracker and check the Owned list for garbled names like \"Ind/1/B Colossus\".",
            "Launch the app once: any such stored names are repaired to their real names (Colossus) automatically, and the items show as owned.",
            "Scan Logs for Owned Blueprints: names recovered from old logs land under their real names, not the other tool's format.",
            "Items that genuinely are not in your item list are left alone rather than deleted — nothing you owned should disappear from the Owned list.",
        ],
    },
    {
        "title": "Blueprint Tracker lists and filters (#354, #374)",
        "items": [
            "Type/Class/Size/Grade dropdowns and the search box narrow the Owned list as well as the Available list.",
            "Clear every filter: both lists show all of their items again.",
            "No component appears in Available and Owned at the same time (the \"stacking\" report).",
            "Commodity crafting-material lines (e.g. \"Power Plants: 10 items\") never show up as fake blueprint items in either list.",
        ],
    },
    {
        "title": "Window layout and String Editor columns (#364)",
        "items": [
            "Below full screen, every tab has its horizontal scrollbar in the same place, and nothing is clipped or squeezed off the edge.",
            "Drag a String Editor column divider: the column resizes, and the filter box under it follows to match its new width.",
            "Double-click a column divider: the column snaps to fit its widest content.",
            "Scroll the String Editor sideways: the filter boxes stay glued to their own columns instead of stranding.",
            "Reload (Apply Enhancements, a merge, or a language change): the filter row stays below the column names, never covering them.",
            "Drag the window narrower than its content: it shrinks freely and scrolls, rather than refusing to resize.",
            "Simple mode opens with no scrollbar and no dead space above the footer links.",
            "More > Reset Window Proportions: the confirm dialog says settings and localization data are untouched; window, docks and column widths return to defaults.",
            "Restart: your window size and column widths are remembered.",
            "Export Settings and open the zip: it carries no column widths (those stay machine-local).",
        ],
    },
    {
        "title": "Star Citizen install detection (#370)",
        "items": [
            "With more than one Star Citizen install on the machine, Config shows the one you actually play (the newest Data.p4k), not the first drive letter found.",
            "Extract DataForge: it completes normally rather than hanging for many minutes on a stale or half-installed copy.",
            "Point Config at a folder with no usable Data.p4k and extract: the message names the DCB file, its size and the p4k path, and suggests Verify Files.",
        ],
    },
    {
        "title": "Stale-output detection and translated runs (#363, pool headings)",
        "items": [
            "Generate Enhancements, then change any Tag Builder setting WITHOUT regenerating, and restart the app.",
            "At startup, Save Tag Changes and Generate Enhancements are both red: the files on disk no longer match your settings, and the app says so without you cycling a checkbox.",
            "The reported case: on an install upgraded from an older version, tick \"annotate component tags in mission descriptions\" and restart. The buttons light up, not grey over stale output.",
            "Regenerate: both buttons go green, and the annotations actually appear in game.",
            "Import Settings from a backup whose Tag Builder config differs from your current one: the buttons light up instead of clearing.",
            "Interrupt or fail a generation run: the buttons stay red for a retry, rather than going grey over files the tag config never reached.",
            "Switch language and restart: the freshness checks and the category status dots read that language's generated files, not English ones.",
            "On a translated run, a mission offering more than one blueprint pool shows its pool headings translated, not in English.",
        ],
    },
    {
        "title": "Portable build",
        "items": [
            "Unzip the portable build into a deep folder path (several nested folders), run it, extract and apply: no path-length errors.",
            "Close the app and delete the whole portable folder to the Recycle Bin: the delete succeeds without a path-too-long failure.",
        ],
    },
]


def plan_hash() -> str:
    """Short stable digest of the plan content.

    Stored alongside a tester's check-marks; when the plan changes the hash
    changes, so stale marks (now pointing at different items) are discarded.
    """
    blob = json.dumps(TEST_SECTIONS, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:12]


def item_key(section_idx: int, item_idx: int) -> str:
    """Stable key for one checklist item (``"<section>:<item>"``)."""
    return f"{section_idx}:{item_idx}"


def all_item_keys() -> list[str]:
    """Every item key in section/item order."""
    return [
        item_key(s, i)
        for s, section in enumerate(TEST_SECTIONS)
        for i in range(len(section["items"]))
    ]


def total_items() -> int:
    return sum(len(section["items"]) for section in TEST_SECTIONS)


def progress(checked) -> tuple[int, int, int]:
    """Return (done, total, percent) for the set of checked item keys.

    Only keys that exist in the current plan count, so a stale/foreign key
    can't push the count past the total.
    """
    valid = set(all_item_keys())
    done = sum(1 for k in checked if k in valid)
    total = len(valid)
    pct = round(done * 100 / total) if total else 0
    return done, total, pct


def build_report(checked, tester_name: str, version: str, notes: str = "") -> str:
    """Render the tester's run as a markdown report (clipboard or Discord).

    Shows overall and per-section progress and a ✅/⬜ line per item, so a
    reader sees exactly what was and wasn't verified.
    """
    checked = set(checked)
    done, total, pct = progress(checked)
    tester = tester_name.strip() or "Anonymous"
    lines = [
        f"**Smart Citizen v{version} - Test Plan Report**",
        f"Tester: {tester}",
        f"Progress: {done}/{total} ({pct}%)",
        "",
    ]
    for s, section in enumerate(TEST_SECTIONS):
        sec_keys = [item_key(s, i) for i in range(len(section["items"]))]
        sec_done = sum(1 for k in sec_keys if k in checked)
        lines.append(f"__{section['title']}__ ({sec_done}/{len(sec_keys)})")
        for i, text in enumerate(section["items"]):
            mark = "✅" if item_key(s, i) in checked else "⬜"
            lines.append(f"{mark} {text}")
        lines.append("")
    notes = notes.strip()
    if notes:
        lines.append("__Notes__")
        lines.append(notes)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def discord_chunks(report: str, limit: int = 1900) -> list[str]:
    """Split a report into Discord-message-sized chunks (2000-char hard cap).

    Splits on line boundaries so a markdown line is never cut mid-way. A single
    line longer than *limit* is hard-sliced as a last resort.
    """
    chunks: list[str] = []
    current = ""
    for line in report.split("\n"):
        while len(line) > limit:
            # Pathological single long line: hard-slice it.
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = line if not current else current + "\n" + line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
