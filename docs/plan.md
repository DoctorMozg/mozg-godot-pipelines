# mozg-godot — implementation plan

Status: approved 2026-11-12, including the asset registry and localization added the same day. Research behind every item is in `docs/research/01-16`.

## Goals (from the user)

1. A Claude Code marketplace for Godot 4 game development, shaped like `mozg-video-plugins`.
1. **Fast feedback**: per-edit checks under 1 s, per-task checks under 10 s, full gate only before commit.
1. **One review hub in the browser** for every resource (2D, sprites, 3D, audio, UI screenshots, shaders as clips, design graphs, translated strings). Each item can be approved or **marked for redo** with a note, and the decision reaches the agent automatically.
1. **Game-design tools**: progression graphs with analysis (reachability, chain length per playstyle, pacing, duration), balance simulation, and sourced web research on reference games and mechanics.
1. **Asset storage**: every game resource is registered with metadata, versions, provenance, comments and notes.
1. **Localization**: strings are stored with context and notes, translated, checked and built into what Godot loads.

## Assumptions

- Python 3.11 stdlib for every kit; heavy or optional tools are detected, never required (`godotkit doctor` reports them).
- Godot 4.7.2 at `/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64` is the test engine; support floor 4.4 (UID files) is checked by fixtures later, not promised now.
- AloneGodot is a **read-only** test bed: kits run against a scratch worktree of it, never commit to it.
- Browser libraries are vendored into the plugin (offline, pinned), not loaded from a CDN at runtime.
- Genres: the suite targets any Godot game. Besides AloneGodot (2D, UI-heavy campaign), two tiny test beds in `testbeds/` cover a 3D action arena and an RTS, so every check is proven on three kinds of game.
- Disk is ext4: `cp --reflink=auto` falls back to a real copy of `.godot` (still avoids reimport). Disk is 95 % full: fixtures stay small, scratch worktrees are cleaned.

## Structure

```
plugins/
  godot-core/      godotkit   fast loop tiers, gates, receipts, hooks, init/verify/test/scene skills
  godot-assets/    assetkit   asset registry (records, versions, events, provenance) + browser review hub
  godot-l10n/      l10nkit    string store, translation pipeline, checks, PO build, pseudo-loc
  game-design/     designkit  design data, graph analysis, simulation, views, interview/canon/research skills
  godot-studio/               team orchestration on mz-dev-pipe
  godot-art/       artkit     2D + 3D assets via fal-media, import/VRAM audits
  godot-ui/        uikit      brief → HTML prototype → Godot handoff, theme, multi-res capture
  godot-audio/     audiokit   cue sheet, synth/fal SFX, loudness, buses, listening
  mozg-godot-suite/           dependencies only
```

`godot-assets` replaces the approved `godot-review`. The hub shows the registry, and a decision made in the hub is a registry event, so registry and review share one store and one contract. Art, audio, UI, design and l10n write records through the contracts in `contracts/`, never by importing another kit.

## Fast loop (godot-core)

```
Tier 0  <1 s   every edit (PostToolUse hook)   no new Godot process
        gdscript formatter/lint on the changed file  +  LSP diagnostics from a long-lived
        `godot --editor --headless --lsp-port P` per worktree  +  .tscn/.tres reference lint
Tier 1  <10 s  per task (`godotkit check --affected`)
        affected tests from a dependency graph (preload/extends/class_name/ext_resource),
        one fresh headless process on a warm .godot, verdict from log tokens + summary line
Tier 2  gate   before commit (`godotkit gate` → receipt)
        warm-cache import + uid churn check, full parse gate, boot gate with real input,
        duration-balanced shards with isolated user://, optional native capture
```

Every command prints one JSON line; exit code of Godot is never trusted alone.

### GDScript standard

Research: `docs/research/17-gdscript-strict-typing.md`, `18-gdscript-architecture.md`, `19-gdscript-tooling.md`.

- Strict profile:
  - `untyped_declaration`, the four `unsafe_*` warnings, `missing_await`, the `unused_*` and `shadowed_*` warnings, `integer_division` and `narrowing_conversion` at Error.
  - `return_value_discarded` at Warn.
  - `directory_rules` excludes `res://addons`.
- Enforcement: in a debug or editor build an Error-level warning fails `load()`, so `godotkit check` enforces the profile with no extra tool. Proven on 4.7.2 in A5a; the gate's own probe scripts load with every warning at Error, since the project's levels apply to them too.
- `godotkit strict` reports the project's levels against the profile, and with `--write` sets them; that changes `project.godot`, so a skill asks the owner first.
- `godotkit lint` checks the architecture rules Godot does not:
  - no `get_parent()` and no `..` node paths;
  - no string `connect("…")` or `emit_signal("…")`;
  - no `free()` on a Node without a comment;
  - `create_timer` in gameplay passes `process_always = false`;
  - the gdlint member order.
- `# godotkit:ignore=<rule>` on the line or the line above silences one rule; a plain comment there also satisfies the `free()` rule. AloneGodot (2026-11-13): 344 scripts in 0.6 s; 147 `free()`, 108 `get_parent()`, 14 timers, 8 string signals, for the A5r baseline.
- gdlint and gdformat run when installed. `doctor` reports them, and nothing requires them. `godotkit lint` reports their rules as `gdlint:<rule>`, files to reformat as `format` and files they cannot parse as `parse`; gdlint's `class-definitions-order` is dropped because the godotkit member order matches it (inner classes skipped, their bodies ordered).
  AloneGodot (2026-11-13): no member-order finding, as with gdlint; 344 scripts take 16.6 s with gdtoolkit 4.5.0 against 0.6 s without. GDQuest `gdscript-formatter` is not wired: its output is UNTESTED.
- The checkable rules of research 18 ship as a skill reference (`gdscript-rules.md`), which code-writing skills load.

### Scene and resource references

`godotkit lint` also reads `.tscn`/`.tres` text. Behaviour checked on 4.7.2 (2026-11-13):

- An undeclared `SubResource("id")` or `ExtResource("id")`, or a duplicate id, makes the file fail to load.
- An `ext_resource` whose path is gone and whose UID is unknown fails; an unknown UID with a valid path only warns and falls back to the path (`stale-uid`).
- A `parent=` naming no node only warns and drops the node; a `[connection]` from a missing node is lost with no message (`unknown-node-path`). Paths under an instanced node are trusted.
- A scene or resource header UID declared by another file is a `duplicate-uid`.
- AloneGodot: 28 scenes and resources, no finding; one scene takes 0.17 s including the project UID index.

### Shader standard

Research: `docs/research/20-shader-writing.md`, `21-shader-verification.md`.

- Compile gate with no GPU: `--headless` runs Godot's shading-language front end on every `.gdshader` it loads, so `godotkit check` loads each shader and material and fails on `SHADER ERROR`, `Shader compilation failed` or `not supported in Dummy renderer`. Headless errors carry no file name, so the probe loads one shader per marked log section. UNTESTED on 4.7.2.
- Backend gate, optional: Forward+/Mobile under Xvfb with lavapipe and Compatibility with llvmpipe catch SPIR-V and driver errors. Renderer fallback is disabled and the active driver is asserted from the log. `doctor` reports Xvfb and the Mesa drivers; nothing requires them. UNTESTED: Xvfb is not installed on the development machine.
- `godotkit lint` shader rules from research 20:
  - no 3.x names (`SCREEN_TEXTURE`, `DEPTH_TEXTURE`, `hint_color`, `hint_albedo`, `.shader`);
  - colour uniforms and albedo samplers carry `source_color`; every sampler has explicit `filter_*` and `repeat_*`;
  - Forward+-only features sit behind `#if CURRENT_RENDERER`;
  - `ALPHA` written only with a reason; `DEPTH` written on every path;
  - shaders live in `.gdshader` files, not embedded in scenes;
  - no per-spawn `material.duplicate()` in scripts; `instance uniform` instead.
- Review: shaders reach the hub as Movie Maker clips (`--write-movie`, fixed fps) per target renderer; goldens are keyed by renderer, driver and adapter.
- Cost: GPU timings from llvmpipe/lavapipe are not shader cost; timing gates run only on real hardware, while draw calls and pipeline-compilation counters are gated anywhere.
- The checkable rules of research 20 ship as a skill reference (`shader-rules.md`).

### LLM playtesting (`godotkit play`)

Research: `docs/research/35-llm-game-agents.md`, `36-godot-play-bridge.md`, `37-llm-playtest-method.md`.

```
godotkit play  (Python, listens on 127.0.0.1:0, token)
   └─ spawns Godot --fixed-fps 60 on a scratch worktree with an injected bridge autoload (client)
        hello → welcome(seed) → obs ⇄ step{acts, frames:N} ... → end → MOZG_PLAY_SUMMARY line
LLM loop: JSON snapshot (≤ 6k tokens, valid actions listed) → one semantic action → harness checks success
outputs: actions.jsonl (replay script), findings.json (fingerprinted), hub items, cost per run
```

- Lockstep: the bridge blocks the main loop between steps under `--fixed-fps`, so thinking time never becomes game time. It never writes `SceneTree.paused` and starts only with `editor_runtime` plus its user arguments.
- Observation: Control properties (rect, text, `accessibility_name`, focus) and nodes that opt in through group `playtest_observe`. A screenshot is an explicit `look` under Xvfb; headless has none.
- Action: input actions through `Input.parse_input_event` with held frames, clicks on Control rects, and semantic actions the game declares through group `playtest_actor`. The bridge calls only the three catalogue methods: no `Expression`, no arbitrary `call`.
- Modes by genre: `llm_stepped` for UI, turn-based and paused strategy; `scripted_bot` for real-time 3D and RTS micro, where the LLM writes a bot, runs it at full speed and reads the log.
- Oracles in order of trust: engine error, broken invariant, unmet success predicate, stuck detector, time anomaly, LLM observation. A `bug` needs evidence and a replay of the action log without the LLM; LLM remarks on clarity or difficulty are `ux_hypothesis` items for a human playtest.
- Budgets: steps, tokens, wall time and game time are required in every scenario. The cost estimate in research 35 is derived; the first pilot run measures it.

## Asset registry and review hub (godot-assets)

Research: `docs/research/15-web-asset-registry.md`. Every write adds a new file, so parallel worktrees never conflict and no `merge=union` is needed (GitHub web merges ignore it).

```
<project>/registry/                       .gdignore: Godot never imports, loads or exports it
  assets/<family>/<asset_id>/
    asset.json                            id (slug-xxxx, never changes), kind, title, tags, owner, ship
    versions/<ULID>.json                  immutable: files[{role,path,sha256,bytes,storage}], media,
                                          provenance{origin,license SPDX,source_url,attribution,
                                          digital_source_type IPTC,human_edited,c2pa}, generation{
                                          provider,model,job_id,prompt,seed,params,inputs}
    events/<ULID>.json                    immutable: note | decision approve/retake/reject | status |
                                          promote{res_path,godot_uid}; reply_to threads notes
  staging/<asset_id>/<version>.<ext>      candidates before promotion
<project>/.cache/mozg/registry.sqlite     generated index, gitignored, rebuilt when records change
```

- Status is folded from events, never stored: draft → pending_review → approved | retake → final, plus rejected and deprecated. A new version starts pending; a decision on an older version goes stale.
- Godot UID and `res://` path are recorded on promotion as a lookup key; `assetkit doctor` finds moved files by UID, then by sha256, and reports missing files and sha mismatches.
- `assetkit ship-report` answers "which shipped assets are AI-generated" (Steam disclosure).
- Rejected variants are pruned to a content-addressed store outside the repo, keeping sha256 and location in the version record. Git LFS is reported by `doctor`, not required.

```
assetkit hub build → static page + item bundle (thumbs cached by sha256; audio LUFS; glb stats)
assetkit hub serve → 127.0.0.1:random, token, Host/Origin checks, path sandbox
browser: grid with status pills (pending/approved/retake/stale), filters in URL hash, keyboard A/R/J/K,
         per-kind viewer: image + 120/240 px + before/after | sprite frames + onion skin |
         3D model-viewer (+three.js inspect) | audio waveform + loop seam + A/B | video/clip |
         UI per resolution | graph (design) | string per locale with screenshot ; region notes, threads
POST /api/events → the same writer the CLI uses → registry/assets/.../events/<ULID>.json (in git)
hook (SessionStart + UserPromptSubmit): injects retake decisions not yet answered by a newer version
without a server the page is read-only; no localStorage decisions
live updates: server-sent events push new items and versions to the open page; no reload
one hub per project: port and pid in .cache/mozg/hub.json, skills reuse it, `assetkit hub stop` ends it
session-start hook prints the running hub's URL
```

## Localization (godot-l10n)

Research: `docs/research/16-web-i18n.md`. The structured store is the source of truth; Godot files are built from it.

```
<project>/i18n/
  src/<namespace>.json          .gdignore; source records sorted by key: source, context, note,
                                max_chars, max_px, placeholders, markup, plural forms, screenshots,
                                tags, dnt, dynamic key patterns
  locales/<locale>/<ns>.json    .gdignore; text or plural forms, status new|machine|translated|reviewed,
                                source_hash, by{kind,model,at}
  events/<ULID>.json            .gdignore; notes and review decisions on KEY@locale (same event contract)
  glossary.json  style/<locale>.md
  build/<locale>.po             generated, deterministic: msgctxt, plurals, #. notes, #, fuzzy when stale
```

- Agents change strings only through `l10nkit add|edit|remove`; a hook blocks direct edits of `build/`.
- Stale is computed (`source_hash` differs from the hash of source, context and plural forms), never stored; stale entries are built as fuzzy, so Godot falls back to the source text.
- `reviewed` is set only from the hub by a person; the CLI has no command for it.
- Translation: batches per namespace and locale with context, notes, limits, screenshot, glossary, style guide and translation-memory matches; placeholders and BBCode masked as tokens and restored; status `machine` with provenance; a fresh-context QA judge adds findings as events.
- Checks: missing, orphan and duplicate keys (dynamic patterns declared), placeholder and BBCode parity per plural form, plural count per locale, `max_chars`, hardcoded strings in `.gd` and `.tscn` (Godot's extractor patterns, `# NO_TRANSLATE`), and in Godot: `max_px` with the theme font, font coverage, pseudo-loc layout overflow and the `override` run that exposes untranslated text.
- Release gate: shipped locales have 0 missing, 0 stale, 0 check errors.

## Game design (game-design)

```
design/progression  economy  balance   (JSON, single source of truth)
designkit validate | analyze | simulate | sync | render
  analyze : reachability, dead ends, cycles, critical path, depth per playstyle, pacing gaps, coverage matrix
  simulate: Monte-Carlo campaign duration (P10/50/90 vs target band), economy pools, hazards (seeded)
  sync    : drift between design data and .tres / CSV / doc number blocks
  render  : hub items of kind graph/chart (Cytoscape + ELK layout precomputed, charts) → per-node redo
skills: gd-interview (numbered questions → decision log), gd-canon, gd-contracts/handoff (OPEN rows block code),
        gd-balance, gd-review (judge), gd-research (web: reference games/mechanics, sourced, via pipeline-web-researcher)
```

Balance models. `analyze` (graph, reachability, pacing) works for any genre. `simulate` runs one balance model, each with its own JSON schema: campaign and economy (AloneGodot) first, then combat (DPS, time to kill, encounter pacing) on the arena test bed and build order plus counter matrix on the RTS test bed. The shared model interface is extracted only once the second model exists, so it fits two real cases instead of a guess.

## Development process (godot-studio)

Research: `docs/research/07-orchestration-dx.md` (how Codex built AloneGodot). One orchestrator session plans, hands out lanes and merges; each lane is a subagent in its own warm worktree with a set of files it owns. Review in the hub never blocks a lane.

```
design (designkit) ──► tasks with acceptance checks ◄── retake hook (hub redo events)
                              │
        orchestrator: lanes by file ownership; brief = base commit, owned files, checks, "do not push"
              │                    │                         │
        code lane              code lane                asset lanes (fal, synth, UI)
        worktree new (warm)    worktree new (warm)      → registry versions (append-only)
        edit → Tier 0          edit → Tier 0
        test --since → gate    test --since → gate
        → receipt              → receipt
              └──────── merge queue (one at a time) ─────────┘
          merge → rebuild generated files → gate on the merged result → worktree remove
```

### Parallelism rules

1. Data that cannot conflict:
   - Registry versions and events are append-only ULID files.
   - Locale strings are one JSON file per locale and namespace.
   - Design data is one JSON file per entity.
1. Generated files are rebuilt, never merged by hand. After a merge, `.po` files are regenerated and the gate checks freshness; `.import`/`.uid` churn is flagged by the gate.
1. Single-writer files: `project.godot` (autoloads, input map, settings), the main scene and the theme.
   - A lane writes a request file under `.mozg/requests/`.
   - The orchestrator applies requests in the merge queue.
   - The ownership hook blocks direct edits.
1. Scenes are cut along ownership. Large scenes are split into instanced sub-scenes with one owner each, because node and resource ids in `.tscn` files do not merge.
1. Review never blocks. A lane registers a version and moves on; a redo returns as a new task through the retake hook.
1. Machine budget:
   - Code lanes are CPU-bound: about 4 lanes × `--jobs 4` on 16 cores.
   - Asset lanes wait on the network and can run wider.
   - Slow tests are spread across shards by measured duration (A6).
1. Review depth follows risk: mechanical changes get the gate only; a new system, autoload or layer change gets the architecture reviewer.

### Architecture decisions

1. Decided once, by the owner.
   - A new system gets 2–3 options scored on four questions:
     - Can it be tested headless?
     - Which files would it make single-writer?
     - What does it mean for save/load and pause?
     - Does it fit `18-gdscript-architecture.md`?
   - Close calls get a throwaway prototype measured with `boot` and `test`.
   - The owner picks. The choice is recorded in `docs/decisions/NNN-<slug>.md` in the game repo, with "revisit when" triggers.
   - A lane that needs to break a decision stops and asks.
1. Rules become checks:
   - `architecture.json` declares layers (path globs), allowed layer edges, `max_autoloads`, `max_file_lines` and `no_cycles`.
   - `godotkit arch` checks them on the A4 dependency graph, together with `godotkit lint` and the strict warning profile.
   - Semantics: a layer is a list of globs where `*` also crosses folders, and the first matching layer wins. Edges inside a layer and files outside every layer are free. `max_file_lines` covers `.gd` outside `addons/`; `no_cycles` reports each group of scripts that reach each other.
   - AloneGodot dry run (2026-11-13): 0.31 s; no production script depends on tests, none is over 300 lines, one cycle of 8 scripts.
1. Coupling is measured. Gate receipts record reach per test (median, p90, max, entries reaching every file) and the change against the base commit. AloneGodot baseline: median about 60 files, ordinary maximum about 300, `smoke.gd` reaches all 4,159.
1. Fresh-eyes review. Risky changes get an architecture reviewer subagent that has the decision records and rules but not the author's reasoning.
1. Limits: whether an architecture serves the game shows only at runtime. The boot gate, playtests and hub review cover that; the process keeps decisions cheap to revisit rather than claiming them right up front.

## Milestones

Each milestone ≤ 10 files / 400 changed lines (mechanical ports excepted), ends with `make check` green and one commit. Order: A → T → B → C → L → M → P → D to G.

### Phase A — repo and godot-core

| #   | Milestone                                                                                                                                                                                      | verify                                                                                                                                                                                                                                                                                     |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A0  | Scaffold: marketplace.json, CLAUDE.md, Makefile, pyproject, pre-commit, CI; port `tools/` from mozg-video-plugins                                                                              | done `ea8ce6c`                                                                                                                                                                                                                                                                             |
| A1  | godotkit: `doctor`, Godot locator, log judge, isolated `run`                                                                                                                                   | done `16621f7`: real Godot exits 0 on script and parse errors, `run` reports `ok:false`                                                                                                                                                                                                    |
| A2  | `import` + `worktree new`: warm `.godot` copy, `use_multiple_threads=false` option, uid/translation churn report                                                                               | done: warm import 7.1 s against 32.8 s cold, 2.4 GB hardlinked; see `docs/measurements.md`                                                                                                                                                                                                 |
| A3  | `check` parse gate + `boot` gate with injected temporary input bridge                                                                                                                          | done: AloneGodot at `d1d7760~1` fails `boot` with `input_dead` in 3 s, `d1d7760` passes; parse gate 342 scripts in 12.8 s                                                                                                                                                                  |
| A4  | `test`: custom summary-line harness, `godotkit.json` entries, dependency graph, `--since`/`--changed`, parallel jobs with isolated XDG                                                         | done: 43,341 checks match AloneGodot's runners; selection 0.33 s, but `smoke.gd` reaches everything and takes 35–58 s, so affected runs take 41 s or more                                                                                                                                  |
| A4b | GdUnit4 adapter (`results.xml`, `--ignoreHeadlessMode`, empty report fails) and GUT adapter (`-gjunit_xml_file`)                                                                               | done: real GdUnit4 6.2.3 and GUT 9.7.1 judge pass, fail and parse-error suites right; GUT exits 0 on a parse error                                                                                                                                                                         |
| A5  | Tier 0: formatter/lint wrapper, `strict`, `lint` rules, `arch` (layers from `architecture.json` on the dependency graph), LSP client (`lsp start`, `lsp diag`), `.tscn`/`.tres` reference lint | diagnostics for a broken fixture in < 1 s with a warm LSP; an Error-level warning fails `check` on real Godot; a forbidden layer edge fails `arch`. Steps: A5a `strict` (done), A5b `lint` (done), A5b2 gdlint/formatter wrapper (done), A5c scene lint (done), A5d `arch` (done), A5e LSP |
| A5s | Shader gate: headless load of every `.gdshader`/material with marked log sections; shader `lint` rules; `doctor` reports Xvfb and Mesa drivers                                                 | a fixture with an unknown identifier fails `check` on real Godot with the shader path named; a `SCREEN_TEXTURE` fixture fails `lint`                                                                                                                                                       |
| A5r | Baseline: `baseline write`, `baseline shrink`; `check`, `lint`, `arch` and `strict` fail only on new violations or growing counts; a file joins the strict profile once clean                  | a fixture with old violations passes; one new violation fails; `shrink` never raises a count                                                                                                                                                                                               |
| A6  | `gate` + receipts (`receipt write`, `receipt verify`); receipts carry reach metrics against the base commit; duration-balanced shards; post-merge rebuild of generated files                   | gate on fixtures writes a receipt; an edit after the receipt makes verify fail; a change adding a cross-layer edge shows a reach increase                                                                                                                                                  |
| A7  | Hooks: PostToolUse Tier 0 on .gd/.tscn/.tres, 280-line warning, SKIP guard, commit-needs-receipt, single-writer guard (`project.godot`, main scene, theme → request file)                      | hook unit tests; hook adds < 1 s per edit on AloneGodot; a lane edit of `project.godot` is refused with the request path                                                                                                                                                                   |
| A8  | Skills: godot-init, godot-verify, godot-test, godot-scene (+ evals)                                                                                                                            | lint_skills clean; ≥ 3 eval cases per skill pass                                                                                                                                                                                                                                           |
| A9  | `native` + `shot`: real renderer run, multi-resolution capture in one process, UI node/rect snapshot JSON                                                                                      | fixture captured at 3 resolutions from one process; snapshot lists controls with rects                                                                                                                                                                                                     |

### Phase T — test beds

Two tiny projects of plain text files (scenes, scripts, primitive meshes, no binary assets), each under 300 KB, used by `live_godot` tests from Phase A on.

| #   | Milestone                                                                                                                 | verify                                                                                 |
| --- | ------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| T1  | `testbeds/arena3d`: CharacterBody3D player, one enemy, AnimationTree, Camera3D with collision, Jolt physics, seeded start | parse, boot and test gates pass; a scripted bot finishes the arena with a summary line |
| T2  | `testbeds/rts`: about 500 units as MultiMesh, NavigationAgents, one resource, two bases, seeded match                     | gates pass; a bot-vs-bot match ends within a tick budget with a summary line           |

### Phase B — godot-assets

| #   | Milestone                                                                                                                                                                         | verify                                                                                                                                                                                                                     |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1  | Contracts `asset`, `asset-version`, `item-event`; assetkit `new`, `version add`, `note`, `decide`, `status`, sqlite index                                                         | two git worktrees add versions and events to one asset and merge with no conflict; status fold covers every transition                                                                                                     |
| B2  | `promote` (UID read after headless import), `doctor` (moved, missing, sha mismatch), `ship-report`, prune to blob store                                                           | fixture project: moved file found by UID, edited file flagged, AI-generated shipped asset listed                                                                                                                           |
| B3  | `hub build` (2D images) + `hub serve` with security, live updates (SSE), one hub per project (`hub.json`, `hub stop`), URL in the session-start hook; decisions written as events | pytest: token/Host/Origin/path traversal rejected; a second `serve` reuses the running hub; headless Chrome approve/retake writes an event; a new version reaches the open page without reload and makes the old one stale |
| B4  | Viewers: sprite frames, audio (waveform, seam, A/B), 3D (model-viewer, three.js inspect), video, UI multi-res, region notes                                                       | one fixture per kind renders in headless Chrome with no console errors                                                                                                                                                     |
| B5  | Retake hook + `assetkit pending`; skills asset-registry, review-hub; importer for AloneGodot's 36 manifests (dry run)                                                             | hook injects a fixture retake; AloneGodot scratch worktree imports with a report of unmapped fields; evals pass                                                                                                            |

### Phase C — game-design

| #   | Milestone                                                                                                    | verify                                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| C1  | Schemas + `designkit validate`, `designkit analyze`                                                          | AloneGodot progression fixture: dead end and unreachable node reported                       |
| C2  | `simulate` (duration, economy, hazards) + `render` into the hub (graph, pacing, duration, coverage, economy) | seeded runs reproducible; views render; per-node retake reaches the registry                 |
| C3  | `sync` drift check + skills gd-interview, gd-canon, gd-contracts/handoff, gd-review judge                    | drift fixture catches stale number (oxygenPerDay case); evals pass                           |
| C4  | gd-research skill (web research on reference games/mechanics, cited) + gd-balance skill                      | evals pass; sample research report has a source per claim                                    |
| C5  | Combat model (arena) and RTS model (build order, counter matrix); shared model interface extracted           | both test beds simulate from JSON; a dominant-unit fixture is reported by the counter matrix |

### Phase L — godot-l10n

| #   | Milestone                                                                                                                            | verify                                                                                                               |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------- |
| L1  | Contracts `string`, `string-translation`; l10nkit `add`, `edit`, `remove`, `list`, `status` (stale computed); import of Godot CSV    | AloneGodot `i18n/game.csv` (259 keys) imports and exports back to an identical CSV                                   |
| L2  | `build`: PO per locale (msgctxt, plurals, fuzzy when stale), optional 4.6+ CSV                                                       | live_godot: `tr`, `tr_n` and context resolve from the built PO; a stale entry falls back to the source text          |
| L3  | `check`: keys, dynamic patterns, placeholder and BBCode parity, plural count, `max_chars`, hardcoded strings in `.gd` and `.tscn`    | one fixture per rule fails; AloneGodot report produced without false positives on its declared dynamic keys          |
| L4  | Translation: `batch export` (masked, glossary, style, TM, context) and `batch apply` (restore, parity, provenance); QA judge; skills | eval: a fixture batch translated and applied with placeholders intact; a hook blocks edits of `build/`               |
| L5  | In Godot: `max_px`, font coverage, pseudo-loc layout and override runs; per-locale screenshots and string review in the hub          | overflow fixture caught at one resolution; a hardcoded label exposed by the override run; hub review sets `reviewed` |

### Phase M — migration of an existing project

Rehearsed on a scratch worktree of AloneGodot; applying it to AloneGodot itself is a separate task for its owner.

| #   | Milestone                                                                                                                                             | verify                                                                                       |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| M1  | `godot-init` on an existing project: `godotkit.json`, `architecture.json` describing the current graph, `baseline write`, `doctor` report of blockers | AloneGodot worktree: gates pass on unchanged code; the blocker report lists the known issues |
| M2  | Hooks, gates and receipts on; only new code must be clean                                                                                             | a new untyped function fails, old code passes                                                |
| M3  | Imports for real: asset manifests → registry, CSV → string store, design data → JSON                                                                  | round trips give identical files; the hub shows the imported items                           |
| M4  | Clean-up lanes shrink the baseline one module at a time                                                                                               | the baseline count drops and no gate regresses                                               |

### Phase P — gameplay probes

Each probe runs headless where possible, prints one summary line and is judged by `godotkit` like the other gates. Research: 23, 24, 25, 28, 34.

| #   | Milestone                                                                                                             | verify                                                                                                                                    |
| --- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| P1  | Determinism: fixed-tick replay of recorded inputs gives the same state hash                                           | arena and RTS replays match; a seeded random leak fixture fails                                                                           |
| P2  | Scale: units at N = 100, 500, 2,000 report frame time, draw calls, navigation time                                    | RTS budget table in the receipt; a fixture without MultiMesh breaks the budget                                                            |
| P3  | Feel: input-to-response frames, camera clipping, stuck detection                                                      | arena fixture with a one-frame input delay is reported                                                                                    |
| P4  | `play` bridge: lockstep NDJSON over loopback TCP, catalogue groups, input with held frames, replay of `actions.jsonl` | bridge self-test fixture: a held action stays pressed N frames, a click on a Button emits `pressed`; a replay reaches the same state hash |
| P5  | Scenario and finding schemas, oracles, stuck detector, claim checker, cost accounting; findings into the hub          | scenario lint rejects a goal without a success predicate; a planted invariant break becomes a confirmed `bug`; duplicates merge           |
| P6  | Skills `godot-playtest` (llm_stepped) and `godot-bot` (scripted_bot); pilot on AloneGodot UI, arena and RTS test beds | pilot runs end with summary lines; measured cost per scenario replaces the estimate; evals pass                                           |

### Phase D–G — outlines (detailed when reached)

- **D godot-studio**: role map → subagents, ownership manifest + hook, delegation template (base commit, owned files, checks, return contract), request files for single-writer files and the merge queue that applies them, frozen-test lock, worktree lifecycle, risk-based review depth on mz-dev-pipe, decision-record template + options-and-scores step + architecture reviewer agent (see Development process).
- **E godot-art**: art-bible, asset-brief with dependents, art-batch via fal-media (2D and 3D: Trellis/Hunyuan GLB with decimation) writing registry versions with generation provenance, import/mipmap/VRAM audit, readability + style judges.
- **F godot-ui**: ui-brief, HTML prototype template, handoff template, tokens → Theme, multi-res capture into the hub; string keys through l10nkit.
- **G godot-audio**: cues.json, synth/fal SFX, music loop points, loudness checks, bus lint, audition in the hub.

## Decisions (2026-11-12)

1. `godot-assets` (registry + hub) replaces `godot-review`; hub decisions are events in git; no localStorage decisions.
1. `godot-l10n` is its own plugin, built after game design: A → B → C → L → D to G (test beds, migration and probes added 2026-11-13: A → T → B → C → L → M → P → D to G).
1. JSON for registry, i18n and design data; no YAML in kits.
1. Built `.po` files are committed; the gate fails when they are stale.
1. Development runs as an orchestrator with file-owned lanes in warm worktrees and a one-at-a-time merge queue; `project.godot`, the main scene and the theme are single-writer (2026-11-13).
1. Architecture is decided by the owner from scored options, recorded as decision records, enforced by `godotkit arch` and tracked by reach metrics in receipts (2026-11-13).
1. The suite targets any genre: test beds for a 3D action arena and an RTS, a baseline ratchet for existing projects, a migration phase and gameplay probes (2026-11-13).
