# Narrative content systems (Godot 4.7)

Source: web research of 2026-11-13 against the Godot 4.7 docs and the Dialogue Manager, Dialogic, ink, Yarn Spinner and Arcweave repos and docs. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

- **Dialogue Manager (Nathan Hoad)** is the safest default for a GDScript project on Godot 4.6+. It is MIT-licensed and released often (v4.2.0, Oct 2026). Dialogue lives in plain-text `.dialogue` files that diff well. Line IDs (`[ID:KEY]`) go straight into Godot's own POT/CSV template generation.
- **Dialogic 2** is still alpha (Alpha 20, Jul 2026, Godot 4.5+). It supports CSV translation only and writes `#id:` tags into timeline lines.
- **Ink (godot-ink)** and **Yarn Spinner (C#)** both need the .NET build of Godot. The GDScript port of Yarn Spinner is alpha and requires Godot 4.6+.
- For tooling, the useful engine-level facts are these:
  - Godot 4.6 added `?context` and `?plural` CSV columns.
  - `EditorTranslationParserPlugin` lets any custom dialogue format feed POT generation.
  - `AnimationPlayer.seek()` skips the Call Method events between the old and new time. A naive "skip cutscene" button therefore loses state changes. This is the biggest cutscene pitfall.
  - Godot 4.7 stable shipped about 2026-06-19 and 4.7.2 about 2026-08-18. Both dates come from third-party news ([cinevva](https://app.cinevva.com/news/2026-06-19-godot-4-7-released), [gamedev.net](https://gamedev.net/news/5172-godot-engine-472-stable-released/)). The godotengine.org article was not found. UNVERIFIED against the official source.

## Addons and tools

| Tool                              | Version / last release                                          | Godot                                  | Licence                            | Language                                                                                       | Source format (git diff)                                                                                     |
| --------------------------------- | --------------------------------------------------------------- | -------------------------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Dialogue Manager                  | v4.2.0, 30 Oct (2026 inferred: v4.x targets 4.7)                | 4.6+ (v3.10 for 4.4/4.5, v3.3 for 4.3) | MIT                                | GDScript; optional C# wrapper                                                                  | `.dialogue` plain text: diffs well                                                                           |
| Dialogic 2                        | Alpha 20, 21 Jul (2026 inferred)                                | 4.5+, 4.6+ recommended                 | MIT                                | GDScript                                                                                       | Text timelines (`.dtl`) and characters (`.dch`). UNVERIFIED: these extensions are not named in the docs read |
| godot-ink (paulloz)               | v1.1.2, 12 Feb (year not shown: UNVERIFIED)                     | Godot 4.x                              | MIT                                | Needs C#/.NET; usable from GDScript through interop                                            | `.ink` plain text: diffs well                                                                                |
| inkgd (ephread)                   | No Godot 4 release; `godot4` branch says "compatible with 4.2+" | 4.2+ (branch only)                     | MIT                                | GDScript port                                                                                  | `.ink`                                                                                                       |
| ink compiler (inkle)              | 1.2.1, 05 May (year not shown)                                  | n/a                                    | MIT (UNVERIFIED: licence not read) | n/a                                                                                            | `.ink`                                                                                                       |
| Yarn Spinner for Godot (C#)       | v0.3.23, 2026-10-06 (sample project on 4.7.2)                   | 4.x                                    | MIT                                | C# required                                                                                    | `.yarn` plain text plus `.yarnproject`                                                                       |
| Yarn Spinner for Godot (GDScript) | Alpha ("not recommended to ship")                               | 4.6.x+                                 | Free; paid tier planned            | Pure GDScript, no .NET                                                                         | `.yarn`                                                                                                      |
| Arcweave Godot plugin             | v3.1.0, 20 Oct (year not shown)                                 | 4.x                                    | MIT                                | Needs .NET; partial GDScript API                                                               | Arcweave JSON export                                                                                         |
| articy:draft X                    | No official Godot importer; "Generic Engine Export"             | n/a                                    | Commercial                         | Community: zephyr-articy-godot (GDScript JSON importer), Articy2Godot (to Dialogic, v2.0 2025) | JSON (diffs poorly when large)                                                                               |
| Rhubarb Lip Sync                  | Version not shown (UNVERIFIED)                                  | No Godot integration listed            | Licence not read (UNVERIFIED)      | CLI                                                                                            | TSV/JSON/XML mouth cues                                                                                      |

Sources:

- Dialogue Manager: https://github.com/nathanhoad/godot_dialogue_manager, its /releases page, and docs/Upgrading_Version.md
- Dialogic: https://github.com/dialogic-godot/dialogic and its /releases page
- Ink: https://github.com/paulloz/godot-ink/releases, https://github.com/ephread/inkgd, https://github.com/inkle/ink/releases
- Yarn Spinner: https://github.com/YarnSpinnerTool/YarnSpinner-Godot/releases and https://docs.yarnspinner.dev/3.1/yarn-spinner-for-godot/godot-gdscript
- Arcweave: https://github.com/arcweave/arcweave-godot-plugin (and its /releases page)
- articy: https://forum.godotengine.org/t/articy-to-godot-json-importer-and-player-addon/140370 and https://aimarzhang.itch.io/articy-exporter-for-godot
- Rhubarb: https://github.com/DanielSWolf/rhubarb-lip-sync

## 1. Branching data models

**Dialogue Manager v4.** (Source: [Basic_Dialogue.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Basic_Dialogue.md), [Upgrading_Version.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Upgrading_Version.md).)

- Structure:
  - Cues start with `~ name`. They were renamed from "titles" in v4.
  - `=> cue` jumps, and `=> END` / `=> END!` end the flow.
  - `=>< file/cue` jumps and returns.
  - `import "res://x.dialogue" as x` imports another file.
  - Responses are `- text`, with nested lines under them.
  - Random lines use `%` / `%3` weights. Tags look like `[#mood=happy]`.
- Breaking change in v4: response conditions must self-close, so `- Text [if cond /]` replaces `- Text [if cond]`.
- `DialogueLine.translation_key` was renamed to `static_id`.

```
~ start
Nathan: Hi! [ID:HI_IM_NATHAN]
- Ask about work [if Quest.is_active("work") /]
	=> work
- Leave
	=> END
```

**Dialogic 2.** Timelines can be edited as plain text with highlighting and auto-completion ([docs.dialogic.pro](https://docs.dialogic.pro/)). The grammar has no dedicated reference page: UNVERIFIED beyond the variable examples in section 2.

**Ink and Yarn.** Both use plain-text scripts with knots/stitches (ink) or nodes (Yarn). Yarn lines carry a unique `#line:<id>` tag, which the compiler adds automatically when it is missing ([Yarn tags/metadata](https://docs.yarnspinner.dev/write-yarn-scripts/advanced-scripting/tags-metadata.md)).

## 2. Variables, conditions and save integration

**Dialogue Manager** ([Conditions_Mutations.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Conditions_Mutations.md)):

- Conditions use `if`/`elif`/`else`, `match`/`when`, and inline `[if x]a[else]b[/if]`.
- Mutations use `$> expr`. `set`/`do` still work but are deprecated.
- Variables resolve against autoloads, an `extra_game_states` array (searched in order), `using SomeGlobal` shortcuts, and `locals.` (which must always be prefixed).
- The docs do not describe dialogue-owned persistent storage. In practice, game state lives in your own autoloads and objects, and you save those. Resuming means storing a cue or line id and calling `get_next_dialogue_line(resource, cue)` ([Using_Dialogue.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Using_Dialogue.md)). That resume pattern is UNVERIFIED as documented behaviour.

**Dialogic 2** ([variables.html](https://docs.dialogic.pro/variables.html)):

- Variables are defined in the Variables tab and grouped in folders, e.g. `{Folder.var}`.
- Text timelines use `set {x} = 20`, `set {F.v} += 2` and `if {Player.Health} > 5:`.
- Save and load go through `Dialogic.Save.save()` / `Dialogic.Save.load()`. An empty slot name means the default slot, per a maintainer in discussion [#2104](https://www.github.com/dialogic-godot/dialogic/discussions/2104). There is no docs page for this: medium confidence.

**Yarn (GDScript)** ([docs](https://docs.yarnspinner.dev/3.1/yarn-spinner-for-godot/godot-gdscript)):

- The default `YarnInMemoryVariableStorage` keeps variables in memory only.
- To persist them, subclass `YarnVariableStorage`.

## 3. Localization

**Engine level** ([gettext 4.7](https://docs.godotengine.org/en/4.7/tutorials/i18n/localization_using_gettext.html), [spreadsheets 4.7](https://docs.godotengine.org/en/4.7/tutorials/i18n/localization_using_spreadsheets.html), [EditorTranslationParserPlugin](https://docs.godotengine.org/en/4.7/classes/class_editortranslationparserplugin.html)):

- POT generation: Project Settings > Localization > Template Generation, then Add files and Generate.
- `tr("Shop", "Main Menu")` produces `msgctxt`. `tr_n()` handles plurals.
- `# TRANSLATORS:` comments become translator notes, and `NO_TRANSLATE` excludes a string.
- CSV rules:
  - The first column holds keys, which are unique and case-sensitive.
  - Columns whose names start with `_` are comments.
  - `?context` and `?plural` columns are new in 4.6. Automatic Control translation ignores them, so call `tr`/`tr_n` manually.
  - Save as UTF-8 without BOM.
- `EditorTranslationParserPlugin._parse_file(path) -> Array[PackedStringArray]`. Each entry is `[msgid, msgctxt, msgid_plural, comment, source_line]`.
- On 4.3–4.5, the CSV `?context`/`?plural` columns do not exist. Use PO there.

**Dialogue Manager v4** ([Translations.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Translations.md)):

- Every line goes through `tr()`. `translation_source` can be None, CSV, PO, or Guess.
- `.dialogue` files are added to Template Generation automatically, and its bespoke CSV exporter was removed in favour of Godot's.
- With a static ID, the ID becomes the key. Text without an ID is keyed by the text itself. The v4 upgrade guide says the context is now always "dialogue".
  - CONFLICT DETECTED: Translations.md shows `msgctxt "HI_IM_NATHAN"`, `msgid "Hi! I'm Nathan."`, while Upgrading_Version.md says the static_id is now the key and the context is always "dialogue". Both are on the main branch; check the actual POT output on v4.2.0.
- A `## note` line becomes a translator comment. BBCode stays inside the translatable text.

**Dialogic 2** ([translation.html](https://docs.dialogic.pro/translation.html)):

- Translation is CSV only.
- "Update CSV files" appends `#id:14`-style IDs to timeline lines. "Collect translation" builds the Godot translation files.
- Character names and glossaries are translated too. Untranslated glossary entries do not fall back to the default locale.

**Yarn (C#)**:

- Generates CSVs with more context fields than Godot's, which are converted to `.translation` files ([README](https://github.com/YarnSpinnerTool/YarnSpinner-Godot)).

**Voice-over ids.** Reuse the line key as the audio filename, e.g. `res://vo/<locale>/<ID>.ogg`:

- DM: `static_id`. Its docs say static IDs exist to match voice-acted lines.
- Dialogic: `#id:`.
- Yarn: `#line:`.
- The filename convention is a recommendation, not a documented addon feature.

## 4. Quests and objectives

No official Godot quest system exists. A data-driven design built on engine primitives looks like this:

- Use a `class_name` Resource saved as `.tres`. Resources are text and version-control friendly ([resources 4.7](https://docs.godotengine.org/en/4.7/tutorials/scripting/resources.html)).
- Loaded resources are cached and shared ("only loads it once"). Keep runtime progress in a separate state dictionary, or `duplicate()` the resource. Never mutate the definition.

```gdscript
class_name QuestDef extends Resource
@export var id: StringName
@export var title_key: String          # translation key, not display text
@export var objectives: Array[ObjectiveDef] = []

# QuestLog autoload: progress is plain data, so saving is var_to_str/JSON of one Dictionary
var state: Dictionary = {}   # quest_id -> {"status": "active", "counters": {...}}
func on_event(kind: StringName, subject: StringName) -> void:
	for qid in state: _advance(qid, kind, subject)   # event-driven, not polled
```

- Use a small state machine per quest: `inactive -> active -> completed | failed`.
- Dialogue reads state through the autoload, e.g. DM `[if QuestLog.is_active("x") /]`, and writes it through mutations (`$> QuestLog.start("x")`).

## 5. Cutscenes

Sources: [track types 4.7](https://docs.godotengine.org/en/4.7/tutorials/animation/animation_track_types.html), [AnimationPlayer 4.7](https://docs.godotengine.org/en/4.7/classes/class_animationplayer.html), [AnimationMixer 4.7](https://docs.godotengine.org/en/4.7/classes/class_animationmixer.html).

What the docs say:

- Call Method tracks do not run in editor preview.
- `callback_mode_method` defaults to DEFERRED, meaning calls run after events are processed.
- Animation Playback tracks sequence other AnimationPlayers. They need "Editable Children" on instanced scenes, and a player cannot reference itself.
- `seek(t, update, update_only)` behaviour:
  - "Events between the current frame and `seconds` are skipped."
  - Seeking to the end does not emit `animation_finished`. The docs point to `AnimationMixer.advance()` instead.
  - `update_only=true` skips method, audio and animation-playback tracks.
- `animation_finished` is not emitted for looping animations.

Skippable pattern: put state changes in an idempotent `apply_end_state()` rather than only in method keys.

```gdscript
func skip() -> void:
	_anim.seek(_anim.current_animation_length, true)  # skips method keys in between
	apply_end_state()                                 # flags, positions, quest updates
	_finish()                                         # do not wait for animation_finished
```

- UNVERIFIED: whether `advance(remaining)` fires every intermediate method key in 4.7. Test it before relying on it.
- Cameras: animate a dedicated `Camera2D`/`Camera3D` and call `make_current()` from a method key. Restore the previous camera in `_finish()`. This is a pattern; no single doc page covers it.
- No timeline tool beyond AnimationPlayer was verified for 4.7. Third-party cutscene sequencers: UNVERIFIED.

## 6. Barks and contextual lines

No addon-specific source was found. Common approach:

- A bark table keyed by `(event, speaker, conditions)`.
- Per-line cooldowns and "said once" flags kept in save data.
- Lines picked at random by weight, e.g. DM `%` weighted lines ([Basic_Dialogue.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Basic_Dialogue.md)).

Barks must go through the same translation keys as dialogue. The design itself is opinion/pattern (UNVERIFIED as a standard).

## 7. Text presentation

- `visible_characters` (-1 shows all) and `visible_ratio` stay in sync with each other.
- `get_total_character_count()` excludes BBCode. Counting is by Unicode codepoint, so a multi-codepoint emoji counts as several characters.
- Tags must not be entangled.
- Source: [RichTextLabel 4.7](https://docs.godotengine.org/en/4.7/classes/class_richtextlabel.html).

```gdscript
func type_out(label: RichTextLabel, cps: float = 40.0) -> void:
	label.visible_characters = 0
	var total := label.get_total_character_count()
	while label.visible_characters < total:
		label.visible_characters += 1
		await get_tree().create_timer(1.0 / cps).timeout
```

- Built-in effects ([BBCode 4.7](https://docs.godotengine.org/en/4.7/tutorials/ui/bbcode_in_richtextlabel.html)):
  - `[wave amp freq connected]`, `[tornado]`, `[shake rate level]`, `[fade start length]`, `[rainbow]`, `[pulse]`.
  - Custom effects are a `RichTextEffect` with a `bbcode` member and `_process_custom_fx(char_fx)` returning `true`, registered via `install_effect()`. An unregistered tag shows up as literal text.
  - Animated effects pause with the SceneTree unless the process mode is changed.
  - Prefer `append_text()` or `push_*()` over reassigning `text`.
- Dialogue Manager's `DialogueLabel` emits `started_typing`, `finished_typing`, `paused_typing` and `spoke(letter, speed)`, and supports inline `[wait]`/`[speed]`/`[next]` ([Using_Dialogue.md](https://github.com/nathanhoad/godot_dialogue_manager/blob/main/docs/Using_Dialogue.md)).
- Voice-over sync: start the `AudioStreamPlayer` keyed by the line id when the line is shown. Either drive the reveal from the stream length, or let the text finish first and advance on audio end. This is a pattern, UNVERIFIED as an addon feature.
- Lip-sync: Rhubarb outputs timed mouth cues A–F plus optional G/H/X as TSV/JSON/XML. It lists no Godot integration, so cues must be imported into an animation or sprite-frame track. The importer is UNVERIFIED (none confirmed).

## 8. Narrative testing

- No addon documents a built-in graph linter. UNVERIFIED for Dialogic and Yarn; DM docs show only that `create_resource_from_text()` fails on syntax errors.
- Practical approach:
  - Parse source files, which are text in DM, ink, Yarn and Dialogic.
  - Build a cue/node graph and validate it statically (section "What a tool could check").
  - Run an automated playthrough headless. Use `get_next_dialogue_line` in DM, pick every response in breadth-first order with a visited set, and assert each line has a translation in each locale via `TranslationServer`.
  - Judge the run by a printed summary line, not by exit code (project rule).

## 9. Writer workflow outside Godot

- Twine: no official Godot importer found (UNVERIFIED).
- Ink (Inky editor) and Yarn (VS Code extension) are the most git-friendly options, being plain text.
- Arcweave has an official plugin, but it needs .NET Godot and C# web export is unsupported ([Arcweave plugin](https://github.com/arcweave/arcweave-godot-plugin)).
- articy:draft X has only a generic export to Godot. The importers are community-made (see table).

## Checkable rules an agent should follow

1. Pin the addon version in `addons/<name>/plugin.cfg` and check it against the engine version: DM v4 needs 4.6+, Dialogic 2 needs 4.5+, Yarn GDScript needs 4.6+.
1. Do not use Yarn C#, godot-ink or Arcweave unless `project.godot` has a `[dotnet]` section and a `.csproj` exists.
1. Dialogue source is text (`.dialogue`, `.ink`, `.yarn`, `.dtl`). Binary or JSON blobs from external tools must be regenerated by a recorded command, not hand-edited.
1. Every player-facing dialogue line has a stable ID: DM `[ID:…]`, Yarn `#line:`, Dialogic `#id:`.
1. Line IDs are unique across the project. A duplicate fails the check.
1. In DM v4, every response condition is self-closing (`[if … /]`).
1. In DM, `set`/`do` are not used. Use `$>`, because they are deprecated in v4.
1. In DM, `locals.` variables are always prefixed.
1. Every variable used in a condition or mutation resolves to a declared autoload property, a `using` target, or a Dialogic variable.
1. Every `.dialogue` file appears in `internationalization/locale/translations_pot_files` (Template Generation).
1. Translation CSVs are UTF-8 without BOM, have unique case-sensitive keys, and use `?context`/`?plural` only when `config/features` is 4.6 or later.
1. Every key in the source language has a non-empty value in each shipped locale, or is listed in an allowlist.
1. A line containing BBCode has the same tag set in every translation.
1. Every voice-over file matches `vo/<locale>/<line_id>.<ext>` and every voiced line has a file.
1. Quest definitions are `.tres` Resources with unique `id`. Runtime state never writes back into them.
1. Quest titles and objectives store translation keys, not display text.
1. Every cutscene's AnimationPlayer has a skip path that calls an end-state function. No state change exists only as a method key.
1. Skip code does not wait on `animation_finished` after `seek()` to the end.
1. Cutscene animations used with `animation_finished` are not set to loop.
1. Custom BBCode tags used in dialogue have a `RichTextEffect` registered on the label.
1. Typewriter code uses `get_total_character_count()`, not `text.length()`.
1. Every number shipped (CPS, cooldowns) carries a source and a date, per project rule.

## What a tool could check automatically

- **Graph lint.** Parse cues and jumps, then report:
  - jumps to missing cues
  - unreachable cues (no inbound edge and not an entry point)
  - dead ends (no `END` and no outgoing jump, where the format requires one)
  - imports pointing to missing files
  - response blocks whose conditions are all statically false
- **Dangling IDs.** Report:
  - duplicate line IDs
  - IDs in translation CSV/PO with no source line (orphans)
  - source lines without IDs
  - VO files without lines, and lines without VO
- **Untranslated lines.** Diff source keys against each locale column or `.po`, flag empty `msgstr`, and compare the BBCode tag multiset and `{var}` placeholders per translation.
- **Variable references.** Extract identifiers from `if`/`elif`/`match`/`$>` and Dialogic `{…}`. Resolve them against autoload scripts in `project.godot` (`[autoload]`), `using` clauses, and Dialogic variable definitions.
- **Version lint.** Read `config/features` in `project.godot` against the addon's `plugin.cfg` version, and flag v3-only syntax (unclosed `[if …]`, `translation_key`) in a v4 project.
- **Cutscene skip support.** For each `.tscn` with an AnimationPlayer, list method-track keys, which are text `method` entries in the `.tscn`. Require a matching skip handler, flag looping animations awaited by `animation_finished`, and flag self-referencing animation-playback tracks.
- **Headless playthrough.** Run `godot --headless` with a script that walks every branch with a visit cap and prints `NARRATIVE_SUMMARY lines=N errors=M`. Judge the run by that line.
- **POT parity.** Regenerate the POT and diff it against the committed one, to catch stale templates.

## Pitfalls

- `seek()` silently skips method keys, so skipped cutscenes leave flags unset. `seek()` to the end also never emits `animation_finished`.
- Method keys do not fire in editor preview, so preview gives a false sense of correctness.
- Lines without static IDs are keyed by text, so fixing a typo orphans every translation and VO file.
- DM v3 to v4 renamed titles to cues, made response conditions self-closing, renamed `translation_key` to `static_id`, removed the CSV exporter, and changed the POT key/context. There is a docs conflict on the context, noted in section 3.
- Dialogic is alpha: "code may change at any Dialogic Release". Glossary translations do not fall back.
- C#-only tools (godot-ink, Yarn C#, Arcweave) block web export in Godot 4 C#, per the Arcweave docs.
- inkgd has no Godot 4 release, and the Yarn GDScript version is alpha.
- Shared cached Resources: mutating a loaded quest `.tres` changes every user of it.
- `visible_characters` counts codepoints, so emoji and combining marks reveal oddly.
- Automatic Control translation ignores CSV `?context`/`?plural`.
- CSVs saved by Excel are ANSI by default, so they break the import.
- Year missing on several GitHub release pages (godot-ink, Arcweave, ink): treat those dates as UNVERIFIED.

## Risks and uncertainties

- Release years for DM and Dialogic are inferred from engine targets. Re-check them on the release tags.
- The DM POT msgctxt behaviour is contradicted between two of its own docs.
- Dialogic's `.dtl`/`.dch` extensions and save API come from memory and a GitHub discussion, not docs.
- No authoritative sources were found for barks, quest architecture, Twine import or Godot lip-sync. Those sections are patterns, marked as such.

## Sources

- Godot 4.7 docs:
  - https://docs.godotengine.org/en/4.7/tutorials/i18n/localization_using_gettext.html (POT generation, context, plurals)
  - https://docs.godotengine.org/en/4.7/tutorials/i18n/localization_using_spreadsheets.html (CSV rules, 4.6 `?context`/`?plural`)
  - https://docs.godotengine.org/en/4.7/classes/class_editortranslationparserplugin.html (custom POT parser)
  - https://docs.godotengine.org/en/4.7/classes/class_richtextlabel.html and https://docs.godotengine.org/en/4.7/tutorials/ui/bbcode_in_richtextlabel.html (typewriter, effects)
  - https://docs.godotengine.org/en/4.7/tutorials/animation/animation_track_types.html, https://docs.godotengine.org/en/4.7/classes/class_animationplayer.html and https://docs.godotengine.org/en/4.7/classes/class_animationmixer.html (cutscenes, seek and skip)
  - https://docs.godotengine.org/en/4.7/tutorials/scripting/resources.html (custom Resources, caching)
- Dialogue Manager:
  - https://github.com/nathanhoad/godot_dialogue_manager (README)
  - /releases and docs/Basic_Dialogue.md, Conditions_Mutations.md, Translations.md, Upgrading_Version.md and Using_Dialogue.md in that repo
- Dialogic:
  - https://github.com/dialogic-godot/dialogic and its /releases page
  - https://docs.dialogic.pro/, https://docs.dialogic.pro/translation.html and https://docs.dialogic.pro/variables.html
  - https://www.github.com/dialogic-godot/dialogic/discussions/2104 (save API)
- Ink:
  - https://github.com/paulloz/godot-ink and its /releases page
  - https://github.com/ephread/inkgd
  - https://github.com/inkle/ink/releases
- Yarn Spinner:
  - https://github.com/YarnSpinnerTool/YarnSpinner-Godot and its /releases page
  - https://docs.yarnspinner.dev/3.1/yarn-spinner-for-godot/godot-gdscript
  - https://docs.yarnspinner.dev/write-yarn-scripts/advanced-scripting/tags-metadata.md
  - https://www.yarnspinner.dev/blog/monthly_jun_26 (GDScript nearing beta)
- External writer tools:
  - https://github.com/arcweave/arcweave-godot-plugin and its /releases page
  - https://forum.godotengine.org/t/articy-to-godot-json-importer-and-player-addon/140370 and https://aimarzhang.itch.io/articy-exporter-for-godot (articy community tools)
- Lip-sync: https://github.com/DanielSWolf/rhubarb-lip-sync
- Godot release dates (third-party): https://app.cinevva.com/news/2026-06-19-godot-4-7-released and https://gamedev.net/news/5172-godot-engine-472-stable-released/
