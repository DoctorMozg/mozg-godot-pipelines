# Game feel, onboarding, accessibility and playtesting (Godot 4.7)

Source: web research of 2026-11-13 against the Godot 4.7 docs, Game Accessibility Guidelines, Xbox Accessibility Guidelines 3.2, GDC Vault overviews and Steam docs. GDScript examples and the headless probes are UNTESTED on 4.7.2.

Research date: 2026-11-13. "Accessed" means the page was fetched on that date. GAG = Game Accessibility Guidelines; XAG = Xbox Accessibility Guidelines.

## Executive summary

- **Juice must be optional and tunable.** Screen shake, hit stop and squash-and-stretch make a game more satisfying, but XAG 117 asks that camera shake, bobbing and blur be avoided or that players can turn them off.
- **Hit stop through `Engine.time_scale` has three side effects.** It slows every timer and every delta-driven tween, it does not slow audio, and it does not change the physics tick rate. Restore code and UI tweens must ignore the time scale.
- **Accessibility has concrete numbers to follow.** GAG gives the basic tier (remapping, subtitles, readable default text size, separate volume sliders, settings that persist). XAG adds measurable values: text of at least 18 px at 1080p on PC and 26 px on console, scalable to 200%; subtitle lines of at most 40 characters and at most 2 lines; flashes no faster than about 3 per second over about 20% of the screen.
- **Playtesting needs two kinds of evidence.** Observation (think-aloud, blind tests) shows why players struggle. Telemetry (funnels, death and quit points) shows where and how often. In Godot, telemetry must be opt-in, use a random ID per install rather than `OS.get_unique_id()`, and be checked against a schema.
- **Much of this can be checked by a CLI kit.** It can grep `project.godot` and the settings scripts, run the game headless with injected input, and validate telemetry JSON.

## 1. Game feel and juice

**Definitions**

- Swink defines game feel as "real-time control of virtual objects in a simulated space, with interactions emphasised by polish". Source: *Game Feel*, Morgan Kaufmann/CRC. Sources disagree on the year: CONFLICT DETECTED: Wikipedia says 2008, eolt.org says 2009 (https://en.wikipedia.org/wiki/Game_feel, accessed 2026-11-13).
- Jonasson and Purho, "Juice It or Lose It", GDC Europe 2012, call juice "maximum output for minimum input" (https://gdcvault.com/play/1016487/Juice-It-or-Lose). The quote comes from Game Developer's 2013 write-up, not from the talk itself.
- Camera smoothing, framing and shake math: Eiserloh, "Math for Game Programmers: Juicing Your Cameras With Math", GDC 2016 (https://gdcvault.com/play/1023146/Math-for-Game-Programmers-Juicing).
- UNVERIFIED: the "trauma" model (shake strength = trauma², trauma decays linearly, offsets driven by noise rather than random jumps) is commonly credited to this talk. The Vault page is members-only, so it could not be confirmed.

**When juice hurts**

- Folmer Kelly, "Don't Juice It or Lose It", GDC Europe 2014: polish that ignores context breaks immersion. His examples are dust where no dust should be and bouncy tweens on hard surfaces (https://gdcvault.com/play/1020861/Don-t-Juice-It-or).
- XAG 117 says to "Avoid the use of camera shake, camera bobbing effects, motion blur… or provide an option to turn off these behaviors". It cites Halo Infinite's 0–100% sliders as the example to follow (https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/117, updated 2026-06-17).
- XAG 118 rules out flashes faster than about 3 per second that cover about 20% or more of the screen, and saturated red flashes. It prefers removing such content over showing a warning screen (https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/118, updated 2026-06-17).
- Muzzle flashes, hit flashes and white-screen effects are therefore accessibility hazards as well as style choices.

**Godot implementation notes (4.7 docs)**

- **`Engine.time_scale`** affects `Timer`, `SceneTreeTimer`, `_process` and `_physics_process`. Three caveats from the docs:

  - "keep this property above 0.0".
  - "This does not affect audio playback speed", so use `AudioServer.playback_speed_scale` for audio.
  - It "does not automatically adjust physics_ticks_per_second".

  Source: https://docs.godotengine.org/en/stable/classes/class_engine.html

- **Restoring after hit stop** needs a timer that runs in real time: `SceneTree.create_timer(time_sec, process_always=true, process_in_physics=false, ignore_time_scale=false)`. Pass `ignore_time_scale=true` (https://docs.godotengine.org/en/stable/classes/class_scenetree.html).

- **Tweens**

  - `Tween.set_ignore_time_scale(true)` keeps UI and pause-menu tweens running at real speed.
  - Tweens are "not designed to be reused", so create a new one for each animation.
  - Available curves: TRANS_LINEAR, TRANS_SINE, TRANS_QUAD, TRANS_CUBIC, TRANS_QUART, TRANS_QUINT, TRANS_EXPO, TRANS_CIRC, TRANS_ELASTIC, TRANS_BACK, TRANS_BOUNCE, TRANS_SPRING. Ease modes: EASE_IN, EASE_OUT, EASE_IN_OUT, EASE_OUT_IN.

  Source: https://docs.godotengine.org/en/stable/classes/class_tween.html

- **Physics interpolation** (Project Settings > Physics > Common > Physics Interpolation) removes stepping when the tick rate differs from the refresh rate.

  - The docs warn of "a slight delay to input" in fast twitch games.
  - Call `reset_physics_interpolation()` after a teleport, or the object streaks from its old position.

  Source: https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/using_physics_interpolation.html

The examples below are illustrations written for this report. They have not been run.

```gdscript
# Autoload "Feel": one owner for time_scale, so overlapping hit stops never restore a wrong value.
extends Node
var shake_scale := 1.0      # bound to the accessibility slider, 0..1
var trauma := 0.0
var _noise := FastNoiseLite.new()
var _hitstop_depth := 0

func hit_stop(duration_s: float, scale := 0.05) -> void:
	if shake_scale == 0.0 and Settings.reduce_motion: return
	_hitstop_depth += 1
	Engine.time_scale = scale                       # never 0.0 (docs note)
	await get_tree().create_timer(duration_s, true, false, true).timeout
	_hitstop_depth -= 1
	if _hitstop_depth == 0: Engine.time_scale = 1.0

func add_trauma(amount: float) -> void:
	trauma = minf(trauma + amount, 1.0)

func shake_offset(cam: Camera2D, delta: float, max_px := 12.0) -> void:
	trauma = maxf(trauma - delta * 1.5, 0.0)
	var k := trauma * trauma * shake_scale
	var t := Time.get_ticks_msec() * 0.05
	cam.offset = Vector2(_noise.get_noise_2d(t, 0.0), _noise.get_noise_2d(0.0, t)) * max_px * k
```

```gdscript
# Squash and stretch on landing: a fresh tween each time, eased out.
func squash(sprite: Node2D) -> void:
	var tw := sprite.create_tween().set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
	sprite.scale = Vector2(1.25, 0.8)
	tw.tween_property(sprite, "scale", Vector2.ONE, 0.18)
```

- Shake should move `Camera2D.offset`, or a child pivot node in 3D, not the camera's position. Smoothing and limits then stay correct, and the camera does not clip into walls.
- UNVERIFIED: the wall-clipping risk is reported in a 2016 attendee blog of Eiserloh's talk, not confirmed from the talk itself.

## 2. Onboarding and tutorials

- **Teach by doing.** GAG Basic (cognitive) lists "Include interactive tutorials" (https://gameaccessibilityguidelines.com/full-list/, accessed 2026-11-13).

- **Four-step level structure.** Nintendo's introduce → develop → twist → conclude structure (kishōtenketsu, after director Koichi Hayashida) is explained in Game Maker's Toolkit, "Super Mario 3D World's 4 Step Level Design", 2015 (https://www.mcvuk.com/development/video-nintendos-level-design-secrets-in-four-steps). This is secondary coverage; the video itself was not viewed.

- **Progressive disclosure and the cognitive basis.** Hodent, "The Gamer's Brain, Part 2: UX of Onboarding and Player Engagement", GDC 2016 (https://gdcvault.com/play/1022951) covers:

  - limited attention and memory;
  - teaching one mechanic at a time, in context;
  - the risk of front-loaded text.

  Book: *The Gamer's Brain*, CRC Press, 2017.

- **Let players start quickly.** GAG Basic: "Allow the game to be started without the need to navigate through multiple levels of menus" and "Allow players to progress through text prompts at their own pace".

- **First-time user experience (FTUE) metrics** (generic funnel practice; specific target numbers are UNVERIFIED):

  - share of new players who complete each tutorial step;
  - time to the first meaningful action;
  - number of failed attempts at each taught mechanic;
  - share of players who quit before the first save;
  - share who return for a second session.

## 3. Difficulty and balancing

- **XAG 108** (https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/108, updated 2026-06-17):
  - "ideally four or more" difficulty presets;
  - difficulty can be changed "at any time without losing game progress";
  - separate settings for separate mechanics (for example, puzzle versus combat difficulty) or assists such as auto-aim;
  - an "ultra-low difficulty mode";
  - preset names must not belittle the player ("Wimp Mode" is the counter-example);
  - pause available at any time in single-player, including during cutscenes;
  - both manual save and autosave.
- **Assist mode example: Celeste.** Game speed can be lowered (to 50%), with invincibility, infinite stamina and chapter skip. The designers chose to frame it as fitting "specific needs" (https://www.vice.com/en/article/celeste-assist-mode-change-and-accessibility; secondary source, original game text not checked). GAG has a case study page: https://gameaccessibilityguidelines.com/celeste-assist-mode.
- **Dynamic difficulty adjustment example: the Left 4 Dead AI Director.** It drives pacing from estimated player intensity: Booth, "The AI Systems of Left 4 Dead", Valve 2009 (https://cdn.fastly.steamstatic.com/apps/valve/2009/ai_systems_of_l4d_mike_booth.pdf). Only the PDF's opening was seen. The pacing details are therefore UNVERIFIED.
- **Hidden adaptive difficulty can be resented if players discover it.** This is opinion; no primary source was found (UNVERIFIED). Prefer settings the player can see.
- **Difficulty curve.** Introduce, practise, combine, test; then a short easier stretch after each spike. This is design convention, supported by the GMTK four-step video above.

## 4. Accessibility as design

**GAG Basic tier** (https://gameaccessibilityguidelines.com/full-list/, accessed 2026-11-13). Numbers of guidelines in the higher tiers: Motor 11/4, Cognitive 17/6, Vision 13/10, Hearing 11/3, General 8/3.

| Category  | Basic guidelines                                                                                                                                                                                               |
| --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Motor     | Remappable controls; adjustable sensitivity; adjustable game speed; haptics toggle; UI reachable with the same input method as gameplay; large, well-spaced controls; simple controls or a simpler alternative |
| Cognitive | No flicker or repetitive patterns; text at the player's own pace; interactive tutorials; simple language and formatting; start without deep menus                                                              |
| Vision    | High contrast; readable default font size; no information carried by colour alone; sensible default field of view (3D)                                                                                         |
| Hearing   | Subtitles for important speech, clearly presented; no information carried by sound alone; separate volume for effects, speech and music                                                                        |
| General   | Settings saved; accessibility features described in-game and on the store page; wide choice of difficulty; ask for accessibility feedback                                                                      |

**Higher tiers**

- "Allow subtitle/caption presentation to be customised" is Intermediate.
- "Allow the font size to be adjusted" is Advanced.

**XAG measurable values**

- **XAG 101, text** (https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/101, updated 2026-06-17):
  - minimum default size, measured as body height: console 26 px at 1080p; PC 18 px at 1080p;
  - scalable to 200%;
  - at least one sans-serif option;
  - at most 80 characters per line;
  - line spacing of at least 1.5.
- **XAG 104, subtitles** (https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/104, updated 2026-06-17):
  - on by default, or settable before any audio plays;
  - speaker named;
  - at most 40 characters per line and at most 2 lines;
  - mixed case;
  - background with adjustable opacity (0–100%);
  - a live preview of the settings;
  - directional arrows for off-screen sounds.
- **XAG index:** 23 guidelines (101–123), version 3.2, published 2023-06-08 (https://learn.microsoft.com/en-us/gaming/accessibility/guidelines). Most relevant here: 107 Input, 112–113 UI navigation and focus, 116 Time limits, 117 Motion, 118 Photosensitivity.

**AbleGamers APX** (https://accessible.games/apx; https://accessible.games/accessible-player-experiences/access-patterns/)

- 22 design patterns: 12 Access Patterns (Control and Presentation) and 10 Challenge Patterns.
- Use them to brainstorm solutions alongside the checklists.

**What Godot 4.7 offers**

- Remapping through `InputMap.action_erase_events` and `action_add_event`, saved to a `ConfigFile` in `user://`.
- Godot 4.5 added screen reader support for Control nodes through AccessKit. The release notes say "its integration is still in its experimental phase" (https://godotengine.org/releases/4.5/).
- Theme-wide font scaling through a root Theme `default_font_size` or `content_scale_factor`. This is engine knowledge; UI layout is covered by the separate UI research.

```gdscript
# Remap one action and persist it; called from the controls menu.
func rebind(action: StringName, ev: InputEvent) -> void:
	InputMap.action_erase_events(action)
	InputMap.action_add_event(action, ev)
	var cfg := ConfigFile.new()
	cfg.load("user://settings.cfg")  # missing file is fine on first run
	cfg.set_value("input", action, ev)
	cfg.save("user://settings.cfg")
```

## 5. Playtesting methods

- **Think-aloud.** "Recruit representative users. Give them representative tasks to perform. Shut up and let the users do the talking." (Nielsen, https://www.nngroup.com/articles/thinking-aloud-the-1-usability-tool/). It is cheap and shows why players are confused. It also changes how people play, so do not take timing measurements from think-aloud sessions.
- **Blind first-time tests.** The tester has never seen the game and receives no help. This is the only valid test of onboarding. Each tester can be "first-time" only once, so recruit new testers for every tutorial iteration.
- **Surveys** come after the session. Use a fixed question set across builds so results can be compared. Observed behaviour outweighs what players say about themselves.
- **Steam Playtest** (https://partner.steamgames.com/doc/features/playtest, accessed 2026-11-13):
  - a free "child" app attached to the main game;
  - players sign up from the game's store page and are admitted Limited (in batches) or Open (automatically);
  - "players signing up for a Playtest aren't under nondisclosure agreements";
  - reviews and playtime are kept separate from the main game;
  - charging for access is not allowed;
  - above 50,000 keys Valve treats it as an open beta.
- **Closed betas.** For confidentiality, use a hidden Playtest app with keys, or Release State Override keys (at most 2,500 per app). Signup and NDAs must then be handled by the developer.
- **Accessibility playtests.** GAG Basic asks studios to "solicit accessibility feedback". AbleGamers runs Player Panels (https://accessible.games).

## 6. Telemetry for design, privacy-respecting

**Events worth logging**

- `session_start` and `session_end` (gives session length);
- `tutorial_step` (gives the funnel);
- `level_start`, `level_complete`, `death` with position and cause (gives heatmaps and death points);
- `quit` with the last checkpoint (gives quit points);
- `setting_changed` (shows which accessibility options players actually use).

**Privacy**

- The ICO's sample DPIA for a mobile game uses legitimate interests for gameplay analytics and anonymises "as soon as it is collected" (https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/childrens-information/childrens-code-guidance-and-resources/dpia-tools/mobile-gaming-app/step-4-assess-necessity-and-proportionality/). That is a template example, not a ruling.
- UNVERIFIED: whether pseudonymous telemetry without consent is lawful in every EU member state. The safe default is opt-in with a separate toggle for each purpose (Fieldfisher summary of Spanish and Belgian guidance: https://www.fieldfisher.com/en/insights/spanish-and-belgian-gdpr-guidance-for-the-video-game-industry).
- **Do not use `OS.get_unique_id()` as the player ID.** It is tied to the device, can change when the OS or hardware changes, can be faked, and returns an empty string on Web (https://docs.godotengine.org/en/stable/classes/class_os.html). Instead, generate random bytes once and store them in `user://`. Deleting that file resets the ID.

```gdscript
# Opt-in event queue; nothing leaves the machine until consent is true.
const SCHEMA_VERSION := 1
func track(name: String, props := {}) -> void:
	if not Settings.telemetry_consent: return
	_queue.append({"v": SCHEMA_VERSION, "event": name, "t": Time.get_unix_time_from_system(),
		"sid": _session_id, "build": ProjectSettings.get_setting("application/config/version"), "p": props})
	# Flushed in batches via HTTPRequest, or written to user://telemetry.jsonl for offline playtests.
```

**Reading the data**

- Cluster deaths by position and cause.
- A spike in deaths followed by a quit marks a difficulty wall.
- A spike in deaths without quits may simply be a good challenge.
- Confirm each hotspot by observing players before changing the design: telemetry shows where, observation shows why.
- Compare builds on the same funnel definitions.
- Change one variable per iteration where possible.
- These are practice heuristics; no primary source was fetched.

## 7. Performance feel: input latency and frame pacing

From "Fixing jitter, stutter and input lag" (https://docs.godotengine.org/en/stable/tutorials/rendering/jitter_stutter.html, 4.7):

- Offer V-Sync as a player option.
- Swapchain Image Count = 2 (4.3+, Forward+ and Mobile renderers) reduces latency but makes the frame rate less stable.
- Raising Physics Ticks Per Second to 120, 180 or 240 reduces physics-induced latency at a CPU cost.
- `Input.set_use_accumulated_input(false)` delivers every input event, at a CPU cost.
- With VRR (G-Sync/FreeSync), cap the frame rate just below the refresh rate, e.g. `Engine.max_fps = 141` on a 144 Hz monitor.
- Command-line flags `--disable-vsync` and `--max-fps` exist.

Feel advice:

- Respond on the frame the input arrives: start animation, sound and particles before any server or physics confirmation.
- Buffer inputs and use coyote time to hide small timing errors. This is common practice; no primary source was fetched (UNVERIFIED).

## Checkable rules an agent should follow

1. Every camera shake goes through one function that multiplies by a `shake_scale` setting (0–100%). Check: grep for writes to `offset` or `h_offset`/`v_offset` outside that function (XAG 117).
1. Exactly one autoload writes `Engine.time_scale`, and it never writes 0.0. Check: grep `time_scale\s*=` (Engine docs).
1. Hit-stop restore timers pass `ignore_time_scale=true`; UI tweens call `set_ignore_time_scale(true)`. Check: grep `create_timer(` near `time_scale`.
1. No `Tween` is kept in a variable and replayed; a new tween is created per animation (Tween docs).
1. A reduce-motion setting turns off head bob, weapon sway, motion blur and screen flashes (XAG 117).
1. Full-screen flashes last longer than 333 ms per cycle, or cover less than 20% of the screen, or the flash effect has a toggle (XAG 118). Playtest checklist item, or the automated scan in the next section.
1. Every gameplay action in `project.godot [input]` can be rebound from an in-game menu, and bindings persist in `user://` (GAG Basic motor).
1. The UI can be driven entirely by the gameplay input method: focus neighbours are set and a keyboard or gamepad can reach every Control (GAG Basic; XAG 112/113).
1. Subtitles are on by default or offered before the first voice line, and the speaker is named (XAG 104).
1. No subtitle line is longer than 40 characters; at most 2 lines are visible at once (XAG 104). Check: lint the dialogue and translation files.
1. Separate volume sliders exist for music, effects and voice, backed by separate audio buses (GAG Basic hearing).
1. Default body text is at least 18 px at 1080p on PC (26 px on console) and scales to 200% without clipping (XAG 101).
1. No state is shown by colour alone; each coloured state also has an icon, text or shape (GAG Basic vision).
1. Every sound that carries gameplay information has a visual cue as well (GAG Basic hearing).
1. There are at least 4 difficulty presets, or separate assist toggles, that can be changed mid-game without losing progress, with neutral names (XAG 108).
1. The game can be paused at any time in single-player, including during cutscenes (XAG 108).
1. All settings persist across restarts (GAG Basic general). Headless test: change a setting, quit, relaunch, read it back.
1. The tutorial teaches each mechanic by having the player perform it, with at most one new mechanic per step. Text prompts advance on input, not on a timer (GAG Basic cognitive).
1. Every tutorial step emits a `tutorial_step` event, so the funnel can be measured.
1. Telemetry is off until the player consents, uses a random ID stored in `user://` rather than `OS.get_unique_id()`, and every event carries a schema version (ICO DPIA; OS docs).
1. Gameplay logic and moving bodies update in `_physics_process`; teleports call `reset_physics_interpolation()` (physics interpolation docs).
1. V-Sync and the frame cap are player settings (jitter, stutter and input lag docs).
1. Every playtest build records its build ID, and every finding names the build it was seen on.
1. Accessibility features are listed in-game and on the store page (GAG Basic general).

## What a tool could check automatically

**Settings presence (static, grep-based)**

- **Settings keys.** Parse `project.godot` and the settings scripts and scenes for keys or labels matching `remap|rebind`, `subtitle`, `shake|screen_shake|reduce_motion`, `text_size|font_scale|ui_scale`, `colorblind`, `difficulty|assist`, `volume_(music|sfx|voice)`. Report each GAG Basic item as present or missing.
- **Input coverage.** List the `[input]` actions in `project.godot` and check that each appears in the rebind UI scene or script.
- **Audio buses.** Read `default_bus_layout.tres` and require at least 3 buses beyond Master (music, effects, voice).
- **Dangerous patterns** (risky code shapes):
  - `Engine.time_scale = 0`;
  - writes to `time_scale` from more than one file;
  - `Tween.new()`;
  - `OS.get_unique_id` reaching the telemetry code;
  - `create_timer(` near `time_scale` without the fourth argument set to `true`.
- **Subtitle lint.** Read CSV/PO/JSON dialogue: line length ≤ 40 characters, ≤ 2 lines, speaker field present (XAG 104).
- **Font size check.** For theme `.tres` files and `theme_override_font_sizes`, convert to pixels at 1080p from the `display/window/size/*` and stretch settings, and flag values below 18 px. This is approximate, because the XAG measures body height, not point size.

**Running the game headless**

- **Settings persistence.** Launch with `--headless`, call a test script that changes every setting, quit, relaunch and compare. Judge by an explicit log summary line, per project rules.
- **Input-to-response probe.**
  - Inject the action with `Input.parse_input_event()`.
  - Count physics and process frames until the game emits a response signal (animation started, velocity changed, sound played).
  - Fail if more than 1 physics tick.
  - This measures engine-side latency only, not display latency.
  - UNVERIFIED: whether `RenderingServer.frame_post_draw` timing means anything under the headless dummy renderer. For frame-based timing, use `--fixed-fps`, or `--write-movie` with a real renderer under Xvfb.
- **Flash scan** (needs Xvfb and the renderer).
  - Record a test path with `--write-movie`.
  - Compute the change in average luminance between frames and the share of the screen involved.
  - Flag runs of more than 3 flashes per second (≥10% luminance change) over ≥20% of the screen, and saturated red flashes (R/(R+G+B) ≥ 0.8), following XAG 118.
  - This is a heuristic, not a substitute for a Harding FPA test.

**Telemetry**

- **Schema validation.** Validate `user://telemetry.jsonl` or the outgoing payloads against a JSON Schema in `contracts/`:
  - required fields `v`, `event`, `t`, `sid`, `build`;
  - an enumerated event set;
  - no fields matching email, name, IP or a hardware ID.
- **Consent gate.** Run headless with consent off and assert that zero events are written and no `HTTPRequest` is made.
- **Funnel report.** From JSONL, compute tutorial-step completion, deaths per level and cause, quit points and median session length, as a Python stdlib script.

## Pitfalls

- Overlapping hit stops, each restoring `time_scale = 1.0`, cut each other short. Or a hit stop restored by a scaled timer takes 20 times too long.
- Hit stop slows timers and tweens but not audio, so sounds run ahead of a frozen frame (Engine docs). Decide deliberately whether audio should match.
- A high `time_scale` without more physics ticks makes physics imprecise (Engine docs).
- Shaking the camera's `position` fights smoothing and limits and can clip through geometry; use `offset`.
- Shake with no off switch harms players with motion sensitivity (XAG 117). Flashes on hit can fail XAG 118.
- Juice that ignores context breaks immersion: bouncy tweens on hard surfaces, dust where there is none (Kelly, GDC Europe 2014).
- Tutorials made of text walls or timed prompts; testing onboarding only with players who have already seen it.
- Reading playtest surveys as truth while ignoring observed behaviour; changing many variables between builds.
- Tracking players by `OS.get_unique_id()`, or sending telemetry before consent. Web builds get an empty ID.
- Treating Steam Playtest as confidential; it is not (Steam docs).
- Turning on physics interpolation without `reset_physics_interpolation()` on teleports, so objects streak.
- Counting on Godot's screen reader support as finished; 4.5 marks it experimental.
- Easy modes with belittling names, or difficulty that cannot be changed without restarting (XAG 108).

## Sources

- GAG full list: https://gameaccessibilityguidelines.com/full-list/ — basic tier and tier counts (accessed 2026-11-13).
- XAG index v3.2 (2023-06-08): https://learn.microsoft.com/en-us/gaming/accessibility/guidelines and https://devdocs.xbox.com/build/game-principles/accessibility/xbox-accessibility-guidelines.md
- XAG 101 / 104 / 108 / 117 / 118 (updated 2026-06-17): https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/{101,104,108,117,118}
- AbleGamers APX: https://accessible.games/apx
- Godot 4.7 docs: Engine, Tween, SceneTree, OS, jitter/stutter/input lag, physics interpolation (URLs inline). Godot 4.5 release notes: https://godotengine.org/releases/4.5/
- GDC Vault: 1016487 (Juice It or Lose It, 2012), 1020861 (Don't Juice It or Lose It, 2014), 1023146 (Eiserloh 2016), 1022951 (Hodent 2016).
- Steam Playtest: https://partner.steamgames.com/doc/features/playtest
- NN/g think-aloud: https://www.nngroup.com/articles/thinking-aloud-the-1-usability-tool/
- ICO sample DPIA (mobile game) and the Fieldfisher summary: URLs inline.
- Valve L4D AI PDF (2009); GMTK coverage (mcvuk); Celeste coverage (Vice) — secondary or partially read.

## Risks and gaps

- **GDC talks were not watched.** The Vault pages are login-gated, so talk content is taken from session overviews and press coverage.
- **Some details are secondary.** The Swink year conflict, the Celeste wording and the L4D Director details come from secondary sources.
- **Probe behaviour is untested.** Headless and dummy-renderer behaviour of the latency and flash probes is untested: mark UNTESTED until run against Godot 4.7.2.
- **The GAG site carries no page dates;** "accessed 2026-11-13" is used instead.
