# Translation Provenance

Provenance is tracked **inline** in each `languages/<lang>/ui.json` (#182). Every
leaf is an object with two fields:

```json
"apply_btn": { "ht": "Appliquer au jeu", "at": "Appliquer au jeu" }
```

- **`ht`** — the human translation. Non-empty means a human translated this key.
- **`at`** — the AI translation, used as a fallback. `tr()` shows `ht` when it is
  non-empty and falls back to `at` otherwise.

So the structure itself says who translated what:

- **`ht` non-empty** → human-translated. Never edited or overwritten by AI; only
  replaced by a better human translation.
- **`ht` empty, `at` non-empty** → no human translation yet; the app shows the AI
  string. **These are exactly the keys a human translator should review.** Find
  them by grepping a language file for `"ht": ""`.
- **both empty** → untranslated; the app falls back to the English base.

The English file is the source: every leaf is `{"ht": "<source text>", "at": ""}`
(English needs no AI fallback).

## Workflow

- **Translators:** translate a key by filling its `ht`. That immediately takes
  over from the AI `at` in the app — no list to update, the structure is the
  record. Leave `at` as-is (it stays as the safety net if `ht` is ever cleared).
- **Pre-release AI backfill:** any key still missing an `at` for an exposed
  language gets one (Claude, styled on the file's existing human strings for
  register and terminology), so no shipped language shows raw English. Seeding a
  human key's `at` from its own `ht` is fine — the known-good human text is the
  best fallback.
- The guided tour lives in `assets/tutorial.json` (English) and is translated per
  language under the `tutorial.*` keys. English has no `tutorial.*` section, so
  those keys are language-only by design.

## Needs human re-review

Keys whose **English source changed after they were human-translated**. The
`ht` values below are still the translator's words for the old English text,
so they were left untouched (AI never edits `ht`); a human should re-translate
them against the new source.

- `enhancements.apply_tag_changes_btn` — English renamed from "Apply Tag
  Changes" to "Save Tag Changes" (#214, 2.1.2). Affects french,
  portuguese_br, spanish (all three still translate "Apply...").

## Backfill log

- **2.3.0 cycle (2026-07-17, Claude Sonnet 5):** AI backfill of the in-app docs
  (#248). french and portuguese_br `HELP.md`/`ABOUT.md` gained the 2.2.0
  sections they were missing (Simple & Advanced mode, dirty-state button
  colors + Unapplied Changes prompt, App Updates, Blueprint Tracker tab,
  Mission Titles, FAQ tab, medical consumables, RS tags/rep-track XP, Restore
  user.ini, credits updates); their `LEGAL.md` was already current. spanish
  gained its first `HELP.md`/`ABOUT.md`/`LEGAL.md`, translated in full from
  the English originals using Thord82's ui.json terminology (Mejoras,
  Rastreador de blueprints, Aplicar mejoras, …). All of it is AI text styled
  on the existing human ui.json strings — flagged for review by the language
  leads (Akwa/Ishikudeska for french, Nxzzin for portuguese_br, Thord82 for
  spanish) per the policy below; button names in the docs follow what the
  translated UI actually shows today, including french's stale
  `apply_tag_changes_btn` (see *Needs human re-review*).

- **2.2.0 pre-release (2026-07-15, Claude Fable 5):** AI backfill of the keys
  this cycle added in English only. french and portuguese_br each gained 43
  `at`-only keys (Blueprint Tracker tab, blueprint shuttle/facets, log-scan
  dialogs, Unapplied Changes dialog, medical consumables description, plus the
  tour's new `blueprint_tracker` step); spanish gained 75, including its first
  full guided-tour translation (`tutorial.*`, all 19 steps). The stale
  `tutorial.enh_categories.description` `at` in french/portuguese_br was
  refreshed for the two categories added this cycle (it had no `ht`). All new
  strings are `ht: ""` so translators can find them the usual way.

## Per-language notes

- **english** — source language. All strings authored by the maintainer.
- **french** — human-translated by **Akwa**, process led by **Ishikudeska**. AI
  fallbacks (Claude Opus 4.8) cover the keys whose `ht` is still empty (the tour,
  progress strings, and a handful of dialogs/config keys — grep `"ht": ""`), plus
  the `HELP.md` / `ABOUT.md` / `LEGAL.md` documents in this folder.
- **portuguese_br** — human-translated by **Nxzzin**, process led by
  **Ishikudeska**. Same AI-fallback coverage as french (grep `"ht": ""`), plus the
  `HELP.md` / `ABOUT.md` / `LEGAL.md` documents.
- **spanish** — human-translated by **Thord82**. The in-app UI strings were
  contributed as a full `ui.json` and converted to the `{ht, at}` shape (his
  strings landed in `ht`; `at` left empty). A handful of newer keys added after
  his contribution are still untranslated (grep `"ht": ""` — the simple-mode
  page, FAQ tab, a few toolbar/filter/column labels); they fall back to English
  until the pre-release AI backfill. The `HELP.md` / `ABOUT.md` / `LEGAL.md`
  documents in this folder are AI translations (2.3.0 cycle) pending Thord82's
  review. The base `global.ini` for Spanish is sourced
  from Thord82's repo (`Thord82/Star_citizen_ES`, branch `propuestas_thord`),
  which tracks the current game build far more completely than the prior Dymerz
  source (99.9% vs 78.4% key coverage). Spanish writes to the game's
  `spanish_(spain)` Localization folder with `g_language = spanish_(spain)`
  (`SC_LANGUAGE_IDS`), confirmed to render in-game.
