# Level design, world building and cameras (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7), the 4.3–4.7 release notes and addon repos. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

Since Godot 4.3, 2D levels are built from several `TileMapLayer` nodes, and `TileMap` is deprecated. Since 4.5, layers merge their collision shapes into chunks (`physics_quadrant_size`, default 16). In 3D, GridMap/MeshLibrary handles modular kits. CSG is meant for blockout, and since 4.4 it can be baked to a mesh or collision shape. 4.7 adds a MeshLibrary editor, CSG Autosmooth and vertex snapping. Large worlds need either a double-precision engine build that you compile yourself or origin shifting. Streaming uses `ResourceLoader.load_threaded_*`. For cameras, the engine provides `Camera2D` limits, smoothing and drag margins plus `SpringArm3D`. Phantom Camera (MIT, v0.11.0.4) is the main camera addon. Split screen means one SubViewport per player, either sharing `world_2d` or inheriting the parent's World3D. Most level-quality rules can be checked by a stdlib tool reading `.tscn` text. Reachability and draw-call budgets need a live Godot run.

## 1. 2D levels

**TileMapLayer replaces TileMap (4.3).** The 4.3 release notes say "a new `TileMapLayer` node to replace the old approach completely." They also say the deprecated node "is still supported for the time being", and that the editor converts it in one click (https://godotengine.org/releases/4.3/). The 4.7 class page says "Deprecated: Use multiple TileMapLayer nodes instead", and the conversion path is TileMap bottom panel → toolbox → "Extract TileMap layers as individual TileMapLayer nodes" (https://docs.godotengine.org/en/stable/classes/class_tilemap.html). High confidence.

**TileMapLayer properties (4.7)** (https://docs.godotengine.org/en/stable/classes/class_tilemaplayer.html):

- `rendering_quadrant_size` (default 16) batches tiles into one canvas item. It "doesn't apply to Y-sorted layers."
- `physics_quadrant_size` (default 16) merges cell shapes into bigger collision shapes. Setting it to `1` disables the chunking.
- `collision_enabled`, `navigation_enabled` and `occlusion_enabled` all default to `true`.
- `use_kinematic_bodies` (default false) is meant for moving layers such as platforms.
- `y_sort_origin` fakes height levels.

Edits are batched to the end of the frame, and `update_internals()` is described as "computationally expensive". `_use_tile_data_runtime_update` should return true only when needed, because it carries "a significant performance penalty".

**4.5 physics chunking.** The release notes say "TileMapLayer physics merge cell shapes into bigger collision shapes whenever possible" (https://godotengine.org/releases/4.5/). The migration guide adds that `get_coords_for_body_rid()` now returns quadrant coordinates, and that you should set `physics_quadrant_size = 1` to get the old behaviour back (https://docs.godotengine.org/en/stable/tutorials/migrating/upgrading_to_godot_4.5.html). High confidence.

**TileSet authoring (4.7)** (https://docs.godotengine.org/en/stable/tutorials/2d/using_tilesets.html):

- Sources are either Atlas or Scenes Collection.
- Terrain sets come in three modes: Match Corners and Sides, Match Corners, and Match Sides.
- Physics, navigation and occlusion layers must exist on the TileSet before you can draw per-tile shapes.
- Custom data layers (for example damage or destructible) are shared by every instance of a tile. Use alternative tiles for variants.
- Scene tiles "come with a greater performance overhead … every scene is instanced individually". Use them "only … when necessary".
- Tile proxies remap IDs after atlases are merged.
- Since 4.2, rotating or flipping a tile during placement no longer needs alternative tiles.
- Since 4.6, scene tiles rotate in 90° steps (https://godotengine.org/releases/4.6/).
- 4.7 adds a 2D Scene Paint Mode (key B) that scatters scenes off the grid (https://godotengine.org/releases/4.7/).

**Y-sort.** Enable `y_sort_enabled` on the layer and its parent. Rendering quadrants are skipped on Y-sorted layers, so a large Y-sorted layer costs more to draw (class page above). The cost increase is UNVERIFIED: it is inferred from that docs sentence, not benchmarked.

```gdscript
# Clamp Camera2D to the used area of a ground layer
func fit_camera(cam: Camera2D, ground: TileMapLayer) -> void:
    var r := ground.get_used_rect()
    var ts := Vector2(ground.tile_set.tile_size)
    var tl := ground.to_global(Vector2(r.position) * ts)
    var br := ground.to_global(Vector2(r.end) * ts)
    cam.limit_left = int(tl.x); cam.limit_top = int(tl.y)
    cam.limit_right = int(br.x); cam.limit_bottom = int(br.y)
```

## 2. 3D levels

**GridMap (4.7)** (https://docs.godotengine.org/en/stable/classes/class_gridmap.html):

- Defaults: `cell_size` is `Vector3(2,2,2)`, `cell_octant_size` is 8, `bake_navigation` is false.
- GridMap is not a VisualInstance3D, so `layers` cannot cull or hide it.
- `make_baked_meshes()` prepares the meshes for LightmapGI.

MeshLibrary authoring (https://docs.godotengine.org/en/stable/tutorials/3d/using_gridmaps.html):

- Build a Node3D root with MeshInstance3D children, then use Scene → Export As → MeshLibrary.
- Put materials in the mesh's own material slot.
- Each item gets one StaticBody3D for collision.
- A NavigationRegion3D child is baked per item, and its cell size must match the NavigationServer map cell size.

Version notes: 4.6 added Bresenham line painting for GridMap (https://godotengine.org/releases/4.6/), and 4.7 added a dedicated MeshLibrary editor (https://godotengine.org/releases/4.7/).

**CSG for blockout (4.7 page, which itself warns it was "not yet updated for 4.7")** (https://docs.godotengine.org/en/stable/tutorials/3d/csg_tools.html):

- The page says CSG is "mainly intended for prototyping".
- Keep CSG trees small and use binary operations only where needed.
- Since 4.4 you can bake with CSG → Bake Mesh Instance or Bake Collision Shape, or from script with `bake_static_mesh()` and `bake_collision_shape()`. These methods are absent from the 4.3 class page (https://docs.godotengine.org/en/4.3/classes/class_csgshape3d.html).
- Baking does not hide the source CSG node, so hide it yourself.
- The baked collision shape needs a StaticBody3D or AnimatableBody3D parent.
- CSG mesh data updates one frame late, so `await get_tree().process_frame` before baking in `_ready`.
- Scene → Export As → glTF 2.0 sends a blockout to Blender.
- For production, the page points to FuncGodot or Cyclops.

Version notes: 4.4 replaced the CSG backend with the Manifold library (https://godotengine.org/releases/4.4/), and 4.7 added `Autosmooth` with a default angle of 50° (https://godotengine.org/releases/4.7/).

**Blender to Godot (4.7)** (https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html):

| Suffix             | Effect                                                                 |
| ------------------ | ---------------------------------------------------------------------- |
| `-col`             | Keeps the mesh and adds a trimesh static collision (accurate but slow) |
| `-convcol`         | Keeps the mesh and adds a convex collision                             |
| `-colonly`         | Replaces the mesh with a StaticBody3D. Blender empties map to shapes   |
| `-convcolonly`     | Like `-colonly`, with convex decomposition                             |
| `-occ`             | Keeps the mesh and adds an Occluder3D                                  |
| `-occonly`         | Replaces the mesh with an Occluder3D                                   |
| `-navmesh`         | Replaces the mesh with a navigation mesh                               |
| `-rigid`           | RigidBody3D                                                            |
| `-vehicle`         | VehicleBody3D                                                          |
| `-wheel`           | VehicleWheel3D                                                         |
| `-noimp`           | Skips the node                                                         |
| `-loop` / `-cycle` | Sets the loop flag on animation clips (no hyphen needed)               |

- Suffixes accept `-`, `$` or `_` and are case-insensitive.
- `nodes/use_node_type_suffixes=false` turns them off, but `-noimp`, `-loop` and `-vcol` still apply.
- Inherited scenes allow local additions, but base nodes cannot be removed and subresources must be saved externally.
- `EditorScenePostImport._post_import(scene)` must return the scene (https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/import_configuration.html).
- 4.6 can generate a CollisionShape3D from a primitive mesh through the Mesh menu (https://godotengine.org/releases/4.6/).

**Modular kits.** Snap kit pieces to one grid unit equal to `cell_size`. 4.4 added surface snapping in the editor and 4.7 added vertex snapping (B) and a vector ruler (Shift) (https://godotengine.org/releases/4.4/, https://godotengine.org/releases/4.7/). Choosing kit units equal to `cell_size` is general practice, not a docs rule.

## 3. Version and addon table

| Item                                                                                                                     | Version / date                                                                           | Licence                                       | Source                                                                                            |
| ------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| TileMapLayer added, TileMap deprecated; 2D physics interpolation                                                         | 4.3 (2024)                                                                               | MIT (engine)                                  | https://godotengine.org/releases/4.3/                                                             |
| Integer stretch scale mode; tile rotate/flip without alternatives                                                        | 4.2                                                                                      | MIT                                           | multiple_resolutions and using_tilesets pages                                                     |
| CSG on Manifold; CSG bake to mesh/collision; 3D physics interpolation; Jolt built in (experimental); 3D surface snapping | 4.4                                                                                      | MIT                                           | https://godotengine.org/releases/4.4/                                                             |
| TileMapLayer physics chunking (`physics_quadrant_size`)                                                                  | 4.5                                                                                      | MIT                                           | https://godotengine.org/releases/4.5/                                                             |
| Jolt default for new 3D projects; rotatable scene tiles; GridMap line paint                                              | 4.6                                                                                      | MIT                                           | https://godotengine.org/releases/4.6/                                                             |
| MeshLibrary editor; CSG Autosmooth; vertex snap; 2D Scene Paint; `CollisionShape2D.one_way_collision_direction`          | 4.7, released 2026-06-19 (date from secondary sources only)                              | MIT                                           | https://godotengine.org/releases/4.7/, https://app.cinevva.com/news/2026-06-19-godot-4-7-released |
| Godot 4.7.2                                                                                                              | 2026-08-18 (secondary source)                                                            | MIT                                           | https://gamedev.net/news/5172-godot-engine-472-stable-released/                                   |
| Phantom Camera                                                                                                           | v0.11.0.4, 27 Oct (year assumed 2026); badge says Godot 4.4+                             | MIT                                           | https://github.com/ramokz/phantom-camera/releases                                                 |
| Terrain3D (C++ GDExtension)                                                                                              | v1.1.0-stable, 30 Oct (year assumed 2026); "Supports Godot 4.5-4.8+"; up to 65.5×65.5 km | MIT                                           | https://github.com/TokisanGames/Terrain3D/releases                                                |
| HTerrain (Zylann)                                                                                                        | Godot 4.6+; "not in active development", bug fixes only                                  | UNVERIFIED (LICENSE.md exists, type not read) | https://github.com/Zylann/godot_heightmap_plugin                                                  |
| Cyclops Level Builder                                                                                                    | 1.5.0 for Godot 4.7+ (1.0.2 for 4.2+); release date not shown                            | MIT                                           | https://github.com/blackears/cyclopsLevelBuilder                                                  |
| FuncGodot (TrenchBroom, Hammer, J.A.C.K., NetRadiant Custom; `.map`/`.vmf`)                                              | Godot 4; release version UNVERIFIED                                                      | MIT                                           | https://github.com/func-godot/func_godot_plugin                                                   |

## 4. Level organisation and streaming

**One scene per level** works for bounded levels. For open worlds, split the world into chunk scenes and stream them in with threaded loading. The streaming pattern is general practice and has no official tutorial: UNVERIFIED as an official recommendation.

API facts (https://docs.godotengine.org/en/stable/classes/class_resourceloader.html):

- Signature: `load_threaded_request(path, type_hint="", use_sub_threads=false, cache_mode=1)`.
- Status values: `THREAD_LOAD_INVALID_RESOURCE`=0, `IN_PROGRESS`=1, `FAILED`=2, `LOADED`=3.
- Poll the status once per frame rather than in a loop.
- `load_threaded_get` blocks like `load()` if called before loading finishes (https://docs.godotengine.org/en/stable/tutorials/io/background_loading.html).
- `use_sub_threads` loads faster but "may affect the main thread".

```gdscript
var _pending: Dictionary = {}  # path -> Vector2i chunk

func request_chunk(c: Vector2i) -> void:
    var path := "res://levels/world/chunk_%d_%d.tscn" % [c.x, c.y]
    if ResourceLoader.load_threaded_request(path) == OK:
        _pending[path] = c

func _process(_dt: float) -> void:
    for path in _pending.keys():
        match ResourceLoader.load_threaded_get_status(path):
            ResourceLoader.THREAD_LOAD_LOADED:
                var node := (ResourceLoader.load_threaded_get(path) as PackedScene).instantiate()
                $Chunks.add_child(node); _pending.erase(path)
            ResourceLoader.THREAD_LOAD_FAILED, ResourceLoader.THREAD_LOAD_INVALID_RESOURCE:
                push_error("chunk load failed: %s" % path); _pending.erase(path)
```

**Large worlds** (https://docs.godotengine.org/en/stable/tutorials/physics/large_world_coordinates.html). With single-precision floats, the docs recommend these maximum distances from the origin:

| Game type    | Recommended max distance | Float step at that range |
| ------------ | ------------------------ | ------------------------ |
| First person | about 4096               | about 0.0002             |
| Third person | about 8192               | about 0.0005             |
| Top-down 3D  | about 32768              | about 0.0019             |
| Any 3D game  | about 65536              | about 0.0039             |

- Double precision requires building both the editor and the export templates yourself with `scons precision=double`. Output binaries get a `.double` suffix.
- GDExtensions must be rebuilt for a double build. That includes Terrain3D, an inference from it being a GDExtension.
- 2D rendering does not benefit from double precision.
- GPUParticles3D with local coords disabled still snaps.
- Server and clients must use the same build type.
- Origin shifting is the low-end alternative, but the docs do not describe how to do it.

**Level data apart from logic.**

- Mark spawn points with `Marker2D`/`Marker3D` in a named group such as `spawn` or `checkpoint`.
- Use `Area2D`/`Area3D` with `body_entered` for triggers. Exported fields on a small trigger script hold the target such as a door or checkpoint id.
- Keep checkpoint state in an autoload or save resource, not in the level scene.
- The group and autoload conventions above are project conventions, not engine rules.

## 5. Cameras

**Camera2D (4.7)** (https://docs.godotengine.org/en/stable/classes/class_camera2d.html):

- Limits default to ±10,000,000 with `limit_enabled=true`. `limit_smoothed` defaults to false.
- Position smoothing: `position_smoothing_enabled=false`, `speed=5.0`.
- Drag margins: `drag_*_margin=0.2`, but `drag_horizontal_enabled` and `drag_vertical_enabled` default to false.
- `zoom` defaults to `Vector2(1,1)`. `process_callback` defaults to IDLE.
- `reset_smoothing()` snaps the camera to its smoothing target. Call it after a teleport.

Pixel art:

- Stretch mode `viewport` with integer scale mode, available since 4.2 (https://docs.godotengine.org/en/stable/tutorials/rendering/multiple_resolutions.html).
- The setting `rendering/2d/snap/snap_2d_transforms_to_pixel` conflicts with smoothing and causes jitter, according to community reports (https://forum.godotengine.org/t/pixel-art-jittering/75305). UNVERIFIED against official docs. The ProjectSettings page was too large to read in full.

**Camera3D rigs.**

- `SpringArm3D` (4.7) casts a ray, or a `shape` if set, along its +Z axis and pulls its children in on a hit. Defaults: `spring_length=1.0`, `margin=0.01`, `collision_mask=1`. Exclude the player with `add_excluded_object(rid)` (https://docs.godotengine.org/en/stable/classes/class_springarm3d.html).
- Third person: player → yaw pivot → pitch pivot → SpringArm3D → Camera3D. First person: Camera3D under a head pivot.
- With physics interpolation on, give the camera `top_level=true` and follow `get_global_transform_interpolated()` in `_process`. Disable interpolation on mouse-look cameras (https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/advanced_physics_interpolation.html).

**Shake.** Godot has no built-in shake. The common pattern is trauma² multiplied by noise applied to `offset` (2D) or `h_offset`/`v_offset` (3D). The pattern comes from Squirrel Eiserloh's GDC 2016 talk "Juicing Your Cameras With Math" (https://www.gdcvault.com/play/1023557/). That URL is from memory: UNVERIFIED.

```gdscript
extends Camera2D
@export var max_offset := Vector2(12, 8)
@export var decay := 1.5
var trauma := 0.0
var _noise := FastNoiseLite.new()
var _t := 0.0
func add_trauma(a: float) -> void: trauma = minf(trauma + a, 1.0)
func _process(dt: float) -> void:
    _t += dt * 60.0
    trauma = maxf(trauma - decay * dt, 0.0)
    var k := trauma * trauma
    offset = Vector2(_noise.get_noise_1d(_t), _noise.get_noise_1d(_t + 100.0)) * max_offset * k
```

**Phantom Camera** (MIT, Godot 4.4+):

- PhantomCamera2D/3D nodes drive a Camera2D or Camera3D through PhantomCameraHost. The highest-priority camera wins, and the switch is tweened.
- Follow modes: Glued, Simple, Group, Path, Framed, Third Person (3D, uses SpringArm3D).
- Look At (3D). Zoom (2D).
- Shake and noise features are not shown on the README: UNVERIFIED (https://github.com/ramokz/phantom-camera).

**Split screen** (https://docs.godotengine.org/en/stable/tutorials/rendering/viewports.html):

- There is one active camera per Viewport.
- In 3D, a SubViewport uses its parent's World3D by default, so per-player SubViewports see the same 3D world automatically.
- In 2D, every Viewport has its own World2D. Share it in code with `$P2View.world_2d = $P1View.world_2d`.
- Each viewport is another render pass, so draw cost scales roughly with the player count (https://uhiyama-lab.com/en/notes/godot/split-screen-multiplayer/, dated 2026-07-09, secondary source).
- A shared `world_2d` together with MultiplayerSpawner has been reported to break (forum, 4.3: https://forum.godotengine.org/t/split-screen-networked-multiplayer/77697).

## 6. Greybox and metrics

- Derive level metrics from the character controller, not by eye. Peak jump height is v₀²/(2g). Jump distance is horizontal speed × 2v₀/g. Gaps, ledges and step heights should be tuned below those numbers with a margin.
- Read gravity from `physics/2d/default_gravity` or `physics/3d/default_gravity`, plus any controller override.
- Any specific numbers, such as a 1.8 m capsule or 0.3 m step height, are conventions and UNVERIFIED.
- Workflow: CSG or GridMap blockout with prototype textures (Kenney CC0, per the CSG page), then playtest, then kit art, then bake CSG.

## 7. Testing levels

- **Reachability (3D or 2D nav).** Wait a physics frame, and continue only once `NavigationServer3D.map_get_iteration_id(map) > 0`, where 0 means the map has never synced. Then call `map_get_path(map, spawn, goal, true)`. A pass means the path is non-empty and its last point is within ε of `map_get_closest_point(map, goal)` (https://docs.godotengine.org/en/stable/classes/class_navigationserver3d.html). Navigation only approximates jumps, so platformers need scripted bots or jump links.
- **Softlock.** For every reachable region, check that a path back to a checkpoint or the exit exists. A bot that has been stuck (position delta < ε) for N seconds fails the test. The method is a design proposal: UNTESTED.
- **Out of world.** Every level should have a kill or respawn Area below the geometry's minimum Y, or a bounds check in the player script. Probe at random navmesh points as well.
- **Performance per level.** In a rendered run (not `--headless`), read the `Performance.get_monitor()` values `OBJECT_NODE_COUNT`, `RENDER_TOTAL_DRAW_CALLS_IN_FRAME`, `RENDER_TOTAL_PRIMITIVES_IN_FRAME`, `RENDER_VIDEO_MEM_USED`, `PHYSICS_3D_ACTIVE_OBJECTS` and `NAVIGATION_3D_POLYGON_COUNT` (https://docs.godotengine.org/en/stable/classes/class_performance.html). Whether draw calls report 0 under `--headless` is UNVERIFIED.
- Print a single summary line and judge the run by it, never by the exit code, per the project rule.

## Checkable rules an agent should follow

1. No `type="TileMap"` node in any `.tscn`. Use `TileMapLayer`.
1. Every level scene has at least one `Marker2D`/`Marker3D` in group `spawn`, or a node named `Spawn*`.
1. Every `Area2D`/`Area3D` has at least one `CollisionShape*`/`CollisionPolygon*` child, and each has a `shape` (or polygon) set.
1. Every Area has a non-zero `collision_mask` (defaults count as non-zero), and its trigger script connects `body_entered` or `area_entered`.
1. Shipped level scenes contain no `CSG*` nodes, or the CSG root is `visible=false` beside a baked MeshInstance3D.
1. A baked CSG `CollisionShape3D` sits under a `StaticBody3D` or `AnimatableBody3D`.
1. Every `GridMap` has a `mesh_library` set, and its `cell_size` matches a project constant.
1. A TileMapLayer that calls `get_coords_for_body_rid` in scripts sets `physics_quadrant_size = 1`.
1. A TileMapLayer with `y_sort_enabled` also has a Y-sorted parent.
1. Scene-collection tiles are used only for interactive tiles. The count of scene tiles per layer stays under a budget.
1. Every TileSet whose tiles collide has at least one physics layer, and TileSets used for pathing have navigation layers.
1. Each level's Camera2D has limits set, or a script that fits them. Default ±10,000,000 limits in a bounded level are a flag.
1. Scripts that teleport the player call `reset_smoothing()` on Camera2D, or `reset_physics_interpolation()` when interpolation is on.
1. Every `SpringArm3D` excludes the player, through `add_excluded_object` or a mask that skips the player's layer.
1. Each Viewport/SubViewport has exactly one camera with `current = true`.
1. Each level declares a kill or respawn Area below its geometry, or a bounds value in level metadata.
1. Chunk loading uses `load_threaded_request` and status polling. There is no `load()` of `res://levels/**` in `_process`.
1. No 3D level coordinate exceeds the recommended range for its game type (first-person 4096, third-person 8192, any 3D 65536) unless the project uses a `.double` template.
1. Imported level `.glb`/`.blend` files use `-col`/`-colonly`/`-navmesh` suffixes or import-dock settings for collision. Collision is not hand-added inside an inherited scene.
1. Level scenes hold data and markers only. Gameplay logic lives in reusable scenes and scripts, so no single level script exceeds N lines.
1. Every checkpoint marker has a unique `checkpoint_id`.
1. Every metric (jump height, gap width) cited in a level doc names its source controller value.

## What a tool could check automatically

- **Static `.tscn`/`.tres` scan (stdlib, no Godot).** The parser reads `[node name= type= parent=]` headers and properties. It flags:
  - deprecated `TileMap` nodes
  - Areas with no shape child, and shapes with no `shape =`
  - levels without a spawn marker
  - `CSG*` nodes left visible in `levels/`
  - GridMaps without a `mesh_library`
  - Camera2D nodes with default limits
  - more than one `current = true` camera per viewport subtree
  - scene-tile counts in a TileSet
  - node count per level against a budget
  - inheritance from an imported `.glb` combined with an overridden collision
- **Script grep.** It flags:
  - `load(` on level paths inside `_process` or `_physics_process`
  - `get_coords_for_body_rid` without `physics_quadrant_size = 1`
  - teleports (assignments to `global_position`) with no reset of smoothing or interpolation nearby
- **Live headless probe (`godot --headless --script probe.gd -- level.tscn`).** It instances the level and waits for the nav map iteration id to be above 0. It then runs spawn→goal and goal→checkpoint `map_get_path` probes, checks that a kill Area exists below the geometry AABB (from `get_meshes()` or VisualInstance3D AABBs), and prints `LEVEL_PROBE level=… reachable=… softlock=… nodes=…`.
- **Live rendered budget run (Xvfb optional, reported by `doctor`).** It renders N frames from each camera or spawn, records `RENDER_TOTAL_DRAW_CALLS_IN_FRAME`, primitives and VRAM, and compares them to per-level budgets.
- **Bounds check.** It computes the max |coordinate| of nodes and AABBs, then compares the result to the large-world table.

## Pitfalls

- 4.5 changed what `get_coords_for_body_rid` returns: the quadrant, not the tile. Tile-specific logic such as ladders or hazards breaks silently. Fix it with `physics_quadrant_size = 1` (4.5 migration guide).
- `rendering_quadrant_size` is ignored on Y-sorted layers.
- Scene tiles instance one scene per cell.
- Baked CSG leaves the source node visible, which doubles the geometry. Baking in `_ready` without waiting a frame gives an empty shape.
- `-navmesh` and `-colonly` remove the visible mesh. Use `-col` to keep it.
- GridMap ignores visibility `layers`, so a light-cull mask won't exclude it.
- `load_threaded_get` blocks if called before the status is LOADED.
- Navigation maps sync at the end of the physics frame. A path query in the same frame as `_ready` returns empty.
- A third-person SpringArm3D that hits the player's own capsule makes the camera snap in.
- Camera2D smoothing combined with pixel snapping causes jitter (community reports, UNVERIFIED officially).
- Each Viewport has its own World2D, so 2D split screen shows an empty screen until `world_2d` is shared.
- Double precision needs custom templates, rebuilt GDExtensions and the same build type on every networked peer.
- The CSG tutorial page is marked "not yet updated for 4.7".
- Since 4.6, new projects default to Jolt physics. Existing projects keep their setting, so a physics-based reachability bot can behave differently from one project to the next.

## Risks and uncertainties

- Dates without a year on the GitHub release pages (Phantom Camera, Terrain3D) are assumed to be 2026.
- The 4.7 and 4.7.2 release dates come from secondary sources only.
- Not verified: the HTerrain licence, the FuncGodot release version, the pixel-snap setting names and defaults, and draw-call monitors under `--headless`.
- The camera shake, softlock and level-metric numbers are practice, not documentation.

## Sources

- TileMapLayer class: https://docs.godotengine.org/en/stable/classes/class_tilemaplayer.html
- TileMap class: https://docs.godotengine.org/en/stable/classes/class_tilemap.html
- Using TileSets: https://docs.godotengine.org/en/stable/tutorials/2d/using_tilesets.html
- Upgrading to 4.5: https://docs.godotengine.org/en/stable/tutorials/migrating/upgrading_to_godot_4.5.html
- Release notes 4.3–4.7: https://godotengine.org/releases/4.3/, https://godotengine.org/releases/4.4/, https://godotengine.org/releases/4.5/, https://godotengine.org/releases/4.6/, https://godotengine.org/releases/4.7/
- CSG tools: https://docs.godotengine.org/en/stable/tutorials/3d/csg_tools.html
- CSGShape3D in 4.3 (absence check): https://docs.godotengine.org/en/4.3/classes/class_csgshape3d.html
- GridMap class and tutorial: https://docs.godotengine.org/en/stable/classes/class_gridmap.html, https://docs.godotengine.org/en/stable/tutorials/3d/using_gridmaps.html
- Node type customization (suffixes): https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/node_type_customization.html
- Import configuration: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/import_configuration.html
- Background loading and ResourceLoader: https://docs.godotengine.org/en/stable/tutorials/io/background_loading.html, https://docs.godotengine.org/en/stable/classes/class_resourceloader.html
- Large world coordinates: https://docs.godotengine.org/en/stable/tutorials/physics/large_world_coordinates.html
- Camera2D, SpringArm3D, Viewports, advanced physics interpolation, multiple resolutions: their docs.godotengine.org/en/stable pages, linked above
- NavigationServer3D and Performance classes: https://docs.godotengine.org/en/stable/classes/class_navigationserver3d.html, https://docs.godotengine.org/en/stable/classes/class_performance.html
- Addon repos: Phantom Camera, Terrain3D, HTerrain, Cyclops, FuncGodot (URLs in the table)
- Secondary sources for release dates and split-screen cost: Cinevva, GameDev.net, uhiyama-lab, and the Godot forum (URLs above)
