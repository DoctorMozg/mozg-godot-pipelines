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
  godot-studio/    studiokit  lanes, ownership, frozen tests, merge queue, decision records
  godot-art/       artkit     art bible and briefs, fal-media ingest into the registry, import, VRAM and GLB audits
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

### Baseline (`godotkit baseline`)

- `godotkit-baseline.json` in the project root counts old violations per gate, file and rule; counts, not lines, because lines move with every edit above a finding.
- `lint` and `arch` apply it whenever the file exists: a (file, rule) whose count grows fails with all its findings listed, since which one is new cannot be told; `--no-baseline` shows everything.
- `baseline write [--gates …]` records the gates asked for (default: `lint`, and `arch` where `architecture.json` exists); `baseline shrink` lowers each count to what is found now and never raises or adds one.
- gdlint findings are counted when gdtoolkit is installed at write time; installing it later makes its findings new.
- `check` applies it too: a failed script is rule `load`, a shader error rule `shader`. A run that failed only on such files and grew no count passes with reason `baselined`; a crash, timeout or missing summary never does, and `baseline write` refuses to record one.
- `check --strict` runs the parse gate with the strict profile in a temporary `override.cfg`, leaving `project.godot` untouched; its failed scripts are the files not yet strict (baseline gate `strict`). A file leaves the baseline at the next `shrink` once it loads clean, and from then on fails if it regresses: a file joins the strict profile once clean.
- `baseline write` defaults to every gate that applies; without Godot, `check` and `strict` are listed as `skipped`.
- AloneGodot worktree at HEAD (2026-11-13): every gate in 15.2 s; 282 lint findings, no `check` failure, 65 of 342 scripts not yet strict. 36 of those fail with "Failed to compile depended scripts", so strict clean-up goes from leaves to dependents.

### Gate and receipts (`godotkit gate`)

- `gate` runs every step even after one fails, so one run shows everything: warm import (fails when it changes tracked or new files: generated files are committed, never merged by hand), parse gate, `lint`, and `arch` where `architecture.json` exists; each applies the baseline.
- It always writes a receipt to `.godot/godotkit/receipts/<time>-gate.json`: Godot version, HEAD, tree hash and every step with status, reason, duration and detail. There is no separate `receipt write`, because a receipt not produced by a gate run would be a claim nothing checked.
- Tree hash: a clean tree is named by its HEAD tree; a changed one by that tree plus `git hash-object` (no `-w`) of every changed and untracked path outside `.godot`. It writes nothing to the object store: the first version ran `git add -A` into a copied index, which on AloneGodot's main checkout (4,628 untracked art files) took 65 s and left 4,937 unreachable loose objects (2.6 GB) behind. Every godotkit git call sets `GIT_OPTIONAL_LOCKS=0`, so `git status` never rewrites the index of a project it only reads. Same checkout now: 9.3 s, nothing written. Writing a receipt never changes the hash.
- `receipt verify` fails with `no_receipt`, `stale` (the tree moved on) or `gate_failed`.
- Reach in the receipt: for the test entries present at `--base` (default HEAD), median, p90 and max files reached, and entries that may load any file (counted apart, not in max), on the committable working tree (`git ls-files -co --exclude-standard`) and at the base read from git without a checkout, with the change. A new cross-layer preload shows as a max increase.
- AloneGodot (2026-11-13): working tree 0.35 s, a commit 0.25 s. HEAD against HEAD~30: median 62, p90 250 to 251, max 1,346 to 1,463, one entry (`smoke.gd`) may load anything. The max is `card_resources_test.gd`, whose built paths cover whole art folders; the next entry reaches 253.
- Further steps: `strict` when the baseline holds strict counts (a project at the profile is already held to it by `check`), `boot` when a main scene is set, and every non-native test entry.
- Test entries run longest first by the seconds recorded in `.godot/godotkit/durations.json` (never-timed ones first), so a pool of `--jobs` finishes together; `godotkit test` uses the same order and results keep catalogue order.
- AloneGodot worktree at HEAD (2026-11-13), baseline of `lint` and `strict`: 98 s with `--jobs 4`, 65 s of it tests (44 entries, 48,007 checks; 196 s of entry time, longest 43.6 s, so about 49 s is the floor at 4 jobs; the gain of longest-first ordering on a second run is UNTESTED). Two findings. Import rewrites 67 tracked files, because the committed `.import` files predate the current import. 15 entries fail, as under `godotkit test`: they raise expected errors with no `godotkit.json` allow-list, which `godot-init` (M1) writes. By `78b719d` (2026-11-14) import churn is 0 and the suite has 68 entries; the adopted gate takes 99 to 119 s (`docs/migration-rehearsal.md`).
- Proven 2026-11-13 on real Godot: a fresh fixture fails `import` because its first import writes `main.gd.uid`; after committing it the gate passes, and a new file makes `verify` report `stale`.

### Hooks (`hooks/hooks.json`, `godotkit hook EVENT`)

- Protocol: the hook reads the event JSON on stdin; when it has something to say it exits 2 with the message on stderr, which blocks a PreToolUse call and reaches the agent after a PostToolUse one.
- `post-edit` (Edit, Write, MultiEdit on `.gd`, `.tscn`, `.tres` and shader files): lint findings the baseline does not cover, errors from a language server that is already running (it never starts one), and a warning once a script passes the line cap less 20 (`max_file_lines` from `architecture.json`, else 300).
- `pre-edit`: in a linked worktree (a lane), edits of `project.godot`, the main scene and the project theme (`gui/theme/custom`), named by path or uid, are refused with a request path under `.mozg/requests/`. The main checkout is the orchestrator and edits them.
- `pre-bash`: `git commit` of anything beyond docs needs a passing gate receipt for the current tree hash, and `SKIP=` or `--no-verify` are refused. A commit run from above the project folder is not seen (UNTESTED how often agents do that).
- Measured on AloneGodot (2026-11-13), Python start included: `post-edit` and `pre-edit` 0.14 to 0.19 s on a 300-line script, a scene, a shader and `project.godot`; with a live language server the fixture's error arrives within 1 s. The commit guard costs one tree hash (9.3 s on the main checkout with 4,628 untracked files, under its 30 s timeout).

### Skills (godot-core)

- `godot-verify` (fast loop, gate, receipt), `godot-test` (summary-line entries written test-first, allow-lists, native entries), `godot-init` (doctor, read-only survey, owner-approved plan, baseline, first gate) and `godot-scene` (`.tscn`/`.tres` text rules and checks). Each repeats the hard rules in `data/hard_rules.md`.
- Skills call `godotkit` through `bin/godotkit`, which is on the Bash PATH while the plugin is enabled and runs `python3 -I` on the plugin's own `src/`; the hooks use the same launcher.
- Probed on 4.7.2 (2026-11-13) for `godot-scene`: a scene without `load_steps`, or with a wrong one, loads; ids are free text; a node may sit under a node of an instanced scene. A node declared before its parent is dropped with one warning and leaks (`godotkit run --scene` fails with `engine_error`); two siblings with one name load silently. `godotkit lint` catches neither yet.
- Routing evals (2026-11-13): 12 cases, 3 runs each, with and without the plugin. Every positive case fired its skill 3 of 3 with the plugin and 0 of 3 without; every near miss stayed silent while its owner fired 3 of 3. Cost $6.42, 238 s.

### Native runs and captures (`--native`, `godotkit shot`)

- `run --native` and `test --native` render for real on `DISPLAY` (`--display-driver x11`), else `WAYLAND_DISPLAY` (UNTESTED), else under `xvfb-run` with a 3840x2160 screen; with none, the command fails with `no_display` (exit 2) and never passes. Native runs add `--audio-driver Dummy`.
- `shot --sizes 1280x720,1920x1080,2560x1080,1024x768 --out DIR` adds a probe autoload that sizes the window to each size in one process and writes `<W>x<H>.json` (each visible control: path, class, text, canvas rect and window-pixel rect) and `<W>x<H>.png`. A window or image that differs from the size asked fails (`size_mismatch`, `no_image`), and the report names the display, renderer and adapter, so a silent renderer fallback shows.
- `--layout-only` runs headless with no display. Probed on 4.7.2 (2026-11-13): headless control rects equal the native ones at every size, stretch included, but `frame_post_draw` never fires headless, so the probe waits on process frames there.
- The probe loads under the strict warning profile; a run is capped with `--quit-after`, so a probe that fails to load ends with its error, not a timeout.
- Fixture (2026-11-13, X11, RTX 4090, Compatibility): 4 sizes in 1.6 s natively, 0.18 s layout-only. AloneGodot main scene on a scratch worktree: 46 controls per size, 9.1 s natively and 3.6 s layout-only for 4 sizes. llvmpipe under Xvfb is UNTESTED: Xvfb is not installed here.

### Language server (`godotkit lsp`)

- `lsp start` runs `godot --editor --headless --lsp-port P` in its own session, records pid and port in `.godot/godotkit-lsp.json`, reuses a live server, and sends one warm-up `initialize`, since the first one parses the workspace.
- `lsp diag FILE…` opens each script on one connection and waits for its `publishDiagnostics`; severity 1 fails, severity 2 is listed. With no live server it reports `no_lsp` instead of starting one.
- Measured on 4.7.2 (2026-11-13): fixture project starts in 1.6 s; AloneGodot scratch worktree starts in 12.4 s, and every `diag` of one script takes 0.19 s end to end.

### Scene and resource references

`godotkit lint` also reads `.tscn`/`.tres` text. Behaviour checked on 4.7.2 (2026-11-13):

- An undeclared `SubResource("id")` or `ExtResource("id")`, or a duplicate id, makes the file fail to load.
- An `ext_resource` whose path is gone and whose UID is unknown fails; an unknown UID with a valid path only warns and falls back to the path (`stale-uid`).
- A `parent=` naming no node only warns and drops the node; a `[connection]` from a missing node is lost with no message (`unknown-node-path`). Paths under an instanced node are trusted.
- A scene or resource header UID declared by another file is a `duplicate-uid`.
- AloneGodot: 28 scenes and resources, no finding; one scene takes 0.17 s including the project UID index.

### Shader standard

Research: `docs/research/20-shader-writing.md`, `21-shader-verification.md`.

- Compile gate with no GPU: `--headless` runs Godot's shading-language front end, so `godotkit check` compiles every `.gdshader` and every `.tres` Shader, ShaderMaterial or VisualShader before loading scripts, and fails on `SHADER ERROR` (issue kind `shader_error`). Proven on 4.7.2 (2026-11-13):
  - a shader compiles on first use, not on load, so the gate asks each one for its uniform list;
  - headless errors name no file (`at: (null) (:2)`), so each load sits in a marked log section; an error in an include names it (`(res://x.gdshaderinc:2)`);
  - `failed_shaders` lists the loaded file, the file holding the error, line and message;
  - `not supported in Dummy renderer` concerns shader types and nodes such as VoxelGI, not shader code; inside a section it still fails the file;
  - AloneGodot: 342 scripts and 1 shader in 5.8 s, no finding; a planted unknown identifier is reported at its line.
- Backend gate, optional: Forward+/Mobile under Xvfb with lavapipe and Compatibility with llvmpipe catch SPIR-V and driver errors. Renderer fallback is disabled and the active driver is asserted from the log. `doctor` reports `xvfb-run` and the lavapipe ICD and llvmpipe library under `software_drivers`; nothing requires them. UNTESTED: Xvfb is not installed on the development machine.
- `godotkit lint` shader rules from research 20 (`.gdshader`, `.gdshaderinc`, `.shader`); rule ids in brackets:
  - no 3.x names (`SCREEN_TEXTURE`, `DEPTH_TEXTURE`, `NORMAL_ROUGHNESS_TEXTURE`, `hint_color`, `hint_albedo`) \[`legacy-shader-name`\] and no `.shader` files \[`legacy-shader-file`\];
  - colour uniforms and albedo samplers carry `source_color` \[`source-color`\], judged by name (colour, tint, albedo, emission, diffuse); every `sampler2D` has explicit `filter_*` and `repeat_*` \[`sampler-hints`\];
  - `hint_normal_roughness_texture` sits inside `#if CURRENT_RENDERER == RENDERER_FORWARD_PLUS` \[`renderer-guard`\];
  - `ALPHA` written only with a comment on the line or above \[`alpha-write`\]; `DEPTH` written on every path, where an `if` counts only with an `else` that also writes it, and loops never count \[`depth-every-path`\];
  - shaders live in `.gdshader` files, not embedded in scenes \[`embedded-shader`\];
  - no `duplicate()` of a name with a `material` or `mat` segment without a comment \[`material-duplicate`\]; `instance uniform` instead.
  - AloneGodot (2026-11-13): its one shader passes; 7 `material-duplicate`, all real `StandardMaterial3D` copies, for the A5r baseline.
- Review: shaders reach the hub as Movie Maker clips (`--write-movie`, fixed fps) per target renderer; goldens are keyed by renderer, driver and adapter.
- Cost: GPU timings from llvmpipe/lavapipe are not shader cost; timing gates run only on real hardware, while draw calls and pipeline-compilation counters are gated anywhere.
- The checkable rules of research 20 ship as a skill reference (`shader-rules.md`).

### Determinism replay (`godotkit replay`)

- Each run is its own Godot process under `--fixed-fps 60` with an injected autoload. At the start of physics frame n, before any game node, the probe hashes the state of the first node in group `playtest_state` (its `state_hash() -> String`) every `--every` frames, then presses that frame's actions as `InputEventAction` and flushes the input buffer, so the game reads them on the same frame.
- The actions file `godotkit-actions/1` (`godotkit/actions.py`) is JSONL: a header (`schema`, `scene`, `frames`, `every`), press rows `{"f", "action", "pressed", "strength"}`, gesture rows `{"f", "click": path}` and `{"f", "do": name, "args"}` (played after the frame's presses), and hash rows `{"f", "hash"}`; a replay hashes on every `every` frame and on each frame the file hashed. `--record FILE` writes the action changes polled each frame and the hashes of one run, and never replaces a file; a replay of it must reach the same hashes (`mismatch` otherwise), and runs must agree with each other (`diverged`). The play bridge (P4) writes the same file.
- Found on the RTS bed (4.7.2, 2026-11-15): with async navigation map iterations, the first synced frame came one frame later in 1 of 6 processes, which shifts every recorded press by one tick; the match's outcome was the same. With `navigation/world/map_use_async_iterations=false` and `region_use_async_iterations=false`, 12 of 12 runs agreed.
- A person records natively without `--fixed-fps`, so play runs in real time (UNTESTED: no human recording yet).

### Scale probe (`godotkit perf`)

- `godotkit.json` holds `"perf": {"property", "sizes", "warmup", "frames", "budget", "scene"}`. Each size is its own lockstep run with vsync off: the probe starts the scene again with the property set before `_ready`, skips the warmup, then times every frame. `frame_ms` is wall time between frames, `process_ms` and `physics_ms` the game's callbacks, all as p95; `draw_calls`, `objects`, `nodes` and custom monitors (`group/name`) are maxima. A budget with an unknown metric is refused; one naming a custom monitor the game never registered fails as `missing_metric`.
- Godot refreshes its `TIME_*` monitors once per real second, so a lockstep run of fast frames read 0 for them; the probe times frames itself. Navigation time comes from a custom monitor the game registers: the RTS bed queries its routes once at start, so it has none per frame.
- The gate runs `perf` headless, where the renderer counters read zero and stay unjudged (`unmeasured`); `godotkit perf --native` judges them.
- RTS bed (4.7.2, 2026-11-15), p95 frame headless / native RTX 4090: 100 units 0.13 / 0.70 ms, 500 units 1.7 / 2.4 ms, 2,000 units 51 ms headless (physics 51 ms: in a dense battle each retargeting unit scans about a thousand enemies in its 3x3 cells). Draw calls stay at 6 at every size. The gate budgets 100 and 500 units.
- Forward+ instanced 1,000 `MeshInstance3D` boxes sharing a mesh into 1 draw call (4.7.2, 2026-11-15); the cost of a crowd without MultiMesh shows in `objects` (1,000) and `nodes`, not draw calls.

### Feel probe (`godotkit feel`)

- `godotkit.json` holds `"feel": {"subject", "actions", "move", "walk", "budget", "scene"}`, with budget keys `input_frames`, `camera_clip_frames` and `stuck_frames`. Every run goes through the replay probe, so the game needs the `playtest_state` hash of P1.
- Input latency: an idle run and one run per action, pressed on frame 30 and held 10 frames, each hashed every frame; the latency is the frames from the press to the first hash that differs from the idle run. No difference within 20 frames is a breach with value `null`. A hash that leaves out what the press changes (the arena's first hash left out the animation state, so `attack` far from the enemy changed nothing) reads as no response.
- Camera clipping and stuck spans come from one run of the `walk` actions file, sampled every frame: the camera clips when its position is inside a body or level geometry blocks the ray to the subject; characters and rigid bodies crossing the ray are looked past (the arena's enemy crossed it 12 frames on a correct camera). Stuck is the longest span of frames the subject moved under 1 mm a frame while a `move` action was held.
- The first clipping check looked only for the camera inside a body: with a 6 m arm the camera ends beyond the arena's 1 m south wall, outside it, so the ray to the subject is what catches it.

### Play bridge (`godotkit play start|step|end`)

- `play start` writes a session folder under `<project>/.godot/godotkit/play/<id>/` and starts a detached daemon (`playsession.py`) that listens on 127.0.0.1 with a random token, injects `gd/play_bridge.gd` as an autoload and runs Godot with `--fixed-fps 60`. `play step --act JSON --frames N` and `play end` each send one request to it (`playclient.py`); every peer's first line carries the token, and the hello the bridge sends is stored without it.
- The bridge says hello on the first physics frame, once the scene is ready: Godot version, input actions (no `ui_*`) and the `playtest_actions()` catalogue. Each observation is the state after `frame` frames: hash, Controls that are interactive or carry text (path, type, text, rect, focus, disabled, accessibility name, at most 100), `playtest_observe` states, holds with frames left, applied acts as actions-file rows, rejected acts, `playtest_do` results and errors from an `OS.add_logger` logger.
- Acts: `action` with `hold_frames` (pressed on the step's first frame, released `hold_frames` later, across steps), `click` on a visible Control (mouse motion, press and release at the rect's centre through `get_final_transform()`) and `do` for a catalogue name. An unknown action, a missing Control or an undeclared name is rejected and not recorded. `look` saves a PNG natively and answers `no_renderer` headless.
- `play end` releases holds, prints `MOZG_PLAY_SUMMARY status=... steps=... frames=... errors=...`, judges the log and writes `actions.jsonl`; `godotkit replay --actions` of it reaches the same hashes (the UI fixture, 2 runs, 2026-11-15). A session ends itself after `--idle` seconds (900) or `--max-steps` (200).
- Headless windows are 64x64 px on 4.7.2, so a click on a Button at (600, 400) missed until the bridge and the replay probe set the window to the project's viewport size (2026-11-15).
- `godotkit check --strict` on a copy of the arena with the probes inside is a live test: a probe that fails to parse is silently absent, and the game then runs until the timeout (two orphaned runs spun at 90 % CPU before that test existed).

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
- Budgets: steps, tokens, wall time and game time are required in every scenario. Measured on AloneGodot `first-day` (Opus 5.5 headless, 2026-11-15): $0.65 for 6 steps and 14 agent turns, about $0.05 a turn, the top of research 35's derived $0.02–0.045 a decision. A turn carries about 52k prompt tokens, nearly all cache reads, against the 13k research 35 assumed.

### Playtest scenarios and findings (`godotkit playtest lint` and `judge`)

- A scenario (`contracts/playtest-scenario.schema.json`) names a goal, a mode, a persona, seeds, at least one success predicate and a budget of steps, tokens, wall seconds and frames; invariants and milestones are optional. A predicate is `{query: "Node.key", op, value}` over the `playtest_observe` states keyed by node name, or `{log_absent: text}`. `playtest lint` refuses a success list made only of `log_absent`, an ordering op on a non-number and repeated ids.
- Each step of a session appends `{step, act, frames, wall_s, obs}` to `trace.jsonl`. `playtest judge --session ID --scenario FILE` reads it after `play end` and judges in order of trust: engine errors (one finding per normalised message), broken invariants, success, no new hash or milestone for `stuck_after_steps` (20), a spent budget, a late milestone. The result is `pass`, `fail_bug`, `fail_stuck`, `fail_budget`, `fail_unmet` or `invalid`.
- A run without measured cost is `invalid` (`no_cost`): `--usage` reads the JSON of `claude -p --output-format json`, cached prompt tokens counted as input, or `--tokens-in` and `--tokens-out` give it. `--report` adds the agent's claims, checked against the last state (a claim about state the game lacks counts as contradicted), and remarks with a node path or screenshot, which become `ux_hypothesis` findings.
- A finding (`contracts/playtest-finding.schema.json`) is one file under `<project>/playtest/findings/`, named `f-` and 12 hex characters of the sha1 of its fingerprint (oracle, scene, assertion, top frame, normalised error). The same fingerprint from another run merges: its run id is added, `occurrences` grows and confidence only rises. A bug is replayed from the run's `actions.jsonl` without the agent: an engine error is `confirmed` when the replay logs the same normalised error, an invariant when the replay reaches the recorded hashes. The run itself goes to `playtest/runs/<id>/run.json` with its actions file; `playtest/.gdignore` keeps Godot out.
- The hub lists findings beside assets and strings. Approve (fix it), reject (not a problem) and retake (run again) are item events under `playtest/events`; the status folds from the latest, `open` until one exists.

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
- Contracts live in `contracts/`; an installed plugin cannot read the repo root, so each plugin that needs one carries a copy in `data/contracts/`, and a repo test fails when a copy differs. The stdlib checker understands only the keywords the contracts use and refuses a schema with any other.
- The fold is total: an event its status does not allow when it comes (two merged worktrees can produce one) is listed as ignored, a decision on an older version as stale; the CLI refuses both when it writes.
- `assetkit ship-report` answers "which shipped assets are AI-generated" (Steam disclosure).
- Staged files of retaken and rejected versions are pruned to a content-addressed store outside the repo (`<store>/sha256/<aa>/<sha256>`; `$ASSETKIT_STORE`, else the XDG data home). Version records stay as written, so a `prune` event marks the version and the version's sha256 locates the blob. `doctor` counts pruned files and how many this machine's store holds, without failing on another machine's. Git LFS is reported by `doctor`, not required.
- `ship-report` counts a version as AI-made when it or a parent version is `generated` or carries an IPTC generative source type (`trainedAlgorithmicMedia`, `compositeWithTrainedAlgorithmicMedia`, `compositeSynthetic`, `virtualRecording`, and `composite`, which may hold AI; cv.iptc.org, read 2026-11-14).

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

- Routing evals of asset-registry and review-hub (2026-11-14, Claude Code 2.1.325): 6 cases, 3 runs each, with and without the plugin. Each positive fired its skill 3 of 3 with the plugin and 0 of 3 without; each near miss stayed silent while the other skill fired 3 of 3. Cost $3.09, 116 s.
- Manifest import (B5), AloneGodot at 78b719d in a scratch worktree, 2026-11-14: 55 manifests (57 found, 2 `.original.` copies skipped; the plan's 36 grew), 684 take records, 530 distinct versions of 318 assets (77 repeats), no missing file or sha mismatch; dry run 4.2 s, apply 4.4 s, 7.6 MB of records; hub shows 251 pending, 41 approved, 26 rejected. 13 manifests use shapes the importer skips (depth conversions, layer and UI concept lists), 154 takes record no model (imported as generated, `unrecorded`), and 193 field names stay unmapped (top: technical_review, review_status, job_record, step_id). Licence is `LicenseRef-unreviewed` until a person sets it. The real import is M3.
- Region notes carry a W3C media fragment (`xywh=percent:x,y,w,h` or `t=start,end`), an optional file role and frame; the writer refuses a box outside the picture or a reversed range. Viewers live in `data/hub/viewers.js`, one per asset kind; sprite frames come from `frame*` files in numeric order or from one sheet split by `--media hframes=… vframes=…`.
- Browser tests drive headless Chrome over its DevTools pipe (`--remote-debugging-pipe`, fds 3 and 4) with the stdlib only; they are marked `live_browser` and run by `make test-browser`, outside `make check`.
- The hub writes through the same `Review` class as the CLI, so a click obeys the same rules; a decision on a version that is no longer current shows as stale.
- Registered files are the only files served, with a `sandbox` CSP, so an SVG cannot run script in the hub's origin. Starting a hub uses `fcntl`, so it is POSIX-only for now.

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
  render  : SVG views and render.json for the hub: layered graph (stdlib layout), duration, pacing, coverage, economy → per-node redo
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

Each milestone ≤ 10 files / 400 changed lines (mechanical ports excepted), ends with `make check` green and one commit. Order: A → T → B → C → L → X → M → P → D to G.

### Phase A — repo and godot-core

| #   | Milestone                                                                                                                                                                                      | verify                                                                                                                                                                                                                                                                                                                                |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| A0  | Scaffold: marketplace.json, CLAUDE.md, Makefile, pyproject, pre-commit, CI; port `tools/` from mozg-video-plugins                                                                              | done `ea8ce6c`                                                                                                                                                                                                                                                                                                                        |
| A1  | godotkit: `doctor`, Godot locator, log judge, isolated `run`                                                                                                                                   | done `16621f7`: real Godot exits 0 on script and parse errors, `run` reports `ok:false`                                                                                                                                                                                                                                               |
| A2  | `import` + `worktree new`: warm `.godot` copy, `use_multiple_threads=false` option, uid/translation churn report                                                                               | done: warm import 7.1 s against 32.8 s cold, 2.4 GB hardlinked; see `docs/measurements.md`                                                                                                                                                                                                                                            |
| A3  | `check` parse gate + `boot` gate with injected temporary input bridge                                                                                                                          | done: AloneGodot at `d1d7760~1` fails `boot` with `input_dead` in 3 s, `d1d7760` passes; parse gate 342 scripts in 12.8 s                                                                                                                                                                                                             |
| A4  | `test`: custom summary-line harness, `godotkit.json` entries, dependency graph, `--since`/`--changed`, parallel jobs with isolated XDG                                                         | done: 43,341 checks match AloneGodot's runners; selection 0.33 s, but `smoke.gd` reaches everything and takes 35–58 s, so affected runs take 41 s or more                                                                                                                                                                             |
| A4b | GdUnit4 adapter (`results.xml`, `--ignoreHeadlessMode`, empty report fails) and GUT adapter (`-gjunit_xml_file`)                                                                               | done: real GdUnit4 6.2.3 and GUT 9.7.1 judge pass, fail and parse-error suites right; GUT exits 0 on a parse error                                                                                                                                                                                                                    |
| A5  | Tier 0: formatter/lint wrapper, `strict`, `lint` rules, `arch` (layers from `architecture.json` on the dependency graph), LSP client (`lsp start`, `lsp diag`), `.tscn`/`.tres` reference lint | done: a broken script gets LSP diagnostics in 0.19 s on an AloneGodot worktree; the strict profile makes `check` fail an untyped script on real Godot; a forbidden layer edge fails `arch`. Steps A5a–A5e: `strict`, `lint`, gdlint/gdformat, scene references, `arch`, `lsp`                                                         |
| A5s | Shader gate: headless load of every `.gdshader`/material with marked log sections; shader `lint` rules; `doctor` reports Xvfb and Mesa drivers                                                 | done: an unknown identifier fails `check` on real Godot with `res://bad.gdshader` line 2 named, and a planted one in AloneGodot's shader is found at its line (5.8 s for 342 scripts and 1 shader); a `SCREEN_TEXTURE` fixture fails `lint`; `doctor` lists lavapipe and llvmpipe. Steps `adca0f5` (gate), then the shader lint rules |
| A5r | Baseline: `baseline write`, `baseline shrink`; `check`, `lint`, `arch` and `strict` fail only on new violations or growing counts; a file joins the strict profile once clean                  | done: a project with old violations passes `lint`, `arch` and `check`; one new violation fails; `shrink` never raises a count; on real Godot an untyped file is baselined under `check --strict`, leaves the baseline once typed and fails when it regresses                                                                          |
| A6  | `gate` + receipts (`receipt write`, `receipt verify`); receipts carry reach metrics against the base commit; duration-balanced shards; post-merge rebuild of generated files                   | done: a fixture gate writes a receipt and an edit makes `receipt verify` report `stale`, on real Godot; a new cross-layer preload raises reach max by 2 against HEAD; on AloneGodot the gate runs every step in 98 s and reports real import churn and 15 entries lacking an allow-list                                               |
| A7  | Hooks: PostToolUse Tier 0 on .gd/.tscn/.tres, 280-line warning, SKIP guard, commit-needs-receipt, single-writer guard (`project.godot`, main scene, theme → request file)                      | done: 12 hook tests (one live, language server); `post-edit` 0.14 to 0.19 s per edit on AloneGodot; a lane edit of `project.godot` is refused with a `.mozg/requests/` path, tested in a real linked worktree                                                                                                                         |
| A8  | Skills: godot-init, godot-verify, godot-test, godot-scene (+ evals)                                                                                                                            | done: `tools/lint_skills.py` clean; 12 routing evals pass 36 of 36 runs (3 per skill, near misses included); the godot-test harness template and the godot-scene format rules checked on 4.7.2                                                                                                                                        |
| A9  | `native` + `shot`: real renderer run, multi-resolution capture in one process, UI node/rect snapshot JSON                                                                                      | done: a fixture is captured at 3 sizes from one process (PNG sizes match, rects follow the anchors); the layout snapshot lists every visible control with canvas and window-pixel rects; AloneGodot's main scene captured at 4 sizes in 9.1 s                                                                                         |

### Phase T — test beds

Two tiny projects of plain text files (scenes, scripts, primitive meshes, no binary assets), each under 300 KB, used by `live_godot` tests from Phase A on.

| #   | Milestone                                                                                                                                     | verify                                                                                                                                                                                                                                                                 |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| T1  | `testbeds/arena3d`: CharacterBody3D player, one enemy, AnimationTree, Camera3D with collision, Jolt physics, seeded start                     | done: strict parse, boot (input live) and test gates pass; the bot wins seed 7 in 163 ticks twice alike and prints its summary line; a spring arm that ignores walls fails the camera entry; 18.8 KB of text (2026-11-14)                                              |
| T2  | `testbeds/rts`: about 500 units as MultiMesh, paths from NavigationServer3D queries (no node per unit), one resource, two bases, seeded match | done: strict parse, boot (input live), test and the full gate pass; seed 7 ends at tick 3009 with 500 units at peak, two runs give one state hash; a navmesh without the obstacle hole fails the detour check; 0.63 ms per tick headless, 16.1 KB of text (2026-11-14) |

### Phase B — godot-assets

| #   | Milestone                                                                                                                                                                         | verify                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| --- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| B1  | Contracts `asset`, `asset-version`, `item-event`; assetkit `new`, `version add`, `note`, `decide`, `status`, sqlite index                                                         | done: two worktrees add a version, a decision and notes to one asset and merge with no conflict; the fold is tested on all 42 (status, action) pairs, stale decisions and merged order; records are checked against the contracts by a stdlib checker that agrees with jsonschema (2026-11-14)                                                                                                                                                                 |
| B2  | `promote` (UID read after headless import), `doctor` (moved, missing, sha mismatch), `ship-report`, prune to blob store                                                           | done: a promoted file moved with its sidecar is found by UID, moved without it by sha256, an edited one flagged; an AI-generated shipped asset is listed, also through a human-edited child version; a real 4.7.2 import gives a promoted PNG its UID (2026-11-14)                                                                                                                                                                                             |
| B3  | `hub build` (2D images) + `hub serve` with security, live updates (SSE), one hub per project (`hub.json`, `hub stop`), URL in the session-start hook; decisions written as events | done: pytest refuses a wrong token, a foreign Host or Origin, `../` and symlinked paths, oversized and malformed bodies; a second `serve` reuses the running hub; in headless Chrome 155 approve and retake clicks write events, a new version reaches the open page over SSE without a reload and marks the old decision stale, and the static build opens read-only from disk (2026-11-14)                                                                   |
| B4  | Viewers: sprite frames, audio (waveform, seam, A/B), 3D (model-viewer, three.js inspect), video, UI multi-res, region notes                                                       | done except 3D: in headless Chrome 155 an image, a sprite sheet, sprite frame files, UI captures at two resolutions, a VP8 clip (seeks over HTTP Range) and two WAV versions (waveform, loop seam, A/B) render with no console error; a dragged box and a marked time become region notes. 3D deferred by the owner on 2026-11-14: three.js and model-viewer are ES modules, which a static build opened from disk cannot load; models show as a download link |
| B5  | Retake hook + `assetkit pending`; skills asset-registry, review-hub; importer for AloneGodot's art manifests (dry run)                                                            | done: a fixture retake reaches the session through the real hook launcher once per session; AloneGodot (55 manifests) imports in a scratch worktree, 530 versions of 318 assets, with a report of 193 unmapped fields; 6 routing evals pass 36 of 36 runs (2026-11-14)                                                                                                                                                                                         |

### Phase C — game-design

| #   | Milestone                                                                                                    | verify                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| --- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| C1  | Schemas + `designkit validate`, `designkit analyze`                                                          | done: a fixture of AloneGodot's radio route to E01 reports a planted loop that locks E07 (cycle, three unreachable nodes) and a dead end, with E01's critical path (57.5 h, 18 steps); all 296 nodes of `demos/progression-data.js` at 78b719d convert, validate and analyze in 0.4 s: all reachable, depth 44, 36 dead ends (devices whose benefit is no prerequisite; `leaf: true` silences them), 7 coverage gaps (2026-11-14)                                                                                                 |
| C2  | `simulate` (duration, economy, hazards) + `render` into the hub (graph, pacing, duration, coverage, economy) | done: seeded runs repeat byte for byte; on all 296 AloneGodot nodes at 78b719d, 15 terminals x 1,000 runs take 0.8 to 2.1 s, and one player needs 60.5 h to E01 against analyze's 57.5 h critical path; render draws graph, duration, pacing and coverage (economy when pools exist) in 0.8 s; registered as graph and chart assets, a hub click on a node writes a node=E01 note, which a retake brings to `assetkit pending`. Economy and hazards are checked on fixtures only: AloneGodot records no start stocks (2026-11-14) |
| C3  | `sync` drift check + skills gd-interview, gd-canon, gd-contracts/handoff, gd-review judge                    | done: `sync` on the AloneGodot oxygen fixture flags `oxygenPerDay` 12 against 2 and `survival.tres` 120 against 720; decision, canon and contract records with `designkit handoff`, which refuses a contract with an OPEN or missing field; skills gd-interview, gd-canon, gd-contracts and gd-review (fresh-reader sheet); evals 2026-11-14: 12 cases, with-arm 36/36, positives 0/3 without the plugin, near misses silent with the owner skill firing 3/3, $6.25, 323 s                                                        |
| C4  | gd-research skill (web research on reference games/mechanics, cited) + gd-balance skill                      | done: `designkit cite` checks that every Findings claim cites a numbered source with a URL and an access date; a sample report on oxygen and food pacing (two parallel web researchers) passes with 12 claims and 13 sources; gd-research and gd-balance skills; evals 2026-11-14: 6 cases, with-arm 18/18, positives 0/3 without the plugin, near misses silent with the owner skill firing 3/3, $5.24                                                                                                                           |
| C5  | Combat model (arena) and RTS model (build order, counter matrix); shared model interface extracted           | done: `"model"` in design.json picks campaign, combat or rts behind one `BalanceModel` interface; the arena bed's design (10 balance numbers, 20 bound copies, sync clean) predicts the bot's 90 health left exactly; the rts bed's (12 numbers, 24 copies) predicts 600 ore mined by tick 600 against 750 measured, inside a 25% tolerance set from that first run (seed 7, Godot 4.7.2, 2026-11-14); a cheaper equal unit is reported `dominant`, a rock-paper-scissors set is not; live tests in `tests/test_calibration.py`   |

### Phase L — godot-l10n

| #   | Milestone                                                                                                                            | verify                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| --- | ------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| L1  | Contracts `string`, `string-translation`; l10nkit `add`, `edit`, `remove`, `list`, `status` (stale computed); import of Godot CSV    | done: AloneGodot `i18n/game.csv` at 78b719d (256 keys, not 259) imports into `i18n/src/game.json` and exports back identical after sorting rows by key (owner's choice 2026-11-14: export is key-sorted) in 0.1 s; keys are unique across namespaces, files rewrite byte-identically, an edited source turns its translations stale, a stale cell exports empty                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| L2  | `build`: PO per locale (msgctxt, plurals, fuzzy when stale), optional 4.6+ CSV                                                       | done: live_godot on 4.7.2 (2026-11-14), from the built PO and from the 4.6+ CSV alike: `tr`, `tr` with context, `tr_n` in ru for 1, 2, 5 and 21, a backslash, a stale entry (PO fuzzy, CSV empty cell) and a missing one fall back to the en text; msgid is the key and msgid_plural repeats it; Plural-Forms from a 29-locale table with its source and date; `build --register` lists the PO in project.godot                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| L3  | `check`: keys, dynamic patterns, placeholder and BBCode parity, plural count, `max_chars`, hardcoded strings in `.gd` and `.tscn`    | done: a failing fixture per rule (placeholders, BBCode, plural count, max_chars, shape, undeclared placeholder, duplicate source, orphan, unknown key, undeclared dynamic, unused key, hardcoded in .gd and .tscn, release gate); AloneGodot at 78b719d (tracked code, 12 declared patterns): 0 errors, all 149 literal keys resolve, 8 warnings each confirmed by grep: 4 keys no file uses, 3 duplicate sources, 1 key built from a variable prefix that cannot be checked; test folders and `# NO_TRANSLATE` lines are skipped                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| L4  | Translation: `batch export` (masked, glossary, style, TM, context) and `batch apply` (restore, parity, provenance); QA judge; skills | done: a 5-string fixture batch (named and printf placeholders, BBCode, `%%`, a 3-form plural, a glossary) translated by a fresh agent following `l10n-translate` and applied with every token restored, `check` 0 errors; one length refusal was fixed and re-applied; a fresh `l10n-judge` caught a planted adjective-for-verb error as major, and its note came back in the next export; the hook refuses edits of `i18n/src`, `locales`, `build` and `events`; trigger evals 36/36, $3.08 (2026-11-14); the skills and judge await the owner's draft gate                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| L5  | In Godot: `max_px`, font coverage, pseudo-loc layout and override runs; per-locale screenshots and string review in the hub          | done: `l10nkit measure` finds a Russian label over its `max_px` and the missing CJK glyphs of the default font (live, Godot 4.7.2); `l10nkit pseudo` shows a scene in an accented en_XA locale 30% longer and finds a keyless label, a clipped tab, and a row off screen at 800x600 but not at 1280x720 (live); the hub lists translations with notes and the records' screenshots, and its approve writes an item-event that l10nkit reads as `reviewed` (live_browser; a repo test checks both kits agree on every state). `l10nkit shot` draws a scene in each locale on a display from the PO the store builds, saves one PNG per locale and size under `i18n/shots/` and indexes the keys each shows (`string-shots` contract); a Russian title renders at 640x360 on the desktop X11 display while a label with auto-translate off keeps its key and stays out of the index (live, Godot 4.7.2); a window the screen shrinks is reported `window_clamped` and its picture dropped; the hub shows each picture beside the KEY@locale rows it names, arriving over SSE without a reload (live_browser) (2026-11-14) |

### Phase X — Codex host

The same Claude-format plugins run in Codex: no `.codex-plugin/`, no renderer. Each fix is host-neutral, so Claude Code behaves as before. Probed on Codex CLI 0.169.0 (2026-11-14): the marketplace and 14 skills load; `bin/` is not on PATH; plugin hooks run once trusted in `/hooks`, with `CLAUDE_PLUGIN_ROOT` set; `apply_patch` reaches a hook as `{"command": "<patch>"}`; plugin agents are not loaded; the workspace-write sandbox runs headless Godot but blocks the X11 socket and hides localhost from the host.

| #   | Milestone                                                                                                                                                                     | verify                                                                                                                                                                                                           |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| X1  | Kit paths: each plugin's hard rules name `<plugin>/bin/<kit>` and a sibling plugin's kit                                                                                      | done: synced into all 14 skills by `lint_skills.py`; Codex ran `godot-verify`'s `godotkit doctor` by its absolute cache path, `ok` (2026-11-14)                                                                  |
| X2  | Edit hooks read Codex `apply_patch` (Add, Update, Delete, Move); matchers add `apply_patch`                                                                                   | done: unit tests on the captured payload shape; one `edits.py` per kit, kept identical by a repo test; a Codex patch of `i18n/src/game.json` is blocked by the hook and the file stays unchanged (2026-11-14)    |
| X3  | Sandbox causes named: `display_unreachable` from the log of a Godot run with no display server, `sandboxed_network` from `hub serve` under `CODEX_SANDBOX_NETWORK_DISABLED=1` | done: in the Codex workspace-write sandbox `godotkit shot` and `l10nkit shot` report `display_unreachable` and `hub serve` reports `sandboxed_network`; the skills say to rerun outside the sandbox (2026-11-14) |
| X4  | Agent and question fallbacks: the l10n judge as a fresh subagent from `agents/l10n-judge.md`, gd-review's reader, gd-research's web tools, godot-init's plain question        | done: Codex spawned a read-only subagent from the agent file, which found a planted adjective-for-verb error as major (2026-11-14)                                                                               |
| X5  | README install for Codex, `make test-codex`                                                                                                                                   | done: the live_codex test installs the marketplace into a throwaway Codex home; a skill runs `l10nkit status` and a trusted hook refuses a record patch, 24.6 s (2026-11-14)                                     |

### Phase M — migration of an existing project

Rehearsed 2026-11-14 on a throwaway local clone of AloneGodot `78b719d`; report and kit findings in `docs/migration-rehearsal.md`. Applying it to AloneGodot itself is a separate task for its owner.

| #   | Milestone                                                                                                                                             | verify                                                                                             |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| M1  | `godot-init` on an existing project: `godotkit.json`, `architecture.json` describing the current graph, `baseline write`, `doctor` report of blockers | done: gate passed on unchanged code in 102 s (54 entries, 14 native skipped, 118,064 checks)       |
| M2  | Hooks, gates and receipts on; only new code must be clean                                                                                             | done: an untyped function failed `check` and `strict` and its commit was refused; typed, it passed |
| M3  | Imports for real: asset manifests → registry, CSV → string store, design data → JSON                                                                  | done: 256 strings identical in content, sorted by key; hub lists 318 assets; design `sync` 23/23   |
| M4  | Clean-up lanes shrink the baseline one module at a time                                                                                               | done: two lanes took lint 499 → 485; lane gates and the merged gate (119 s) passed                 |
| M5  | Report and kit fixes                                                                                                                                  | done: K1, K2, K9 in `e6f1bc5`, K8 in `5843704`; K3, K5, K6, K7, K10 open                           |

### Phase P — gameplay probes

Each probe runs headless where possible, prints one summary line and is judged by `godotkit` like the other gates. Research: 23, 24, 25, 28, 34.

| #   | Milestone                                                                                                             | verify                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| --- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| P1  | Determinism: fixed-tick replay of recorded inputs gives the same state hash                                           | done: `godotkit replay`; arena (a 9-press walk, 600 frames, 0.27 s a run) and RTS (3,100 frames, 1.0 s) agree over 3 runs; an unseeded `randf()` fixture diverges at the first checkpoint; a moved press is a `mismatch` (2026-11-15)                                                                                                                                                                                                                                                      |
| P2  | Scale: units at N = 100, 500, 2,000 report frame time, draw calls, navigation time                                    | done: `godotkit perf` and gate step `perf`; the RTS receipt holds a table for 100 and 500 units (p95 frame 0.13 and 1.7 ms headless); a 1,000-box crowd of nodes breaks the node budget headless and the object budget natively, its MultiMesh twin passes (2026-11-15)                                                                                                                                                                                                                    |
| P3  | Feel: input-to-response frames, camera clipping, stuck detection                                                      | done: `godotkit feel` and gate step `feel`; the arena answers `move_forward` and `attack` on the frame they are pressed; a controller one frame late is reported for both, a spring arm that ignores walls clips 154 frames and is stuck 117 against the south wall (2026-11-15)                                                                                                                                                                                                           |
| P4  | `play` bridge: lockstep NDJSON over loopback TCP, catalogue groups, input with held frames, replay of `actions.jsonl` | done: `godotkit play start`, `step` and `end` with the injected bridge; the UI fixture holds `walk` 10 frames over two steps, a click on a Button at (600, 400) emits `pressed`, `build` runs through `playtest_do`, undeclared acts are rejected, and the session's `actions.jsonl` replays to its 4 hashes (2026-11-15)                                                                                                                                                                  |
| P5  | Scenario and finding schemas, oracles, stuck detector, claim checker, cost accounting; findings into the hub          | done: `godotkit playtest lint` and `judge`, hub section; a live 10-frame `walk` hold on the UI fixture breaks `Main.held <= 5` and is judged a `bug` its replay confirms; a second session with the same fingerprint (fake bridge) merges into one finding with 2 occurrences; a run without measured cost is `invalid` (2026-11-15)                                                                                                                                                       |
| P6  | Skills `godot-playtest` (llm_stepped) and `godot-bot` (scripted_bot); pilot on AloneGodot UI, arena and RTS test beds | done: the arena bot passes in 36 steps (216 frames, 8.1 s) and the RTS bot in 14 (1,680 frames, 2.9 s, winner 1 at tick 1617), both at no model cost; AloneGodot `first-day` played by headless Opus 5.5 ends `fail_unmet` in 6 steps (310 frames), since the clock starts only after a drag the bridge lacks: 14 agent turns over 382 s, 723,528 tokens in (673,215 cache reads), 5,754 out, $0.65, 4 claims with none contradicted, 3 `ux_hypothesis` findings; evals 18/18 (2026-11-15) |

### Phase D — godot-studio

Kit `studiokit` drives the lanes of the Development process section. godot-core already has `worktree new` and `remove`, the single-writer guard with its `.mozg/requests/` files, the gate and `receipt verify`. studiokit calls them through the `godotkit` CLI (`GODOTKIT`, then `PATH`) and never imports them. Research: `docs/research/07-orchestration-dx.md` §1.2, §1.3, §4.3.

- A lane record is `<git common dir>/mozg/lanes/<id>.json`: id, task pointer, base commit, worktree, branch `lane/<id>`, owned globs, forbidden scope, checks, risk, frozen hashes, status. Like git's own worktree metadata it is per clone, so it never merges and never changes the tree the gate hashes.
- Owned globs follow `architecture.json`: `*` also crosses folders. A new lane is refused when a tracked file matches the globs of an open lane, so parallel lanes are disjoint by construction.
- A merge runs `git merge --no-ff --no-commit`, the frozen-hash check and `godotkit gate` on the merged tree. It commits "Merge verified <id>" only when both pass and aborts the merge otherwise, so main never holds an unverified merge.

| #   | Milestone                                                                                                                                                                                             | verify                                                                                                                                                                                                                                                                                                                                                |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| D1  | Plugin and lane store: `studiokit lane new`, `list`, `show`, `brief` (the seven delegation fields), worktree through `godotkit worktree new`, overlap refusal                                         | done: `dfeb025`, `5444002`; on a scratch repo with a stub godotkit a lane gets a worktree on `lane/<id>` beside the repo, its record sits in `.git/mozg/lanes/` with the tree clean, a lane over a file an open lane owns (tracked, or named by both) is refused, and the brief carries the seven fields (2026-11-15)                                 |
| D2  | Ownership hook: `studiokit hook pre-edit` refuses a lane edit outside its globs                                                                                                                       | done: `5444002`; in a real linked worktree an owned edit and a request file pass, an edit outside is refused with the lane id and globs (exit 2), the main checkout, a worktree without a lane and a path outside any repository pass (2026-11-15)                                                                                                    |
| D3  | Frozen tests and `studiokit check`: `freeze` records sha256 of reviewed tests, the hook refuses their edits; `check` judges the diff against owned globs, frozen hashes and `godotkit receipt verify` | done: `2493d3a`, `6f00456`; `not_owned`, `frozen_changed`, `dirty`, `no_commits` and a stale receipt each fail `lane check` with one problem, a clean lane passes, and a lane rebased onto newer main is judged from the merge-base, not its old base (2026-11-15)                                                                                    |
| D4  | Merge queue: `studiokit merge` (check, merge without commit, frozen hashes, gate, commit or abort), worktree and branch removed, requests carried by the lane listed                                  | done: `37a32d2`; a passing lane lands as "Merge verified hud" with two parents and its request listed, worktree and branch gone; a failed gate on the merged tree, main changing a frozen test, a lane failing its check and a dirty main each leave main at its commit with a clean tree; a conflict names main's commit to rebase onto (2026-11-15) |
| D5  | Decision records: `studiokit decision new` and `lint` over `docs/decisions/NNN-<slug>.md` (options scored on the four questions, choice, revisit-when); `architecture-reviewer` agent                 | done: `b6d2c94`; a fresh record fails lint as `unscored` and `placeholder`, a scored accepted record passes, and a missing choice, trigger, score, column, status or section each give one problem; the agent file validates (2026-11-15)                                                                                                             |
| D6  | Skills `studio-lanes` (orchestrator: plan lanes, brief, background subagents, merge queue, review depth by risk) and `studio-decide`; evals                                                           | done: skill lint clean; evals 2026-11-15 (6 cases, 36 runs, $3.36): positives fired 3/3 with the plugin and 0/3 without, near misses stayed silent and the sibling fired 3/3. The first round scored 0: a `dependencies` entry in `plugin.json` silently kept both skills from loading under `--plugin-dir`, so the manifest names none               |
| D7  | Live two-lane rehearsal on a copy of the arena bed                                                                                                                                                    | done: live on Godot 4.7.2 (2026-11-15): two lanes on a committed copy of the arena bed, an out-of-scope edit and a frozen-test edit refused by the hook, each lane gated, checked and merged through the queue with the real gate on the merged tree; two "Merge verified" commits, no worktree left, 24 s in all                                     |

### Phase E — godot-art

Kit `artkit` keeps the art bible and the asset briefs, audits imports and GLB files, and turns a generated file into a registry version. Generation stays with fal-media's skills and `falkit`. artkit reads the ledger export they write and calls `assetkit` through its CLI, so no plugin imports another. Research: `docs/research/03-graphics.md`, `10-web-asset-pipelines.md`, `27-rendering-vfx-import.md`; digest of 2026-11-15 in the task notes.

- Stores: `art/bible.json` (master style, families with rendering mode, minimum subject size at 120 and 240 px and aspect ratios, identity roots with approval and a superseded list, palette legend as semantic hex, banned list) and `art/briefs/<id>.json` (family, hook, readability note, roots and refs by name, forbidden content, contrast plan, dependents, canon topic ids, the registry asset once one exists). `art/policy.json` maps folder globs to import rules and budgets.
- Shipped defaults carry research 27's numbers (compress modes, mipmaps +33 %, 4096 px for mobile and web, bits per pixel per format) marked UNTESTED with source and date. No poly budget has a tested source, so a project sets its own.
- 3D: Trellis is not in fal-media, so meshes come from Hunyuan 3D v3.1 pro with `face_count` (40,000 to 1,500,000; fal-media price table of 2026-11-10). A mesh call is made outside a plan, under the spend guard, and exported with `falkit ledger export --call`.
- Judges give a technical pass, never an approval; the owner decides in the hub.

| #   | Milestone                                                                                                                                                                                                                                                                    | verify                                                                                                                                                                                                                                                                                                                                                            |
| --- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| E1  | Plugin, bible and briefs: `artkit lint` (approved roots, palette hex, families, briefs' roots, refs, canon topics and dependents known, no dependents cycle) and `artkit dependents ID` (transitive fan-out)                                                                 | done: `artkit lint` and `artkit dependents`; 15 tests cover each finding, a root change reaching every brief downstream and a two-brief cycle                                                                                                                                                                                                                     |
| E2  | Import audit: `artkit audit` reads `.import` files and PNG, JPEG and WebP headers, applies the policy by folder and sums estimated VRAM against the budget                                                                                                                   | done: `artkit audit` reads PNG, JPEG and WebP headers and `.import` params, applies the first matching rule and the target's size limit, and sums VRAM against the budget; bits per pixel measured on 4.7.2 desktop on 2026-11-15 (VRAM 8 alpha, 4 opaque, 8 high quality; raw 32 and 24; mipmaps ×1.334), lossless and lossy counted as raw (UNTESTED); 30 tests |
| E3  | GLB audit: triangles, materials and embedded textures read from the GLB's JSON chunk, budgets by folder                                                                                                                                                                      | done: `artkit audit` also reads every `.glb` (triangles drawn per node, so instances count, strips and fans included; materials; images) and applies `max_triangles` and `max_materials` by folder; a cut file is reported as unreadable; 13 tests, and a GLB exported by Godot 4.7.2 (two boxes) read as 24 triangles and 2 materials                            |
| E4  | Registry ingest: `assetkit version add --param KEY=VALUE` (godot-assets); `artkit register BRIEF --ledger FILE --request-id ID` creates the asset on first use and adds a version with provider, endpoint, request id, prompt and charged dollars; a retake names its parent | with stub `assetkit`, a ledger entry becomes the exact `new` and `version add` calls; a second register on the same brief is a retake with `--parent`; a failed or unknown request is refused                                                                                                                                                                     |
| E5  | Readability pre-check and judge sheets: stdlib PNG decode, 120 and 240 px downscales, luminance contrast check; `artkit judge sheet` for the `art-readability-judge` and `art-style-judge` agents                                                                            | a grey-on-grey fixture fails the contrast check and a contrasted one passes; the style sheet lists the roots shown                                                                                                                                                                                                                                                |
| E6  | Skills `art-bible` (bible, roots for owner approval, briefs) and `art-batch` (brief → fal-media → register → audit → judges → hub); evals                                                                                                                                    | skill lint clean; evals pass with positives firing and near misses silent                                                                                                                                                                                                                                                                                         |
| E7  | Live: one 2K still (nano-banana 2.1) and one Hunyuan GLB at `face_count` 40,000 on a copy of the arena bed, registered, audited and imported headless                                                                                                                        | both versions in the registry with request id and cost, `artkit audit` reports them, the import log is clean; the spend is recorded                                                                                                                                                                                                                               |

### Phase F–G — outlines (detailed when reached)

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
1. Codex is a second host of the same Claude-format plugins, adapted by host-neutral skill text and hook input parsing rather than a renderer or a second manifest; Phase X runs before the migration (2026-11-14).
