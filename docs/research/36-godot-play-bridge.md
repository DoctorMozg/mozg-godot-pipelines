# Runtime bridge for LLM-driven playtesting (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org/en/4.7, Godot source at 4.7-stable, Godot PRs and the repos of Godot RL Agents, GdUnit4, GUT, GodotE2E and related tools. Bridge behaviour is UNTESTED on 4.7.2.

## Executive Summary

The best fit for the existing kit is a lockstep design:

- Python listens on 127.0.0.1, and the injected autoload connects to it as a client.
- Messages are newline-delimited JSON over `StreamPeerTCP`.
- The game runs with `--fixed-fps`. The bridge blocks the main loop between steps, so the LLM's thinking time never turns into game time.

This is the pattern Godot RL Agents uses, minus its wall-clock speedup.

Observation comes from tree walks plus a per-game catalogue:

- Controls with their rects, text and accessibility names.
- Entities that put themselves in a group.
- Geometric visibility, computed by the bridge.

Screenshots and Movie Maker need a real renderer, so they need Xvfb. Under `--headless` the viewport texture is not backed by anything.

Input goes through `Input.parse_input_event`. Holds are tracked by the bridge across physics frames.

On safety, the main finding is that `TCPServer.listen()` and `StreamPeerTCP.bind()` default to `"*"`, which means every interface. Making the game a client removes the listening socket from the game entirely.

## Key Findings

### 1. Transport

**F1.1 — TCP bind default (high, 2026-11-13).** `TCPServer.listen(port, bind_address="*")` listens on "all available addresses (both IPv4 and IPv6)". `"::1"` or `"127.0.0.1"` restricts it to loopback. `StreamPeerTCP.bind(port, host="*")` has the same default. A bridge that calls `listen(port)` without an address is reachable from the LAN. [TCPServer 4.7, StreamPeerTCP 4.7]

**F1.2 — Godot RL Agents uses the game as client (high).** `sync.gd` hardcodes `ip = "127.0.0.1"`, defaults to port `11008`, and is overridable with `port=N`. It calls `connect_to_host`, sets `set_no_delay(true)`, and polls `get_status()`. Python (`gdrl`) is the server.

- Messages are `put_string(JSON.stringify(...))` / `get_string()`.
- Message types: handshake, env_info, reset, action, call, close. Godot replies with reset/step `{obs, reward, done, info}`.
  [sync.gd main]

**F1.3 — StreamPeer string framing (high for the prefix, medium for byte order).** `put_utf8_string` writes a 32-bit unsigned size prefix, and `get_utf8_string(-1)` reads it. `big_endian` defaults to `false`, which implies a little-endian prefix. The docs do not state the byte order outright, and they describe the string as "zero-terminated".

- UNVERIFIED: whether a trailing NUL byte is counted in the length.
- Recommendation: do not rely on it. Use explicit framing, either NDJSON or `put_32` + `put_data`.

**F1.4 — WebSocketPeer works but is a poor fit (high).**

- It can serve through `TCPServer.take_connection()` + `accept_stream()`, and needs `poll()` every frame.
- `inbound_buffer_size` and `outbound_buffer_size` default to 65535, so large observations or base64 screenshots need larger buffers.
- Python 3.11's stdlib has no WebSocket client or server. The kit would have to hand-roll RFC 6455 framing.

**F1.5 — stdin/stdout is possible but fragile (high for the API, medium for the assessment).**

- `OS.read_string_from_stdin(buffer_size=1024)` "can be blocking", which suits lockstep.
- Stdout is shared with engine logs, so it needs a marker prefix. The kit already parses logs, which makes this workable.
- `application/run/flush_stdout_on_print` defaults to `false`, and its `.debug` override defaults to `true`. Flushing therefore differs between debug and release.
- The 1024-byte read buffer can split long commands.

**F1.6 — Files are the slowest option.** File polling costs a filesystem stat per frame. It is only useful as a fallback, and for passing large artefacts (screenshots) by path.

**F1.7 — The remote debugger channel (medium).**

- `--remote-debug tcp://127.0.0.1:P` makes the game connect to a debug server.
- `EngineDebugger.register_message_capture(name, callable)` and `send_message` carry custom messages.
- The wire format is Godot's binary Variant encoding. A stdlib Python port is feasible but heavy.
- PlayGodot uses this route and needs a custom engine fork (secondary listings only, so UNVERIFIED).
- Not recommended as the primary transport.

**F1.8 — Latency (UNVERIFIED locally).** Loopback TCP round trips are sub-millisecond. With `set_no_delay(true)` and `TCP_NODELAY` in Python, the LLM call (seconds) dominates the loop. No 4.7.2 measurement exists.

### 2. Clock control

**F2.1 — `--fixed-fps` decouples game time from wall time (high, source).**

- `MainTimerSync::advance_checked` replaces the measured step: `if (fixed_fps != -1) { p_process_step = 1.0 / fixed_fps; }`. Physics steps come from `floor(time_accum * physics_ticks_per_second)`.
- `Main::iteration()` applies the `max_physics_steps` clamp only when `fixed_fps == -1`, and returns early with no frame-pacing sleep in fixed mode.
- Consequence: a bridge that blocks the main thread for 10 s while the LLM thinks gives the next frame a delta of exactly 1/F.
- Without `--fixed-fps`, the next frame sees 10 s of wall time. Physics is capped at `max_physics_steps_per_frame` (default 8, set via `physics/common/max_physics_steps_per_frame`), while `_process` delta is not capped, so objects jump.
  [main.cpp, main_timer_sync.cpp @4.7-stable]

**F2.2 — Movie Maker (high).**

- `--write-movie` forces `fixed_fps = 60` unless `--fixed-fps` is given (main.cpp).
- Output is "non-real-time", and "visual output remains identical" regardless of hardware speed.
- Stop it with `get_tree().quit()` or `--quit-after N`, not Ctrl+C, which corrupts AVI files.
- The `movie` feature tag is set while it runs.
- A lockstep LLM session recorded this way plays back at normal speed with no visible think pauses. It needs a real renderer, so Xvfb. Whether it works under `--headless` is UNVERIFIED (likely blank or error, see F3.5).
  [Creating movies 4.7, Feature tags 4.7]

**F2.3 — Pausing the SceneTree is a weaker clock (high).**

- `SceneTree.paused` stops 2D/3D physics, collision detection and their signals.
- Pausable nodes stop `_process`, `_physics_process`, `_input` and `_input_event`.
- Gotchas that make pause-based stepping leak time:
  - `SceneTree.create_timer(time_sec, process_always=true, ...)` defaults to running while paused.
  - Tween pause behaviour depends on the bound node (`TWEEN_PAUSE_BOUND`), and `TWEEN_PAUSE_PROCESS` ignores pause.
  - The game's own pause menu also writes `paused`, so the bridge and the game would fight over it.
- Godot RL Agents still uses pause + unpause around a blocking read.
- Recommendation: lockstep blocking with `--fixed-fps`, leaving `paused` to the game.

**F2.4 — Engine API (high).** `Engine.time_scale` scales both the process step and the physics step in `iteration()`. Other relevant properties:

- `Engine.physics_ticks_per_second`
- `Engine.max_physics_steps_per_frame`
- `Engine.get_physics_frames()` / `get_process_frames()`, which serve as step counters.
- `--time-scale` and `--frame-delay` CLI flags exist.

GdUnit4 "time factor" sets `Engine.time_scale` and scales `physics_ticks_per_second`, capped at 9.

**F2.5 — No manual physics stepping in 4.7 (high).** PR #76462, which adds `PhysicsServer2D/3D.space_step()`, is still open (last activity 2026-11-05, milestone 4.x). The only way to advance physics is to advance engine frames.

**F2.6 — Determinism (medium).**

- Godot RNG is seeded from local time by default. Fixed results need `seed()` and per-instance `RandomNumberGenerator.seed`, with `state` snapshots.
- Jolt, the default 3D engine for new projects since 4.6, is deterministic only when "APIs that modify the simulation are called in exactly the same order" with the same binary.
- Cross-platform determinism needs `CROSS_PLATFORM_DETERMINISTIC`. UNVERIFIED whether official Godot builds enable it.
- UNVERIFIED: run-to-run reproducibility of Godot Physics 2D/3D and Jolt-in-Godot on one machine with `--fixed-fps` and seeded RNG. Test it: two runs of the same action log, compare per-frame state hashes.
- Wall-clock reads (`Time.get_ticks_msec`, `ignore_time_scale` timers and tweens) break replay.
- UNVERIFIED: whether `ignore_time_scale` timers use the unscaled fixed step or true wall time under `--fixed-fps`.

### 3. Observation

**F3.1 — UI (high).** From the Control, Viewport and CanvasItem class pages:

- `Viewport.gui_get_focus_owner()` and `gui_get_hovered_control()`.
- `Control.get_global_rect()`, `is_visible_in_tree()` and `focus_mode`.
- Text via class-specific properties (`Label.text`, `Button.text`, `LineEdit.text`, `RichTextLabel.get_parsed_text()`).
- `Control.accessibility_name`, `accessibility_description`, `accessibility_live` and `accessibility_labeled_by_nodes`.

**F3.2 — AccessKit data cannot be read back in-process (high).**

- DisplayServer has only `accessibility_update_set_*` setters (name, role, bounds). The only getters are `accessibility_element_get_meta`, `accessibility_has_element` and `accessibility_screen_reader_active`.
- `FEATURE_ACCESSIBILITY_SCREEN_READER` is listed for Linux X11/Wayland, macOS and Windows, not for headless.
- Reading the tree externally through AT-SPI would need a display, D-Bus and `--accessibility always`. UNVERIFIED under Xvfb.
- Recommendation: build the UI observation from Control properties, including `accessibility_name`. Do not use AccessKit.

**F3.3 — World state.**

- `SceneTree.get_nodes_in_group()` lets the game opt entities in.
- Positions come from `global_position`.
- Visibility should be computed geometrically:
  - 3D: `Camera3D.is_position_in_frustum` / `unproject_position`, plus an occlusion raycast.
  - 2D: canvas transform against `Viewport.get_visible_rect()`.
- UNVERIFIED: whether VisibleOnScreenNotifier2D/3D fire under the dummy renderer. Assume not.
- (Camera APIs: medium, from general 4.x knowledge, not re-fetched.)

**F3.4 — Screenshots need a renderer (high).**

- `Viewport.get_texture().get_image()` can be "completely black or outdated if used too early". Await `RenderingServer.frame_post_draw` first.
- Save to PNG and send the path, not the bytes.
- With Xvfb and a real renderer this works (GodotE2E's CI uses `xvfb-run`). Repo research 21 covers Xvfb with lavapipe or llvmpipe.

**F3.5 — Headless capture returns nothing usable (high from source; UNTESTED on 4.7.2).**

- `--headless` = `--display-driver headless --audio-driver Dummy`, and RenderingServer returns dummy values.
- In the dummy storage, `render_target_get_texture` returns `RID()`, and `texture_2d_get` on it hits `ERR_FAIL_NULL_V` and returns an empty `Ref<Image>`. Expect null plus an error line.
- 4.7 adds no offscreen or headless rendering mode: no CLI option, and nothing in the 4.7 release notes.

### 4. Action

**F4.1 — Input injection APIs (high).**

- `Input.parse_input_event(e)` "feeds an InputEvent to the game" and "also generates Node.\_input() calls". It is the general route, and `InputEventAction` through it is the documented way to synthesise actions.
- `Input.action_press/release` updates action state only: "will not cause any Node.\_input() calls". Games that read actions in `_unhandled_input` miss it.
- `Viewport.push_input(e, in_local_coords)` injects into one viewport. GdUnit4 does both `Input.parse_input_event`, then `Input.flush_buffered_events()`, then `viewport.push_input`. Doing both risks double delivery. UNVERIFIED whether GdUnit4 de-duplicates.
- `use_accumulated_input` is on by default, and buffered events are flushed at least once per frame. GUT's author needed 7 frames before asserting. The bridge should call `flush_buffered_events()` after injecting.

**F4.2 — Holds (high).**

- `is_action_just_pressed` is true only "on the frame or tick" of the press.
- A hold is a press event at frame t and a release at t+N, with no repeats in between. Synthetic keys get no OS echo events.
- GUT has `hold_for("Nf")`, `hold_frames(n)` (physics frames) and `release_all()`. GdUnit4 has `simulate_action_press/release` and `simulate_frames`.
- The bridge must release everything on reset, end and disconnect.

**F4.3 — Mouse (medium).**

- `Input.warp_mouse` and `Viewport.warp_mouse` work on Windows, macOS and Linux only. Under the headless display server they likely do nothing (UNVERIFIED).
- Instead, send `InputEventMouseMotion` and `InputEventMouseButton` with `position` and `global_position` set. Clicking a Control means clicking the centre of its `get_global_rect()`.
- 4.7 adds per-device IDs: `InputEvent.DEVICE_ID_KEYBOARD=16`, `DEVICE_ID_MOUSE=32`. Synthetic events should set these.
- 4.7 also adds an opt-in project setting that ignores gamepad input while the window is unfocused. UNVERIFIED whether it filters parsed synthetic joypad events.

**F4.4 — Semantic actions (medium).**

- Calling game methods directly is the high-level lever, for example a NavigationAgent `target_position` with `is_navigation_finished()`.
- `SceneTree.call_group` silently ignores nodes without the method, so the bridge should check `has_method` and report a miss.
- An arbitrary `call(method)` is effectively code execution, through `set_script`, `queue_free` or `Expression`. The catalogue must be a whitelist that the game declares.

### 5. Existing projects (support for 4.7)

| Project                                   | Mechanism                                                                                                                                                | 4.7 status                                                                   | Notes                                                                                                               |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Godot RL Agents (MIT)                     | Sync node, game is TCP client to Python, JSON, pause plus blocking read, `action_repeat=8`, `speedup` scales `physics_ticks_per_second` and `time_scale` | godot-rl 0.8.2 (PyPI, 2025-02-25), Python ≥3.7. No 4.7 statement: UNVERIFIED | Sensors and ONNX inference are RL-oriented. The protocol shape is reusable                                          |
| GdUnit4 scene runner                      | `Input.parse_input_event`, flush, then `push_input`. `set_time_factor` ≤9. `simulate_frames` awaits `process_frame`                                      | Repo research 09: v7.0.0 for 4.7+, v6.2.x for 4.5–4.7.1                      | In-process, not an external agent                                                                                   |
| GUT InputSender                           | Receiver = Input (parse) or Node (calls `_input`/`_gui_input`/`_unhandled_input` directly)                                                               | 9.7.1 used in plan A4b                                                       | `hold_for`, `wait_frames`, `release_all`                                                                            |
| GodotE2E (Apache-2.0)                     | Autoload TCP server, dormant unless `--e2e`. `--e2e-port=0` plus a port file. Token. Python pytest client                                                | Godot 4.5+, 1.2.x line                                                       | Closest analogue. Waits for process, physics frames or game time. Screenshots under Xvfb                            |
| godot-ai-playtest 0.4.0 (MIT, 2026-04-01) | TCP plus plugin, `send_input(action, duration_ms)`, YAML scenarios                                                                                       | "4.x", Python ≥3.10                                                          | Duration in ms is wall-clock and not deterministic                                                                  |
| godot-mcp-runtime (MIT)                   | Injected `McpBridge` autoload, localhost TCP, removed after the run                                                                                      | 4.5+                                                                         | Batched input, UI discovery, screenshots with `likelyBlank`. Runs arbitrary GDScript, which is an anti-pattern here |
| Godot MCP Pro (paid)                      | Editor WebSocket                                                                                                                                         | 4.4+                                                                         | Input record and replay (repo research 09)                                                                          |
| GodotTestDriver (C#, MIT)                 | Drivers over nodes, input including action hold                                                                                                          | Version not stated                                                           | C# only                                                                                                             |
| PlayGodot                                 | RemoteDebugger protocol                                                                                                                                  | Needs an engine fork (UNVERIFIED, secondary sources only)                    | Not usable on stock 4.7.2                                                                                           |

### 6. Safety

**F6.1 — Feature tags (high).** Tags in 4.7:

- `editor_runtime`: "editor build, and running the project".
- `template`: an export template.
- `debug` and `release`.
- `movie`.

Custom tags apply only to exported projects. `OS.is_debug_build()` is true for debug templates and the editor. The bridge should refuse to start unless `OS.has_feature("editor_runtime")` and a user argument after `--` (`OS.get_cmdline_user_args()`) carries the port and token.

**F6.2 — No listener in the game (high).** With the game as client and Python bound to `127.0.0.1:0`, there is no inbound port in the game at all. Python accepts exactly one connection, then checks a token passed via an env var or a 0600 file.

**F6.3 — Bridge stays out of the real project (high).** The kit already injects into a scratch worktree only (plan A3). A permanent action catalogue in the game is data plus whitelisted methods, not a server.

## Trend Analysis

Several independent projects converged on the same design, all dated 2026: an injected or dormant autoload, a TCP loopback connection, a Python client, and frame-based waits.

- GodotE2E
- godot-ai-playtest
- godot-mcp-runtime
- Godot RL Agents

The differences are clock control and safety:

- Only Godot RL Agents is lockstep.
- godot-mcp-runtime ships an eval tool.
- Wall-clock `duration_ms` (godot-ai-playtest) is common but non-deterministic.

None of them uses AccessKit for observation.

## Recommended bridge protocol

```
Python (godotkit play)                         Godot (injected autoload, PROCESS_MODE_ALWAYS)
listen 127.0.0.1:0, token T
spawn godot --fixed-fps 60 [--headless | Xvfb] -- --mozg-bridge=PORT --mozg-token-file=F
                        <-- hello {v, token, godot, project, fps, physics_tps, catalogue}
welcome {seed, max_steps} -->                   seed(); rng seeds; release_all()
                        <-- obs {...}  (frame 0)
loop:
  LLM thinks (game blocked in bridge._physics_process, delta unaffected)
  step {id, act:[...], frames:N} -->             apply acts, flush, run N physics frames,
                                                 expire holds, collect events
                        <-- obs {id, ...}
  ...
end {reason} -->                                 release_all(); print MOZG_PLAY_SUMMARY ...; quit()
```

**Framing.** One JSON object per line (NDJSON). `JSON.stringify(d)` emits a single line, and the Godot side buffers by `\n`. Messages larger than 1 MiB are an error, and screenshots are sent as paths.

**Blocking.** The bridge reads in its `_physics_process` with `stream.poll()` and `OS.delay_msec(2)` until it has a full line. It quits with a summary line on disconnect or after a configurable idle timeout.

**Message sketch:**

```json
{"t":"hello","v":1,"token":"...","godot":"4.7.2.stable","fps":60,"physics_tps":60,
 "catalogue":{"input_actions":["move_left","jump"],
   "semantic":[{"name":"go_to","node":"Player","args":{"target":"Vector2|node_path"},"doc":"walk via NavigationAgent2D"}]}}

{"t":"step","id":7,"frames":10,"act":[
  {"k":"action","name":"jump","hold_frames":6,"strength":1.0},
  {"k":"key","keycode":"KEY_E","hold_frames":1},
  {"k":"click","control":"HUD/Menu/StartButton"},
  {"k":"mouse","x":412,"y":300,"button":1},
  {"k":"text","value":"Bob"},
  {"k":"semantic","name":"go_to","args":{"target":"Door2"}}]}

{"t":"obs","id":7,"frame":1210,"physics_frame":1210,"game_time":20.166,
 "scene":"res://levels/l1.tscn","paused":false,
 "focus":"HUD/Menu/StartButton","hovered":null,
 "ui":[{"path":"HUD/HP","cls":"Label","text":"HP 3","rect":[8,8,80,24],"vis":true,"dis":false,"a11y":"Health"}],
 "entities":[{"path":"Player","cls":"CharacterBody2D","pos":[120,340],"on_screen":true,"state":{"hp":3}}],
 "held":[{"k":"action","name":"jump","left":0}],
 "events":[{"f":1203,"sig":"Player.jumped"}],
 "log":{"errors":0,"warnings":1,"last_error":null},
 "results":[{"i":0,"ok":true},{"i":5,"ok":false,"err":"semantic_not_found"}],
 "shot":"scratch/play/7.png"}

{"t":"end","reason":"goal|max_steps|timeout|error"}
```

**Catalogue.**

- Low-level actions: `InputMap.get_actions()`, excluding `ui_*` unless the menu needs them.
- Semantic actions: nodes in group `playtest_actor` with `playtest_actions() -> Array[Dictionary]` and `playtest_do(name, args) -> Dictionary`.
- Observed state: nodes in group `playtest_observe` with `playtest_state() -> Dictionary`.
- The bridge calls only those three method names.

**Replay.** The step log (`seed`, `fps`, every `step`) is a replay script. Replaying under Movie Maker on Xvfb produces the review clip, and per-frame state hashes check determinism.

## Checkable rules

1. The bridge never calls `TCPServer.listen`. If a listener is ever needed, it passes `"127.0.0.1"` explicitly.
1. The bridge starts only when `OS.has_feature("editor_runtime")` is true and the user args contain `--mozg-bridge`. Otherwise it frees itself.
1. The token is checked before any other message is handled.
1. Every play run passes `--fixed-fps`. Without it the run reports `clock=realtime` in its summary line.
1. The bridge never writes `SceneTree.paused`. It never uses `Expression`, `set_script`, `load` of user strings, or `call` outside the three catalogue methods.
1. Every held input is released on `end`, disconnect and scene change.
1. `Input.flush_buffered_events()` follows each injection batch.
1. Screenshots are requested only when the renderer is not dummy. In headless mode the request returns `{"ok":false,"err":"no_renderer"}`.
1. Each run ends with `MOZG_PLAY_SUMMARY status=… steps=… frames=… errors=…` and is judged by that line, not the exit code.
1. The RNG is seeded from `welcome.seed`.

## What a tool could check automatically

- Grep the scratch bridge and catalogue scripts for `listen(` without an address, `Expression`, `str_to_var`, `set_script` and `.call(` with a non-literal method name.
- Grep game code for wall-clock reads in gameplay paths: `Time.get_ticks_msec`, `get_unix_time`, `create_timer(` with `ignore_time_scale=true`, `set_ignore_time_scale`, `randomize()` and an unseeded `RandomNumberGenerator.new()`. Report these as replay risks.
- After the run, verify that `project.godot` and `export_presets.cfg` in the real project are byte-identical (no leaked autoload).
- Determinism probe: replay the same step log twice and diff the per-frame entity state hashes.
- Bridge self-test on a fixture:
  - A held action keeps `is_action_pressed` true for N physics frames.
  - `is_action_just_pressed` fires once.
  - A click on a Button rect emits `pressed`.
- Catalogue lint: every `playtest_actions()` entry has `name`, `args` and `doc`, and `playtest_do` handles each name (the fixture calls each one with sample args).

## Risks and Uncertainties

- UNTESTED on 4.7.2:
  - Headless `get_image()` returning null.
  - Movie Maker under `--headless`.
  - `warp_mouse` under the headless display server.
  - VisibleOnScreenNotifier under the dummy renderer.
  - Run-to-run physics determinism.
  - `ignore_time_scale` timer behaviour under `--fixed-fps`.
- Blocking the main thread freezes a windowed run (Xvfb is fine), and audio stops. Games with threads (WorkerThreadPool, loading threads) keep running in wall time while the main loop is blocked, which breaks lockstep for async loads. Mitigation: `wait_until` steps on a predicate rather than a frame count.
- Games that read raw `_input` positions, or use custom input layers (Guide, G.U.I.D.E-style addons), may need catalogue-level semantic actions instead.
- The token-in-file scheme assumes a single user. Like godot-ai, it does not protect against a compromised same-user process.
- The godot-rl and godot-ai-playtest version support for 4.7 is unstated. GodotE2E's latest release line is inferred from its compatibility table.
- CONFLICT DETECTED: GdUnit4 injects through both `Input.parse_input_event` and `Viewport.push_input`, while the Godot docs present each as a standalone route. Whether this double-delivers to `_input` is unverified, so the bridge should use one route (`parse_input_event`).

## Sources

- TCPServer 4.7 (`listen` default `"*"`): https://docs.godotengine.org/en/4.7/classes/class_tcpserver.html
- StreamPeerTCP 4.7 (`bind`, `set_no_delay`): https://docs.godotengine.org/en/4.7/classes/class_streampeertcp.html
- StreamPeer 4.7 (`put_utf8_string` framing, `big_endian`): https://docs.godotengine.org/en/4.7/classes/class_streampeer.html
- WebSocketPeer 4.7 (`accept_stream`, buffer sizes): https://docs.godotengine.org/en/4.7/classes/class_websocketpeer.html
- Command line 4.7 (`--headless`, `--fixed-fps`, `--write-movie`, `--remote-debug`, `--accessibility`): https://docs.godotengine.org/en/4.7/tutorials/editor/command_line_tutorial.html
- Engine 4.7: https://docs.godotengine.org/en/4.7/classes/class_engine.html
- main.cpp @4.7-stable (fixed fps, physics clamp, time_scale): https://raw.githubusercontent.com/godotengine/godot/4.7-stable/main/main.cpp
- main_timer_sync.cpp @4.7-stable: https://raw.githubusercontent.com/godotengine/godot/4.7-stable/main/main_timer_sync.cpp
- Dummy texture storage @4.7-stable: https://raw.githubusercontent.com/godotengine/godot/4.7-stable/servers/rendering/dummy/storage/texture_storage.h
- Creating movies 4.7: https://docs.godotengine.org/en/4.7/tutorials/animation/creating_movies.html
- Pausing games 4.7: https://docs.godotengine.org/en/4.7/tutorials/scripting/pausing_games.html
- SceneTree 4.7 (`create_timer` defaults, signals): https://docs.godotengine.org/en/4.7/classes/class_scenetree.html
- Tween 4.7 (pause modes): https://docs.godotengine.org/en/4.7/classes/class_tween.html
- PR #76462 `space_step` (open): https://github.com/godotengine/godot/pull/76462
- Random number generation 4.7: https://docs.godotengine.org/en/4.7/tutorials/math/random_number_generation.html
- Using Jolt Physics 4.7: https://docs.godotengine.org/en/4.7/tutorials/physics/using_jolt_physics.html
- Jolt determinism: https://jrouwe.github.io/JoltPhysics/
- Input 4.7: https://docs.godotengine.org/en/4.7/classes/class_input.html
- InputEvent 4.7 (device IDs): https://docs.godotengine.org/en/4.7/classes/class_inputevent.html
- Using InputEvent 4.7 (propagation order, InputEventAction): https://docs.godotengine.org/en/4.7/tutorials/inputs/inputevent.html
- Viewport 4.7 (`push_input`, `get_texture` note, focus and hover): https://docs.godotengine.org/en/4.7/classes/class_viewport.html
- Control 4.7 (`accessibility_*`): https://docs.godotengine.org/en/4.7/classes/class_control.html
- DisplayServer 4.7 (accessibility setters only): https://docs.godotengine.org/en/4.7/classes/class_displayserver.html
- OS 4.7 (stdin, user args, `has_feature`): https://docs.godotengine.org/en/4.7/classes/class_os.html
- ProjectSettings 4.7 (flush_stdout defaults): https://docs.godotengine.org/en/4.7/classes/class_projectsettings.html
- EngineDebugger 4.7: https://docs.godotengine.org/en/4.7/classes/class_enginedebugger.html
- Feature tags 4.7: https://docs.godotengine.org/en/4.7/tutorials/export/feature_tags.html
- Godot 4.7 release notes: https://godotengine.org/releases/4.7/
- Godot 4.5 release (AccessKit): https://godotengine.org/releases/4.5/
- Godot 4.6 release (Jolt default): https://godotengine.org/releases/4.6/
- Godot RL Agents: https://github.com/edbeeching/godot_rl_agents ; plugin: https://github.com/edbeeching/godot_rl_agents_plugin ; sync.gd: https://raw.githubusercontent.com/edbeeching/godot_rl_agents_plugin/main/addons/godot_rl_agents/sync.gd ; PyPI: https://pypi.org/project/godot-rl/
- GdUnit4 scene runner docs: https://godot-gdunit-labs.github.io/gdUnit4/latest/advanced_testing/sceneRunner/ ; source: https://raw.githubusercontent.com/godot-gdunit-labs/gdUnit4/master/addons/gdUnit4/src/core/GdUnitSceneRunnerImpl.gd
- GUT input: https://gut.readthedocs.io/en/latest/Mocking-Input.html ; https://gut.readthedocs.io/en/latest/class_ref/class_gutinputsender.html
- GodotE2E: https://github.com/RandallLiuXin/godot-e2e ; https://godotengine.org/asset-library/asset/edit/22125
- godot-ai-playtest: https://pypi.org/project/godot-ai-playtest/
- godot-mcp-runtime: https://github.com/Erodenn/godot-mcp-runtime
- godot-ai: https://github.com/hi-godot/godot-ai
- GodotTestDriver: https://github.com/chickensoft-games/GodotTestDriver
- PlayGodot (secondary listing only, UNVERIFIED): https://smithery.ai/skills/Randroids-Dojo/godot
- Local context:
  - docs/plan.md (A3 bridge, T1 bot)
  - docs/research/09-web-godot-mcp-tooling.md
  - docs/research/21-shader-verification.md (Xvfb, Movie Maker)
  - docs/research/32-game-feel-playtesting.md
