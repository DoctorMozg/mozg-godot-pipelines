# Research library

Research behind `docs/plan.md`. Documents 01–16 shaped the suite's structure. Documents 17–34 are a Godot 4.7 practice library: each ends in checkable rules and a list of checks a kit could run, and feeds a lint rule, a gate probe or a skill reference.

Status markers used throughout: UNVERIFIED means no primary source confirmed the claim; UNTESTED means it has not been run on Godot 4.7.2. A claim moves into a shipped skill or check only after it is tested, or it ships with its marker.

## Suite structure (2026-11-12)

| #   | Topic                                                | Basis                      |
| --- | ---------------------------------------------------- | -------------------------- |
| 01  | Conventions of the two mozg marketplaces             | local repos                |
| 02  | Game design in AloneGodot                            | AloneGodot, Codex sessions |
| 03  | Graphics and art pipeline in AloneGodot              | AloneGodot                 |
| 04  | Sound in AloneGodot                                  | AloneGodot                 |
| 05  | Testing and quality gates in AloneGodot              | AloneGodot                 |
| 06  | UI/UX in AloneGodot                                  | AloneGodot                 |
| 07  | Orchestration and developer experience in AloneGodot | AloneGodot, Codex sessions |
| 08  | Prior art: Godot plugins and marketplaces for agents | web                        |
| 09  | Godot agent tooling: MCP servers, CLI, tests, lint   | web                        |
| 10  | AI asset pipelines                                   | web                        |
| 11  | Existing review surfaces in AloneGodot               | AloneGodot                 |
| 12  | Game design analysis and visualisation tools         | web                        |
| 13  | Local review hub                                     | web                        |
| 14  | Fast edit → check → feedback loop                    | web                        |
| 15  | Project asset registry                               | web                        |
| 16  | Localization                                         | web                        |

## Godot 4.7 practice library (2026-11-13)

| #   | Topic                                                | Feeds                                                                                  |
| --- | ---------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 17  | GDScript strict typing and warnings                  | godot-core: `strict`, parse gate                                                       |
| 18  | GDScript architecture                                | godot-core: `lint`, `arch`; `gdscript-rules.md` reference                              |
| 19  | GDScript lint, format, check and test tooling        | godot-core: Tier 0, `test`                                                             |
| 20  | Writing shaders                                      | godot-core: shader lint; godot-art reference                                           |
| 21  | Verifying shaders from the CLI                       | godot-core: headless shader gate, optional render gate; godot-assets: shader clips     |
| 22  | UI/UX: layout, themes, focus, scaling, accessibility | godot-ui: scene/theme lint, resolution matrix probe                                    |
| 23  | Networking and multiplayer                           | godot-core: `@rpc` and replication lint, two-instance probe                            |
| 24  | Performance and profiling                            | godot-core: hot-path lint, leak smoke test, benchmark scene                            |
| 25  | Physics, movement and animation                      | godot-core: physics lint, layer audit, headless physics probes                         |
| 26  | Input, save/load and settings                        | godot-core: InputMap lint, unsafe-load grep, save round-trip probe                     |
| 27  | Rendering, lighting, VFX and import                  | godot-art: `.import` audit, VRAM budget, renderer/feature lint                         |
| 28  | AI, navigation and procedural generation             | godot-core: seeded reproducibility, reachability probes; game-design: generator checks |
| 29  | Export, platforms and release                        | godot-core: export preset lint, dry-run exports, licence completeness                  |
| 30  | Extending Godot, addons and version control          | godot-core: VCS hygiene, UID integrity, engine pin, addon manifest                     |
| 31  | Audio implementation                                 | godot-audio: bus layout lint, import audit, loudness via ffmpeg                        |
| 32  | Game feel, onboarding, accessibility, playtesting    | game-design: playtest and telemetry checks; godot-ui: accessibility settings           |
| 33  | Dialogue, quests and cutscenes                       | godot-l10n: line ids, untranslated lines; game-design: dialogue graph lint             |
| 34  | Level design, worlds and cameras                     | game-design: level metrics; godot-core: scene lint, reachability probe                 |

## Findings that change plans

- 26: a crafted `.po` file runs code on Godot 4.1.0–4.7.2, unpatched as of 2026-10-26. godot-l10n must build `.po` files only from its own store and never import outside ones unchecked.
- 26: `ConfigFile.load`, `str_to_var` and `.tres` loading can run code; saves must be plain data.
- 30: C# cannot export to the web on 4.7; a web target means GDScript or a GDExtension.
- 30: 4.6 rewrote scene headers; an engine upgrade lands as its own commit.
- 25: new 3D projects default to Jolt from 4.6, older ones keep GodotPhysics; checks read the setting, never assume it.
- 21: `--headless` compiles shaders through the front end, so a GPU-free shader gate is possible; backend errors need a renderer.
- 33: `AnimationPlayer.seek()` skips method keys, so a cutscene skip needs an explicit end-state function.
