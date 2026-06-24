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

## Per-language notes

- **english** — source language. All strings authored by the maintainer.
- **french** — human-translated by **Akwa**, process led by **Ishikudeska**. AI
  fallbacks (Claude Opus 4.8) cover the keys whose `ht` is still empty (the tour,
  progress strings, and a handful of dialogs/config keys — grep `"ht": ""`), plus
  the `HELP.md` / `ABOUT.md` / `LEGAL.md` documents in this folder.
- **portuguese_br** — human-translated by **Nxzzin**, process led by
  **Ishikudeska**. Same AI-fallback coverage as french (grep `"ht": ""`), plus the
  `HELP.md` / `ABOUT.md` / `LEGAL.md` documents.
- **spanish** — stub (`_comment`, no translations). Hidden from the language
  selector until human translations land. A fully machine-translated language is
  not shipped as "available".
