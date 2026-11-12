# Godot 4.x agent tooling: MCP servers, CLI, tests, lint (web research, Nov 2026)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## MCP servers

| Project                              | Architecture                                                                 | Run                 | Errors           | Screenshot                           | Input                      | Edit                                             | License                    | Godot          | Signal                                                                                    |
| ------------------------------------ | ---------------------------------------------------------------------------- | ------------------- | ---------------- | ------------------------------------ | -------------------------- | ------------------------------------------------ | -------------------------- | -------------- | ----------------------------------------------------------------------------------------- |
| github.com/Coding-Solo/godot-mcp     | Node stdio → Godot CLI, no addon                                             | yes                 | get_debug_output | no                                   | no                         | create_scene/add_node/save_scene/UIDs            | MIT                        | 4.x (UID 4.4+) | 6.6k stars; Apr 2026 RCE fix (arbitrary GDScript instantiation via add_node/create_scene) |
| github.com/raising-heart/godot-mcp   | fork + .claude-plugin + skill                                                | yes, headless tests | check_scripts    | Movie Maker (needs display)          | no                         | same; GODOT_MCP_READ_ONLY=1                      | MIT                        | 4.x            | 0 stars                                                                                   |
| github.com/hi-godot/godot-ai         | stdio attach → Python server (auth HTTP) → editor plugin (auth WS, loopback) | project_run         | logs_read        | editor_screenshot                    | kbd/mouse/gamepad/actions  | 46 tools/120+ ops                                | MIT                        | 4.7+           | ~3.5k stars, active                                                                       |
| github.com/Erodenn/godot-mcp-runtime | npx; injects temporary McpBridge autoload (TCP), removed after               | run_project, attach | yes              | take_screenshot                      | keys/mouse/UI/actions/text | 43 tools, JSON schemas, profiling, live GDScript | MIT                        | 4.5+           | —                                                                                         |
| github.com/signalcompose/godot-mcp   | TS → editor WS                                                               | yes                 | yes              | ?                                    | ?                          | 90+ tools                                        | source-available (not OSI) | 4.6+           | 1 star                                                                                    |
| github.com/ee0pdt/Godot-MCP          | stdio + addon                                                                | yes                 | ?                | ?                                    | ?                          | CRUD                                             | MIT                        | ?              | 621 stars                                                                                 |
| GDAI MCP                             | closed binary addon                                                          | yes                 | yes              | yes                                  | yes                        | yes                                              | paid $19                   | 4.1/4.2+       | commercial                                                                                |
| Godot MCP Pro                        | Node → editor WS                                                             | yes                 | yes              | + compare_screenshots, record_frames | record/replay              | 187 tools                                        | paid $15                   | 4.4+           | commercial                                                                                |
| Ziva, Summer Engine                  | vendor editors                                                               | —                   | —                | —                                    | —                          | —                                                | proprietary/freemium       | —              | vendor                                                                                    |
| AI Assistant Hub (FlamxGames)        | in-editor chat, not MCP                                                      | —                   | —                | —                                    | —                          | —                                                | MIT                        | 4.x            | —                                                                                         |
| Godot official                       | none; Godot restricts AI-authored PRs (Jun-Jul 2026 press)                   |                     |                  |                                      |                            |                                                  |                            |                |                                                                                           |

Architectures: (a) CLI-only, (b) editor plugin + WS bridge, (c) injected runtime autoload. (c) fits agent CLIs best. Version floors fragment (4.4+/4.5+/4.6+/4.7+).

## Godot CLI facts (4.7 docs)

- `--headless --path P`, `--import` (implies --editor --quit), `-s script --check-only`, `--quit`, `--quit-after N`, `--write-movie out.png|.avi` (forces --fixed-fps), `--export-release/--export-debug/--export-pack` (output dir must exist), `--doctool --gdscript-docs`, `--lsp-port/--dap-port` (editor only; defaults 6005/6006, from memory), `--log-file`, `--gpu-validation`. `--test` only in tests=yes builds.
- `--check-only` per-script: can't resolve autoloads/class_name, false errors on fresh clone without .godot/, ignores warnings-as-errors. Better: `--headless --import` then boot run `--quit-after N` grepping log for SCRIPT ERROR / Parse Error / ERROR.
- Headless often exits 0 after failure (forum, reproduced 4.4.1-4.7.2): import with syntax error exits 0 on 4.5+; broken-script scene runs as bare node; RPC errors only in the other process log. ⇒ judge by logs + explicit success markers, never exit code.
- `--headless` uses dummy renderer; screenshots need a display (Xvfb). 4.7 offscreen headless rendering UNVERIFIED.

## Test frameworks

- GdUnit4 (github.com/godot-gdunit-labs/gdUnit4, MIT): v7.0.0 for 4.7+, v6.2.x for 4.5-4.7.1; CLI, gdunit4-action, HTML+JUnit XML, Scene Runner (input sim, await signals). Best fit.
- GUT (github.com/bitwes/Gut, MIT): one release per Godot version (9.7.1 ↔ 4.7); gut_cmdln.gd; JUnit XML. Forum: false "All tests passed" when its scripts fail to load on mismatched versions.
- WAT: Godot 3 only.
- Visual regression: no standard. Options: write-movie PNG diff, injected autoload viewport capture, MCP Pro compare_screenshots (paid).

## Lint/format

- gdtoolkit (gdlint/gdformat), last release 4.5.0 Oct 2025 — may lag 4.6/4.7 syntax.
- GDQuest GDScript Formatter v0.26.0 (Sep 2026), `--check`, `--safe`, `lint` subcommand, pre-commit; more active.
- No built-in formatter (PR #76211 status unverified). Static-typing warnings via `debug/gdscript/warnings/*` (can be errors), visible in import/editor runs, not --check-only.

## Other engines

- Unity MCP in com.unity.ai.assistant (Unity 6+); CoplayDev unity-mcp. Bevy bevy_brp_mcp over Bevy Remote Protocol (closest analogue to injected runtime bridge). Borrow: in-process protocol, JSON output schemas with null+warning, authenticated loopback, read-only flag, input record/replay.

## Recommendation

Build a thin owned CLI (`godot-agent`/godotkit): locate binary (GODOT_PATH → PATH → --version), `import`, `check` (boot gate + log parse), `test` (GdUnit4 JUnit wrapper, GUT optional), `shot`/`frames` (write-movie under Xvfb or injected autoload), `fmt`/`lint` (GDQuest, gdtoolkit fallback), `export`. One JSON line per command, never trust exit code. Phase 2: runtime autoload bridge for screenshots/input. Never build an editor bridge; recommend hi-godot/godot-ai (4.7+) or Coding-Solo (older) as optional MCP. Don't default to signalcompose/GDAI/MCP Pro.

Perfectionist: no live editor control, log heuristics fragile. Pragmatist: edit text → import → boot → test → screenshot covers most of the loop; ~1 week to build.

## Risks

Exit-code lies (fixture projects in CI per Godot minor); rendering needs display; import before anything on fresh clones; GUT/GdUnit4 version mapping table needed; gdtoolkit staleness; ecosystem volatility; unverified: LSP/DAP defaults, built-in formatter, Unity CLI MCP, official Unreal MCP.

## Sources

docs.godotengine.org command_line_tutorial; repos linked above; forum.godotengine.org/t/things-that-exit-0-in-godot-4-headless.../145990; gdquest.com/library/gdscript_formatter; pypi gdtoolkit; PC Gamer / The New Stack / GamingOnLinux on Godot AI policy; docs.rs/bevy_brp_mcp; Unity AI assistant docs.
