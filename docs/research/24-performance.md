# Performance and profiling (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org/en/latest (may run ahead of 4.7), the 4.3–4.7 release notes and engine PRs. The benchmark script and probes are UNTESTED on 4.7.2.

Source note: the class and tutorial pages below were fetched from `docs.godotengine.org/en/latest/` on 2026-11-13. That branch may already be post-4.7 (4.8-dev). Claims that are version-sensitive are tied to release notes where possible. Swap `/latest/` for `/4.7/` when persisting, and re-check any page that differs.

## Executive summary

- Measure first. Godot exposes three layers of data:
  - the editor Profiler, Visual Profiler, Monitors and ObjectDB Profiler (the last added in 4.6);
  - the scriptable `Performance` singleton with custom monitors, plus RenderingServer/Viewport render counters, including pipeline-compilation counters (added in 4.4);
  - native tracing through Tracy, Perfetto or Instruments, which needs a custom engine build (added in 4.6).
- All three layers can be read from a script, so a CLI kit can run a fixed benchmark scene and record frame-time percentiles and render counters. Two caveats:
  - `--headless` returns dummy rendering values.
  - Render counters are valid only after 2 rendered frames.
- The 4.3–4.7 changes that matter most:
  - 4.4 added ubershaders and pipeline precompilation (stutter mitigation), 2D batching on all renderers, and built-in experimental Jolt.
  - 4.5 added the shader baker, which cuts load time but does not remove stutter.
  - 4.6 made Jolt the default for new projects only and added the tracing profilers and ObjectDB snapshots.
  - 4.7 made Perfetto the default for Android builds.

## 1. Frame budget and measuring

- At 60 Hz the budget is 16.66 ms. The profiler uses the physics frame as its reference. When CPU and GPU work separately, the slower of the two sets the frame time. Think in ms, not FPS: removing 8 ms from a 10 ms frame is a 5x gain, but the same 8 ms from a 58 ms frame is small. Sources: [the_profiler](https://docs.godotengine.org/en/latest/tutorials/scripting/debug/the_profiler.html), [general_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/general_optimization.html).
- Time small sections by hand with `Time.get_ticks_usec()`. Repeat the timed code 1000 or more times and average, because caches and the scheduler add noise ([cpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/cpu_optimization.html)).
- Test for fill rate: disable V-Sync and compare FPS in a large window and a small one ([gpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/gpu_optimization.html)).
- Reliable benchmarks need a fixed scene and camera path, warmup frames, V-Sync off (`--disable-vsync`), many samples, and p50/p95/p99 plus max rather than mean FPS.
  - Do not use `--fixed-fps` for timing. It "disables real-time synchronization" ([command_line_tutorial](https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html)).
  - `--frame-delay` simulates CPU load, and `--benchmark`/`--benchmark-file` (editor builds) write startup/runtime timing as JSON (same page).
  - Warmup, percentiles and the methodology as a whole: UNVERIFIED as an official Godot recommendation. It is standard practice.

## 2. Built-in tools

- **Profiler.** It is off by default because "profiling is performance-intensive". It shows Frame/Physics/Idle time and script functions, as Inclusive or Self time. Autostart (added in 4.4) catches the first seconds of loading. `--profiling` turns on script-debugger profiling from the CLI. Sources: [the_profiler](https://docs.godotengine.org/en/latest/tutorials/scripting/debug/the_profiler.html), [4.4 notes](https://godotengine.org/releases/4.4/).

- **Visual Profiler.** It shows per-frame CPU/GPU render time. UNVERIFIED: no current docs page describes it. `--gpu-profile` prints the GPU tasks that took the most time ([CLI](https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html)).

- **Monitors.** `Performance.get_monitor(Performance.X)` has 60 built-in monitors:

  - time: TIME_FPS, TIME_PROCESS, TIME_PHYSICS_PROCESS, TIME_NAVIGATION_PROCESS;
  - memory; OBJECT_COUNT, OBJECT_RESOURCE_COUNT, OBJECT_NODE_COUNT, OBJECT_ORPHAN_NODE_COUNT;
  - RENDER_TOTAL\_{OBJECTS,PRIMITIVES,DRAW_CALLS}\_IN_FRAME and video/texture/buffer memory;
  - physics 2D/3D; navigation (combined, 2D and 3D);
  - PIPELINE_COMPILATIONS\_{CANVAS,MESH,SURFACE,DRAW,SPECIALIZATION}.

  Some monitors are debug-only and return 0 in release exports, and some update about once per second ([Performance](https://docs.godotengine.org/en/latest/classes/class_performance.html)).

- **Custom monitors.** `Performance.add_custom_monitor("game/enemies", callable)` works in debug and release exports. The editor graphs them under Debugger > Monitors ([custom_performance_monitors](https://docs.godotengine.org/en/latest/tutorials/scripting/debug/custom_performance_monitors.html)).

- **RenderingServer counters.**

  - `RenderingServer.get_rendering_info(RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME | ..._PIPELINE_COMPILATIONS_* | ..._VIDEO_MEM_USED)` returns 0 until at least 2 frames have rendered ([RenderingServer.xml](https://raw.githubusercontent.com/godotengine/godot/master/doc/classes/RenderingServer.xml)).
  - Per viewport: `Viewport.get_render_info(RENDER_INFO_TYPE_VISIBLE|SHADOW|CANVAS, RENDER_INFO_DRAW_CALLS_IN_FRAME)` ([Viewport](https://docs.godotengine.org/en/latest/classes/class_viewport.html)).
  - CPU/GPU render time: `viewport_set_measure_render_time` then `viewport_get_measured_render_time_cpu/gpu`, plus `get_frame_setup_time_cpu()` ([RenderingServer.xml](https://raw.githubusercontent.com/godotengine/godot/master/doc/classes/RenderingServer.xml)).

- **Headless.** `--headless` = `--display-driver headless --audio-driver Dummy`. "Most functions from RenderingServer will return dummy values" in that mode ([RenderingServer docs](https://docs.godotengine.org/en/latest/classes/class_renderingserver.html)). Render counters therefore need a real display or Xvfb. CPU-only checks such as script time and node/orphan counts work headless.

- **ObjectDB Profiler (added in 4.6).** Debugger > ObjectDB Profiler.

  - Take snapshots, then use "Diff Against" for per-class instance deltas, inbound and outbound references, and RefCounted cycles.
  - It does not see native classes that are not exposed to scripting ([objectdb_profiler 4.6](https://docs.godotengine.org/en/4.6/tutorials/scripting/debug/objectdb_profiler.html), [4.6 notes](https://godotengine.org/releases/4.6/)).

## 3. External profilers

| Tool                                    | Status                                                                                                                                                                                                                 | Source                                                                                                                           |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Tracy                                   | Added in 4.6. Needs a custom build: `scons target=template_release debug_symbols=yes profiler=tracy profiler_path=...`. GDScript zones arrived in PR #113279 and memory macros in PR #112702. Docs cite Tracy v0.13.0. | [4.6 notes](https://godotengine.org/releases/4.6/), [docs PR #11484](https://github.com/godotengine/godot-docs/pull/11484/files) |
| Perfetto                                | Added in 4.6 (`profiler=perfetto`, Android). Since 4.7 it is the default tracing tool for Android editor and template builds.                                                                                          | [4.7 notes](https://godotengine.org/releases/4.7/)                                                                               |
| Instruments                             | Named as supported in the 4.6 notes. The docs list it under sampling profilers.                                                                                                                                        | [4.6 notes](https://godotengine.org/releases/4.6/)                                                                               |
| perf / HotSpot / VerySleepy / Callgrind | These are sampling profilers that need `debug_symbols=yes`. Only Callgrind is shown on cpu_optimization. UNVERIFIED: the current URL of the sampling-profilers page (it returned 404).                                 | [cpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/cpu_optimization.html)                           |
| Superluminal                            | UNVERIFIED: no official Godot page found.                                                                                                                                                                              | —                                                                                                                                |
| RenderDoc                               | Usable on Vulkan/D3D12 builds. UNVERIFIED: no official 4.7 page was fetched. `--gpu-validation` turns on API validation layers.                                                                                        | [CLI](https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html)                                        |

The Tracy integration came in PR #104851, which added the `profiler=` SCons option for tracy and perfetto. Its merge version was confirmed only through the 4.6 notes.

## 4. CPU-side costs

- **Typed GDScript.** "typed GDScript improves performance by using optimized opcodes when operand/argument types are known at compile time". Turn on the `UNTYPED_DECLARATION` warning to enforce it ([static_typing](https://docs.godotengine.org/en/latest/tutorials/scripting/gdscript/static_typing.html)). The size of the speedup is UNVERIFIED.

- **Nodes have a cost.** Fewer nodes doing more work can be faster. `remove_child` can beat hiding or pausing a node. Servers bypass the SceneTree. Use object pooling for physics objects (and against C# GC) ([cpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/cpu_optimization.html)).

- **Signals vs polling, and `_process` discipline.** Use `set_process(false)` when idle, cache `@onready` refs, and avoid per-frame Array/Dictionary/String allocation. UNVERIFIED: this is common practice with no official benchmark found.

- **Threading.**

  - The active scene tree is not thread-safe. Build subtrees off-tree and attach them with `add_child.call_deferred(...)`.
  - Most servers are thread-safe, but AStar2D/3D/AStarGrid2D are not.
  - Array/Dictionary resizes need a Mutex.
  - Do not modify one Resource from several threads.
  - Rendering thread model "Separate" has known bugs. Physics "Run on Separate Thread" is a separate setting.

  Source: [thread_safe_apis](https://docs.godotengine.org/en/latest/tutorials/performance/thread_safe_apis.html).

- **Threads and WorkerThreadPool.** Create threads ahead of time ("slow, especially on Windows") ([using_multiple_threads](https://docs.godotengine.org/en/latest/tutorials/performance/using_multiple_threads.html)). In WorkerThreadPool, "Every task must be waited for completion", and using it for cheap work can be slower ([WorkerThreadPool](https://docs.godotengine.org/en/latest/classes/class_workerthreadpool.html)).

```gdscript
func _process(_d: float) -> void:
    var gid := WorkerThreadPool.add_group_task(_step_enemy, enemies.size())
    WorkerThreadPool.wait_for_group_task_completion(gid)  # enemies.size() must not change meanwhile
func _step_enemy(i: int) -> void:
    enemies[i].tick()  # touch only data, never the scene tree
```

- **Servers.** Use them for tens of thousands of instances per frame. RIDs are manual: keep a reference to the Resource yourself, because the server does not refcount it. Free RIDs with `RenderingServer.free_rid` (UNVERIFIED name; check the class reference) ([using_servers](https://docs.godotengine.org/en/latest/tutorials/performance/using_servers.html)).
- **MultiMesh.** One draw primitive draws up to millions of instances, but there is no per-instance culling. Split the instances into one MultiMesh per area. Set `transform_format` before `instance_count`, and use `visible_instance_count` to draw fewer ([using_multimesh](https://docs.godotengine.org/en/latest/tutorials/performance/using_multimesh.html)).

## 5. Loading, memory, stutter

- **Threaded loading.**
  - `ResourceLoader.load_threaded_request(path, "", use_sub_threads, CACHE_MODE_REUSE)` starts the load.
  - Poll `load_threaded_get_status(path, progress)` once per frame, not in a loop.
  - `load_threaded_get` blocks until loading finishes ([ResourceLoader](https://docs.godotengine.org/en/latest/classes/class_resourceloader.html)).
  - `preload` resolves at script compile/load time, and `load` is synchronous and cached (CACHE_MODE_REUSE is the default).

```gdscript
func _process(_d: float) -> void:
    var p: Array = []
    if ResourceLoader.load_threaded_get_status(LEVEL, p) == ResourceLoader.THREAD_LOAD_LOADED:
        get_tree().change_scene_to_packed(ResourceLoader.load_threaded_get(LEVEL))
```

- **Pipeline stutter** ([pipeline_compilations](https://docs.godotengine.org/en/latest/tutorials/performance/pipeline_compilations.html)):
  - Since 4.4, ubershaders and precompilation during load mitigate it.
  - Monitor spikes outside loading screens mean hitches. Surface spikes mean a feature was not enabled ahead of time. Any DRAW compilations should be reported as bugs.
  - Spawned effects: keep a hidden instance in an always-present node.
  - Compatibility renderer: show materials and particles for at least 1 frame during loading.
  - The shader baker (4.5, per export preset) cuts load time but "will generally not resolve existing stutters". It does not work for Compatibility, web or headless exports.
- **Memory and leaks.**
  - Watch OBJECT_ORPHAN_NODE_COUNT and OBJECT_COUNT over time ([Performance](https://docs.godotengine.org/en/latest/classes/class_performance.html)).
  - Use ObjectDB snapshot diffs (4.6+).
  - Running with `--verbose` reports leaked instances at exit. UNVERIFIED: the exact flag behaviour was not confirmed on the CLI page.

## 6. Rendering: 2D and 3D

- **2D batching** works on all renderers since 4.4 and "drastically reduces the number of draw calls" ([4.4 notes](https://godotengine.org/releases/4.4/)). Before that, the 4.2 docs said Vulkan renderers did not batch 2D ([4.2 gpu_optimization](https://docs.godotengine.org/en/4.2/tutorials/performance/gpu_optimization.html)). Batches break on texture and material changes.
  - 4.7: AtlasTexture tiling in TextureRect reduces texture changes on low-end devices ([4.7 notes](https://godotengine.org/releases/4.7/)).
  - UNVERIFIED: the `rendering/2d/batching/item_buffer_size` default of 16384 (seen only on a commit mirror).
- **Mesh LOD.**
  - Generated automatically on import of glTF, .blend, FBX and Collada. OBJ needs Import As: Scene.
  - The threshold is Rendering > Mesh LOD > LOD Change > Threshold Pixels, default 1 px. `Viewport.mesh_lod_threshold` sets it per viewport and `lod_bias` per node.
  - It can cause issues on skinned meshes ([mesh_lod](https://docs.godotengine.org/en/latest/tutorials/3d/mesh_lod.html)).
- **Visibility ranges (HLOD).** Use begin/end/margins and `visibility_parent`. Fade mode Disabled is cheapest, because fades force transparency ([visibility_ranges](https://docs.godotengine.org/en/latest/tutorials/3d/visibility_ranges.html)).
- **Occlusion culling** ([occlusion_culling](https://docs.godotengine.org/en/latest/tutorials/3d/occlusion_culling.html), [Viewport](https://docs.godotengine.org/en/latest/classes/class_viewport.html)):
  - Enable it in project settings, then bake an OccluderInstance3D.
  - It costs CPU, because Embree rasterizes the occluders.
  - It is best indoors. It helps the Mobile renderer most, since Mobile has no depth prepass.
  - Moving a baked occluder rebuilds the BVH, which is expensive.
  - Web templates do not support it by default.
- **Shadows.** Use smaller shadow maps, and turn off shadows on small or distant lights ([gpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/gpu_optimization.html)). `positional_shadow_atlas_size = 0` disables omni and spot shadows ([Viewport](https://docs.godotengine.org/en/latest/classes/class_viewport.html)).
- **GI cost, from cheapest:** ReflectionProbe (update Once) < LightmapGI < VoxelGI < SSIL < SDFGI. VoxelGI, SSIL and SDFGI are Forward+ only. On Mobile, use only LightmapGI and ReflectionProbes. SSAO is costly on low-end hardware ([GI intro](https://docs.godotengine.org/en/latest/tutorials/3d/global_illumination/introduction_to_global_illumination.html)).

## 7. Physics and navigation

- **Jolt timeline.** Built in as experimental in 4.4, enabled with `physics/3d/physics_engine` ([4.4 notes](https://godotengine.org/releases/4.4/)). Since 4.6 it is the default for new projects, and existing projects are not switched ([4.6 notes](https://godotengine.org/releases/4.6/), [using_jolt_physics](https://docs.godotengine.org/en/latest/tutorials/physics/using_jolt_physics.html)).
- **Jolt settings and costs.**
  - Settings live under `physics/jolt_physics_3d`.
  - Generate All Kinematic Contacts can waste a lot of CPU.
  - The ray-cast face index adds about 25% memory to ConcavePolygonShape3D.
  - Kinematic bodies against concave or heightmap shapes are a common hotspot.
  - Run on Separate Thread with Jolt is experimental.
- **Physics in general.** Use simple collision shapes, and pool or remove off-screen bodies. A lower tick rate cuts CPU but adds jitter and input lag. Interpolation is far cheaper than a physics tick ([cpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/cpu_optimization.html)).
  - Physics interpolation came to 2D in 4.3 and 3D in 4.4, and moved into SceneTree in 4.5.
  - Setting keys from memory: `physics/common/physics_ticks_per_second` (default 60), `physics/common/max_physics_steps_per_frame`, `physics/common/physics_interpolation`. UNVERIFIED key spelling, so check against ProjectSettings.
- **TileMapLayer chunk physics (4.5)** merges cell shapes into fewer bodies ([4.5 notes](https://godotengine.org/releases/4.5/)).
- **Navigation.**
  - 4.4: map sync moved to an async background thread ([4.4 notes](https://godotengine.org/releases/4.4/)).
  - 4.5: a dedicated 2D server, and async navigation as an opt-in ([4.5 notes](https://godotengine.org/releases/4.5/)).
  - Navmesh chunking (4.3) reduces allocation ([4.3 notes](https://godotengine.org/releases/4.3/)).
  - TIME_NAVIGATION_PROCESS and the NAVIGATION\_\* monitors measure the cost.

## 8. Low-end targets

- **Web.** Compatibility (WebGL 2) only. Single-threaded export is the default since 4.3, and slower. Thread Support needs COOP/COEP cross-origin isolation headers. Browsers pause inactive tabs ([exporting_for_web](https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_web.html)). WASM SIMD came in 4.5 ([4.5 notes](https://godotengine.org/releases/4.5/)).
- **Mobile.** Tile GPUs make post-processing and viewport textures expensive. Use VRAM compression and keep transparency small ([gpu_optimization](https://docs.godotengine.org/en/latest/tutorials/performance/gpu_optimization.html)). The Mobile renderer uses F16 since 4.5. Profile on device with Perfetto (default on Android since 4.7).
- **Steam Deck.** UNVERIFIED: no official Godot guidance found. Treat it as a Linux/Vulkan target and profile on device with Tracy or perf.

## Version-specific features

| Feature                                                                                                                                                               | Version                                                        | Source                                                                                                           |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| 2D physics interpolation, acyclic render graph, navmesh chunking, single-threaded web default                                                                         | 4.3 (2024-08-15)                                               | [4.3](https://godotengine.org/releases/4.3/)                                                                     |
| Jolt built in (experimental), ubershaders and pipeline precompilation, 2D batching on all renderers, 3D physics interpolation, async nav map sync, profiler autostart | 4.4 (2025-03-03)                                               | [4.4](https://godotengine.org/releases/4.4/)                                                                     |
| PIPELINE_COMPILATIONS\_\* monitors                                                                                                                                    | 4.4 (UNVERIFIED: inferred from the pipeline_compilations page) | [pipeline_compilations](https://docs.godotengine.org/en/latest/tutorials/performance/pipeline_compilations.html) |
| Shader baker, chunk TileMap physics, 2D navigation server, WASM SIMD, Mobile F16, SMAA                                                                                | 4.5                                                            | [4.5](https://godotengine.org/releases/4.5/)                                                                     |
| Jolt default for new projects, Tracy/Perfetto/Instruments, ObjectDB Profiler, D3D12 default on Windows, faster SSR                                                    | 4.6 (January 2026)                                             | [4.6](https://godotengine.org/releases/4.6/)                                                                     |
| Perfetto default for Android builds, per-pass environment UBO, AtlasTexture tiling                                                                                    | 4.7 (release date UNVERIFIED, mid-2026)                        | [4.7](https://godotengine.org/releases/4.7/)                                                                     |

## Checkable rules an agent should follow

1. Every new `.gd` file declares types for its variables, parameters and returns. Check: `UNTYPED_DECLARATION` is set to warn/error in `project.godot`, and `godot --check-only` is clean.
1. `_process` and `_physics_process` call no `get_node()`, `$Path`, `find_child`, `get_nodes_in_group` or `load()` (grep the function bodies).
1. No `Array()`, `{}`, `[]` literal or `PackedScene.instantiate()` inside `_process`, except in a documented pool (grep).
1. Scripts that only react to events use signals and call `set_process(false)`, or have no `_process` at all.
1. Scenes that are instantiated repeatedly (bullets, enemies) go through a pool node. Grep for `instantiate()` near timers or `_process`.
1. Worker-thread code (`Thread.start`, `WorkerThreadPool.add_*`) never touches tree nodes. Tree mutations use `call_deferred` or `set_deferred`.
1. Every `WorkerThreadPool.add_task` or `add_group_task` id is passed to a matching `wait_for_*` call.
1. Every `Thread.start` has a matching `wait_to_finish()` in `_exit_tree`.
1. AStar2D, AStar3D and AStarGrid2D objects are never shared across threads.
1. Level loads use `load_threaded_request` plus `load_threaded_get_status` polling. `load_threaded_get` is called only after the status is LOADED.
1. Large assets are not `preload`ed in autoloads. `preload` of more than about 1 MB of scenes in an autoload is flagged (the threshold is an assumption, not an official number).
1. Every `RenderingServer.*_create()` or `PhysicsServer*.*_create()` RID is freed in `_exit_tree` or `_notification(NOTIFICATION_PREDELETE)`.
1. A MultiMesh sets `transform_format` before `instance_count`. Very large MultiMeshes are split per region.
1. Every 3D mesh import keeps LOD generation on unless a comment justifies turning it off (`.import`: `meshes/generate_lods=true`).
1. Visibility-range fade mode is Disabled unless a fade is a design requirement.
1. OccluderInstance3D nodes are static. Flag any script that moves one.
1. VoxelGI, SDFGI and SSIL are absent from scenes when the renderer is `mobile` or `gl_compatibility`.
1. Web exports use the Compatibility renderer. Thread Support is on only when the host sends COOP/COEP headers.
1. 3D projects created before 4.6 state their physics engine explicitly. Jolt projects avoid non-default joint soft-limit properties.
1. The physics tick rate stays at 60 unless a measured reason is recorded. Interpolation is on if the tick rate is lowered.
1. Performance claims cite a benchmark artifact (scene, commit, Godot version, device, p50/p95/p99), never one FPS reading.
1. Effects spawned at runtime are pre-warmed in the loading scene, whose pipeline-compilation counters must settle before gameplay.
1. Custom monitors are registered with category names (`game/...`) and removed in `_exit_tree`.

## What a tool could check automatically

- **Static checks.** Grep or parse `.gd` files for rules 2–3 and 5–9. Parse `project.godot` for the renderer, physics engine, tick rate, interpolation, occlusion culling and GDScript warning levels. Parse `.import` files for `generate_lods` and VRAM compression. Parse `.tscn` files for VoxelGI/SDFGI under the Mobile or Compatibility renderer, and for fade modes. Parse `export_presets.cfg` for the shader baker and web thread support.
- **Orphan/leak smoke test (headless OK).** Load each scene, free it, and wait 2 frames. Assert that `OBJECT_ORPHAN_NODE_COUNT` returns to baseline and `OBJECT_COUNT` does not grow over N cycles. These are debug-only monitors, so use a debug build.
- **Benchmark scene (needs a display or Xvfb, not `--headless`).** Run `godot --path P --disable-vsync res://bench/bench.tscn -- --frames=600`. Parse the `BENCH_RESULT` line (judge the run by the log, not the exit code). Compare against a stored baseline with a tolerance.

```gdscript
extends Node3D
const WARMUP := 120
var frames := 600
var _t: PackedFloat64Array = []
var _n := 0
var _last := 0
func _ready() -> void:
    RenderingServer.viewport_set_measure_render_time(get_viewport().get_viewport_rid(), true)
    _last = Time.get_ticks_usec()
func _process(_d: float) -> void:
    var now := Time.get_ticks_usec()
    _n += 1
    if _n > WARMUP: _t.append((now - _last) / 1000.0)
    _last = now
    $CameraPath/PathFollow3D.progress_ratio = float(_n) / (WARMUP + frames)  # fixed path
    if _t.size() >= frames: _finish()
func _pct(s: PackedFloat64Array, p: float) -> float:
    return s[clampi(int(ceil(p * s.size())) - 1, 0, s.size() - 1)]
func _finish() -> void:
    var s := _t.duplicate(); s.sort()
    var vp := get_viewport().get_viewport_rid()
    var r := {
        "godot": Engine.get_version_info().string, "adapter": RenderingServer.get_video_adapter_name(),
        "p50_ms": _pct(s, .5), "p95_ms": _pct(s, .95), "p99_ms": _pct(s, .99), "max_ms": s[-1],
        "draw_calls": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_DRAW_CALLS_IN_FRAME),
        "primitives": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_TOTAL_PRIMITIVES_IN_FRAME),
        "vram_bytes": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_VIDEO_MEM_USED),
        "pipeline_draw": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_DRAW),
        "pipeline_surface": RenderingServer.get_rendering_info(RenderingServer.RENDERING_INFO_PIPELINE_COMPILATIONS_SURFACE),
        "cpu_render_ms": RenderingServer.viewport_get_measured_render_time_cpu(vp),
        "gpu_render_ms": RenderingServer.viewport_get_measured_render_time_gpu(vp),
        "nodes": Performance.get_monitor(Performance.OBJECT_NODE_COUNT),
        "orphans": Performance.get_monitor(Performance.OBJECT_ORPHAN_NODE_COUNT),
    }
    print("BENCH_RESULT " + JSON.stringify(r))
    get_tree().quit()
```

- The kit side computes deltas against the baseline. It fails when p95/p99 regress by more than X%, or when any `pipeline_draw > 0` (the docs say draw-time compilations are bugs).
- The pipeline counters are cumulative or per frame; this is UNVERIFIED. Read them before and after the warmup and take the difference.
- **Pipeline-stutter probe.** Sample the PIPELINE_COMPILATIONS\_\* monitors every frame after the loading screen. Any increase in SURFACE or DRAW during gameplay is a finding.
- **Startup timing.** `--benchmark-file out.json` (editor builds only).
- **Doctor checks.** Detect Xvfb (needed for render counters on CI), a Tracy-enabled custom build and perf. Report them, never require them.

## Pitfalls

- Using `--headless` for render benchmarks returns dummy RenderingServer values ([RenderingServer](https://docs.godotengine.org/en/latest/classes/class_renderingserver.html)).
- Reading render info before 2 frames gives 0 ([RenderingServer.xml](https://raw.githubusercontent.com/godotengine/godot/master/doc/classes/RenderingServer.xml)).
- Debug-only monitors read 0 in release exports, and some update only about once per second ([Performance](https://docs.godotengine.org/en/latest/classes/class_performance.html)).
- `--fixed-fps` disables real-time sync, so frame times measured with it are not real.
- The editor profiler slows the game significantly. Do not quote absolute ms taken with it running.
- The shader baker does not fix gameplay stutter. Changing MSAA or other features mid-game triggers new compilations ([pipeline_compilations](https://docs.godotengine.org/en/latest/tutorials/performance/pipeline_compilations.html)).
- Projects created before 4.6 are not switched to Jolt. Do not assume the default.
- A MultiMesh is culled as one unit. One large MultiMesh can cost more than nodes.
- Alpha fades on visibility ranges add transparency cost and sorting glitches.
- Moving occluders rebuilds the BVH every frame.
- Threaded web exports fail without COOP/COEP headers.
- WorkerThreadPool tasks that are never waited on leak.
- The 4.4-dev canvas batching caused a Forward+ 2D regression in one report ([issue #99420](https://github.com/godotengine/godot/issues/99420)). Measure after an engine upgrade.

## Conflicts and unverified items

- CONFLICT DETECTED: the [4.2 gpu_optimization](https://docs.godotengine.org/en/4.2/tutorials/performance/gpu_optimization.html) page says Vulkan renderers do not batch 2D. The [4.4 notes](https://godotengine.org/releases/4.4/) say batching works on all backends. The 4.4 notes apply to 4.4 and later.
- CONFLICT DETECTED: the 4.6 release notes name Instruments as a tracing profiler. Docs PR #11484 lists only Tracy and Perfetto as tracing profilers and puts Instruments under sampling profilers.
- UNVERIFIED: exact physics setting keys; `free_rid` name; `item_buffer_size` default; Visual Profiler docs; Superluminal and RenderDoc docs; Steam Deck guidance; the speedup size from typed GDScript; signals vs polling cost; whether the pipeline counters are cumulative; the 4.7 release date; that the PIPELINE monitors arrived in 4.4; `--verbose` leak reporting.

## Sources

- Godot release notes: [4.3](https://godotengine.org/releases/4.3/), [4.4](https://godotengine.org/releases/4.4/), [4.5](https://godotengine.org/releases/4.5/), [4.6](https://godotengine.org/releases/4.6/), [4.7](https://godotengine.org/releases/4.7/). Used for the version boundaries.
- Class references: [Performance](https://docs.godotengine.org/en/latest/classes/class_performance.html), [Viewport](https://docs.godotengine.org/en/latest/classes/class_viewport.html), [RenderingServer.xml](https://raw.githubusercontent.com/godotengine/godot/master/doc/classes/RenderingServer.xml), [ResourceLoader](https://docs.godotengine.org/en/latest/classes/class_resourceloader.html), [WorkerThreadPool](https://docs.godotengine.org/en/latest/classes/class_workerthreadpool.html).
- Tutorials: [the_profiler](https://docs.godotengine.org/en/latest/tutorials/scripting/debug/the_profiler.html), [custom monitors](https://docs.godotengine.org/en/latest/tutorials/scripting/debug/custom_performance_monitors.html), [ObjectDB profiler 4.6](https://docs.godotengine.org/en/4.6/tutorials/scripting/debug/objectdb_profiler.html), [general](https://docs.godotengine.org/en/latest/tutorials/performance/general_optimization.html), [CPU](https://docs.godotengine.org/en/latest/tutorials/performance/cpu_optimization.html) and [GPU](https://docs.godotengine.org/en/latest/tutorials/performance/gpu_optimization.html) optimization, [pipeline compilations](https://docs.godotengine.org/en/latest/tutorials/performance/pipeline_compilations.html), [thread-safe APIs](https://docs.godotengine.org/en/latest/tutorials/performance/thread_safe_apis.html), [threads](https://docs.godotengine.org/en/latest/tutorials/performance/using_multiple_threads.html), [servers](https://docs.godotengine.org/en/latest/tutorials/performance/using_servers.html), [MultiMesh](https://docs.godotengine.org/en/latest/tutorials/performance/using_multimesh.html), [mesh LOD](https://docs.godotengine.org/en/latest/tutorials/3d/mesh_lod.html), [visibility ranges](https://docs.godotengine.org/en/latest/tutorials/3d/visibility_ranges.html), [occlusion culling](https://docs.godotengine.org/en/latest/tutorials/3d/occlusion_culling.html), [GI intro](https://docs.godotengine.org/en/latest/tutorials/3d/global_illumination/introduction_to_global_illumination.html), [Jolt](https://docs.godotengine.org/en/latest/tutorials/physics/using_jolt_physics.html), [static typing](https://docs.godotengine.org/en/latest/tutorials/scripting/gdscript/static_typing.html), [web export](https://docs.godotengine.org/en/latest/tutorials/export/exporting_for_web.html), [CLI](https://docs.godotengine.org/en/latest/tutorials/editor/command_line_tutorial.html).
- [godot-docs PR #11484](https://github.com/godotengine/godot-docs/pull/11484/files) for the tracing profilers page and its SCons flags. Engine PRs #104851, #112702 and #113279 were seen through a git mirror and are cited by number only.
- [godot issue #99420](https://github.com/godotengine/godot/issues/99420) for the 4.4-dev 2D batching regression report.

Concerns:

- Docs were read from `/en/latest/`, not `/4.7/`.
- The benchmark script is written from the APIs above but has not been run on 4.7.2. Mark it UNTESTED until a `live_godot` run confirms it, as the project rules require.
