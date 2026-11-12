# Game AI, navigation and procedural generation (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7), the 4.3–4.7.1 release notes and addon repos. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

- Godot 4.7 has a complete built-in navigation stack. It covers navmesh baking (editor or runtime, threaded), path queries, RVO avoidance, links and layers. Map sync has run on a background thread since 4.4, and 2D got its own NavigationServer2D in 4.5. The 4.6 and 4.7 release pages list no navigation features. 4.7.1 fixed one avoidance bug (GH-120249).
- `TileMap` is deprecated in favour of `TileMapLayer`, which arrived in 4.3. A deprecated-`TileMap` scan is a cheap and reliable lint.
- For AI architecture, **LimboAI** (MIT, C++ module or GDExtension; v1.8.1 targets 4.7.2) and **Beehave** (MIT, GDScript; v2.9.3 says it works with 4.7) are the maintained behaviour-tree choices. **Godot State Charts** (MIT, GDScript) covers hierarchical FSMs. Utility AI and GOAP have only minor addons or demos.
- Procgen determinism depends on using a dedicated `RandomNumberGenerator` per stream. `Array.shuffle()` and `pick_random()` use the global seed. The PCG32 algorithm is an "implementation detail", so golden seeds have to be pinned to a Godot version.

## 1. Navigation (NavigationServer2D/3D)

- **Nodes.** `NavigationRegion2D/3D` holds a `NavigationPolygon` or `NavigationMesh`. `NavigationAgent2D/3D` is an optional helper and never moves its parent. `NavigationLink2D/3D` connects polygons across gaps. `NavigationObstacle2D/3D` affects avoidance, and since 4.3 it can also affect or carve baking. Source: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_introduction_2d.html (4.7)
- **First-frame sync.** Map iteration 0 means the map has never synced, and path queries before the first sync come back empty. `map_get_iteration_id()` wraps back to 1. `map_force_update()` is deprecated because it is "incompatible with asynchronous updates". Source: https://docs.godotengine.org/en/stable/classes/class_navigationserver2d.html (4.7)
- **Baking.** In the editor, use the bake button. At runtime, call `bake_navigation_polygon(true)` or `bake_navigation_mesh(true)` for a threaded bake. Through the server, call `parse_source_geometry_data()` (main thread only, because the SceneTree is not thread-safe), then `bake_from_source_geometry_data_async()` on a worker thread. `NavigationMeshSourceGeometryData2D/3D` can be reused, for example to bake for several agent sizes. `parsed_geometry_type` chooses meshes, colliders or both. `source_geometry_mode` chooses root children or groups. Parsing visual meshes stalls the RenderingServer, so runtime rebakes should parse physics shapes. `cell_size` "should match the navigation map" cell size. Source: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_using_navigationmeshes.html (4.7)
- **Chunks.** `baking_rect` / `baking_rect_offset` (2D) and `filter_baking_aabb` plus `border_size` (3D) produce edge-aligned chunks for large worlds. In 3D, `border_size` works on xz only. Added in 4.3. Sources: https://godotengine.org/releases/4.3/ and the baking page above.
- **Layers.** `navigation_layers` is an int bitmask. Changing the layers on a query is cheap. Changing a region's layers takes effect at the next map sync, which costs more. Source: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_using_navigationlayers.html (4.7)
- **Links.** A link has `start_position`, `end_position`, `bidirectional` and a search radius. The default radius is the project setting `navigation/2d_or_3d/default_link_connection_radius`. If no polygon lies within the radius, the link is disabled. A link "does not provide any specialized movement", so game code handles the jump or teleport, usually on the agent's `link_reached(details)` signal. Sources: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_using_navigationlinks.html and https://docs.godotengine.org/en/stable/classes/class_navigationagent2d.html (4.7)
- **Agent path following.** Call `get_next_path_position()` exactly once per `_physics_process`, after checking `is_navigation_finished()`. Calling it from signal callbacks risks recursion. Defaults: `path_desired_distance` 20, `target_desired_distance` 10, `path_max_distance` 100, `path_search_max_polygons` 4096. Use `is_target_reachable()` and `get_final_position()` to detect an unreachable target.
- **Avoidance (RVO).** Set `avoidance_enabled`, set `velocity` each frame and read `safe_velocity` from `velocity_computed`. Without a `target_position`, the safe velocity is zero. `avoidance_layers` and `avoidance_mask` work like physics layers. A higher `avoidance_priority` means the agent does not yield to lower-priority agents. `use_3d_avoidance` runs a separate simulation. Avoidance ignores navmesh and physics, and perfectly head-on tests often fail by design. Source: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_using_navigationagents.html (4.7)

```gdscript
func _ready() -> void:
    actor_setup.call_deferred()

func actor_setup() -> void:
    await get_tree().physics_frame  # wait for first map sync
    agent.target_position = goal

func _physics_process(_d: float) -> void:
    if agent.is_navigation_finished():
        return
    var next := agent.get_next_path_position()
    velocity = global_position.direction_to(next) * speed
    move_and_slide()
```

### Performance (navigation)

Source for all points: https://docs.godotengine.org/en/stable/tutorials/navigation/navigation_optimizing_performance.html (4.7)

- Parse simple collision shapes, not visual meshes. Raise `cell_size` and `cell_height` as far as quality allows. For flat, blocky levels, monotone or layers partitioning bakes faster than watershed. Never scale source geometry through node scale.
- Map resync is expensive. Merging by vertex is cheap, while merging by edge connection is expensive. The navigation performance monitors show the ratio.
- Do not set `target_position` every frame. Re-path only when the target has moved past a threshold, and stagger agents across frames.
- An **unreachable target** forces a search of every reachable polygon. Search cost scales with polygon and edge count, not world size, so per-tile navmeshes from TileMaps are costly.
- `AStarGrid2D.get_point_path()` is not thread-safe. Source: https://docs.godotengine.org/en/stable/classes/class_astargrid2d.html (4.7)

## 2. TileMapLayer and grid pathfinding

- `TileMap` is marked "Deprecated: Use multiple TileMapLayer nodes instead". The editor converts a TileMap with "Extract TileMap layers". `TileMapLayer` arrived in 4.3, and the old node is still supported "for the time being". Sources: https://docs.godotengine.org/en/stable/classes/class_tilemap.html (4.7) and https://godotengine.org/releases/4.3/
- `TileMapLayer` has `navigation_enabled`, `get_navigation_map()` / `set_navigation_map()`, `set_cell(coords, source_id, atlas_coords, alternative)` (a source of -1 erases the cell), `set_cells_terrain_connect()` and `set_cells_terrain_path()`. The terrain calls need terrain combinations defined in the TileSet. `update_internals()` forces the batched end-of-frame update and is expensive. Since 4.5, physics merges cell shapes into larger bodies. Sources: https://docs.godotengine.org/en/stable/classes/class_tilemaplayer.html (4.7) and https://godotengine.org/releases/4.5/
- **AStarGrid2D.** Set `region` (a Rect2i; `size` is deprecated), `cell_size`, `diagonal_mode`, `default_compute_heuristic` and `jumping_enabled`. Jumping disables weight scaling. `update()` is needed after changing region, size or offset, and it **clears solids and weights**. `set_point_solid`, `fill_solid_region` and `set_point_weight_scale` need no `update()`. `is_dirty()` reports a pending update. Source: https://docs.godotengine.org/en/stable/classes/class_astargrid2d.html (4.7)
- `allow_partial_path` on `get_id_path` and `get_point_path` (AStar2D, AStar3D, AStarGrid2D) was added in 4.3 by PR #88047. With a solid target it can be very slow. Sources: https://github.com/godotengine/godot/pull/88047 and the AStarGrid2D docs above.

```gdscript
var grid := AStarGrid2D.new()
grid.region = layer.get_used_rect()
grid.cell_size = Vector2(16, 16)
grid.diagonal_mode = AStarGrid2D.DIAGONAL_MODE_ONLY_IF_NO_OBSTACLES
grid.update()  # before marking solids; update() wipes them
for c in layer.get_used_cells():
    if layer.get_cell_tile_data(c).get_custom_data("solid"):
        grid.set_point_solid(c)
var path := grid.get_id_path(start, goal)
```

## 3. AI architecture patterns and addons

- **FSM.** Choose node-per-state (inspectable and scene-editable) or an enum plus `match` in code (cheap and testable). A hierarchical FSM nests the two. These are design patterns with no single official source, so they are offered as opinion.
- **LimboAI** (limbonaut/limboai). MIT. Ships as both a C++ module (custom engine build) and a GDExtension, which is "more convenient but somewhat limited". Provides behaviour trees with a visual editor, `BTPlayer`, a `LimboHSM` hierarchical FSM (no GUI editor), `BTState`, a blackboard with scopes and plans, and a runtime debugger. Releases: v1.8.0 (19 Jun, adds 4.7) and v1.8.1 (20 Aug 2026, engine builds on 4.7.2-stable). About 3.1k stars. Sources: https://github.com/limbonaut/limboai and https://github.com/limbonaut/limboai/releases
- **Beehave** (bitbrain/beehave). MIT, pure GDScript, node-based behaviour trees, runtime debug view, performance monitors, GdUnit tests. Latest release is v2.9.3 (18 Aug), "compatible with latest Godot 4.7". About 3.3k stars. Source: https://github.com/bitbrain/beehave/releases
  - CONFLICT DETECTED: the Beehave README maps "2.10+ to Godot 4.5+", but the newest tagged release is v2.9.3. Pin by tag and test against 4.7.2.
- **Godot State Charts** (derkork/godot-statecharts). MIT, GDScript and C#, statecharts built from nodes, guarded and delayed transitions, in-game debugger, supports "Godot 4 or later". No release or version was visible. Source: https://github.com/derkork/godot-statecharts
- **Utility AI GDExtension** (JarkkoPar). MIT, GDExtension. Provides utility agents, BTs, state trees and a node query system. Supports "Godot 4.1.2 or newer". Builds are Win64 and Linux64, with experimental web and macOS. About 108 stars. UNVERIFIED: whether it works with 4.7 or is still maintained. Source: https://github.com/JarkkoPar/Utility_AI_GDExtension
- **GOAP.** viniciusgerevini/godot-goap is an MIT **demo**, not an addon ("personal experiment not tested in high load"). Its planner, agent, actions and goals are worth reading as a reference. Source: https://github.com/viniciusgerevini/godot-goap
- **Perception.** Physics space queries are safe only in `_physics_process()`. Use `PhysicsRayQueryParameters2D.create(from, to)` with `collision_mask` and `exclude`. An empty Dictionary means no hit. `RayCast2D` is the code-free option. Areas cover vision cones and hearing radii. Source: https://docs.godotengine.org/en/stable/tutorials/physics/ray-casting.html (4.7)
- **Steering.** Godot has no built-in steering library. Seek, flee and arrive are written by hand and fed into `velocity`, or into the agent's `velocity` when RVO is used. UNVERIFIED: no maintained, official steering addon was confirmed.

## 4. Procedural generation

- **RNG.** The global RNG is seeded randomly by default. `seed(n)` makes it reproducible. A `RandomNumberGenerator` instance has its own `seed` and `state`. Set `seed` first, because it resets `state`, then restore `state`. Only assign `state` values that were read from `state`. Similar seeds give similar streams ("no avalanche effect"), so hash them, for example with `"name".hash()`. The algorithm (PCG32 today) "is an implementation detail and should not be depended upon". `rand_weighted()` returns -1 on an empty array. Sources: https://docs.godotengine.org/en/stable/classes/class_randomnumbergenerator.html and https://docs.godotengine.org/en/stable/tutorials/math/random_number_generation.html (4.7)
- `Array.pick_random()` and `shuffle()` "use a common, global random seed". Seeded generators should therefore shuffle with their own RNG, for example a Fisher-Yates loop over `rng.randi_range`. Source: https://docs.godotengine.org/en/stable/classes/class_array.html (4.7)
- **Noise.** `FastNoiseLite` defaults: `noise_type` Simplex Smooth, `seed` 0, `frequency` 0.01, FBM fractal, 5 octaves, `domain_warp_enabled` false, `offset`. Values are "mostly [-1, 1], but not always", and cellular types can exceed 1. Use `NoiseTexture2D` for baked textures. Source: https://docs.godotengine.org/en/stable/classes/class_fastnoiselite.html (4.7)
- **WFC.** AlexeyBond/godot-constraint-solving is MIT and written in GDScript. It supports TileMapLayer, TileMap (including some hex), and GridMap as a flat plane, with backtracking, multithreaded 2D generation, and rule inference from example maps. Full 3D is not implemented. Source: https://github.com/AlexeyBond/godot-constraint-solving
- **Gaea** (gaea-godot/gaea) is MIT and graph-based (2D and 3D). Gaea 2.0 targets Godot 4.4 and is "in early development"; use v1.x for 4.3 and earlier. UNVERIFIED: whether it works on 4.7. Source: https://github.com/gaea-godot/gaea
- **Runtime meshes.** `ArrayMesh` is "slightly faster" than `SurfaceTool`. `MeshDataTool` is slow. `ImmediateMesh` suits debug drawing and geometry rebuilt every frame. All four run on the CPU. Indexed arrays are faster. In `SurfaceTool`, set attributes before `add_vertex`, because the first vertex fixes the format. Call `generate_normals()` before `generate_tangents()`, and both before `commit()`. `SurfaceTool.generate_lod()` is deprecated; use `ImporterMesh.generate_lods()`. Sources: https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/index.html and https://docs.godotengine.org/en/stable/classes/class_surfacetool.html (4.7)

```gdscript
func generate(seed_value: int) -> void:
    var rng := RandomNumberGenerator.new()
    rng.seed = hash(seed_value)  # spread similar seeds
    var noise := FastNoiseLite.new()
    noise.seed = rng.randi()
    for x in w:
        for y in h:
            var n := noise.get_noise_2d(x, y)
            layer.set_cell(Vector2i(x, y), 0, Vector2i(0 if n < 0.0 else 1, 0))
```

## 5. Testing AI and procgen

These are practices, not official Godot guidance, so they are offered as opinion.

- **Golden seeds.** Commit a small set of seeds with a hash of their output (cells or vertices). Re-baseline when the Godot version changes, because the RNG algorithm is not guaranteed.
- **Invariants over N seeds.** Flood-fill connectivity, start-to-exit reachability through AStarGrid2D or a navmesh query (end point within ε of the target), room count and size bounds, no spawns inside solids.
- **Statistical tests.** Over 1k seeds, check tile-frequency or weighted-choice distributions with a chi-square tolerance band. Make the runs deterministic by fixing the seed list.
- **Headless navigation probes.** Wait for `map_get_iteration_id() > 0`, then call `map_get_path` for a list of point pairs and assert the path is non-empty and its final point lies near the target.

## Version-specific features

| Feature                                                          | Version                          | Source                                                           |
| ---------------------------------------------------------------- | -------------------------------- | ---------------------------------------------------------------- |
| AStarGrid2D class                                                | 4.0                              | UNVERIFIED (no release note checked)                             |
| `TileMapLayer` node; `TileMap` deprecated                        | 4.3                              | https://godotengine.org/releases/4.3/                            |
| Navmesh chunk baking (baking bounds, border_size)                | 4.3                              | https://godotengine.org/releases/4.3/                            |
| Obstacle `affect_navigation_mesh` / `carve_navigation_mesh`      | 4.3                              | https://godotengine.org/releases/4.3/                            |
| Agent `simplify_path` and server path simplification             | 4.3                              | https://godotengine.org/releases/4.3/                            |
| AStar `allow_partial_path`                                       | 4.3                              | https://github.com/godotengine/godot/pull/88047                  |
| Async (background-thread) map sync; new pathfinding heap         | 4.4                              | https://godotengine.org/releases/4.4/                            |
| Gaea 2.0 minimum                                                 | 4.4                              | https://github.com/gaea-godot/gaea                               |
| Dedicated NavigationServer2D; async region iterations            | 4.5                              | https://godotengine.org/releases/4.5/                            |
| TileMapLayer merged physics shapes                               | 4.5                              | https://godotengine.org/releases/4.5/                            |
| `path_search_max_polygons` / `max_distance`, `path_return_max_*` | UNVERIFIED (present in 4.7 docs) | class_navigationagent2d (4.7)                                    |
| Rotatable scene tiles; GridMap Bresenham paint                   | 4.6                              | https://godotengine.org/releases/4.6/                            |
| 2D Scene Paint Mode (PR 109360)                                  | 4.7                              | https://godotengine.org/releases/4.7/                            |
| Fix: agents re-added to avoidance after pause (GH-120249)        | 4.7.1                            | https://godotengine.org/article/maintenance-release-godot-4-7-1/ |
| LimboAI 1.8.x for 4.7; Beehave 2.9.3 for 4.7                     | 2026                             | addon release pages                                              |

## Checkable rules an agent should follow

1. No `type="TileMap"` node in `.tscn` files and no `TileMap.new()` or `extends TileMap` in `.gd` files. Use `TileMapLayer`.
1. No path query (`target_position =`, `map_get_path`, `query_path`) in `_ready()` unless it comes after `await get_tree().physics_frame`, `call_deferred`, or a `map_get_iteration_id() == 0` guard.
1. No `map_force_update(` calls, since the method is deprecated.
1. `get_next_path_position()` appears only in `_physics_process`, and only after an `is_navigation_finished()` check.
1. Avoidance agents with `avoidance_enabled = true` connect `velocity_computed` and assign `velocity`.
1. `parse_source_geometry_data` is never called from a `Thread` or `WorkerThreadPool` task.
1. Runtime rebakes use `bake_from_source_geometry_data_async` or `bake_navigation_*(true)`, never a synchronous bake in a gameplay loop.
1. Runtime-baked NavigationPolygon and NavigationMesh resources set `parsed_geometry_type` to static colliders, not meshes.
1. NavigationMesh `cell_size` and `cell_height` match the map's cell settings in the project settings.
1. No node scale on navmesh source geometry (scale ≠ 1 on parsed nodes).
1. `target_position` is not reassigned unconditionally inside `_physics_process` or `_process`; a distance threshold guards it.
1. After `AStarGrid2D.update()`, solids and weights are applied again, never before the update.
1. `AStarGrid2D.size` is not used; `region` is used instead.
1. Generators take a seed parameter and use a local `RandomNumberGenerator`. No global `randi()`, `randf()`, `randomize()`, `shuffle()` or `pick_random()` inside generation code.
1. `rng.state` is assigned only from a previously saved `state`, and after `seed`.
1. `FastNoiseLite.seed` comes from the generator's RNG, not the default 0 or `randi()`.
1. Noise thresholds do not assume a range strictly within [-1, 1] for cellular noise; clamp the value first.
1. `SurfaceTool` calls `generate_normals()` before `generate_tangents()`, and both before `commit()`.
1. No `SurfaceTool.generate_lod(` calls (deprecated).
1. `allow_partial_path=true` is not used where the target may be solid or disabled.
1. Addons are pinned to a tagged version recorded in the repo, and the LimboAI variant (module or GDExtension) is stated.
1. Every golden seed file records the Godot version it was made with.

## What a tool could check automatically

- **Deprecated TileMap scan.** Grep `.tscn` and `.tres` for `type="TileMap"` and `.gd` for `\bTileMap\b(?!Layer)`. Report each file and line with the 4.3 deprecation reference.
- **Seeded reproducibility.** Run the generator headless twice per seed (`godot --headless --script`), hash the output (`get_used_cells()` plus atlas coords, or the mesh arrays), and require identical hashes. A third run in a fresh process catches hidden global-RNG use. The run prints an explicit `SUMMARY seeds=N mismatches=0` line, so it is not judged by exit code alone.
- **Golden seeds.** Compare hashes against a committed JSON of `{seed, godot_version, hash}`. If the Godot version differs, report "re-baseline" instead of failing.
- **Connectivity and reachability.** Flood-fill walkable cells from the start, then assert that all required cells (exits, keys, spawns) are reached and the walkable fraction lies in a set band. Cross-check with `AStarGrid2D.get_id_path` and require a non-empty path.
- **Navmesh probes.** Load the scene, wait until `map_get_iteration_id(map) > 0`, and assert `get_process_info(INFO_POLYGON_COUNT) > 0`. For each probe pair, check that `map_get_path` is non-empty and that its last point is within ε of `map_get_closest_point(target)`. Also report how many probes are unreachable.
- **Navigation perf budget.** Record the vertex-merge versus edge-connection counts from `get_process_info` and fail if edge connections dominate.
- **Static lint of rules 2–8, 11, 13–19** using regex over `.gd`, plus resource property reads from `.tres` and `.tscn` (cell_size, parsed_geometry_type, scale).
- **Distribution test.** Over K seeds, chi-square tile frequencies against expected weights at a fixed tolerance.
- **Addon inventory.** Read `addons/*/plugin.cfg` versions and compare them with the 4.7-compatible versions in the table above.

## Pitfalls

- Querying paths on the first frame returns an empty path, and the agent then thinks it has arrived.
- Calling `get_next_path_position()` twice per frame, or from signal callbacks, causes jitter or recursion.
- A small `path_max_distance` with per-frame re-pathing makes agents dance. Overshooting `path_desired_distance` makes them backtrack.
- RVO without a `target_position` gives a zero `safe_velocity`. Avoidance ignores walls, and head-on symmetric tests fail.
- A `NavigationLink` does not move the agent; the game must handle traversal, typically on `link_reached`.
- Unreachable targets make a search exhaustive, which causes frame spikes. Validate that targets are reachable at generation time instead.
- Per-cell TileMapLayer navigation produces many small polygons, which makes search and resync expensive. For large maps, bake one region.
- Parsing visual meshes at runtime stalls rendering, and a tiny `cell_size` can freeze or crash the game.
- `AStarGrid2D.update()` silently wipes solids and weights, and `jumping_enabled` ignores weights.
- Global `shuffle()` and `pick_random()` inside "seeded" generators break reproducibility, and similar seeds give similar maps without hashing.
- RNG output may change across Godot versions, so golden seeds are not portable.
- Beehave's README and tags disagree on versioning. The LimboAI GDExtension has fewer features than the module.

## Risks and uncertainties

- UNVERIFIED: the Godot versions that introduced AStarGrid2D `region`, `path_search_max_polygons` and `path_return_max_*`, and `rand_weighted()`.
- UNVERIFIED: whether Utility AI GDExtension and Gaea 2.0 work on 4.7.2. Commit dates for State Charts, Gaea and the WFC addon were not visible, so their maintenance status is not confirmed.
- The 4.4 and 4.5 release-page fetches were truncated after about 100k characters, so smaller navigation items may be missing.
- Testing guidance (golden seeds, chi-square bands) is engineering opinion, not Godot documentation.

## Sources

- Navigation tutorials (4.7): navigation_using_navigationmeshes, navigation_using_navigationagents, navigation_optimizing_performance, navigation_introduction_2d, navigation_using_navigationlayers, navigation_using_navigationlinks, all under https://docs.godotengine.org/en/stable/tutorials/navigation/
- Class reference (4.7): NavigationServer2D, NavigationAgent2D, AStarGrid2D, TileMap, TileMapLayer, RandomNumberGenerator, Array, FastNoiseLite and SurfaceTool, all under https://docs.godotengine.org/en/stable/classes/
- Other tutorials (4.7): https://docs.godotengine.org/en/stable/tutorials/math/random_number_generation.html, https://docs.godotengine.org/en/stable/tutorials/physics/ray-casting.html and https://docs.godotengine.org/en/stable/tutorials/3d/procedural_geometry/index.html
- Release notes: https://godotengine.org/releases/4.3/, https://godotengine.org/releases/4.4/, https://godotengine.org/releases/4.5/, https://godotengine.org/releases/4.6/, https://godotengine.org/releases/4.7/, https://godotengine.org/article/maintenance-release-godot-4-7-1/ and https://godotengine.org/article/release-candidate-godot-4-7-rc-1/
- PR #88047 (AStar partial paths): https://github.com/godotengine/godot/pull/88047
- Addons: https://github.com/limbonaut/limboai (and /releases), https://github.com/bitbrain/beehave (and /releases), https://github.com/derkork/godot-statecharts, https://github.com/JarkkoPar/Utility_AI_GDExtension, https://github.com/viniciusgerevini/godot-goap, https://github.com/AlexeyBond/godot-constraint-solving and https://github.com/gaea-godot/gaea
