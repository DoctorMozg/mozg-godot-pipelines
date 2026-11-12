# Input, save/load and player settings (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.3–4.7), the 4.5–4.7 release notes, Godot source at 4.7-stable, Godot PRs, an oss-security disclosure and Steamworks docs. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

- **Input.** Godot 4.7 sends each event through `_input`, then the GUI, then `_shortcut_input`, `_unhandled_key_input`, `_unhandled_input`, and finally physics picking. Gameplay belongs in `_unhandled_input` or in polling, so the GUI can consume events first.
- **Gamepads.** Since 4.5, desktop gamepads go through SDL3. 4.7 adds iOS to SDL3, motion sensors, and a setting that ignores joypads while the window is unfocused.
- **Save safety.** Loading untrusted `.tres`/`.res`, a ConfigFile, `str_to_var`, or `get_var(true)` can run code. The engine fix for text deserialization (PR #80585) was closed unmerged on 2026-07-06. Saves should be plain data: JSON, or `store_var` with objects off.
- **Atomic writes.** At runtime, `FileAccess` writes are not atomic, because `backup_save` defaults to `false`. Games must write to a temp file and rename it themselves.
- **Open CVE-class bug.** On 2026-10-26 a `.po` code-execution bug was disclosed for 4.1.0–4.7.2. It is unpatched.

## 1. InputMap and actions

- **Where actions live.** Actions are defined in Project Settings > Input Map. The docs recommend `snake_case` names (https://docs.godotengine.org/en/stable/tutorials/inputs/input_examples.html, 4.7).
- **Runtime API.** `InputMap` provides `add_action(action, deadzone=0.2)`, `action_add_event`, `action_erase_events`, `action_set_deadzone`, and `load_from_project_settings()`, which resets to the project defaults (https://docs.godotengine.org/en/stable/classes/class_inputmap.html, 4.7). Runtime changes are not persisted; the game must save them itself.
- **Deadzones.** CONFLICT DETECTED: the gamepad tutorial says "the default value is 0.5" for Input Map actions (https://docs.godotengine.org/en/stable/tutorials/inputs/controllers_gamepads_joysticks.html, 4.7). The `InputMap.add_action` signature defaults to 0.2 (class_inputmap, 4.7). Most likely the editor uses 0.5 and the script API uses 0.2, so code should always pass the deadzone explicitly.
- **Two-axis input.** Use `Input.get_vector()`, which "handles deadzone in a correct way for most use cases". Use `get_axis()` for one axis and `get_action_strength()` for triggers (controllers doc, 4.7).
- **`exact_match`.** With `false`, extra modifiers and the joypad motion direction are ignored (class_input, 4.7).

## 2. Callbacks, propagation and GUI consumption

The order in 4.7 (https://docs.godotengine.org/en/stable/tutorials/inputs/inputevent.html):

1. Embedded-window management, then the focused embedded Window.
1. `_input()`.
1. GUI: `_gui_input` / `gui_input`. A Control consumes the event with `accept_event()`.
1. `_shortcut_input()`, for keys, shortcuts and joypad buttons only.
1. `_unhandled_key_input()`.
1. `_unhandled_input()`.
1. Physics picking, which calls `_input_event`.

Other rules from the same page:

- `get_viewport().set_input_as_handled()` stops propagation.
- GUI mouse events bubble to ancestors according to `mouse_filter`. GUI key and joypad events do not bubble.
- Polling (`Input.is_action_pressed`) suits continuous actions. Events suit discrete ones (input_examples, 4.7).

```gdscript
func _unhandled_input(event: InputEvent) -> void:
    if event.is_action_pressed("jump"):
        _buffer_jump()
        get_viewport().set_input_as_handled()

func _physics_process(_delta: float) -> void:
    var move := Input.get_vector("move_left", "move_right", "move_up", "move_down")
```

Since 4.5, `Input.is_action_just_pressed_by_event(action, event)` tells you whether *this* event triggered the press. Use it inside `_input` (absent from the 4.4 docs, present in 4.5: https://docs.godotengine.org/en/4.5/classes/class_input.html).

**Input buffering.** Godot has no built-in action buffer, so store a timestamp when the event arrives and consume it within a window (UNVERIFIED that no official helper exists; none was found in the class reference). A related setting, `agile_event_flushing`, flushes buffered events before every idle and physics frame and is off by default. Its original 2021 post said only Android buffered input then, and the setting path was later renamed (https://godotengine.org/article/agile-input-processing-is-here-for-smoother-gameplay). The current setting path is UNVERIFIED.

## 3. Gamepads

**SDL3 driver.** Since 4.5, SDL3 handles controllers on Windows, macOS and Linux. Android and Web keep Godot's own code (controllers doc, 4.7). 4.7 moved iOS to SDL3 (https://godotengine.org/releases/4.7/). The SDL bundled at the `4.7-stable` tag is 3.2.28 (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/thirdparty/README.md). UNVERIFIED that 4.7.2 ships the same version.

**Mappings.**

- `Input.add_joy_mapping` takes SDL-format strings, and `remove_joy_mapping` removes them (class_input, 4.7).
- To test a mapping, set the `SDL_GAMECONTROLLERCONFIG` environment variable before launch (controllers doc).
- `get_joy_guid` returns `__XINPUT_DEVICE__` for XInput devices on Windows. `get_joy_info()` is always empty on Android and Web (class_input, 4.7).
- The controllers doc says Windows is limited to 4 controllers via XInput. That may predate SDL3; UNVERIFIED for 4.7.

**Hot-plugging.** Connect to the `Input.joy_connection_changed(device, connected)` signal. Do not assume device order: `get_connected_joypads()` ordering is not stable across restarts (class_input, 4.7). On Linux, hot-plugging needs udev; without it you must poll (controllers doc).

**Button prompts.**

- Pick a prompt set from `get_joy_name()` and `get_joy_info()` vendor_id/product_id (class_input). There is no built-in glyph API.
- Generic pads report "USB Gamepad" (controllers doc).

**Steam Input.**

- Steam injects a virtual Xbox controller, so "the controller will show up in your game as an Xbox controller". PlayStation touchpad click and Options both collapse to Start (https://partner.steamgames.com/doc/features/steam_controller/steam_input_gamepad_emulation_bestpractices).
- To get the true device type and Steam glyphs, query `GetInputTypeForHandle` and `GetGlyphForActionOrigin` through the Steamworks API, for example via GodotSteam (same page).
- UNVERIFIED: how the SDL3 driver's own device detection interacts with Steam's virtual pad.

**Other.**

- Since 4.7, `input_devices/joypads/ignore_joypad_on_unfocused_application` ignores pads while unfocused; it is off by default (releases/4.7; controllers doc). Before that, pads fed unfocused windows.
- Provide a vibration-intensity slider (controllers doc).

## 4. Keyboard, mouse and touch

- **Key fields.** Use `physical_keycode` for game controls such as WASD, `keycode` for shortcuts, and `key_label` for on-screen prompts (https://docs.godotengine.org/en/stable/classes/class_inputeventkey.html, 4.7). To display a physical key, use `DisplayServer.keyboard_get_label_from_physical()`.
- **Emulation.** `Input.emulate_mouse_from_touch` and `emulate_touch_from_mouse` turn one pointer type into the other (class_input). UNVERIFIED: the project defaults.
- **Freehand input.** Set `use_accumulated_input = false` for precise freehand input (class_input).
- **4.7 additions** (releases/4.7):
  - a `VirtualJoystick` node;
  - device IDs on keyboard and mouse events (telling apart devices of the same type is not supported yet);
  - initial touch on Wayland.

## 5. Rebinding UI and persisting bindings

Do not save `InputEvent` objects with `ConfigFile.set_value` or `var_to_str`. They serialize as Objects, which is the same unsafe path as section 7. Save plain dictionaries and rebuild the events.

```gdscript
static func event_to_dict(e: InputEvent) -> Dictionary:
    if e is InputEventKey: return {"t": "key", "code": e.physical_keycode}
    if e is InputEventJoypadButton: return {"t": "jb", "code": e.button_index}
    if e is InputEventJoypadMotion: return {"t": "ja", "code": e.axis, "dir": signf(e.axis_value)}
    if e is InputEventMouseButton: return {"t": "mb", "code": e.button_index}
    return {}

func apply_bindings(saved: Dictionary) -> void:
    InputMap.load_from_project_settings()  # defaults first, so new actions keep their bindings
    for action: String in saved:
        if not InputMap.has_action(action): continue  # ignore stale or injected names
        InputMap.action_erase_events(action)
        for d: Dictionary in saved[action]:
            InputMap.action_add_event(action, dict_to_event(d))
```

The listen-for-key screen should:

- capture in `_input`;
- call `set_input_as_handled()`;
- ignore joypad motion below the deadzone;
- detect and resolve conflicts.

## 6. Save formats and trade-offs

| Format          | API                                         | Pros                                                                                                                                 | Cons                                                                                                                                                                                                                                                                     |
| --------------- | ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| JSON            | `JSON.stringify` / `JSON.parse`             | Readable and diffable. The official tutorial uses it.                                                                                | Limited types: no Vector2, Color, etc. All numbers become float. INF and NAN are lossy. `JSON.from_native`/`to_native` (4.4+) round-trip engine types and ignore objects unless `allow_objects` is set (https://docs.godotengine.org/en/stable/classes/class_json.html). |
| ConfigFile      | `ConfigFile.save`/`load`, `*_encrypted*`    | Recommended for user configuration (https://docs.godotengine.org/en/stable/tutorials/io/saving_games.html).                          | Its text parser can build Objects. The docs carry no warning (class_configfile 4.7). Treat a file from outside as unsafe (section 7).                                                                                                                                    |
| Binary Variant  | `store_var`/`get_var(allow_objects=false)`  | Compact and typed. Objects are off by default.                                                                                       | Opaque. `get_var(true)` warns "can contain code which gets executed" (https://docs.godotengine.org/en/stable/classes/class_fileaccess.html).                                                                                                                             |
| Custom Resource | `ResourceSaver.save`, `ResourceLoader.load` | Typed and editor-friendly. `FLAG_COMPRESS` is binary-only (https://docs.godotengine.org/en/stable/classes/class_resourcesaver.html). | Can embed a GDScript and run code on load. Has a cache (`CACHE_MODE_IGNORE` needed to reload). The ResourceLoader docs carry no warning (class_resourceloader 4.7).                                                                                                      |

**Encryption.**

- `FileAccess.open_encrypted` needs a 32-byte key (class_fileaccess).
- Encryption deters casual editing only, because the key ships in the binary. This is an inference, not a documented claim.

**Node trees vs data models.**

- The official tutorial saves a "Persist" group by calling each node's `save()` and recreating it from `load(node_data["filename"])` (saving_games, 4.7). Loading a path taken from the save file is itself an injection point.
- Prefer a plain data model (dictionaries of ids and fields), validated against an allowlist of scene ids.

## 7. Security of untrusted saves

- **Resources.** `.tres`/`.res` from untrusted sources can embed a GDScript that runs on load. The community fix, godot-safe-resource-loader, rejects embedded GDScript and non-`res://` external resources. It is blocklist-based, and the author says "some clever person might find a way of circumventing it" (https://github.com/derkork/godot-safe-resource-loader).
- **ConfigFile and `str_to_var`.** Text deserialization creates objects. Issue #80562 tracked this, and PR #80585 would have added an `allow_objects` flag. That PR was closed unmerged on 2026-07-06: reduz called it "a false sense of security", and the author said the approach is not "a sufficient security measure" (https://github.com/godotengine/godot/pull/80585). So in 4.7.2, `ConfigFile.load` and `str_to_var` remain unsafe on untrusted input.
- **Binary.** `bytes_to_var` and `get_var()` with the default `false` do not decode objects. `bytes_to_var_with_objects` carries a remote-code-execution warning (https://docs.godotengine.org/en/stable/classes/class_@globalscope.html, 4.7).
- **`.po` translations.** A crafted Plural-Forms header in a `.po` file runs code in 4.1.0–4.7.2. It was unpatched as of 2026-10-26; PRs #123130 and #123857 were not merged then (https://openwall.com/lists/oss-security/2026/10/26/19). This matters for mods and for user-supplied translations.
- **Safe path.** Read JSON or `get_var(false)`, then validate the schema (types, ranges, allowlisted ids) before building any nodes. "Untrusted" covers shared saves, mods, cloud downloads and anything under `user://`.

## 8. Versioning, atomic writes, paths, cloud, slots

**Versioning.** Put a `"version": int` at the top of every save. Migrate step by step (`while v < CURRENT: data = MIGRATIONS[v].call(data); v += 1`), and keep a fixture of each old version in the tests. This is general practice, not a Godot doc.

**Atomic writes.**

- In the runtime engine, `FileAccess::backup_save` is `static inline bool backup_save = false` (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/core/io/file_access.h).
- When it is enabled, a Unix `WRITE` goes to `mkstemp` `<path>-XXXXXX` and is renamed on close (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/drivers/unix/file_access_unix.cpp).
- The editor registers `filesystem/on_save/safe_save_on_backup_then_rename = true` (https://raw.githubusercontent.com/godotengine/godot/4.7-stable/editor/settings/editor_settings.cpp). UNVERIFIED: the call site that applies it, and whether exported games ever enable it.
- `FileAccess.flush()` exists. A process killed before `close()` loses the buffer (class_fileaccess).

Do the safe write yourself:

```gdscript
static func write_atomic(path: String, text: String) -> Error:
    var tmp := path + ".tmp"
    var f := FileAccess.open(tmp, FileAccess.WRITE)
    if f == null: return FileAccess.get_open_error()
    if not f.store_string(text): return ERR_FILE_CANT_WRITE  # store_* return bool since 4.4
    f.close()
    if FileAccess.file_exists(path):
        DirAccess.rename_absolute(path, path + ".bak")  # loader falls back to .bak
    return DirAccess.rename_absolute(tmp, path)
```

UNVERIFIED: whether `DirAccess.rename` overwrites an existing target on Windows. The code above avoids depending on it. On load, try the main file, then `.bak`, and validate both.

**`user://` locations** (https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html, 4.7):

| Platform | Default                                                      | With `application/config/use_custom_user_dir` |
| -------- | ------------------------------------------------------------ | --------------------------------------------- |
| Windows  | `%APPDATA%\Godot\app_userdata\[project]`                     | `%APPDATA%\[name]`                            |
| macOS    | `~/Library/Application Support/Godot/app_userdata/[project]` | `~/Library/Application Support/[name]`        |
| Linux    | `~/.local/share/godot/app_userdata/[project]`                | `~/.local/share/[name]`                       |
| Mobile   | App-private                                                  | —                                             |
| Web      | IndexedDB virtual filesystem                                 | —                                             |

The custom name comes from `custom_user_dir_name`, which may contain `/`.

**Steam Cloud.**

- Auto-Cloud roots include `WinAppDataRoaming`, `MacAppSupport` and `LinuxXdgDataHome`. Keep `[Cross-Platform]` and use root overrides (https://partner.steamgames.com/doc/features/cloud).
- A custom user dir gives a stable path that the cloud configuration can point to. This is an inference from the two docs above.
- Valve advises keeping files small and split by how often they change, and to "avoid machine-specific configurations such as video settings". Keep the video config out of the cloud path.

**Slots and autosave.**

- Use one file per slot plus a small index or metadata file (name, time, version, thumbnail path).
- Rotate autosaves (`autosave_0..N`).
- Never autosave over the manual slot. This is general practice.

## 9. Player settings

**Applying at runtime** (DisplayServer enums from https://docs.godotengine.org/en/stable/classes/class_displayserver.html, 4.7):

```gdscript
func apply_video(s: Dictionary) -> void:
    get_window().mode = s.window_mode  # WINDOWED / FULLSCREEN / EXCLUSIVE_FULLSCREEN
    DisplayServer.window_set_vsync_mode(s.vsync)  # VSYNC_DISABLED/ENABLED/ADAPTIVE/MAILBOX
    get_viewport().scaling_3d_mode = s.scaler  # BILINEAR, FSR, FSR2, METALFX_*, NEAREST(4.7)
    get_viewport().scaling_3d_scale = s.render_scale
    AudioServer.set_bus_volume_linear(AudioServer.get_bus_index("Music"), s.music)  # 4.4+
```

**Window modes.**

- `EXCLUSIVE_FULLSCREEN` bypasses the compositor on X11.
- On Wayland it equals `FULLSCREEN`.
- On Windows the screen may go black for a moment during the switch.
- `FULLSCREEN` on macOS opens a new desktop.

**V-Sync.** Changing V-Sync needs `FEATURE_SWAP_BUFFERS`, available on Windows, macOS and Linux (class_displayserver).

**Scaling** (https://docs.godotengine.org/en/stable/tutorials/3d/resolution_scaling.html and https://docs.godotengine.org/en/stable/classes/class_viewport.html, 4.7):

- FSR 1.0 and FSR 2.2 are Forward+ only. FSR 2.2 arrived in 4.2 and replaces TAA.
- Compatibility mode allows bilinear only. MetalFX needs the Metal driver.
- FSR sharpness defaults to 0.2.

**Persisting settings.**

- Use a separate `user://settings.cfg`, written atomically, with a `version` key.
- Apply settings at startup before the first frame, and validate each value against the enum or range.
- Platform defaults: use `OS.has_feature("mobile")`, `"web"`, or `"steamdeck"` to choose them. UNVERIFIED: whether a "steamdeck" feature tag exists, so check `OS.get_name()` plus the screen size instead.
- Vibration and accessibility options belong in settings (controllers doc).

## Version-specific features

| Feature                                                                       | Version                                | Source                                                                                                                      |
| ----------------------------------------------------------------------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| FSR 2.2 scaling                                                               | 4.2                                    | resolution_scaling doc                                                                                                      |
| MetalFX spatial/temporal scaling                                              | ≤4.4 (in 4.4 docs; arrival UNVERIFIED) | https://docs.godotengine.org/en/4.4/classes/class_viewport.html                                                             |
| `JSON.from_native`/`to_native`                                                | 4.4 (absent in 4.3 docs)               | en/4.3 vs en/4.4 class_json                                                                                                 |
| `AudioServer.set_bus_volume_linear`                                           | 4.4 (absent in 4.3 docs)               | en/4.3 vs en/4.4 class_audioserver                                                                                          |
| `FileAccess.create_temp`; `store_*` return bool                               | 4.4                                    | https://docs.godotengine.org/en/4.4/classes/class_fileaccess.html                                                           |
| SDL3 joypad driver (Win/macOS/Linux)                                          | 4.5                                    | https://godotengine.org/releases/4.5/                                                                                       |
| `Input.is_action_just_pressed_by_event`                                       | 4.5 (absent in 4.4 docs)               | en/4.4 vs en/4.5 class_input                                                                                                |
| Joypad LED `set_joy_light`/`has_joy_light`                                    | 4.6 (GH-111681)                        | https://docs.godotengine.org/en/4.6/classes/class_input.html, https://godotengine.org/article/dev-snapshot-godot-4-6-dev-4/ |
| Mouse/touch focus split from keyboard/joypad focus                            | 4.6 (GH-110250)                        | https://godotengine.org/article/dev-snapshot-godot-4-6-dev-1/                                                               |
| Joypad motion sensors (gyro/accel, experimental)                              | 4.7 (GH-111679)                        | releases/4.7, class_input 4.7                                                                                               |
| `ignore_joypad_on_unfocused_application`                                      | 4.7                                    | releases/4.7                                                                                                                |
| `VirtualJoystick` node; keyboard/mouse device IDs; SDL3 on iOS; Wayland touch | 4.7                                    | releases/4.7                                                                                                                |
| `SCALING_3D_MODE_NEAREST`                                                     | 4.7 (absent in 4.6 docs)               | en/4.6 vs stable class_viewport                                                                                             |
| HDR output                                                                    | 4.7                                    | releases/4.7                                                                                                                |
| `.po` Plural-Forms code-execution bug                                         | 4.1.0–4.7.2, unpatched 2026-10-26      | openwall oss-security 2026/10/26/19                                                                                         |

## Checkable rules an agent should follow

1. Every action used in `Input.*`/`is_action*("x")` calls exists in `project.godot` `[input]`, or is created through `InputMap.add_action`.
1. Action names are `snake_case`.
1. Gameplay handlers use `_unhandled_input`. `_input` is only for capture or filtering, and calls `set_input_as_handled()`.
1. Two-axis movement uses `Input.get_vector`, not four `is_action_pressed` checks.
1. Movement bindings on `InputEventKey` use `physical_keycode`, not `keycode`.
1. Prompts read `key_label` or `keyboard_get_label_from_physical`, never a hardcoded "W".
1. `InputMap.add_action` calls pass an explicit deadzone.
1. Code subscribes to `Input.joy_connection_changed` when it reads a joypad device id.
1. No literal joypad device index is stored; ids come from `get_connected_joypads()`.
1. Bindings are persisted as plain dictionaries. No `InputEvent` passes into `ConfigFile.set_value`, `var_to_str` or `store_var(_, true)`.
1. Loaded bindings are filtered through `InputMap.has_action`, after `load_from_project_settings()`.
1. No `ResourceLoader.load`/`load()` takes a `user://` path or a path read from a save file.
1. No `get_var(true)`, `bytes_to_var_with_objects`, or `JSON.to_native(_, true)` runs on save data.
1. No `str_to_var` or `ConfigFile.load` runs on files that come from outside the game (shared saves, mods, downloads).
1. Every save and settings file carries an integer `version` field and a migration path.
1. Saves are written to a temp file and renamed. There is a `.bak` fallback.
1. `FileAccess.open` results are null-checked with `get_open_error()`, and `store_*` bool results are checked (4.4+).
1. Save paths start with `user://`, never `res://`.
1. Video settings live in a separate file from cloud-synced saves.
1. Settings are clamped and validated on load before they are applied.
1. FSR modes are offered only when the renderer is Forward+, and MetalFX only on Metal.
1. Fullscreen uses `Window.mode`/`DisplayServer.window_set_mode`, never a resized borderless window hack.
1. A vibration-strength setting exists when `start_joy_vibration` is used.
1. Projects that ship `.po` files from untrusted sources are flagged as vulnerable on 4.1–4.7.2.

## What a tool could check automatically

- **InputMap lint.** Parse `project.godot` `[input]`. Report:
  - unused actions, and actions referenced in `*.gd` string literals but missing from the map;
  - non-snake_case names;
  - key events with `keycode` set and `physical_keycode` = 0;
  - duplicate events across actions;
  - deadzone values outside 0.05–0.9 (a heuristic threshold).
- **Unsafe deserialization grep.** Flag these unless a path allowlist applies: `ResourceLoader.load(`/`load(` whose argument contains `user://` or a variable; `get_var(true`; `bytes_to_var_with_objects`; `to_native(` with `true`; `str_to_var(`; and `ConfigFile` plus `load(` on paths outside `res://`.
- **Save round-trip probe.** A headless Godot script, run against a scratch worktree, that:
  1. builds a sample state and calls the game's `save()`;
  1. loads it back and deep-compares the two;
  1. runs the load against a truncated file and against a file with `version` = current-1;
  1. prints one explicit summary line, which is the pass/fail signal, not the exit code.
- **Malicious fixture probe.** Feed the game's loader a `.tres` with an embedded GDScript whose `_init` prints a marker, and a ConfigFile containing an `Object(...)` with a script. Fail if the marker appears in the log.
- **Atomic write probe.** Kill the process mid-save and check that the main file or `.bak` still parses. On Linux, a static check can verify that the save code uses a `.tmp` file plus `rename`.
- **Settings persistence probe.** Run 1 sets non-default values (window mode, vsync, volume, a rebinding) and quits. Run 2 prints the applied `DisplayServer.window_get_mode`, `window_get_vsync_mode`, `AudioServer.get_bus_volume_linear` and `InputMap.action_get_events`. The probe diffs the two runs. Headless returns dummy display values, so the display part needs Xvfb (an optional tool).
- **Version gate.** Read `config/features` in `project.godot`. Flag 4.4+ or 4.5+ APIs (the table above) when the project targets an older version, and flag `.po` resources on 4.1–4.7.2.
- **Cloud hygiene.** Check that `use_custom_user_dir` is set and `custom_user_dir_name` is non-empty for shipping builds, so the Steam Cloud root is stable.

## Pitfalls

- **Default deadzone.** The tutorial (0.5) and `add_action` (0.2) disagree. Pass it explicitly.
- **Polling in `_physics_process`.** `is_action_just_pressed` there can miss or duplicate presses relative to frames. Buffer from events instead (inferred from the class_input "frame or tick" note). Keyboard ghosting can drop keys (input_examples).
- **GUI blocking.** A full-screen Control with `mouse_filter = STOP` silently eats clicks meant for `_unhandled_input`.
- **XInput GUID.** On Windows it reads `__XINPUT_DEVICE__`, so the GUID alone cannot pick a prompt set.
- **Steam Input.** It turns every pad into an Xbox pad, so device-based prompts are wrong unless you query the Steam API.
- **Unfocused input.** Before 4.7, gamepad input reaches unfocused windows.
- **JSON numbers.** Ints come back as floats, so cast them on load. Loading a `Vector2` from JSON needs `from_native` (4.4+) or manual fields.
- **Resource cache.** `ResourceLoader` caching returns stale data on reload unless `CACHE_MODE_IGNORE` is used.
- **Exported text resources.** With `convert_text_resources_to_binary`, runtime `load()` of a `.tres` packed in the PCK can fail (class_resourceloader).
- **F8 / process kill.** It skips `close()`, so unflushed writes are lost (class_fileaccess).
- **Web.** `user://` lives in IndexedDB and browsers can clear it.
- **Headless.** DisplayServer returns dummy values, so settings probes need a display.
- **Unsafe "safe" loaders.** Scanning keywords in ConfigFile or `.tres` text is not a defence; a forum test reported that `_init` runs before any post-load scan (https://forum.godotengine.org/t/does-this-configfile-scanner-prevent-arbitrary-code-execution/142353).

## Risks and uncertainties

- Version arrivals were inferred by diffing per-version class reference pages, not from changelogs. The MetalFX arrival version is UNVERIFIED.
- UNVERIFIED: the SDL version in 4.7.2 specifically (only the `4.7-stable` tag was read), and the 4-controller Windows limit under SDL3.
- UNVERIFIED: whether the editor setting `safe_save_on_backup_then_rename` ever applies to exported games, and Windows `DirAccess.rename` overwrite semantics.
- The `.po` disclosure is from oss-security, a third party. Patch status after 2026-10-26 should be rechecked.
- Steam Input and SDL3 interaction was not tested.

## Sources

- **Godot 4.7 docs:**
  - inputevent: https://docs.godotengine.org/en/stable/tutorials/inputs/inputevent.html
  - input_examples: https://docs.godotengine.org/en/stable/tutorials/inputs/input_examples.html
  - controllers_gamepads_joysticks: https://docs.godotengine.org/en/stable/tutorials/inputs/controllers_gamepads_joysticks.html
  - saving_games: https://docs.godotengine.org/en/stable/tutorials/io/saving_games.html
  - data_paths: https://docs.godotengine.org/en/stable/tutorials/io/data_paths.html
  - resolution_scaling: https://docs.godotengine.org/en/stable/tutorials/3d/resolution_scaling.html
  - class references: https://docs.godotengine.org/en/stable/classes/ (Input, InputMap, InputEventKey, FileAccess, JSON, ConfigFile, ResourceLoader, ResourceSaver, @GlobalScope, DisplayServer, Viewport, AudioServer)
- **Per-version class references** for dating: https://docs.godotengine.org/en/4.3/, https://docs.godotengine.org/en/4.4/, https://docs.godotengine.org/en/4.5/, https://docs.godotengine.org/en/4.6/
- **Release pages:**
  - https://godotengine.org/releases/4.5/
  - https://godotengine.org/releases/4.7/
  - https://godotengine.org/article/dev-snapshot-godot-4-6-dev-1/
  - https://godotengine.org/article/dev-snapshot-godot-4-6-dev-4/
  - https://godotengine.org/article/dev-snapshot-godot-4-7-dev-1/
  - https://godotengine.org/article/agile-input-processing-is-here-for-smoother-gameplay
- **Godot source at the 4.7-stable tag:** core/io/file_access.h, drivers/unix/file_access_unix.cpp, editor/settings/editor_settings.cpp, thirdparty/README.md
- **Godot PR:** https://github.com/godotengine/godot/pull/80585 (closed 2026-07-06)
- **Security disclosure:** https://openwall.com/lists/oss-security/2026/10/26/19
- **Community loader:** https://github.com/derkork/godot-safe-resource-loader
- **Forum test of a keyword scanner:** https://forum.godotengine.org/t/does-this-configfile-scanner-prevent-arbitrary-code-execution/142353 (forum thread; cited only for the reported `_init` timing in Pitfalls)
- **Steamworks:**
  - https://partner.steamgames.com/doc/features/steam_controller/steam_input_gamepad_emulation_bestpractices
  - https://partner.steamgames.com/doc/features/cloud
