# 07 - Orchestration and development experience (AloneGodot, built with Codex)

Scope: cross-cutting lessons for a Claude Code Godot plugin marketplace. Read-only analysis.
Sources: Codex digests (`scratchpad/codex/role_*.md`, `threads.json`, `tool_usage.json`), the
project (`AGENTS.md`, `CLAUDE.md`, `.mz/`, `tests/`, `.pre-commit-config.yaml`, git history),
`~/.codex/config.toml`, `~/.codex/hooks.json`, and targeted greps of the main rollout
(`rollout-2026-11-08T15-42-43-01a1baf7-c9ee...jsonl`, 325 MB). Counts marked "~" are my
estimates from greps; unmarked counts come straight from the digests or git.

______________________________________________________________________

## 0. The project in numbers

| Metric                            | Value                                                                                                             | Source            |
| --------------------------------- | ----------------------------------------------------------------------------------------------------------------- | ----------------- |
| Wall clock                        | 2026-11-08 to 2026-11-12 (~4.5 days)                                                                              | git log           |
| Commits                           | 389 on main (10 / 55 / 130 / 104 / 90 per day); 27 merge commits                                                  | git log           |
| Threads                           | 536 total: 6 long-lived roles, 338 spawned subagents, 187 Guardian reviews, 4 misc                                | threads.json      |
| Rollout size                      | ~10 GB (the 9 GB the brief mentions)                                                                              | threads.json      |
| Human prompts to the orchestrator | 195 (100 are answers to structured questions, 26 are bare "Proceed/Approve", 8 are "What's next?")                | role_g-alone.md   |
| Orchestrator tool volume          | 4,607 `exec` batches, 1,045 `followup_task`, 741 `send_message`, 149 `spawn_agent`, 198 `wait_agent`, 137 `sleep` | threads.json      |
| Inner calls of g-alone            | 22,713 `exec_command`, 1,018 `apply_patch`, 372 `send_message_to_thread`, 168 `read_thread`                       | role_g-alone.md   |
| Godot code                        | 262 scripts + 344 test files (433 entries in `tests/`), 56.5k lines, 25 `.tres` config resources                  | repo              |
| Task records                      | 38 dirs under `.mz/task/` (48 MB), 22 lessons, ~45 inbox lessons                                                  | repo              |
| Branches / worktrees              | 41 `codex/*` branches, ~36 worktrees left in `/tmp/alone-*` (4 already prunable)                                  | git worktree list |

The human wrote almost no code and almost no corrections. The user's main contribution was
design answers (100 of 195 prompts) and one-word approvals. Everything below is therefore
about how a single orchestrator turned that input into 389 commits without a human in the loop.

______________________________________________________________________

## 1. How work was orchestrated

### 1.1 Topology

```
                         human (designer / approver)
                                   |
                           g-alone  (orchestrator, 1 thread, 150 subagents)
        +---------------+----------+-----------+----------------+
        |               |          |           |                |
  g-alone-graph    g-alon-gd   g-alone-ui   g-alone-sd     g-alone-coder
  art / fal.ai     game design  UI/UX        sound          parallel coding
  (141 subagents:  (11 subag.)  (18 subag.)  (10 subag.)    (13 subag.)
   106 "judge_*")
        |
   each role owns: its own docs, art/, review pages, and its briefs
   each role spawns its own judges / reviewers / researchers
```

Two layers of delegation existed:

1. **Long-lived role threads** (6). They hold domain memory, talk to each other with
   `send_message_to_thread` / `read_thread`, and the human could open any of them. The roster
   lives in `AGENTS.md` as `thread://` links, and `CLAUDE.md` says "all agents form one team led
   by g-alone". The roster was written into AGENTS.md at the user's request on day 4 (H181),
   not designed up front.
1. **Disposable subagents** (338) with job-shaped names. From the `agent_path` values the
   recurring pipeline stages are: `*_research`, `*_plan_review`, `*_test_writer`,
   `*_test_review`, `*_test_coverage`, `*_test_craft`, `*_model_coder`, `*_ui_coder`,
   `*_native_probe` / `*_gpu_verify`, `*_production_review`, `*_final_review`, `*_simplicity`,
   `*_completeness`, plus 106 art `judge_*` agents. This is exactly the mz-dev-pipe `/build`
   pipeline (research, plan, plan-review, tests, test-review, RED, implement, code-review,
   final-review, optimize, completeness) ported to Codex. The task directories prove it:
   `.mz/task/<date>_build_<x>/{research,plan,plan_review,tests,test_review,red_run, implementation,code_review,verification,final_review,optimization,completeness_check, summary,state}.md`.

### 1.2 Delegation message shape (what worked)

Typical `send_message_to_thread` to g-alone-coder (105 of them), 2026-11-11:

> Highest priority ready: P07 lane caller migration, base main cf059a3. Read
> .mz/task/.../plan.md P07 ... **Own only** scripts/transmitter_status_hint.gd and
> tests/{assigned_capture_suite,...}.gd. **In a separate worktree/branch**, replace direct
> running/machine_running reads with running_in(...) ... **Preserve every existing assertion**
> ... no gameplay, schema, UI or other caller edits. **You are not alone; preserve concurrent
> work.** Run pre-commit for those 5 files with Godot at <path> and temp XDG data/config/cache.
> **Report branch/path, scoped commit and checks. I own review/merge; do not push.**

Every delegation carried the same seven fields. This is the template to encode:

| Field                | Example                                                      | Why it mattered                               |
| -------------------- | ------------------------------------------------------------ | --------------------------------------------- |
| Base commit          | `base main cf059a3`                                          | worktrees drift; reviewer can diff exact base |
| Source of truth      | "read plan.md P07"                                           | no re-explaining, plan lives on disk          |
| File ownership       | "Own only X and tests Y"                                     | 5-file batch cap, no merge conflicts          |
| Forbidden scope      | "no gameplay, schema, UI edits"                              | stops coders from improvising design          |
| Isolation            | separate worktree + branch                                   | main stays clean for the orchestrator         |
| Verification command | `pre-commit run --files ...` with `GODOT_BIN`, temp XDG dirs | same gate for coder and reviewer              |
| Return contract      | "branch/path, scoped commit, checks; do not push"            | orchestrator owns merge and push              |

### 1.3 Gates and "receipts"

Receipts were the strongest idea in the setup:

- **Frozen tests by hash.** Test writer alone edits tests. After two independent test reviews the
  suite's `sha256` is recorded (237 `sha256sum` calls in the orchestrator) and "coders never touch
  reviewed tests". After merge the parent compares hashes ("merged source/test hashes match
  reviewed worktree"). Example from state.md: "immutable suite 1a641b4 ... lines 204 / hash f594...".
- **Verified RED before GREEN.** `red_run.md` per task (7 files) captures the failing run.
- **Pre-commit as the single gate.** Nine hooks (gdformat, gdlint, `godot-import`, `godot-parse`
  with `--check-only`, smoke, resources, saves, sound, campaign, review-fixes) all exit 0, logged
  to `/tmp/alone-*-checks.log`; the last commits are literally "Preserve complete verification
  log receipts" and "Archive executed analysis as text receipts".
- **Counted assertions, not "passed".** Success regexes require `[1-9][0-9]* checks, 0 failures`
  (`tests/run_checked_script.sh`), so a runner that executes zero tests cannot pass.
- **Native probes with real input.** 196 pointer/keyboard checks per window size
  (1280x720, 960x540), GPU draw-call counts, framebuffer pixels.
- **Per-task `verification.md` + `state.md`** with `last_verified:`, `what_remains:`,
  `current_wave`, per-coder `DONE` flags; mirrored into `.mz/memory` activity log.
- **Orchestrator re-verification.** After every merge g-alone re-ran the gate itself and
  "compared 14 baseline pure functions byte-for-byte with HEAD".

Review iteration stats recorded by memory (examples): "plan 1 PASS; initial test review 1
correction then PASS; production 0 corrections; final 1 finding corrected; completeness PASS".
Across tasks, 2 of 2 plan reviews and 2 of 3 test reviews contained a FAIL before PASS, i.e.
the review stages caught real problems about once per task, and most were test-quality issues
(vacuous null checks, wrong Variant typing), not production bugs.

### 1.4 What worked

1. **Five-file batch cap** (AGENTS.md: "at most five authored source, test or configuration
   files"). Kept reviews small and merges mechanical. 27 merge commits are named
   "Merge verified X".
1. **Tests-first with a hash lock.** Prevented the classic agent failure of editing the test to
   pass. Matches the user's own Test Integrity rule.
1. **Explicit file ownership + "you are not alone"** (the phrase appears in nearly every
   delegation). Concurrent agents on one tree rarely clobbered each other; the few conflicts
   were about uncommitted `project.godot` and `AGENTS.md` edits from other threads.
1. **Plan lives on disk, messages are pointers.** Delegations reference `plan.md P07`.
1. **Specialist judges for subjective output** (106 art judges, `tabletop_physical_judge`,
   `final_browser_qa`) with an HTML review page the human looks at (`art/progression/ presentation.html`, plus a validation mode with approve/redo and a copy button, H47).
1. **Structured questions to the human.** 52 `request_user_input_async` calls; 100 of the 195
   human prompts are one-click answers. The user answered fast and the orchestrator never had to
   guess design.
1. **Standing authorizations.** "Anything that is scheduled is approved", "incoming briefs are
   rendered through fal.ai immediately", "fix instructions not to require approve between
   phases" (H144). These removed ~30 approval round-trips later in the run.

### 1.5 What wasted time (with evidence)

| Waste                                          | Evidence                                                                                                                                                                                                                                                                                                                                                                                    | Cost estimate                                                                                     |
| ---------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| **Push + ls-remote ritual after every commit** | 155 `git push` calls, 159 `git ls-remote`, 216 push commands in the digest; 16 pushes in the single hour 2026-11-10T01; 8 in 00:00. Only ~18 pushes ever failed. The push was a standing authorization (H14: "persist all changes here"), so the verification `ls-remote` after each was pure ceremony.                                                                                     | ~315 shell round-trips, each also hitting the Guardian                                            |
| **Guardian review per escalation**             | 187 Guardian threads (35% of all threads). Main thread issued ~164 `sandbox_permissions` escalations. Categories: git push/remote 26, git write (commit/worktree/branch) 20, Godot import IPC socket 18, X11 display 14, pre-commit env fetch 9, fal network 7, other ("run the configured checks") 69.                                                                                     | 187 extra LLM sessions; Claude Code equivalent is a one-time allowlist                            |
| **Sandbox forced worktrees in /tmp**           | "Shared Git metadata is read-only. Use isolated checkout /tmp/asteroid-sound-system". `.git` of the main checkout was not writable from a managed worktree, so ~36 worktrees under `/tmp/alone-*`, none cleaned (4 prunable, 32 live + 41 branches). Each worktree needed its own `PRE_COMMIT_HOME=/tmp/...-precommit` (121 uses) and a cold Godot import.                                  | cold import + env fetch per worktree                                                              |
| **SKIP= whack-a-mole**                         | `SKIP=godot-import,godot-parse,godot-smoke,...` appears ~230 times (109 + 56 + 22 + 22 + ...). Coders ran partial hook subsets because full hooks mutate tracked files and take long; final integration then ran the full set. Lesson L-0009: "keep tracked files stable until the whole command exits ... mid-hook restoration makes a passing suite fail the working-tree mutation gate". | duplicated verification, flaky gate                                                               |
| **Polling**                                    | `sleep` 331, `wait_agent` 1,986, `wait` 478, `list_agents` 270 across all threads (137 / 198 in the orchestrator alone). The orchestrator babysat subagents in a poll loop instead of being notified on completion.                                                                                                                                                                         | tokens + wall time; Claude's background subagent notifications remove this                        |
| **Prose-heavy state writing**                  | The orchestrator rewrote `state.md` through inline `python - <<PY ... s.replace(...)` patches (visible in the sampled message), producing very long single-line activity logs with hashes. Memory file `MEMORY.md` activity lines are 400-900 chars.                                                                                                                                        | context bloat, hard to scan                                                                       |
| **Review-round stacking**                      | Per task: plan review, 2 test reviews (+ coverage + craft), RED, production review, final review, simplicity, completeness. The 3D-table task recorded "plan 1 / test 2 correction rounds; code/final 0" yet still ran every stage.                                                                                                                                                         | the pipeline was applied uniformly even to 3-line mechanical migrations (P07..P11 "lane callers") |
| **Human as router**                            | 8 "What's next?" / "What is left to implement?" prompts to the orchestrator; plus `xz`, `.`, `Дфкпук щту`, "Wait, wrong window" in other threads. With 6 threads the human mis-typed into the wrong thread.                                                                                                                                                                                 | orchestration state should be asked for, not remembered                                           |
| **Daemon restarts**                            | 2 `daemon_recovery` injected prompts ("server restarted and interrupted the previous turn"). Work resumed only because state was on disk in `.mz/task/*/state.md`.                                                                                                                                                                                                                          | evidence that disk state is mandatory, not optional                                               |
| **Hook failures from the toolchain itself**    | "Investigate Hook failures" thread: mozg hook bridge pinned to Codex 0.165.0 vs installed 0.167.0 (hooks silently skipped), and a Resolve shell guard rejected unrelated Python containing a backtick (also lesson I-0056: PreToolUse shell parsing rejected heredoc content). Fixed 9 hook declarations, 84,544 tests.                                                                     | one session of debugging infrastructure                                                           |

### 1.6 What the orchestrator should NOT have done by hand

- Hand-editing state files with Python replace scripts (should be a script/skill: `task-state set`).
- Re-computing hashes and comparing by eye (should be one command: `verify-frozen-tests`).
- Polling `list_agents`/`sleep` (should be notification-driven).
- Re-explaining ownership in prose (should be a manifest, see section 4.3).

______________________________________________________________________

## 2. Godot dev-loop specifics

### 2.1 How Godot was launched

One binary, always via env: `GODOT_BIN=/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64`
(also in `.claude/settings.local.json` `env`, and in `~/.codex/config.toml` for the Godot MCP).
Command frequency in the orchestrator: `GODOT_BIN=...` prefix 507, `XDG_DATA_HOME=/tmp/...` 305+,
bare binary 64, `DISPLAY=:0` 171, `PRE_COMMIT_HOME=` 72.

| Purpose                                 | Invocation                                                                                                                                                                                              |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Import / UID / translation regeneration | `$GODOT_BIN --headless --path . --import` (pre-commit hook `godot-import`, `always_run`)                                                                                                                |
| Syntax + strict type check              | `$GODOT_BIN --headless --path . --check-only --script <file>` per file (hook `godot-parse`); strictness comes from warnings-as-errors in `project.godot` ("There is no separate GDScript type-checker") |
| Behavior suites (headless)              | `tests/run_checked_script.sh res://tests/X.gd '<success regex>'`                                                                                                                                        |
| Save regression (18 invocations)        | `tests/run_save_tests.sh`, sequential, each preceded by `--check-only`                                                                                                                                  |
| Native (GPU, real input)                | `DISPLAY=:0 ... tests/run_native_table_tests.sh`, no `--headless`, GL Compatibility renderer, Dummy audio driver                                                                                        |
| Real project startup                    | `tests/run_root_startup_test.sh` (launches the actual main scene)                                                                                                                                       |

Facts the plugin must hard-code, learned the expensive way:

1. **Godot exits 0 after a `SCRIPT ERROR`.** Every runner therefore greps output for
   `SCRIPT ERROR`, `ObjectDB instances were leaked at exit`, `resources still in use at exit`,
   requires a success regex with a nonzero count, and wraps with `timeout` (default 600 s,
   `GODOT_TEST_TIMEOUT`). A plugin test runner must do this; a bare exit code is worthless.
1. **Isolated user data per run.** `XDG_DATA_HOME/XDG_CONFIG_HOME/XDG_CACHE_HOME` in a
   `mktemp -d`, otherwise tests read/write the developer's real saves. A later review found
   "unsafe test user-data defaults" in new audio code, so the rule had to be enforced in
   review as well.
1. **Headless is a dummy renderer.** Lesson L-0002: MultiMesh `get_instance_transform()` returns
   identity/zero headless; Compatibility quantizes colours to float16. Rule in docs: "Native
   tests must still verify the actual rendered result. Do not weaken expected spacing, shader or
   lighting values to accommodate a dummy backend." Native runners "reject a headless backend
   explicitly".
1. **Green headless suites did not prove the game worked.** The user's report in
   g-alone-coder (H3): "When I start project myself: can't click/drag any card, framerate also
   looks pretty low." Root cause (`.mz/reports/2026_11_12_debug_root_startup.md`): the main scene
   was assembled while the root Window was still preparing children, `SaveBootstrap.add_child`
   failed, `Main` disabled input before assigning its controller; test fixtures added Main
   *after* root assembly so they never hit the path. Fix: defer initial startup, and a regression
   `tests/root_startup_entry.tscn` that launches the real main scene and does a real
   press/drag/release. Quote: "Future startup regressions must exercise actual root entry, not
   only deferred fixture loading." This is the single most valuable DX lesson of the project.

### 2.2 `.godot` import cache

- `.godot/` is gitignored; `*.gd.uid` / `.tres.uid` / `.import` sidecars and the generated
  `i18n/game.en.translation` are committed ("Track print window test script UID" is its own
  commit). Every new script commit includes its `.gd.uid` (262 scripts).
- Every fresh worktree has no `.godot`, so the first command there must be `--headless --import`.
  With ~36 worktrees, that cold import repeated 36 times; it also needs the editor IPC socket,
  which is why "Godot import IPC socket" was a recurring sandbox escalation (18 of 164).
- The import step **mutates tracked files** (regenerates translation + UIDs). The pre-commit hook
  then reports "files were modified" (49 occurrences in the orchestrator) and the run must be
  repeated: "First import regenerated English translation/UID metadata; second run clean."
  Lesson L-0009 and memory D-0002: "the smoke hook may exit 1 when files change". Recommended
  behavior: run import once, stage generated files, then run the gate.
- "Clean import-only metadata afterward" is a manual chore in the log; a post-run hook should
  check `git status` for import-only churn.

### 2.3 Editor vs CLI

- The CLI path (headless + pre-commit) did 99% of verification. The Godot MCP
  (`@coding-solo/godot-mcp`) was configured in `config.toml` but used **twice in total**
  (`get_godot_version`, `get_debug_output`) out of ~28k exec batches. The editor was never
  driven. The only visual loop was native test windows on `DISPLAY=:0` plus Chrome DevTools
  for the HTML review pages (g-alon-gd and g-alone-ui: ~190 + 80 devtools calls on prototypes).
- Implication: a Godot MCP is nice-to-have, not core. What agents actually needed was a
  reliable **CLI facade** (import, check-only, run-suite-with-guards, native-run, screenshot),
  not an editor remote control.

### 2.4 Scenes and resources as text

- `.tscn`/`.tres` were edited with `apply_patch` (1,018 in the orchestrator) and Python
  heredocs, and new `.tres` configs were authored as text, always followed by import + a
  resource behavior test (`tests/card_resources_test.gd`, 'Card resources: N checks, 0 failures').
- Review rule found repeatedly: shared `Resource` instances are cached by Godot, so config
  resources must stay read-only and runtime state must live in separate objects (L-0011).
- `assert` is not evaluated in release builds, so validation of authored data must be an
  executable guard (L-0010). Validation of Godot types must check the real engine API, not lint
  (L-0013, e.g. `Color` has no `is_finite`).
- Strict-typing traps recorded as lessons: Variant narrowing (L-0001, 5 hits, most frequent),
  typed empty containers in ternaries (I-0031), enum Dictionary values for Tween enums.

### 2.5 The 300-line file limit

AGENTS.md: "Authored source and test files must not exceed 300 lines ... do not compress code or
remove useful verification to satisfy it." Enforced by `gdlintrc` `max-file-lines: 300`.

Effects (measured):

- 606 `.gd` files (262 scripts, 344 tests); max file is exactly 300 lines and several tests sit at
  exactly 300 (`simulation_suite.gd`, `simulation_concurrency_suite.gd`,
  `execution_context_integration_suite.gd`, `transmitter_state_suite.gd`), i.e. files are cut at
  the limit.
- Tests split into `*_suite.gd` composed by a parent suite via `preload` (see
  `simulation_suite.gd` importing 4 sub-suites). Good for review and parallel work, but it
  created hundreds of tiny files and many `DI-/EC-/CP-` style micro-tasks.
- Splitting interacts badly with lint: lesson L-0020 "short file can exceed complexity limits
  (public-method count)". The limit pushed agents to extract "facade" helpers that tripped
  other gdlint rules.
- It made the five-file batch cap workable (one concern per file), which is probably the real
  win. Cost: a refactor phase ("start with refactoring", H133) had to be run before features.
- A plugin should ship the limit as a configurable default (`max-file-lines`) with the
  split-by-responsibility guidance, not a hard 300.

### 2.6 Typed-resource configuration rule

AGENTS.md: "All configurable parameters belong in Godot resource files rather than hardcoded
GDScript values. Use typed resources for game rules and presentation tuning, keep mutable runtime
state separate, and retain player-facing text in CSV localization files."

Result: 25 `.tres` files (`board_geometry`, `card_visual`, `card_motion`, `table_camera`,
`survival`, `health`, `sound_settings`, `recipes`, ...) each backed by a typed `Resource` script,
`i18n/game.csv` for all text, and `docs/architecture-and-configuration.md` as the map. Costs:
validation code for every resource (lessons L-0010, L-0014, L-0015, I-0063: "format-valid
catalogs can fail later"), plus tests that assert rendered values change when the resource
changes (L-0015). It paid off in art/UX iteration (the user adjusted look without code edits),
but "tuning moved to resources" needed a mandatory pattern: typed resource + validator + behavior
test that mutates the resource. That triple is a template the plugin can scaffold.

### 2.7 Other Godot-specific gotchas worth encoding

- Camera refit must be skipped when bounds are unchanged or hover/pickup are erased (L-0004).
- Native pointer probes under stretch scaling must use `push_input` with viewport-local events
  (L-0016); OS-window coordinates hit the wrong control.
- Audio device unavailable on CI/sandbox: use the Dummy driver and say so in the receipt.
- `Variant` comparisons and nullable results must be asserted non-null before dereference, and
  the failure counted, or a runtime error may not fail the process (L-0003).
- Source order and `preload` cycles: tests use `const X = preload("res://...")` heavily.

______________________________________________________________________

## 3. Recurring user frustrations and corrections

The user rarely complained; corrections are concentrated and mostly about **art and UX intent**,
and about **agents not asking for the next thing**. Ranked by recurrence.

| #   | Theme                           | Evidence (quote / location)                                                                                                                                                                                                                                                                                                                                                                                                                                                                          | Count                                                                                    |
| --- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- |
| 1   | Art direction drift             | "No, should be more photorealistic and dark" (graph H4); "make a proper masculine guy" (H16); "psychology cards more abstract, research blueprint-like" (H17); "multitool is grey on grey background" (H18); "conditions use parts of the body" (H32); "bugged hands. Redo." (H37); "habitat too small ... should look like part of a crushed ship" (H42, H45); "No expiry should not be shown on the card" (H28); "painted version ... Arcane/Shyrdak redo" (H139); "Pilot is not a guy not a girl" | ~12; promoted into AGENTS.md as dated "corrected by the user on ..." bullets (7 of them) |
| 2   | "Always update the review page" | "don't forget to always update presentation.html" (H46), "After finishing all cards update ..." (H21)                                                                                                                                                                                                                                                                                                                                                                                                | 3 + lesson L-0008                                                                        |
| 3   | UX felt wrong in the real app   | "cards are being dragged to the top so you can't see" (H110); "z-fighting ... WASD movement not eased" (H75); "parallax should happen when camera moves, not hover" (H76); "cards should raise more ... face camera" (H77, H78); "Can't scroll right" (gd H38); "framerate low, can't click/drag" (coder H3); "scrollbar below the screen" (L-0017)                                                                                                                                                  | ~8; all found by the human launching the game, not by tests                              |
| 4   | No dummy/placeholder art left   | "no dummy drawings should be left - only rendered ones" (H57); "Continue with temporary image cards" was an explicit user-chosen exception                                                                                                                                                                                                                                                                                                                                                           | 2                                                                                        |
| 5   | Approval friction               | "Approve (fix instructions not to require approve between phases)" (H144); "Approve all phases" (H107); "Next time a brief comes: start subagent without approval" (graph H39); "anything scheduled is approved" (H41); "Approve all defaults"                                                                                                                                                                                                                                                       | 6; each ended as a standing rule in AGENTS.md                                            |
| 6   | Orchestrator not self-driving   | "What's next?" x8, "What is left to implement?", "Are there any pending questions?", "What's left?"                                                                                                                                                                                                                                                                                                                                                                                                  | ~11                                                                                      |
| 7   | Scope discipline                | "If something is not in the docs - don't yet implement it - consult g-alon-gd" (H188); "no need for forecasting, part 2 not needed yet" (H4); "Save this to ideas but let's not implement it yet" (gd H70)                                                                                                                                                                                                                                                                                           | 4                                                                                        |
| 8   | Complexity pushback             | "This a little bit convoluted. I feel more and more we should maybe remove card system - it's too hard to handle." (gd H73), leading to "magnetic slots" simplification                                                                                                                                                                                                                                                                                                                              | 1, but design-defining                                                                   |
| 9   | Wrong-thread / typo noise       | "Wait, wrong window. forget Arcane/Shyrdak comments." (H141); `xz`, `.`, "ignore 2 last messages" (graph H23-25)                                                                                                                                                                                                                                                                                                                                                                                     | ~5; consequence of 6 parallel threads                                                    |
| 10  | Don't invent                    | "Figure out initial balance quantities yourself" (the one time delegation was welcomed); "Come up with ..." prompts are invitations, everything else wants questions first                                                                                                                                                                                                                                                                                                                           | n/a                                                                                      |

Cross-cutting pattern: **the same correction had to be said once per thread.** The art rules
had to be told to g-alone-graph and again were relevant to g-alone-ui; the fix was copying them
into AGENTS.md (shared). mz-memory's `memory-note --lesson` produced the same effect later
(L-0007, L-0008, L-0005, L-0006 all came from `trig=correction`). A plugin should make "a user
correction becomes a shared rule" the default path.

Process rules the user imposed through AGENTS.md (indirectly describing past pain):
300-line cap, no hardcoded parameters, five-file batches, "Continue authorized refactoring
without asking between phases", fal.ai only, "Do not silently switch models", "never overwrite
accepted originals", "keep fal job receipts".

______________________________________________________________________

## 4. What a Claude Code Godot plugin marketplace should provide cross-cuttingly

### 4.1 Reuse map: what already exists in claude-mozg-pipelines

Evidence that this is not hypothetical: `~/.codex/config.toml` already lists mz-base, mz-memory,
mz-handoff, mz-dev-base, mz-dev-pipe, mz-dev-git, mz-research-pipe, mz-creative, and
`~/.codex/hooks.json` dispatches `mz-memory`, `mz-handoff`, `mz-knowledge` hooks
(`SessionStart`, `UserPromptSubmit`, `SessionEnd`). AloneGodot's `.mz/` tree is the output of
those plugins running under Codex.

| Need                                                                                                                           | Existing plugin                                                                                                               | Verdict                                                                                                                                        |
| ------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Cross-session memory, lessons, auto-injection after /clear and compaction                                                      | `mz-memory` (`.mz/memory/MEMORY.md`, `lessons.md`, journal, `memory-note --lesson`, `lessons-promote`)                        | **Reuse as dependency.** Do not rebuild. Add only Godot lesson *seeds* (L-0001, 0002, 0003, 0010, 0013, 0016 above are general Godot lessons). |
| Handoff after N compactions                                                                                                    | `mz-handoff` (`/mz-handoff:handoff`, Stop + SessionStart hooks, facts from transcript/git)                                    | **Reuse.** Needs one addition: handoff should also record active worktrees/branches.                                                           |
| Build / debug / audit / polish / optimize pipelines (research, plan, plan-review, tests, RED, implement, review, completeness) | `mz-dev-pipe` skills + `pipeline-*` agents                                                                                    | **Reuse as the engine.** The Godot plugin supplies *tooling profile* (commands) and Godot-specific reviewer lenses, not a second pipeline.     |
| Tooling detection                                                                                                              | `mz-dev-pipe:pipeline-tooling-detector`, `pipeline-test-runner`, `pipeline-lint-runner`                                       | Extend with a Godot profile (see 4.4). The test-runner must learn "exit 0 + SCRIPT ERROR = fail".                                              |
| Rules installer                                                                                                                | `mz-rules` `/init-rules` (detects languages, writes `.claude/rules/`)                                                         | Add a `gdscript` rule pack here instead of a new installer.                                                                                    |
| Branch / PR review                                                                                                             | `mz-dev-git:review-branch`, `branch-reviewer` + 6 lenses                                                                      | Reuse for coder worktree review; add a GDScript lens (Variant/typing, assert in release, shared Resource mutation).                            |
| Research / explain / document                                                                                                  | `mz-research-pipe`, `mz-creative:document`                                                                                    | Reuse.                                                                                                                                         |
| fal.ai media pipeline                                                                                                          | `fal-media` plugin (falkit, plans, spend guard, receipts), used heavily (338 falkit calls in graph, 242 in orchestrator)      | Out of scope for this cross-cutting report; reference it as a dependency of the art role.                                                      |
| Task state / approvals                                                                                                         | `mz-dev-pipe/shared/state-schema.md`, `approval-gate.md`, `resume-protocol.md`, `retry-policy.md`, `agent-status-protocol.md` | Reuse verbatim. The Codex run's `state.md` already follows `schema_version: 2`.                                                                |

What does NOT exist and is the real gap (the new plugin's value):

1. A **Godot tooling profile** (CLI facade with guards).
1. A **multi-role team skill** (graphics, design, UI, sound, code) with file ownership.
1. **Worktree-per-coder lifecycle** (create, bootstrap import, merge, cleanup).
1. **Project bootstrap** for Godot (AGENTS/CLAUDE templates, `gdlintrc`, pre-commit, runner scripts).
1. **Real-app smoke** (root startup, native probe) as a first-class gate.
1. **Cost/spend guard** beyond fal (token/agent-count budget for the orchestrator).

### 4.2 Project bootstrap (`/godot-init`)

Generate, with one approval gate (like `/init-rules`):

- `CLAUDE.md` (short) + `AGENTS.md`-equivalent rules: team roster, file-size cap (configurable,
  default 300), "parameters in typed Resources", "text in CSV", five-file batch, standing
  authorizations section left for the user, art-correction log section ("corrected by the user
  on <date>").
- `.claude/rules/gdscript.md` via mz-rules: strict typing/Variant rules, `assert` vs guard,
  shared Resource read-only, pointers to L-00xx seeds.
- `gdlintrc` (`max-file-lines`), `.pre-commit-config.yaml` with the nine-hook pattern
  (gdformat, gdlint, import, parse, smoke, resources, saves, ...), `tests/run_checked_script.sh`
  (guards, timeout, isolated XDG), `.gitignore` (`.godot/`, `.pre-commit-cache/`, `builds/`,
  `*.log`), `project.godot` warnings-as-errors block, `.claude/settings.json` env
  (`GODOT_BIN`), and a `docs/architecture-and-configuration.md` stub.
- A detector for Godot version (4.7.x here) and `GODOT_BIN` discovery with a clear error if
  missing (the repo currently trusts an absolute path in `/home/drmozg/Tools`).

### 4.3 Team / orchestrator skill (map the Codex roles to Claude subagents)

| Codex role                                                                | Claude Code equivalent                                                                                  | Notes                                                                                                      |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| g-alone (orchestrator thread)                                             | The main session running a `godot-team` skill. Not a subagent.                                          | Owns review, merge, push, state.                                                                           |
| g-alone-coder                                                             | `godot-coder` subagent, `isolation: worktree`, tools Read/Write/Edit/Bash/Glob/Grep                     | Returns branch + commit + check log; never pushes. Maps to `mz-dev-pipe:pipeline-coder`.                   |
| test writer + test reviewers                                              | `pipeline-test-writer`, `pipeline-test-reviewer` (reuse)                                                | Add the frozen-hash step.                                                                                  |
| \*\_production_review, \*\_final_review, \*\_simplicity, \*\_completeness | `pipeline-code-reviewer`, `pipeline-completeness-checker`, `mz-base:code-lens-over-engineering` (reuse) | Zero new agents.                                                                                           |
| g-alon-gd (game designer)                                                 | `godot-designer` subagent or a skill run in main context, **read-heavy, writes only docs/**             | Owns GDD, `docs/ideas`. User asked "consult GD for anything undocumented": implement as a gate, see below. |
| g-alone-ui                                                                | `godot-ui-designer` (prototypes in HTML + review page), then coder implements                           | 80% of its tool calls were Chrome DevTools prototypes.                                                     |
| g-alone-graph + 106 judges                                                | `fal-media` skills + `physical-judge` / `take-pick` style judges                                        | Reuse fal-media; add a "review page generator".                                                            |
| g-alone-sd                                                                | `godot-sound` skill                                                                                     | Low usage (8 prompts); maybe fold into a generic research skill.                                           |
| Guardian review (auto-approval)                                           | Claude Code permission rules + `PreToolUse` hooks                                                       | Not an agent; see 4.5.                                                                                     |

Mechanisms the skill must provide (all seen working in the Codex run):

1. **Ownership manifest** per task: `owner -> [globs]`, enforced by a `PreToolUse` hook on
   Edit/Write for subagents (deny writes outside the manifest). Replaces the prose "own only X".
1. **Delegation template** with the seven fields from section 1.2, generated from the plan.
1. **Worktree lifecycle**: create `../<proj>-wt/<task>` on `claude/<task>`, run `godot --import`
   once, share the `.godot` cache via copy (cheap, 36 cold imports were pure waste), merge with
   `--no-ff` "Merge verified <task>", then delete branch and worktree. The Codex run left 36
   worktrees behind.
1. **Frozen-test lock**: after test review, store `sha256` of the test files in `state.md`; a hook
   (or the merge step) fails if a coder diff touches them or hashes differ.
1. **Design gate**: before any coding task, check that the feature is in `docs/` (grep keys
   from plan); if not, stop and invoke the designer or ask the user (the "if not in the docs, don't
   implement" rule, H188).
1. **Batch cap**: plan-reviewer fails a plan with more than N authored files per batch (default 5).
1. **Completion notifications, not polling**: use background subagents and wait for their
   notification; never `sleep`/loop. (Codex run: 331 sleeps, 1,986 waits.)
1. **Parallelism policy**: parallel only if file ownership manifests are disjoint; otherwise serial.
   Codex showed ~5 concurrent coders (p07..p11 lane-caller branches) worked when disjoint.
1. **Right-size pipeline**: skip plan-review/two test reviews for mechanical migrations marked
   `risk: low` in the plan (the P07..P11 caller migrations each ran the full ceremony).
1. **Auto-propose next step**: after each merge, the orchestrator writes `what_remains` and the
   next ready item; "What's next?" should never be needed (8+ prompts).

### 4.4 Godot CLI / MCP integration

Recommendation: ship a **small CLI wrapper (`godotkit`, bash/python, no editor)** as plugin
`bin/`, plus an *optional* MCP. Data: MCP used 2 times; CLI used tens of thousands.

`godotkit` subcommands (all with timeout, isolated XDG, SCRIPT ERROR / leak detection, nonzero
count regex, JSON or one-line summary output):

| Command                                          | Replaces                                                                                                                                    |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `godotkit doctor`                                | version check, `GODOT_BIN`, DISPLAY presence, `gdtoolkit`, pre-commit env                                                                   |
| `godotkit import`                                | `--headless --import`, then reports tracked-file churn (translation, `.uid`) and stages it                                                  |
| `godotkit check <files>`                         | per-file `--check-only --script`                                                                                                            |
| `godotkit test <res://suite> --expect '<regex>'` | `run_checked_script.sh`                                                                                                                     |
| `godotkit native <suite>`                        | non-headless run on `DISPLAY`, rejects headless backend                                                                                     |
| `godotkit boot`                                  | launch the real main scene, assert no `ERROR`/`SCRIPT ERROR` in the first N frames, optional synthetic click/drag (the root-startup lesson) |
| `godotkit shot <scene> --size WxH`               | screenshot for visual review and the HTML review page                                                                                       |
| `godotkit worktree new/merge/rm`                 | section 4.3 item 3                                                                                                                          |
| `godotkit gate`                                  | the nine-hook pre-commit set, with one retry after import churn                                                                             |

MCP: if included, wrap the same commands (`godot_import`, `godot_test`, `godot_boot`,
`godot_screenshot`) so the editor-free path stays the default. A generic editor-control MCP
(`@coding-solo/godot-mcp`) can be an opt-in extra; do not make skills depend on it.

### 4.5 Hooks

| Hook                                                    | Event                                 | Purpose                                                                | Evidence                                |
| ------------------------------------------------------- | ------------------------------------- | ---------------------------------------------------------------------- | --------------------------------------- |
| Ownership guard                                         | PreToolUse Edit/Write (subagents)     | deny out-of-manifest writes                                            | prose-only ownership in Codex           |
| Frozen-test guard                                       | PreToolUse Edit/Write + Stop of coder | deny edits to hashed tests                                             | 237 hash checks done by hand            |
| `.uid` / import completeness                            | PostToolUse Write `*.gd`              | warn if `.gd.uid` missing/uncommitted                                  | 262 `.uid` files committed manually     |
| Import churn check                                      | Stop / pre-commit wrapper             | report tracked-file changes made by `--import`, stage them             | 49 "files were modified" events, L-0009 |
| 300-line guard                                          | PostToolUse Edit/Write on `*.gd`      | tell the agent to split before the gate fails                          | AGENTS.md rule, L-0020                  |
| Hardcoded-parameter nudge                               | PostToolUse                           | grep new numeric/colour literals in non-test scripts, suggest resource | AGENTS.md rule                          |
| No-silent-model-switch                                  | PreToolUse on fal submit              | block if model differs from project lock (`AGENTS.md` art rules)       | "Do not silently switch models"         |
| Dangerous-shell parser must tolerate heredocs/backticks | n/a (lesson)                          | do NOT ship a shell guard that rejects backticks in heredocs           | I-0056, Resolve guard failure           |
| Worktree janitor                                        | SessionStart                          | list stale worktrees/branches, offer cleanup                           | 36 left behind                          |
| Version pin check                                       | SessionStart                          | warn when host CLI version differs from hook bridge pin                | Codex 0.165 vs 0.167 silent skip        |

Permissions (replaces 164 escalations + 187 Guardian sessions): ship a recommended
`settings.json` allowlist: `Bash(godotkit:*)`, `Bash($GODOT_BIN:*)`, `Bash(git worktree:*)`,
`Bash(git push origin main)` only if the user opts in, `Bash(pre-commit run:*)`, read-only git.
Document that `--import` needs write access to `.godot` and the editor IPC socket, and that a
display is required for native runs (`DISPLAY=:0`), so those are the sandbox exceptions to grant
once rather than per command.

### 4.6 Memory and handoff (reuse, with Godot seeds)

- `mz-memory` already produced the right artifacts under Codex: 22 curated lessons, ~45 inbox
  items, digest `D-0001` ("Build phases are capped at five authored files. Order: plan approval,
  reviewed tests, verified RED, GREEN, production review, final review, completeness. Only the
  test writer edits tests/smoke.gd") and `D-0002` (architecture + Godot path). The plugin should
  seed a *starter lessons pack* for Godot (the general ones: L-0001, 0002, 0003, 0004, 0010, 0013,
  0014, 0015, 0016, 0020, 0021 and I-0031/I-0037/I-0056) tagged `godot`, and let projects add art
  lessons themselves.
- Correction capture: keep `memory-note --lesson` + UserPromptSubmit reminder; every art
  correction in section 3 row 1 became a lesson or AGENTS.md bullet only because the user asked.
  Make it automatic for corrections.
- `mz-handoff`: the Codex run survived two daemon restarts only through `state.md`. In Claude
  the Stop hook after N compactions plus `.mz/handoff` fits. Extend the handoff template with
  "active worktrees: branch, owner, status" and "frozen test hashes".
- Do not duplicate: activity log in `.mz/memory` and per-task `state.md` already overlap; keep
  `state.md` per task as the source of truth and have the memory log reference it (one source of
  truth, per the user's own rule).

### 4.7 Cost guard

The run consumed 27,974 exec batches, 1,548 `spawn_agent`, 2,260 `followup_task`, 6,369
`send_message` and 187 Guardian sessions in 4.5 days (10 GB of rollouts). No budget control is
visible. The plugin should provide:

- Agent-count and token budget per task in `state.md` (`budget: subagents 12, review rounds 2`);
  the orchestrator stops and asks when exceeded.
- Pipeline depth by risk (see 4.3 item 9), to avoid full 10-stage ceremony on mechanical edits.
- Polling ban (waits via notification), and a cap on `followup_task` loops (1,045 in orchestrator).
- Reuse the fal spend guard for media (fal-media has estimate_cost / price rule: "Add price rule
  to json and continue", graph H8).
- Report at task end: agents spawned, review rounds, wall time, retries.

### 4.8 Review pages (visual verification loop)

Art and UI were judged by the human in HTML pages (`art/progression/presentation.html`,
`review/index.html`, UI prototypes served on `127.0.0.1:8792`). Provide a `review-page` skill that
(a) regenerates the page from manifests every time art is accepted, (b) has an approve/redo mode
with a "copy list of images to regenerate" button (H47), (c) verifies image loading and
desktop/mobile layout (AGENTS.md demands this) via Chrome tools. This directly addresses
frustration #2.

______________________________________________________________________

## 5. Priorities and open questions

Build order, by return on observed pain:

1. `godotkit` CLI (+ test-runner guards + `boot` real-startup gate). Fixes the biggest bug class
   (green tests, broken game) and removes most escalations.
1. `/godot-init` bootstrap (rules via mz-rules, pre-commit, runner scripts, AGENTS/CLAUDE).
1. `godot-team` skill: delegation template, ownership manifest, worktree lifecycle, frozen tests.
1. Hooks (ownership, frozen tests, `.uid`, import churn, line cap).
1. Godot lesson seeds for mz-memory; handoff template extension.
1. Review-page skill and the art-role bridge to `fal-media`.
1. Optional Godot MCP wrapper.

Pre-existing issues surfaced (not touched; each can be a separate pass if wanted):

- `lessons.md.bak`, `MEMORY.md.bak` and `*.lock` files sit in `.mz/memory` (lock is gitignored, `.bak` is not).
- ~36 stale worktrees and 41 `codex/*` branches in `/tmp` and the repo; 4 worktrees already prunable.
- `~/.codex/AGENTS.md` still says "Never attempt multi-file refactors ... wait for approval" (old
  mz-rule block 0.49.0) while the project's AGENTS.md supersedes it ("continue without asking
  between phases"); contradictory rules at two levels.
- `CLAUDE.md` says "Follow AGENTS.md" and has no Claude-specific content; fine for Codex, but
  for Claude Code the thread:// roster links are meaningless and need translating to subagent
  names.
- Absolute path `/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64` is hardcoded in
  `.claude/settings.local.json`, memory, and plans.
- Gap in my evidence: I did not read the 9 GB raw logs end to end; push/escalation category
  counts are keyword-bucketed and the "other 69" escalation bucket was not further classified.
  The per-thread "FAIL" counts in review files are from 2-3 files each and are indicative only.

Bug autopsy of the headline defect (root startup): it happened because test fixtures built the
scene differently from the real engine startup. A `godotkit boot` gate that launches the actual
main scene and performs one synthetic drag would have caught it on day 1.
