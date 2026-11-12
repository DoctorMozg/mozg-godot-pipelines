# 05 - Testing / QA / Verification / Quality gates (AloneGodot, built with Codex)

Evidence sources: /home/drmozg/Work/Petproj/AloneGodot (tests/, .pre-commit-config.yaml, gdlintrc, project.godot,
.mz/reports, .mz/task/*), Codex rollouts under ~/.codex/sessions/2026/11/{08,11} (main g-alone thread
01a1baf7..., coder 01a1c72b...), digests role_g-alone*.md. One headless check was run: card_resources_test.gd
via run_checked_script.sh = 11700 checks, 0 failures, 8.2 s wall (read-only; XDG isolated by the runner).

## 1. Test architecture

### Framework: NOT GUT, NOT GdUnit4 - a hand-rolled SceneTree runner

- Research (.mz/research/2026_11_08_research_godot_architecture.md:200) recommended "pinned GUT 9.7.1"; the
  project never adopted it. Reality: ~148 `*_suite.gd` (RefCounted classes) + ~82 `*_test.gd` / entry scripts
  (`extends SceneTree`), 433 files incl. `.uid`, ~38.9k lines in tests/. No addons/ dir.
- Pattern: entry script `extends SceneTree`, `_initialize()` -> `_run.call_deferred()`, constructs suites with a
  shared `_check: Callable(bool, msg)`, counts `_checks/_failures`, prints a summary line
  `Card resources: 11700 checks, 0 failures.` and `quit(0 if failures == 0 else 1)`.
  Aggregators: `tests/smoke.gd` (startup + ~15 smoke suites, instantiates real scenes/main.tscn),
  `tests/card_resources_test.gd` (~45 resource/rule suites, 11.7k checks), plus per-domain `*_test.gd`.
- Suites receive a `host` node when they need frames (`SomeSuite.new(_check, self).run()` with `await`).
- Fixtures are shared files: `transmitter_model_fixture.gd` (`F.card_for(model, id)`), `activity_scene_fixture.gd`.
- Strictness comes from the engine, not the test lib: project.godot sets 8 GDScript warnings to `2` (error):
  untyped_declaration, unsafe_property/method_access, unsafe_cast, unsafe_call_argument, unused\_\*...
  So "Warning treated as error" parse failures are the first test layer (91 occurrences in the main rollout).

### Categories (by file-name prefix count in tests/)

| Category                                                          | Examples                                                                                                                                       | Runner                                                                            |
| ----------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Resource/rule validation (typed .tres, catalogs, recipes, styles) | card_definition_resource_suite, recipe_catalog_suite, \*\_style_suite, health_rules_suite                                                      | hook godot-resources (card_resources_test.gd)                                     |
| Startup/scene smoke (real main.tscn, real input)                  | smoke.gd, schedule/clock/health\_\*\_smoke_suite                                                                                               | hook godot-smoke                                                                  |
| Save/load regression (52 save\_\* + 38 transmitter\_\* files)     | save_document/ledger/session/file/layout/view_test, durable\_\*\_suite                                                                         | run_save_tests.sh (31 runners + 2 flag variants + root startup)                   |
| Sound (playback/session/scenario/controls)                        | sound\_\*\_test.gd                                                                                                                             | run_sound_tests.sh (`--max-fps 120 --quit-after 4800 -- --enable-headless-audio`) |
| Campaign configuration / hazard catalog                           | campaign_hazard_identity_test, ...\_leaf_test                                                                                                  | run_campaign_tests.sh                                                             |
| Review regressions                                                | review_fixes_test.gd                                                                                                                           | hook godot-review-fixes                                                           |
| Native/GPU (needs a window)                                       | table_calibration_test, card_pickup, table_parallax, workbench_shell_test, transmitter_scene_test (4 resolutions), card_print_window_gpu_suite | run_native_table_tests.sh - NOT a pre-commit hook                                 |
| Root-entry regression                                             | root_startup_entry.tscn + run_root_startup_test.sh                                                                                             | headless in save runner, native in native runner                                  |
| Simulation/campaign sim                                           | simulation_suite, execution_context\_*, timeline\_* (integer-time deterministic sim)                                                           | inside smoke/resources                                                            |
| Browser demos                                                     | demos/progression-navigation.test.js (JS, node), review/index.html                                                                             | ad hoc                                                                            |

No dedicated "balance simulation harness" or "save migration" tests exist: save compat policy was "reject
incompatible save with a clear message", later "clean save-format break allowed (no migration)" (user answers
H8 in coder thread, game thread line 675). Save tests are round-trip / validation / provenance, not
version-N-to-N+1 fixtures.

### Headless mechanics

- `godot --headless --path . --script res://tests/x.gd [-- flags]`; strict syntax pass:
  `--check-only --script x.gd` per file (hook godot-parse; run_save_tests.sh does both for each runner = TST-16 cost).
- Uniform success contract (tests/run_checked_script.sh): isolated XDG\_{DATA,CONFIG,CACHE}\_HOME in mktemp,
  `timeout ${GODOT_TEST_TIMEOUT:-600}`, and FAIL if any of: exit!=0, `SCRIPT ERROR:`, success regex missing
  (must be `[1-9][0-9]* checks, 0 failures` - non-zero check count prevents "0 checks" green), `ObjectDB instances were leaked at exit`, `resources still in use at exit`. This is the best asset in the repo: "exit 0" is not trusted.
- Known engine traps recorded by Codex research (rollout line 589): `--check-only -s` exits 1 on valid code naming an
  autoload; `--import` and `--quit-after` exit 0 on a parse error (so neither is a parse check); fresh clone has no
  `.godot/` class cache so first run needs `--import`; 4.7.x first `--import` crashed on exit (139) in 3/17 runs.

### Screenshots / visual checks

- There is NO screenshot-diff/golden-image regression. Visual verification was:
  1. Native run on the real GPU (RTX 4090, GL Compatibility) with `DISPLAY=:0`, `--display-driver x11`, `--audio-driver Dummy`,
     temp GDScript probes in /tmp (`asteroid-card-native-check.gd`, `asteroid-table-native-check.gd`) that read
     framebuffers (`get_image`) and assert pixel deltas / clipped fractions / luminance std
     (.mz/task/2026_11_08_build_table_pilot/native-verification.md: "artwork pixel delta 0.030358", "dynamic-light delta
     0.046461", per-map ablation deltas 0.0127/0.0153/0.129).
  1. `view_image` tool 273 times in the main thread (agent looks at PNGs it saved) + chrome-devtools screenshots (3) for
     HTML demos/art presentation page (art/progression/presentation.html).
  1. Matrix of window sizes (1280x720, 960x540, 1920x1080, 2560x1080, 1024x768) in run_native_table_tests.sh.
  1. Profiling: FPS/draw-call counters from `Performance` monitors; one 4392 ms cold first frame found and NOT claimed as fixed.
- GPU suite asserts on real production materials ("cover fixture uses a real production face material").

## 2. Pre-commit hooks (.pre-commit-config.yaml)

| Hook                                                  | What                                                 | Cost (measured/observed)              | Notes                                                                                                                                                                                                                                       |
| ----------------------------------------------------- | ---------------------------------------------------- | ------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| gdformat, gdlint (Scony/godot-gdscript-toolkit 4.5.0) | format + lint; gdlintrc only `max-file-lines: 300`   | ~1-3 s                                | 300-line cap enforced by the linter; 11 suites sit at 298-300 (TST-15)                                                                                                                                                                      |
| godot-import                                          | `--headless --import`, always_run                    | ~2-5 s                                | regenerates `.uid`, `i18n/game.en.translation`; pre-commit then sees modified files and FAILS the hook ("smoke hook may exit 1 when files change", MEMORY D-0002; "Translation regeneration caused the import hook to report file changes") |
| godot-parse                                           | per-.gd `--check-only --script` (serial)             | linear in changed .gd                 | the only real strict-type gate; known false-positive on autoload identifiers                                                                                                                                                                |
| godot-smoke                                           | tests/smoke.gd, regex `PASS: [1-9][0-9]* startup`    | seconds-tens of s                     | real main scene                                                                                                                                                                                                                             |
| godot-resources                                       | card_resources_test.gd (11.7k checks)                | 8 s measured here                     |                                                                                                                                                                                                                                             |
| godot-saves                                           | 31+ runners, each twice (check + run) + root startup | the heavy one (minutes)               |                                                                                                                                                                                                                                             |
| godot-sound                                           | 4 suites, `--quit-after 4800` frames                 | frame-bound, real-time timers (TST-9) | needs `--enable-headless-audio`                                                                                                                                                                                                             |
| godot-campaign                                        | 2 suites                                             | short                                 |                                                                                                                                                                                                                                             |
| godot-review-fixes                                    | review_fixes_test.gd                                 | short                                 |                                                                                                                                                                                                                                             |

Observed full-hook wall time from 221 non-SKIP `pre-commit run` commands in the main thread: median 16.7 s, max 333 s;
final "all nine hooks" runs 8.8-19 s early, 230-333 s late in the project (saves suite growth).

### Why SKIP=... was used 109+56+22+22 times in the main thread (87+ distinct pre-commit invocations) and 17 times in the coder thread

Verified by reading the commands: the SKIP lists are used when the changed files are **docs / task-state markdown**
(`.mz/task/.../state.md`, AGENTS.md, a single `tests/table_parallax.gd`) - pre-commit `--files` with always_run hooks
(`godot-import`, `smoke`, `resources`, `saves`, `sound`, `campaign` have `always_run: true, pass_filenames: false`) would run the whole
engine suite for a markdown edit. Example: `SKIP=godot-import,godot-parse,godot-smoke,godot-resources,godot-saves,godot-sound,godot-campaign pre-commit run --files .mz/task/2026_11_10_build_hazards/state.md`.
Root cause: hooks are `always_run` rather than path-filtered (`files:` / `types`), so the agent had to hand-skip them. Also
partial skip lists on style-only/test-only files (`SKIP=godot-import,godot-parse,godot-smoke pre-commit run --files tests/table_parallax.gd`).
This is a silent gate-weakening risk: SKIP is an env var the agent chooses; nothing records WHICH gates were skipped in the
commit/handoff except the agent's prose. Codex did mostly keep "all nine configured hooks required" for code batches
(tooling.md: "Gate: GODOT_BIN=<engine> pre-commit run --files <batch paths> ... all nine configured hooks required. No direct
formatter/linter invocation.").

### The isolation tricks

- `XDG_DATA_HOME/XDG_CONFIG_HOME/XDG_CACHE_HOME=/tmp/asteroid-*-test-data|/tmp/alone-<task>-xdg/...` (305+32+24+... uses):
  Godot's `user://` maps to `$XDG_DATA_HOME/godot/app_userdata/<project>` on Linux. Save tests write real save files; sound tests
  write cfg; without isolation (a) tests clobber/read the developer's own save, (b) parallel worktrees/agents race on the same
  files, (c) a previous run's leftovers make later runs pass/fail. TST-6 in the review report: "Fixed `user://` names ...
  smoke and resources are XDG-isolated; the save runner is not" (so isolation had to be retrofitted runner by runner); the
  sound-system task found "unsafe test user-data defaults" in integration review.
- `PRE_COMMIT_HOME=/tmp/asteroid-pre-commit` (72+49 uses): the Codex sandbox could not write ~/.cache, and a fresh cache tried to
  fetch the gdtoolkit repo without DNS ("New isolated cache tried fetching dependencies without DNS; reuse installed pinned tools",
  tooling.md). Fix was to copy an existing warmed cache. This is a sandbox artifact, but the lesson is real: pre-commit's remote
  hook repo needs offline-capable setup.
- `GODOT_BIN=/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64` prefix (507 uses): hooks call `${GODOT_BIN:-godot}`; binary is not
  on PATH and not version-pinned (CFG-13 open).
- `DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 --display-driver x11 --rendering-method gl_compatibility`
  (171 uses): native-window tests. Rollout evidence at line 616: default driver chose Wayland and died: `ERROR: Could not initialize the Wayland thread ... Unable to create DisplayServer, all display drivers failed` + `WARNING: 6 ObjectDB instances were leaked`;
  forcing x11 inside the Codex sandbox failed until run with `sandbox_permissions: require_escalated` ("Sandbox access to the display
  socket failed"). So native checks needed explicit user-approved escalation each time; they are therefore NOT in pre-commit.
- `/tmp/asteroid-godot-tracing` (GODOT_BIN wrapper, python execv): swaps `res://tests/smoke.gd` and `card_resources_test.gd` for a
  recorder script when `ASTEROID_TRACE_PHASE` is set, emitting a JSONL golden trace before/after a refactor ("asteroid-refactor-golden.gd").
  I.e. characterization testing for the resource refactor, built ad hoc, 100% in /tmp.
- `python3 /tmp/alone-save-check.py <phase> (--test res://x.gd | files...)` (112 uses): a throwaway driver (not in repo) that sets
  PRE_COMMIT_HOME/XDG/GODOT_BIN, runs either one headless test script or `pre-commit run --verbose --files ...`, writes
  `/tmp/alone-save-<phase>.log`, and prints `phase=<name> exit=<code> log=<path>`. Used for named RED/GREEN phases of the
  save-load build (e.g. `viewport-red`, `viewport-red-v2`: exit=1 with "Parse Error ... requires the subtype bool but supertype
  Variant ... (Warning treated as error)"). It exists because (a) 90 s command timeouts killed pre-commit runs
  (rollout idx 16879: `subprocess.TimeoutExpired ... timed out after 90 seconds`), (b) output was too long for the tool, (c) the agent
  wanted a log artifact per phase to cite later.
- `mktemp` fixture dirs + `trap rm -rf` inside runners; `timeout` wrappers; `kill`/`ps`/`pgrep` (60+31+36) = orphaned Godot
  processes after timeouts.

### Flakiness observed

- "A separate intermittent Medical Pod pickup test failure is being investigated" (2026_11_12_debug_root_startup.md).
- 4392 ms first-frame stall then stable 120 FPS (cold shader compile) - makes any time-boxed test sensitive.
- Sound tests use real-time `create_timer` waits (TST-9) and `--quit-after 4800`.
- First `--import` on a fresh `.godot` crashed (exit 139) 3/17 times on 4.7.1/4.7.2 (recorded by research, rollout 589).
- Orphan/leak warnings at exit are chronic (27 command outputs in main thread contained `ObjectDB instances were leaked`); the
  runner turned this into a hard failure (TST-1/TST-4).

## 3. What Codex struggled with (with evidence)

1. **Green tests that did not cover real startup (the biggest finding).** User: "When i start project myself: can't click/drag any
   card, framerate also looks pretty low." Root cause (.mz/reports/2026_11_12_debug_root_startup.md): SaveBootstrap added a node to the
   root Window during the initial main-scene `_ready` (busy parent); setup failed; Main disabled processing. "Deferred test fixtures
   added Main after root assembly and missed this path." 433 test files, all green, and the game was dead on F5. The fix added
   tests/root_startup_entry.tscn that launches the *actual* main scene and drives real viewport events; report: "Future startup
   regressions must exercise actual root entry, not only deferred fixture loading." Also "process exit 0 despite startup error"
   (startup_input_profile.md) - exit code lies, log scraping is required.
1. **Variant/type strictness as the main red-loop cost.** 91 outputs with "Warning treated as error": `_check()` requires `bool` but `Variant`
   was provided; `Casting "Variant" to "Node3D" is unsafe`; `Variable has no static type`; `Could not find type "SurvivalState" under base simulation.gd` (11 such class-cache/type outputs - nested class/const resolution and missing global class registration).
   Typical fix text from Copernicus review: "only 3 metadata equality expressions replaced with is_same(get_meta(...),expected), because
   Variant== inferred Variant not bool under strict warnings."
1. **Import cache / generated-file churn.** `godot-import` regenerates `.uid` and the compiled `i18n/game.en.translation`; pre-commit counts that as
   "files modified" and the hook fails on the first run; MEMORY D-0002 records the workaround (rerun). Review CFG-15: ~500 tracked `.import`
   sidecars now unused. Subagents were told "do not run import or formatters" (D9, D13, D15) because concurrent import in a shared tree clobbers
   `.godot/` and generated files - hence per-task isolated checkouts `/tmp/alone-<task>`, each needing its own `.godot` and PRE_COMMIT_HOME.
1. **Verification "receipts" were prose + hashes + log files, and expensive to keep honest.** Build workflow demanded RED proof before GREEN:
   "parent verified RED missing Board preload exit1"; "Final test SHA256 62fd2bf... matches both focused test reviews. Test writer alone
   corrected strict Variant comparison; coders did not alter tests"; `.mz/task/*/file-hashes.json`, `logs/initial-red.log`, `headless-green.log`,
   `native-green.log`, `pre-commit.log`; `sha256sum` was run 237 times. Good discipline, but entirely hand-assembled: every task re-invented
   tooling.md ("Engine/XDG/PRE_COMMIT_HOME/Gate/Focused runner/Native runner"). Review rounds were multi-agent ("Plan 1/test 2 correction rounds").
1. **Display-dependent runs need privilege and a human gate.** See Wayland failure above; native gates (`GPU 53 visible drawcalls, 196 actual input checks per window size`) are not reproducible in CI-like pre-commit, and a request to inspect OBS capture was rejected by approval review.
1. **Tests passing by reflection / weak assertions** (review report TST-8,11,12): ~34 sites use `.set("_model")` / `.call(&"_inspect_card")`, 46
   `has_method` probes, `cell.x >= 0`, `!= null` as sole assertion; 39 entry points copy a harness skeleton (TST-13); `smoke.gd:66,72,85,92`
   hardcodes group counts (TST-7); sound tests never `quit(0)` on success (TST-10); global state (locale, root.size) restored inline (TST-17).
1. **Gate honesty gaps found only in late audit:** TST-1 (High): smoke and resources hooks originally had NO `SCRIPT ERROR`/leak/summary check
   and no timeout - they could pass on a script that failed to load. Fixed by run_checked_script.sh only after the 2026-11-12 review.
   TST-2: save runner lacked timeout/summary match. TST-3: native tests unwired (opt-in only).
1. **Long-running commands vs agent tool limits:** 90 s timeouts killed pre-commit (rollout 16879); led to `/tmp/alone-save-check.py`, background
   `write_stdin` polling (2107 calls), `ps/kill/pgrep` cleanup.
1. **Test-suite growth hit the 300-line rule** (AGENTS.md): 148 `_suite.gd` files, smoke.gd had to be split into suites; 11 suites at 298-300 lines;
   `Only the test writer edits tests/smoke.gd` was a coordination rule because many agents touched the aggregator.
1. **Perf claims restrained, correctly:** "Warm profiling measured 120 FPS ... makes no performance-fix claim"; "no bottleneck conclusion from delayed samples".
   Good evidence-hygiene to copy into a skill.

## 4. Plugin proposals

Principle: encode what Codex did by hand per task (tooling.md, /tmp scripts, SKIP lists, hash receipts) into one deterministic
CLI (`godotkit`, in the style of falkit/ffkit already used by the user's other marketplaces) so skills call it instead of re-deriving
env vars. Judges (LLM) only for what scripts can't decide.

### 4.1 `godotkit` CLI (python3 stdlib, no deps; reads `godotkit.toml` / project.godot)

```
godotkit doctor                       # find godot bin (GODOT_BIN, pin in toml), version, display availability, pre-commit cache, .godot present
godotkit import [--if-stale]          # headless --import; sets XDG; detects crash 139 and retries once; reports generated files changed
godotkit parse [files...|--changed]   # strict per-file --check-only; maps "Warning treated as error" to file:line JSON; autoload false-positive workaround
godotkit test list                    # discover entry scripts (extends SceneTree + quit(...)), suites, and which runner owns them
godotkit test run <res://x.gd|--changed|--all|--tag native> [--jobs N] [--timeout S]
      # isolated XDG per run (mktemp), timeout, success-regex contract from run_checked_script.sh:
      #   fail on exit!=0 | SCRIPT ERROR | Parse Error | leaked ObjectDB | resources still in use | missing "[1-9]\d* checks, 0 failures"
godotkit test affected <files>        # map changed scripts/resources -> tests (grep preload()/res:// graph) for scoped runs
godotkit native run <script> [--sizes 1280x720,960x540] [--renderer gl_compatibility]
      # picks x11/Xvfb/Wayland, sets DISPLAY/XAUTHORITY/XDG_RUNTIME_DIR; falls back to `xvfb-run` + llvmpipe; exit code 3 = "no display" (never a silent pass)
godotkit shot <scene|script> --out dir --size WxH --frames N   # deterministic viewport capture (movie-maker or get_image), emits PNG + json manifest
godotkit shot diff <baseline-dir> <new-dir> [--tol 0.01]       # per-image RMSE/SSIM, ROI masks, writes diff PNG; agent then view_image's only failures
godotkit gate [--files ...] [--profile quick|full]              # = pre-commit run with PRE_COMMIT_HOME + GODOT_BIN set; records a receipt
godotkit receipt write|verify         # JSON receipt (below)
godotkit lint-size [--max 300]        # same cap as gdlintrc, plus test-file near-cap report
godotkit saves check <fixtures-dir>   # load every versioned fixture save with current build; assert accept/reject per manifest
godotkit sim run <scenario.tres|json> --seeds 1..200 --out csv  # headless balance sim; summary stats
godotkit worktree new <task>          # git worktree under /tmp/<proj>-<task> + isolated XDG + warmed .godot cache copy + PRE_COMMIT_HOME copy
```

### 4.2 Skills (SKILL.md each, thin; they call godotkit)

1. `godot-test-runner` - headless harness conventions: SceneTree entry skeleton, `_check` callable, summary line, `quit(0/1)`, isolation, success
   contract. Ships `templates/harness.gd` (fixes TST-13: shared base with `check()`, `finish()`, `quit` codes) and `run_checked_script.sh` equivalent
   (as `godotkit test run`). Evidence: TST-1/2/10/13; every project re-implemented this.
1. `godot-scene-smoke` - generate a smoke test for a scene: instantiate under real `root` at the same lifecycle point as `application/run/main_scene`
   (NOT call_deferred), wait N frames, assert no `push_error`/SCRIPT ERROR, check `process_mode`, drive a real `InputEventMouseButton` through
   `Viewport.push_input`, assert readiness flags. Evidence: the F5-dead-input bug missed by 433 tests. Includes a `root_startup_entry.tscn` template.
1. `godot-resource-validation` - for `.tres` typed Resources: generate a suite that loads every resource in a folder with `CACHE_MODE_IGNORE`, checks
   script class, required fields, ranges, cross-references (card -> art -> i18n key), unique ids, and "defaults not mutated" (existing strength in
   repo). Plus i18n CSV audit (all keys referenced, no orphan keys: seen as "47 keys referenced; no missing or orphan keys").
1. `godot-save-compat` - fixtures per schema version under tests/fixtures/saves/vN.json + manifest of expected outcome (accepted / rejected with
   message), round-trip determinism, partial write / corrupt file / atomic-commit tests (SAV-2/10 items), XDG isolation mandatory. Evidence: no
   version-fixture tests existed; policy decisions (reject vs migrate) came as late user questions - skill should ask that question up front.
1. `godot-balance-sim` - deterministic headless sim harness (integer time, seeded RNG), scenario resources, CSV out, regression thresholds (e.g. median
   days survived, resource starvation rate). Evidence: campaign-balance-v1.md / pacing docs existed as prose with no sim runner.
1. `godot-visual-check` - native render procedure: godotkit native/shot, standard window-size matrix, pixel-delta assertions for shader/lighting
   changes, "ablation" method (disable a map and prove pixels change), PNG review protocol with `view_image` only on failing diffs; baseline update requires
   explicit approval. Evidence: native-verification.md methodology, 273 view_image calls done ad hoc.
1. `godot-quality-gate` - how to run gdformat/gdlint/gdparse via pre-commit only (matches user's pre-commit rule), strict-typing cookbook (Variant
   comparisons -> `is_same`, typed arrays, `as` casts, class_name vs preload const resolution), 300-line rule, path-filtered hooks. Ships a
   `.pre-commit-config.yaml` template with `files:` filters (below) so SKIP is never needed.
1. `godot-verify-before-done` - the receipt protocol (4.4): RED proof -> GREEN -> gate, forbids SKIP for code changes, requires listing skipped gates in the
   final message. Evidence: SKIP use, TST-1.
1. `godot-startup-profile` - how to profile cold vs warm FPS, Performance monitors, don't claim bottleneck from delayed samples. Evidence: profile report.

### 4.3 Hooks (plugin hooks.json; scripts call godotkit and must be fast)

- PostToolUse on Edit|Write of `*.gd`: run `godotkit parse <file>` (single `--check-only`, ~1 s) and feed back "Warning treated as error" lines
  immediately. Rationale: strict-warning parse errors were the dominant RED cause (91 outputs) and each one cost a full test-run round trip. Needs the
  autoload false-positive workaround (parse via `-s` with project loaded, not bare `--check-only`).
- PostToolUse on `*.gd` also: line-count warning if > 280 (300-cap) - cheap, avoids late splits (TST-15, AGENTS.md).
- PostToolUse on Edit|Write of `*.tres|*.tscn|*.csv|project.godot`: mark `.godot` stale flag; next `godotkit test run` triggers `--import --if-stale`.
- PreToolUse on Bash matching `SKIP=`/`--no-verify`/`pre-commit run` with SKIP containing godot-\*: warn unless diff touches only docs; log skipped gates
  to `.godotkit/receipts/` (do not block docs-only).
- PreToolUse on Bash `git commit`: require a receipt newer than the newest changed source file (see 4.4), else block with the exact command to produce one.
- PreToolUse on Edit of files listed in `reviewed-tests.lock` (sha256): block editing hash-locked reviewed tests unless the agent is the test-writer role
  (mirrors "coders never touch reviewed tests"; evidence: smoke.gd rule + 237 sha256sum calls).
- SessionStart: `godotkit doctor` summary (binary version vs pin, `.godot` present, display available?), 1-2 lines.
- Stop hook (optional, prompt-type): if .gd/.tres changed this turn and no receipt, ask for gate run.

### 4.4 Receipt format (replaces hand-written tooling.md + sha256 lists)

`.godotkit/receipts/<ts>-<kind>.json`:

```json
{"kind":"gate","godot":"4.7.2.stable","head":"<git sha>","tree_hash":"<hash of changed files>",
 "env":{"xdg":"isolated","display":"headless|x11"},
 "steps":[{"name":"godot-parse","status":"pass","files":12},{"name":"godot-saves","status":"skipped","reason":"docs-only"}],
 "tests":[{"script":"res://tests/card_resources_test.gd","checks":11700,"failures":0,"leaks":0,"secs":8.2}],
 "red_proof":{"script":"res://tests/x_test.gd","exit":1,"log":"logs/red.log","sha256":"..."},
 "skipped_gates":["godot-saves"],"log":"..."}
```

`godotkit receipt verify` fails if tree_hash != current tree, any non-docs gate skipped, or checks==0. The commit hook and the final-report skill
both read it, so "done" claims are mechanical. Evidence: every Codex task handwrote logs/\*.log + hashes; plan said "RED proof verified by parent".

### 4.5 Pre-commit template improvements (ship in godot-quality-gate)

- Path-filter instead of always_run: `godot-parse: types:[gdscript]`; `godot-resources: files: ^(resources/|scripts/|tests/)`; `godot-saves: files: ^(scripts/save|tests/save|...)`;
  `docs`-only commits then run nothing heavy and SKIP disappears.
- `stages`: quick hooks (gdformat, gdlint, parse) at pre-commit; full suites at `pre-push` or `manual` (`pre-commit run --hook-stage manual`).
- `godot-import` as `pass_filenames:false` but `verbose` and idempotent; add a second run to avoid the "files modified" false failure, or exclude
  `i18n/*.translation` from the modified check.
- One generic hook entry `godotkit test run --all` with a manifest of runners instead of 8 bespoke shell scripts (each re-implementing mktemp/XDG/timeout/regex).
- Pin Godot version: `godotkit.toml` `godot = "4.7.2"` verified by `doctor` (CFG-13).

### 4.6 Judges (LLM, pipeline-only, small, read-only - style of fal-media:physical-judge)

- `godot-test-honesty-judge`: reads a diff of tests + `godotkit test list` output; flags reflection into privates, `has_method` probes, existence-only
  assertions, hardcoded counts, deferred-fixture-only coverage of lifecycle code, tests that cannot go RED (no RED receipt). Evidence: TST-7/8/11/12 +
  startup bug. Existing agent `tests-honesty-reviewer` is generic; this one is Godot-aware and receipt-aware.
- `godot-visual-judge`: given baseline/new PNG pair + diff stats + the art-direction excerpt (AGENTS.md rules like "photorealistic dark", readability at
  120-240 px), answers a numbered sheet with JSON (same pattern as physical-judge). Only invoked when `shot diff` exceeds tolerance.
- `godot-startup-coverage-judge`: checks that every autoload/root-added service and `_ready`-time `add_child` to root has a root-entry test.
- `godot-gate-auditor`: before commit, reads receipt + SKIP usage and returns PASS/FAIL JSON with reasons (blocks "docs-only" SKIPs on code diffs).

### 4.7 Agents / orchestration notes

- `godot-test-writer` (only agent allowed to edit reviewed tests/lock), `godot-implementer` (cannot edit locked tests), mirrors the observed
  Codex roles and the MEMORY D-0001 order: plan -> reviewed tests -> verified RED -> GREEN -> production review -> final review -> completeness.
- Subagents running in a shared tree must not run `--import`; `godotkit worktree new` gives each its own `.godot` cache (evidence: D9/D13/D15 prompts).
- Phase size cap (5 authored files) as a configurable gate in `godotkit gate` (warn when changed authored files > N).

### 4.8 Priority order

1. `godotkit test run` + success contract + isolation + `doctor` (removes most of the 507 GODOT_BIN / 305 XDG shell boilerplate).
1. `godotkit parse` + PostToolUse hook (fastest feedback loop for the dominant failure class).
1. Receipts + commit hook + gate auditor (fixes "evidence" problem, SKIP drift).
1. scene-smoke/root-entry template (the most expensive bug that slipped through).
1. native/shot/diff + visual judge (replace ad hoc DISPLAY=:0 probes; needs Xvfb fallback so it is not blocked by sandbox display escalation).
1. save-compat fixtures, resource validation generator, balance sim.

## 5. Pre-existing issues noticed (surface only, not fixed)

- TST-3/5/6(partly)/7/8/9/10/11/12/13/14/15/16/17 still Open per .mz/reports/2026_11_12_godot_code_review.md; native tests not in any hook.
- `.mz/memory/*` shows modified in `git status` of AloneGodot (not caused by this read-only investigation).
- Hooks `always_run` forced the SKIP habit; `gdlintrc` only sets max-file-lines; Godot binary unpinned.
- 148 suites + 82 entry scripts with a duplicated skeleton: a `harness.gd` base would delete a lot of copy-paste (but Rule of Three says it is already justified: 39 copies).
