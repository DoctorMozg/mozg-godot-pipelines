# Extending Godot, addons and version control (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7 and stable), the 4.4–4.7 release notes, Godot posts and source, and the godot-cpp, godot-rust, gd-plug and GodotEnv repos. Checks are UNTESTED on 4.7.2.

## Executive summary

GDScript is still the recommended default. C#/.NET runs on desktop, is experimental on Android and iOS, and as of 4.7 still cannot export to the web: the web support PR is still an open draft. Hot code moves to a GDExtension (godot-cpp or godot-rust) only after profiling shows that your own script logic is the bottleneck. An extension built against an older API level loads on newer minor versions, but not the other way round.

For version control, the rules are:

- Ignore `.godot/`.
- Commit `.uid` files (4.4+) and `.import` files.
- Enforce LF line endings.
- Run Project > Tools > Upgrade Project Files once per minor upgrade and commit the result on its own. 4.6 rewrote scene headers (unique node IDs, no `load_steps`).

4.7 replaces the Asset Library with the Asset Store, which is integrated in the editor. Neither offers a lock file, so pinning addon versions still needs git submodules, vendoring with a manifest, gd-plug, or GodotEnv.

## 1. Language choices

| Option                  | Status at 4.7                                                                                                                                                                                                         | Source                                                                                                                                                          |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| GDScript                | "the recommended language… native to Godot". C# and GDScript performance is "within the same order of magnitude, and C++ is faster than both"                                                                         | https://docs.godotengine.org/en/4.7/about/faq.html                                                                                                              |
| C# (.NET)               | Desktop export supported since 4.0. Android and iOS "experimental" since 4.2. "Projects written in C# using Godot 4 currently cannot be exported to the web platform"                                                 | https://docs.godotengine.org/en/4.7/tutorials/scripting/c_sharp/c_sharp_basics.html, https://docs.godotengine.org/en/4.7/tutorials/scripting/c_sharp/index.html |
| C# web                  | Draft PR #106125 "[.NET] Add web export support" is still open, milestone 4.x, last activity 2026-09-14. The prototype statically links Mono and is called "very brittle": invariant globalization only, a 72 MiB pck | https://github.com/godotengine/godot/pull/106125, https://godotengine.org/article/live-from-godotcon-boston-web-dotnet-prototype/ (2025-05-09)                  |
| .NET version            | 4.4 raised the minimum to .NET 8 and upgrades existing projects automatically when they are opened. Android export needs .NET 9+ (16 KB page support, 4.5)                                                            | https://godotengine.org/releases/4.4/, https://godotengine.org/releases/4.5/                                                                                    |
| C++ (godot-cpp)         | Official bindings. Since v10, "versioned independently from Godot" and able to target 4.3+ through `api_version`                                                                                                      | https://github.com/godotengine/godot-cpp                                                                                                                        |
| Rust (godot-rust/gdext) | Crate `godot`. v0.4 supports 4.2–4.5. v0.5 adds API level 4.6 as the default (`api-4-*` cargo features). Called "production-ready" for its foundations, with "occasional breaking changes"                            | https://godot-rust.github.io/book/toolchain/compatibility.html, https://godot-rust.github.io/book/migrate/v0.5.html                                             |
| Others                  | The FAQ names unofficial Python and Nim bindings. Swift and Kotlin bindings are mentioned in 4.6 release notes (required-parameter metadata)                                                                          | faq.html above, https://godotengine.org/releases/4.6/                                                                                                           |

UNVERIFIED:

- Whether godot-rust has published an `api-4-7` level. No source found.
- Secondary sites say "C# hot reload is on by default in 4.7". It is not in the official 4.7 release page.
- Whether godot-cpp v10 is stable. A 10.0.0-rc1 tag exists, and a meeting agenda planned the stable release after 4.7-stable.

**C#/GDScript interop** (https://docs.godotengine.org/en/4.7/tutorials/scripting/cross_language_scripting.html):

- No inheritance across languages.
- C# can connect to GDScript signals only through `Connect()`.
- GDScript members are addressed by snake_case strings.
- Calling GDScript from C# with missing arguments "fails silently".
- Marshalling `string` and `byte[]` is "comparatively pricey" (c_sharp_basics.html).

**When GDExtension pays off** (https://docs.godotengine.org/en/4.7/tutorials/performance/cpu_optimization.html):

- "Built-in engine functions run at the same speed regardless of the scripting language." Only your own heavy computation gains.
- C++ "will usually result in the fastest code", but it is "the most difficult to deploy" because it needs a build per platform.
- C# can cause GC pauses.
- Profile first (general_optimization.html). Try Server APIs and threads before changing language.
- Good candidates: tight numeric loops such as pathfinding, procedural generation and simulation, or wrapping a native library.

**Modules or GDExtension** (https://docs.godotengine.org/en/4.7/tutorials/scripting/cpp/about_godot_cpp.html):

- A module gives "deeper integration" but needs an engine rebuild and custom export templates.
- godot-cpp needs no engine compile and is easier to distribute.
- Use a module only when GDExtension cannot reach what you need.
- Extensions must match the engine's float precision: double-precision builds need matching extension binaries.

**GDExtension compatibility rules:**

- "GDExtensions targeting an earlier version of Godot should work in later minor versions, but not vice-versa." Extensions targeting 4.0 do not load in 4.1+ (about_godot_cpp.html).
- `.gdextension` file fields:
  - `compatibility_minimum` (4.1+) and `compatibility_maximum` (4.3+).
  - `reloadable = true` hot-reloads godot-cpp extensions (4.2+).
  - Source: https://docs.godotengine.org/en/stable/engine_details/engine_api/gdextension/gdextension_file.html
- The 4.7 Project Settings has a GDExtensions section listing loaded extensions (https://godotengine.org/releases/4.7/).

**Build:**

- SCons is "the main build system". CMake is the "Secondary build system".
- `scons platform=linux api_version=4.3`, or pass `custom_api_file=` with a file from `godot --dump-extension-api`.
- Sources: https://docs.godotengine.org/en/4.7/tutorials/scripting/cpp/build_system/scons.html, https://github.com/godotengine/godot-cpp

## 2. Editor tooling

**`@tool` scripts** (https://docs.godotengine.org/en/4.7/tutorials/plugins/running_code_in_the_editor.html):

```gdscript
@tool
extends Node2D
func _process(delta: float) -> void:
    if Engine.is_editor_hint():
        return            # editor preview only; game logic below
    position.x += delta * 10.0
```

Pitfalls the docs list:

- Freeing nodes the editor is using can crash it.
- Every script a tool script uses must also be `@tool`. Static methods, constants and enums are exempt.
- A script extending a `@tool` script is not a tool script unless it has `@tool` itself.
- Edits a tool script makes have no undo.
- Nodes added from code are not saved unless `node.owner = get_tree().edited_scene_root`.
- After changing a tool script you may need to reopen the scene or restart the editor.

**Other tooling:**

- `@export_tool_button("Label") var act = fn` (4.4) adds inspector buttons from `@tool` scripts (https://godotengine.org/releases/4.4/).
- EditorScript is for one-off batch edits. It must be `@tool`, implement `_run()`, and is run from the script editor. It has no undo, so commit first (same page).
- EditorPlugin needs `addons/<name>/plugin.cfg` with `name`, `description`, `author`, `version` and `script`. Set up in `_enter_tree()` and remove everything in `_exit_tree()`. Register autoloads in `_enable_plugin()` and remove them in `_disable_plugin()`.
- Docks use `EditorDock` with `add_dock()`/`remove_dock()` (4.6+, class marked experimental). A C# EditorPlugin must be built before it can be enabled.
  - https://docs.godotengine.org/en/4.7/tutorials/plugins/editor/making_plugins.html
  - https://docs.godotengine.org/en/4.6/classes/class_editordock.html
- Custom inspectors: EditorInspectorPlugin. Import plugins: EditorImportPlugin (`_get_importer_name`, `_get_recognized_extensions`, `_get_save_extension`, `_get_resource_type`, `_import`), registered with `add_import_plugin()`.
  - The docs say "Never expect the file to be well-formed".
  - `_get_import_options` must return an array even when it is empty.
  - https://docs.godotengine.org/en/4.7/tutorials/plugins/editor/import_plugins.html
  - UNVERIFIED: whether `_get_priority` and `_get_import_order` must be implemented in 4.7. The tutorial does not mention them.
- Custom Resources for data authoring: write `class_name Foo extends Resource` with `@export` fields and save them as text `.tres` so diffs stay readable. An exported Resource "makes them a dependency of the instance". Use `@export_file` when the resource should load lazily (https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/gdscript_exports.html).

## 3. Addon management

- **Asset Store** (https://godotengine.org/article/introducing-the-godot-asset-store/, 2026-05-22):
  - Run by the Foundation and "fully integrated in Godot 4.7".
  - Each asset can have several download versions and a changelog page.
  - No paid assets yet.
  - The old Asset Library "should be considered deprecated" and will become read-only.
  - The 4.7 release notes confirm the Store replaces the Library in the editor (https://godotengine.org/releases/4.7/).
  - No public API or lock file is documented (UNVERIFIED).
- **Placement:** keep third-party code in a top-level `addons/` even when it is not an editor plugin (https://docs.godotengine.org/en/4.7/tutorials/best_practices/project_organization.html).
- **gd-plug** (https://github.com/imjp94/gd-plug):
  - Dependencies are declared in a `plug.gd` that extends `res://addons/gd-plug/plug.gd`.
  - Pin with `plug("user/repo", {"tag": "1.0.0"})` or `{"commit": "<40-char sha>"}`. An unpinned plugin follows the default branch.
  - Run with `godot --headless -s plug.gd install`. Clones go to `.plugged/`.
  - No lock file is documented.
- **GodotEnv** (https://github.com/chickensoft-games/GodotEnv):
  - A .NET tool. Addons are declared in `addons.jsonc` with `url`, `checkout` (default `main`) and `subfolder`. Sources can be remote git, local git, symlink or zip.
  - `addons init` gitignores the addons folder.
  - It also pins the engine (`godotenv godot pin` writes `global.json` or `.godotrc`).
- **Git submodule:** pins an exact commit, but an addon repo usually holds `addons/x` inside a larger tree, so a sparse or subfolder copy is needed.
- **Vendoring:** simplest and reproducible. Record source URL, version, commit and licence per addon in a manifest. Each addon's `plugin.cfg` `version` is the only version Godot itself reads.
- **Licences:** Godot's MIT licence text must ship with the game. Engine third-party notices are in COPYRIGHT.txt, or readable at runtime through `Engine.get_license_info()` and `get_copyright_info()`. Third-party assets need their own notices (https://docs.godotengine.org/en/4.7/about/complying_with_licenses.html).

## 4. Version control

- **Generated files:** Project Manager "Git" option, or Project > Version Control > Generate Version Control Metadata. In source these write:
  - `.gitignore`: `.godot/` and `/android/`
  - `.gitattributes`: `* text=auto eol=lf`
  - Sources: https://raw.githubusercontent.com/godotengine/godot/master/editor/version_control/editor_vcs_interface.cpp, https://docs.godotengine.org/en/4.7/tutorials/best_practices/version_control_systems.html
- **Ignore (4.1+):** `.godot/` (cache, imported files, editor state, `export_credentials.cfg`) and `*.translation` generated from CSV. 3.x/4.0 used a different list because credentials sat in `export_presets.cfg` (same VCS page).
  - The GitHub template also ignores `.nomedia`, `export_credentials.cfg`, `*.tmp`, `.mono/`, `data_*/` and `mono_crash.*.json` (https://github.com/github/gitignore/blob/main/Godot.gitignore).
- **Line endings:** the docs suggest `git config --global core.autocrlf input` on Windows if the metadata files are not used.
- **Git LFS:** the docs' example tracks fbx/gltf/glb/blend/obj, png/svg/jpg/tga/webp/exr/hdr/dds, mp3/wav/ogg, ttf/otf, and Godot binaries (scn/res/material/anim/mesh/lmbake). Each line looks like `*.glb filter=lfs diff=lfs merge=lfs -text`. Set LFS up before the first commit of those files.
- **Commit:** `.import` files ("contain important metadata", https://docs.godotengine.org/en/4.7/tutorials/assets_pipeline/import_process.html). Never commit `.godot/`.
- **`.uid` (4.4+)** (https://godotengine.org/article/uid-changes-coming-to-godot-4-4/, 2025-01-15):
  - Written beside scripts and shaders, for example `player.gd.uid`.
  - Commit them and never ignore them. Move them together with their file when moving outside the editor.
  - If one is missing after a clone, "UID references will break" and Godot falls back to the path with a warning.
  - Imported assets keep their UID in `.import`, and scenes and resources keep it in their header (project research note `docs/research/15-web-asset-registry.md`).
- **Upgrading to 4.6 changes scene files** (https://docs.godotengine.org/en/4.7/tutorials/migrating/upgrading_to_godot_4.6.html, PR #103352):
  - Scenes now save unique node IDs.
  - `load_steps` is no longer written. It was "a frequent source of Git conflicts".
  - Saving a 4.5 scene in 4.6 gives "significant diffs… expected".
  - Run Project > Tools > Upgrade Project Files… and commit the result as one change.
- **Avoiding .tscn/.tres conflicts:**
  - One owner per scene at a time.
  - Small scenes composed by instancing.
  - Data in separate `.tres` files rather than embedded sub-resources.
  - Text formats instead of binary `.scn`/`.res`.
  - Resolve a conflict by re-saving the scene in the editor, not by hand-merging `[ext_resource]` IDs. This is common practice, not from an official source.
- **Editor churn:** opening an older project rewrites `project.godot` `config/features` with the editor version. Imports regenerate `.uid` and `*.translation` (observed in this repo: `docs/research/05-testing.md`, `docs/research/14-web-fast-feedback-loop.md`).

## 5. Structure and naming

- From project_organization.html (4.7):
  - Group assets "as close to scenes as possible", meaning folder by feature.
  - Use snake_case for files and folders, except C# scripts, which use PascalCase to match their class.
  - Use PascalCase node names.
  - Prefer lowercase everywhere, because the exported PCK filesystem is case-sensitive while Windows and macOS are not.
  - An empty `.gdignore` file excludes a folder from import, and `load()` can no longer reach its contents.

## 6. Upgrading and pinning the engine

- Read each migration guide before upgrading.
  - 4.6→4.7 is "relatively safe" (https://docs.godotengine.org/en/4.7/tutorials/migrating/upgrading_to_godot_4.7.html). Notable 4.7 changes:
    - An override of a method with a typed return now inherits that type and needs an explicit `return`.
    - Setting a packed-array element no longer calls the property setter.
    - `AudioStreamPlayer.area_mask` default changed from 1 to 0.
    - `EditorVCSInterface._commit` gained an `amend` parameter.
    - `RichTextLabel` image-unit renames.
    - Several C#-only binary breaks, such as `Animation.length` becoming double.
  - 4.5→4.6: `EditorFileDialog.add_side_menu` removed. AnimationPlayer string properties are now StringName in C#.
- Upgrade steps:
  1. Branch.
  1. Open the project in the new editor.
  1. Run Project > Tools > Upgrade Project Files….
  1. Commit the format change alone.
  1. Fix the API breaks.
  1. Rebuild C# and GDExtensions against the new API.
  1. Run the tests headless.
- `--convert-3to4` only applies to Godot 3 projects.
- **Pinning:**
  - `project.godot` `config/features=PackedStringArray("4.7", …)` records the editor version that last saved the project. The Project Manager reads entries that look like a version and, in 4.7, shows an icon when the project needs an upgrade or a downgrade (https://godotengine.org/releases/4.7/; source mirror of project_manager).
  - C# projects pin `Godot.NET.Sdk/4.7.x` in the `.csproj` or `global.json`.
  - GodotEnv uses `.godotrc` or `global.json`.
  - Godot has no official patch-level pin file (UNVERIFIED that none exists). A repo can add its own, such as `.godot-version`.

## Version-specific features

| Feature                                                                                                                                                                                      | Version                                           | Source                                                            |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- | ----------------------------------------------------------------- |
| Export credentials moved to `.godot/export_credentials.cfg` (new ignore list)                                                                                                                | 4.1                                               | version_control_systems.html (4.7)                                |
| `.gdextension` `compatibility_minimum`; 4.0 extensions stop loading                                                                                                                          | 4.1                                               | gdextension_file.html (stable), about_godot_cpp.html              |
| GDExtension `reloadable` (godot-cpp); C# Android/iOS experimental                                                                                                                            | 4.2                                               | gdextension_file.html; c_sharp_basics.html                        |
| `compatibility_maximum`; godot-cpp v10 minimum target                                                                                                                                        | 4.3                                               | gdextension_file (fr/4.4); godot-cpp README                       |
| `.uid` files plus UID upgrade tool; `@export_tool_button`; typed dictionaries; .NET 8 minimum; embedded game window                                                                          | 4.4                                               | releases/4.4, UID article 2025-01-15                              |
| `@abstract`, variadic args, script backtraces; C# assemblies load from APK; .NET 9 for Android 16 KB pages; GDExtension main-loop callbacks                                                  | 4.5                                               | releases/4.5                                                      |
| Unique node IDs in scenes; `load_steps` removed; Jolt default for new 3D projects; `EditorDock`/`add_dock` (experimental); plugin shortcuts; GDExtension required params plus JSON interface | 4.6                                               | upgrading_to_godot_4.6.html, releases/4.6, class_editordock (4.6) |
| Project > Tools > Upgrade Project Files (documented in 4.6 guide; first release with it UNVERIFIED, 4.4 had the UID resave tool)                                                             | ≤4.6                                              | upgrading_to_godot_4.6.html                                       |
| Asset Store in editor replaces Asset Library; GDExtensions section in Project Settings; Project Manager up/downgrade icon; typed-return override needs explicit return                       | 4.7 (release coverage dated 2026-06-18, Phoronix) | releases/4.7, upgrading_to_godot_4.7.html                         |
| godot-rust v0.5 default API level 4.6                                                                                                                                                        | crate 0.5.x                                       | godot-rust book v0.5 migration                                    |

## Checkable rules an agent should follow

1. `.gitignore` contains `.godot/`.
1. `.gitignore` covers `*.translation` when translations come from CSV, and `export_credentials.cfg`.
1. `.gitattributes` contains `* text=auto eol=lf`.
1. Every LFS-tracked extension in `.gitattributes` has the attribute `filter=lfs diff=lfs merge=lfs -text`, and `git lfs ls-files` lists the matching files.
1. No tracked file lies under `.godot/` (`git ls-files .godot` is empty).
1. Every tracked `*.gd`, `*.gdshader` and `*.cs`… has a tracked `<file>.uid` sibling. UNVERIFIED for `.cs`: the UID article names scripts generally.
1. No `.uid` file is orphaned, meaning its source file is missing.
1. No `*.uid` pattern appears in `.gitignore`.
1. Every imported asset in git has a tracked `.import` sibling.
1. File moves are done in the editor, or `git mv` moves the file and its `.uid`/`.import` together.
1. File and folder names are lowercase snake_case, except C# scripts.
1. No two paths differ only by case.
1. Third-party code lives under `addons/<name>/`, and each plugin has `plugin.cfg` with a `version`.
1. Every addon has a manifest entry recording source, version or commit, and licence, plus a LICENSE file inside its folder.
1. A `@tool` script whose `_process`, `_physics_process`, `_ready` or `_input` changes state checks `Engine.is_editor_hint()`.
1. A script that extends or preloads a `@tool` script and runs in the editor is itself `@tool`.
1. An `EditorPlugin` defines `_exit_tree` and removes everything `_enter_tree` added, with matching `add_*`/`remove_*` pairs.
1. An `EditorScript` is `@tool` and defines `_run`.
1. `project.godot` `config/features` major.minor matches the pinned engine version and the installed binary's `--version`.
1. An engine upgrade lands as its own commit containing only Upgrade Project Files output, before any code changes.
1. A C# project's `Godot.NET.Sdk` version matches the engine version, and no web export preset exists in a C# project.
1. Every `.gdextension` file sets `compatibility_minimum` no higher than the pinned engine version, with libraries present for each exported platform.
1. Data authored as Resources is saved as text `.tres`, not `.res`, unless LFS tracks it.
1. No `.tscn` or `.tres` in git contains conflict markers (`<<<<<<<`).
1. After a headless import (`godot --headless --import`), `git status --porcelain` shows no new churn in `.uid`, `.import` or `project.godot`.

## What a tool could check automatically

- **VCS hygiene:**
  - Parse `.gitignore` and `.gitattributes` against the required entries (rules 1–4).
  - Report `git ls-files .godot`.
  - Report `git config core.autocrlf` when it is `true`.
  - Report binaries over N MB that LFS does not track.
- **UID integrity:**
  - Find scripts and shaders without a `.uid` and orphaned `.uid` files.
  - Find duplicate `uid://` values across `.uid`, `.import` and scene headers.
  - Find `ext_resource uid="uid://…"` values that do not resolve to any known UID.
- **Import completeness:** every importable asset has a `.import` file. Then run `--headless --import` and diff the tree for churn.
- **Engine pin:**
  - Compare `config/features` in `project.godot`, `.godotrc`/`global.json`/csproj SDK, and `"$GODOT_BIN" --version` (e.g. `4.7.2.stable.official…`).
  - Report a mismatch in major.minor, and a patch mismatch as a warning.
- **Addons:** list `addons/*/plugin.cfg` (name, version) and cross-check a manifest, `plug.gd` tags or commits, or `addons.jsonc` `checkout`. Flag:
  - unpinned branches such as `main`
  - a missing licence file
  - an addon missing from the manifest
  - enabled plugins (`[editor_plugins] enabled=`) whose folder is missing
- **`@tool` lint:** use a regex or a GDScript parse to find `@tool` files whose lifecycle callbacks mutate state without `Engine.is_editor_hint()`, `add_child` without setting `owner` in tool code, and `EditorPlugin` subclasses without `_exit_tree`.
- **Naming:** report non-snake_case paths, case-collisions and spaces in paths.
- **Scene health:** report conflict markers, binary `.scn`/`.res` outside LFS, and scenes still carrying `load_steps=` in a project on 4.6+, which points to a missed Upgrade Project Files run.
- **GDExtension:**
  - Check that `compatibility_minimum`/`maximum` cover the engine pin.
  - Check that every `[libraries]` path exists.
  - Flag `reloadable=true` in release-only setups as a warning.
- **C#:** flag a web export preset in `export_presets.cfg` together with a `.csproj`, and a csproj SDK version that does not match the engine.

## Pitfalls

- C# web export does not exist in 4.7. Choose GDScript or GDExtension for web targets.
- An extension built for a newer API level silently fails to load on an older editor. Build for the lowest version you need.
- Double-precision engine builds need extensions built with double precision.
- `@tool` code runs on scene open with no undo and can crash the editor or corrupt a scene. Inherited scripts do not inherit `@tool`.
- Nodes created by tool code vanish on save unless `owner` is set.
- Moving files in a file manager or IDE without their `.uid` gives UID warnings on other machines.
- Opening a project in a newer minor version rewrites many files. Mixing that churn with feature work makes review impossible.
- `core.autocrlf=true` on Windows marks every file as modified.
- Adding LFS after binaries are already committed requires rewriting history.
- Asset Store and Asset Library installs record no pinned version in the project.
- Godot reads only `plugin.cfg` `version`, which is easy to forget when updating a vendored addon.
- A `.gdignore`d folder cannot be loaded at runtime.
- C# hot reload keeps only exported variables, and new exports or signals need a rebuild.
- Godot's MIT licence and COPYRIGHT.txt notices must ship with the game, in addition to addon licences.

## Risks and uncertainties

- The GDExtension tutorial pages moved in the 4.7 docs: `what_is_gdextension` and `gdextension_file` return 404 under `/en/4.7/`. Some field-level claims come from the stable and 4.4/4.5 pages.
- Exact release dates for 4.3–4.6 were not confirmed. 4.7 is dated about 2026-06-18 (Phoronix), and 4.7.1 came about 4 weeks later (gamedev.net).
- Reports of 4.7 C# hot reload and wasm64 web export come only from secondary coverage.

## Sources

Official docs and posts:

- https://godotengine.org/releases/4.4/ , /4.5/ , /4.6/ , /4.7/ (release notes)
- https://docs.godotengine.org/en/4.7/tutorials/migrating/upgrading_to_godot_4.7.html , upgrading_to_godot_4.6.html
- https://docs.godotengine.org/en/4.7/tutorials/best_practices/version_control_systems.html , project_organization.html
- https://docs.godotengine.org/en/4.7/tutorials/assets_pipeline/import_process.html
- https://docs.godotengine.org/en/4.7/tutorials/plugins/running_code_in_the_editor.html , plugins/editor/making_plugins.html , import_plugins.html , index.html
- https://docs.godotengine.org/en/4.6/classes/class_editordock.html
- https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/gdscript_exports.html , cross_language_scripting.html
- https://docs.godotengine.org/en/4.7/tutorials/scripting/c_sharp/index.html , c_sharp_basics.html
- https://docs.godotengine.org/en/4.7/tutorials/scripting/cpp/about_godot_cpp.html , cpp/build_system/scons.html
- https://docs.godotengine.org/en/stable/engine_details/engine_api/gdextension/gdextension_file.html
- https://docs.godotengine.org/en/4.7/tutorials/performance/cpu_optimization.html , general_optimization.html
- https://docs.godotengine.org/en/4.7/about/faq.html , complying_with_licenses.html
- https://godotengine.org/article/uid-changes-coming-to-godot-4-4/ (2025-01-15)
- https://godotengine.org/article/introducing-the-godot-asset-store/ (2026-05-22)
- https://godotengine.org/article/live-from-godotcon-boston-web-dotnet-prototype/ (2025-05-09)

Source code and PRs:

- https://github.com/godotengine/godot/pull/106125 (draft, last activity 2026-09-14)
- https://raw.githubusercontent.com/godotengine/godot/master/editor/version_control/editor_vcs_interface.cpp
- https://github.com/godotengine/godot-cpp (README)

Project repos:

- https://godot-rust.github.io/book/toolchain/compatibility.html , https://godot-rust.github.io/book/migrate/v0.5.html
- https://github.com/imjp94/gd-plug , https://github.com/chickensoft-games/GodotEnv
- https://github.com/github/gitignore/blob/main/Godot.gitignore

Secondary, dates only:

- https://phoronix.com/news/godot-4.7-released
- https://gamedev.net/news/4477/

Local:

- docs/research/15-web-asset-registry.md
- docs/research/05-testing.md
- docs/research/14-web-fast-feedback-loop.md
