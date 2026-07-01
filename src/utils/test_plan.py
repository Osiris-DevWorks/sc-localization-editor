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
# doc. This plan covers Smart Citizen 2.1.0.
TEST_SECTIONS: list[dict] = [
    {
        "title": "Core workflow (smoke)",
        "items": [
            "Launch the app: it opens to the strings table with no crash dialog.",
            "Config tab: extract DataForge from Data.p4k; the progress bar runs start to finish and the table reloads.",
            "Edit a string's Custom Value, then Apply Enhancements; confirm the change shows in-game.",
            "Restore Backup (More menu): a previous global.ini is offered and restores cleanly.",
            "Switch language on the Config tab and back; the table reloads without error.",
        ],
    },
    {
        "title": "Test-build fix (#186, still under test)",
        "items": [
            "Regenerate, then filter a security-threat / destroy-satellite mission; confirm its Hostiles line shows only that mission's own encounter, not a merged sibling roster (#186).",
        ],
    },
    {
        "title": "Blueprints ownership shuttle (Enhancements tab)",
        "items": [
            "Generate Enhancements, then open the Enhancements tab: the Blueprints section lists ownable items on the left and owned items on the right.",
            "Select items on the left, click the right arrow: they move to Owned and gain a blue [Owned] tag in mission POTENTIAL BLUEPRINTS lists.",
            "Use the search box and the Mission / Type / Class / Size / Grade filters; confirm the available list narrows as expected.",
            "Move items back with the left arrow; restart the app and confirm the owned list persisted.",
            "Strings table Owned column: still shows a star and sorts owned-first, but is now read-only (no click-to-toggle).",
        ],
    },
    {
        "title": "Commodity craft-usage tag + legend",
        "items": [
            "Generate Enhancements; open a crafting commodity in-game and confirm it carries a craft-usage tag between CF and Collection, e.g. [CF|QDRV|SHLD].",
            "Tag Builder > Commodities: change the \"Used To Craft\" style (Short/Medium/Long) and the craft-usage separator; regenerate and confirm the tag updates.",
            "Confirm the Mining Compendium journal starts with a \"Crafting Tag Key\" legend decoding the codes.",
        ],
    },
    {
        "title": "Commodity tag separator \"None\" (#97 follow-up)",
        "items": [
            "Tag Builder > Commodities: set Separator to None, regenerate; confirm a two-flag commodity renders as [CFCollection] and the choice persists across a restart.",
        ],
    },
    {
        "title": "Mining Compendium journal revamp",
        "items": [
            "In-game Journal > \"Mining Fundamentals #2: Where to Mine\": each mineral shows an underlined name, a blue \"Locations:\" list, and a blue \"Used To Craft:\" list.",
            "Confirm locations and craft items are one-per-line with dash bullets, alphabetized, with blank lines above each subheader.",
            "Confirm craft categories read as friendly names (e.g. \"Power Plants\", \"Quantum Drives: 7 items (S1-S3)\"), not raw paths.",
        ],
    },
    {
        "title": "Commodity descriptions",
        "items": [
            "Filter a mineable commodity (e.g. Agricium); its description shows a blue \"Locations:\" list of mining spots above the BLUEPRINT DATA block.",
            "Confirm a non-mineable / refined commodity has no Locations block, just BLUEPRINT DATA.",
        ],
    },
    {
        "title": "Mission Titles route tab (#166)",
        "items": [
            "Tag Builder > Mission Titles: confirm Enable, Placement (Prepend/Append/Replace), Route arrow, Title separator, and Location detail controls with a live preview.",
            "With Prepend + \">\" + Name, regenerate; filter a hauling/delivery/courier mission and confirm the title leads with the route (e.g. \"Area18 > Lorville - <original>\").",
            "Apply Enhancements and confirm the route resolves to real place names in-game, not raw ~mission(...) text.",
            "Switch Placement to Replace, regenerate; confirm the title becomes just the route and still keeps its [BP]/[REP] tags.",
            "Set Location detail to Full address; confirm A-to-B titles show fuller addresses (courier \"from X\" is unaffected).",
        ],
    },
    {
        "title": "SC install root retention (#150)",
        "items": [
            "Set the Star Citizen install path, then change it to a different valid location.",
            "Confirm the newly chosen root sticks and does NOT revert to the previous location.",
            "Restart the app and confirm the chosen install root persisted.",
        ],
    },
    {
        "title": "Mission titles (#151)",
        "items": [
            "Filter the table on \"Stop Attack\".",
            "Confirm each matching mission shows an enhanced TITLE (with its [BP]/XP tags), not the full MISSION DETAILS / BLUEPRINTS body.",
            "Confirm other blueprint missions still show their full detail body where expected.",
        ],
    },
    {
        "title": "Ship sort order for ASOP (#142)",
        "items": [
            "On a Ship row, set a number in the new # column (a 0-99 spin box); 0 clears it.",
            "Number two or three favourite ships (e.g. 1, 2, 3) and Apply Enhancements; in-game the name reads like \"01-ShipName\" (number, dash, name).",
            "In-game ASOP: confirm the numbered ships sort in that order (01 before 02 before 10).",
            "Click the # column header to sort: numbered ships come first, ascending.",
            "On a ship whose name starts with digits (e.g. 300i, 600i, 890 Jump), confirm the # column is BLANK until you set a number (no phantom order).",
            "Set an order on that numeric-named ship, then clear it: the base name is never altered (300i stays 300i, not 0i).",
            "Set a number then clear it (back to 0): the row returns to Unmodified.",
        ],
    },
    {
        "title": "Test Plan panel (#144)",
        "items": [
            "Open this panel from the More menu; it docks on the right like the Help panel.",
            "Check and uncheck items: the progress counter and bar update live.",
            "Close and reopen the app: your check-marks persisted.",
            "Use Copy Report and confirm a readable checklist lands on the clipboard.",
            "If a webhook is configured, Submit and confirm the report arrives in Discord.",
        ],
    },
    {
        "title": "Header style label (#164)",
        "items": [
            "Enhancements tab: the mission header style dropdown reads \"Underline\" / \"Blue text\" (not EM3 / EM4).",
            "Pick each option, Generate Enhancements, and confirm section headers render underlined vs blue in-game as labelled.",
        ],
    },
    {
        "title": "Blueprint mission filters (#156)",
        "items": [
            "Strings table: tick \"BP Titles\" and confirm only mission-title rows carrying [BP]/[BP?] remain.",
            "Tick \"BP Descriptions\" only and confirm only rows with a POTENTIAL BLUEPRINTS body remain.",
            "Tick both and confirm titles AND descriptions show; Clear Filters resets both.",
        ],
    },
    {
        "title": "FAQ tab (#152)",
        "items": [
            "Open the new FAQ tab (between About and Legal); it renders four Q&As without error.",
            "Switch theme (light/dark) and confirm the FAQ re-renders with matching colours.",
        ],
    },
    {
        "title": "Stats above description (#153)",
        "items": [
            "Enhancements tab: tick \"Show stats above description\", Generate Enhancements.",
            "Open a ship or component (e.g. a shield generator); confirm the stats block now sits ABOVE the prose blurb, separated by a divider.",
            "Untick it and regenerate; confirm stats return below the description under \"--- STATS ---\".",
        ],
    },
    {
        "title": "Ace-pilot tag (#158)",
        "items": [
            "Generate Enhancements with the \"Ace Pilot Tag\" toggle on.",
            "Filter for ambush/strike missions (e.g. Foxwell) and confirm ace-spawning missions carry an [ACE] title tag (or [ACE?] where only some variants spawn one), alongside [BP]/XP.",
            "Turn the Ace Pilot Tag toggle off, regenerate, and confirm the [ACE] tags disappear.",
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
