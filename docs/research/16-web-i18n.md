# Localization for Godot 4.4-4.7 (web research, 2026-11-12)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## Summary

Plugin-owned structured source of truth (records per namespace + per-locale translation files with source hash), generated Godot runtime files (gettext `.po`, optional 4.6+ CSV) that are not committed. PO is the best runtime/exchange target across 4.4-4.7 (msgctxt, plurals, fuzzy skipped at runtime; Poedit/Weblate/Crowdin native). CSV gained `?context`/`?plural` only in 4.6. Agents change strings only through a validating CLI; stale is computed from the hash; only a human sets `reviewed`. Godot has no CLI POT generator (proposal #10986 open) → plugin needs its own extractor and lint.

## Godot facts

- CSV: UTF-8 no BOM, first column keys, locale headers, `_`-prefixed columns are comments; 4.6+ `?context`, `?plural` + `?pluralrule` row; controls cannot auto-translate plural/context CSV strings; import options compress/delimiter/unescape_keys/unescape_translations.
- PO/MO: msgctxt = tr() 2nd arg, msgid_plural/msgstr[N] from tr_n(); fuzzy entries skipped at runtime; locale from "Language:" header; keep PO in VCS.
- POT generation editor-only: scenes (`text`, `*_text`, `title`, `filters`, `item_*/text`, not LineEdit/TextEdit/CodeEdit, not auto-translate DISABLED); GDScript `tr/tr_n/atr/atr_n`, assignments to text/placeholder_text/tooltip_text, add_item/add_tab/set_tab_title; constant strings only; `# TRANSLATORS:` notes, `# NO_TRANSLATE` exclusion; EditorTranslationParserPlugin for custom formats.
- Runtime: `auto_translate_mode` (INHERIT/ALWAYS/DISABLED), `atr()`, TranslationServer (domains, set_locale, get_plural_rules, pseudolocalize, translate_plural), TranslationDomain locale override (send NOTIFICATION_TRANSLATION_CHANGED).
- Pseudolocalization settings `internationalization/pseudolocalization/*`: expansion_ratio (0.3 typical), replace_with_accents, double_vowels, fake_bidi, override (all `*` → finds hardcoded strings), prefix/suffix, skip_placeholders; `--editor-pseudolocalization` flag.
- locale/fallback "en", locale/test; Remaps for images/audio (not fonts → font fallbacks); 4.5 live translation preview.
- RTL: anchors/margins/container order mirrored, not coordinates; text_direction, layout_direction, structured_text_bidi_override.
- Official VCS docs: ignore `*.translation` (generated binary) — AloneGodot tracking them goes against guidance.

## Format comparison

| Criterion                   | Godot CSV        | PO per locale               | Structured source → generated PO/CSV    |
| --------------------------- | ---------------- | --------------------------- | --------------------------------------- |
| 4.4-4.5 context/plurals     | no               | yes                         | yes via PO                              |
| Per-string metadata         | flat `_` columns | partial (#. #, #\| msgctxt) | full                                    |
| Git diffs / parallel merges | poor             | medium                      | best (namespace + locale files, sorted) |
| Translator tools            | not native       | native                      | via PO export/import                    |
| LLM friendliness            | ok               | noisy                       | best                                    |

Weblate: flags max-length, max-size (px with font), placeholders, bbcode-text; states untranslated / needs editing (fuzzy) / translated / approved (approved not stored in PO). Crowdin: context, maxLength, labels, screenshots.

Perfectionist: PO only. Pragmatist: keep CSV with extra `_` columns. Recommended: structured source + generated PO (4.4+ targets, plurals/context, parallel worktrees).

## Checks

1. Hardcoded strings in .gd (mirror Godot extractor patterns; literal not a key and not in tr/atr; `# NO_TRANSLATE`, allowlist).
1. Hardcoded strings in .tscn/.tres (text/\*\_text/title/item_N/text with effective auto_translate not DISABLED; schema-declared localizable .tres fields).
1. Runtime backstop: pseudo-loc `override` screenshot — readable glyphs = leak.
1. Keys: missing, orphan, duplicate, duplicate (source, context) with different keys; dynamic keys declared as patterns.
1. Placeholder parity: {name}, %s/%d/%.2f/%%, balanced BBCode, \\n — per plural form.
1. Plural completeness vs TranslationServer.get_plural_rules / CLDR.
1. Length budgets: max_chars; max_px measured with theme font in headless Godot.
1. Untranslated/stale (hash computed)/machine-only coverage per locale; stale → `#, fuzzy` in generated PO.
1. Pseudo-loc layout run (expansion 0.3-0.4, accents; fake_bidi pass) at each resolution; overflow detection; screenshots into review hub.
1. Font coverage of locale codepoints.
1. Generated-artefact freshness; keep generated files gitignored.

## LLM translation workflow

- `i18n add KEY --source --context --note --max-chars --plural --screenshot` (validated, sorted insert, no duplicates); hook blocks edits to generated files.
- Translate per namespace/locale batch with context, notes, limits, screenshot, glossary (DNT/approved/forbidden terms), locale style guide, TM matches; mask placeholders/BBCode as tokens, restore, parity check; status `machine` + provenance.
- Separate fresh-context QA (MQM categories), back-translation for high-risk strings; findings as comments.
- Only humans set `reviewed` (hook blocks agents). Release gate: shipped locales 0 missing, 0 stale, 0 errors.
- AMTA 2026 (Tian & Wu): LLM game-LQA error detection F1 — Claude Sonnet 4 0.766, Qwen-2.5-72B 0.711, Gemini 2.0 Flash 0.691; Japanese hardest → keep human sign-off.
- Prior art: Donchitos `localize` skill (modes scan/extract/validate/status/brief/cultural-review/rtl-check/freeze/qa; engine-agnostic). No Godot-specific LLM translation skill found. Share glossary/style guides with the user's docs `translate` skill, not its chunking.

## Record sketch

```yaml
# i18n/src/ui.hud  (source)
HUD_HEALTH_LABEL:
  source: "Health: {current}/{max}"
  context: hud
  note: "Top-left HUD label; numbers are integers."
  max_chars: 24
  max_px: 220
  placeholders: {current: "int, current HP", max: "int, max HP"}
  markup: none
  plural: false
  screenshots: [docs/shots/hud_main.png]
  tags: [ui, hud]
  dnt: false
  owner: ui
# i18n/locales/fr/ui.hud
HUD_HEALTH_LABEL:
  text: "PV : {current}/{max}"
  status: machine            # new|machine|translated|reviewed (stale computed)
  source_hash: 3f9a1c...
  by: {kind: llm, model: ..., at: 2026-11-12}
  reviewer: null
  comments: [{by: qa-agent, at: ..., text: "..."}]
```

Generated (gitignored): `i18n/build/<locale>.po` (#. note, #, fuzzy when stale, flags, #: refs), optional 4.6+ CSV, pseudo.po, POT for vendors; project.godot lists generated .po paths.

## Risks

Custom format tooling + PO round-trip needed; gitignored PO means fresh clones need the build (hook into bootstrap/import/export); extractor drift from Godot's; dynamic keys false orphans; double translation with auto-translate; unverified: PO comment syntax details, .po loading without generated siblings, TranslationDomain version, Font.has_char/get_string_size usage, gdtoolkit 4.7 support, TextServer data needs.

## Key sources

docs.godotengine.org (localization_using_spreadsheets 4.6/latest, localization_using_gettext 4.7, internationalizing_games, ResourceImporterCSVTranslation, TranslationServer, TranslationDomain, ProjectSettings, Node, gui_using_fonts, version_control_systems, command_line_tutorial); godotengine.org releases 4.5/4.6/4.7; godot-proposals#10986; docs.weblate.org (formats, checks, workflows); Crowdin CLI + screenshots; cldr.unicode.org plural rules; aclanthology.org 2026.amta-research.12; Donchitos localize skill; GodotXliff.
