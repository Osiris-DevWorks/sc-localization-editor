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
# doc. This plan covers Smart Citizen 2.2.0 (the diff over its 2.1.2 base).
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
        "title": "Blueprint Tracker tab (#223, #233, #244, #245, #246)",
        "items": [
            "A Blueprint Tracker tab exists with Available blueprints on the left and Owned on the right; move items both ways with the arrow buttons and confirm the Owned list survives an app restart.",
            "Use the search box and the Mission / Type / Class / Size / Grade filters; confirm the Available list narrows as expected and the filter note explains what each facet applies to.",
            "Type filter: armor torso pieces like \"Antium Core\" and \"Carnifex Armor Core\" appear under Armor, and the crossbow under FPS Weapon; nothing obviously misfiled sits in Other.",
            "Click \"Scan Logs for Owned Blueprints\" with a valid game path set: a progress dialog runs the log files, then a summary reports how many blueprints were added and how many are visible.",
            "After the scan, the Owned list contains only real blueprint names: no stray text like \"Stows\" or currency rewards like \"Council Scrip\" / \"MG Scrip\".",
            "Run the scan again immediately: it reports no new blueprints since the last scan (the watermark skips already-imported events).",
            "With no Star Citizen install path set, run the scan: it tells you to set the game folder instead of scanning.",
            "Change the Owned list, then click \"Apply Owned Tags\" (red until clicked): mission POTENTIAL BLUEPRINTS bullets show the blue [Owned] tag on your owned items, and the button turns green.",
        ],
    },
    {
        "title": "Mission Titles redesign + new title data (#232, #238, #239, #243)",
        "items": [
            "Tag Builder > Mission Titles: \"Shorten original titles\" and \"Shorten cargo sizes\" are independent, with per-word checkboxes underneath; the live preview tracks each toggle.",
            "With every shorten checkbox off, generate and check a stock \"... Rank, ...\" hauling title in-game: the rank separator renders as a dash by default (e.g. \"Master Rank - ...\").",
            "Toggle \"Standardize hauling mission names\", regenerate, and confirm hauling titles use the standardized name form.",
            "The General Tags checkboxes ([BP], [ACE], rep, RS, rep track) live in their own group; changing one marks Save Tag Changes dirty (red) and the tag appears/disappears on regen.",
            "Find a Recco Battaglia scan or mining contract: its title carries an [RS ####] tag with the target ore's resource signature (multiple ores slash-joined).",
            "Open a mission with an XP reward: the XP line names the reputation track it feeds (e.g. \"750 XP (Hauling)\").",
            "Open the \"Mining Fundamentals #2: Where to Mine\" journal entry: each covered ore shows a \"Base Resource Signature\" line above its Locations block; ores without a known value show no placeholder.",
        ],
    },
    {
        "title": "Dirty-state buttons & exit guard (#233)",
        "items": [
            "Generate Enhancements, Save Tag Changes, and Apply Enhancements turn red when a relevant change is pending and green (disabled) after running; hovering each explains its state.",
            "After a game patch (or with a stale cache), the Extract from Data.p4k button text turns red to signal a newer build is available.",
            "Close the app while Apply Enhancements is red: a dialog offers Apply Now / Exit Without Applying; Apply Now runs the apply and the app stays open.",
        ],
    },
    {
        "title": "Medical Consumables (#235)",
        "items": [
            "Enable the Medical Consumables category, generate, and check MedPen or OxyPen in-game: the description carries an EFFECT block with a plain-language effect line under the lore.",
            "Xtra variants, BoostPen, and VitalityPen are untouched (no EFFECT block).",
        ],
    },
    {
        "title": "Installer language page (#236, #242)",
        "items": [
            "Run the installer fresh: a Select Language page (English / French / Portuguese (Brazil) / Spanish) appears first, and the app opens in the picked language after install.",
            "Reinstall over an existing install: the page pre-selects your previously saved language, and finishing keeps it.",
            "Guard check (regedit): set selected_language to a made-up value; a /SILENT install leaves it untouched, and an interactive install where you pick French writes french.",
        ],
    },
    {
        "title": "Languages (#237 + 2.2.0 backfill)",
        "items": [
            "Switch to French or Portuguese (Brazil) and restart: tooltips, the Blueprint Tracker tab, the scan dialogs, and the Unapplied Changes prompt all show translated text.",
            "Switch to Spanish and restart, then replay the Tutorial: every tour step is in Spanish.",
            "Game strings still load for the selected language and Apply writes to the matching Localization folder.",
        ],
    },
    {
        "title": "Bug-fix bundle spot checks (#231)",
        "items": [
            "Config tab > Star Citizen Installation > Browse: the dialog opens at your current install path, not a default drive location.",
            "Extract from Data.p4k: the progress dialog runs as one continuous bar without closing early at a phase boundary or sitting frozen at 100% during the cache snapshot.",
            "Mining laser and salvage tool descriptions show clean stat text (no literal <EM4> tags or box characters).",
            "On a fresh profile with an auto-detected install, the Config tab shows the detected SC path instead of a blank field.",
            "The String Editor filter row and preview pane sit in the table area, not inside the shared toolbar, and the Enhancements category grid packs left without horizontal scrolling.",
        ],
    },
    {
        "title": "2.2.1 bug-fix bundle (#251, #261, #255, #267, #269, #273, #259, #281, #266 general fixes)",
        "items": [
            "Apply to Game against a base.ini with one corrupt/non-UTF-8 byte: Apply completes instead of crashing, and every other string (including accented characters) reads correctly.",
            "After Apply, open global.ini in a hex-aware editor: the file starts with a UTF-8 BOM, and in-game every loc string resolves (no raw @KeyName placeholders).",
            "Open the starmap in-game: Crusader shows as \"Crusader\", not \"Stanton (Star)\" or any other collided label.",
            "Blueprint Tracker: XenoThreat limited-time-event items (Purgatory Camo armor/weapons, QuadraCell, FR-66/FR-76 shields, NDB repeaters) appear even though no mission ever advertised them.",
            "On a fresh profile with Star Citizen installed on a non-default drive letter, open the Config tab: the install path is auto-detected without manually browsing.",
            "Switch channels (e.g. LIVE -> PTU): Generate Enhancements does not stay stuck disabled after the switch.",
            "After that same channel switch, Save Tag Changes (Tag Builder) and Apply Owned Tags (Blueprint Tracker) light up clickable so tags can be applied to the new channel.",
            "Tag Builder > Mission Titles: toggle any of the 7 checkboxes that previously didn't arm Save Tag Changes; the button turns red immediately.",
            "Blueprint Tracker: bullets grouped under a reputation-tier sub-header or a MULTIPLE BLUEPRINT POOLS header still show up, not just plain POTENTIAL BLUEPRINTS lists.",
            "Blueprint Tracker: bullets with a \"(Category)\" annotation (e.g. \"Bendix (Fuel Nozzle)\") join their real item instead of appearing as a separate untagged entry.",
            "Blueprint Tracker: all 8 fuel nozzle variants resolve to their real display name (Marlin, Lindstrom, Bendix, Torrez, Ezra, Norfield, Harkin, RN-7s), none left garbled or duplicated.",
            "Blueprint Tracker: the Mining Head family (Helix, Hofstede, Arbor, Klein) all resolve to their real display name.",
            "Apply to Game, then find a refueling mission in-game: fuel nozzle names in POTENTIAL BLUEPRINTS read correctly (e.g. \"Norfield\"), not garbled text like \"Nozzle Fuelgiver Grin Nozzlefast\".",
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
