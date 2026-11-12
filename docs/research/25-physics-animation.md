# Physics, movement and animation (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7), the 4.2–4.7 release notes and the Jolt and Rapier repos. Probes and GDScript examples are UNTESTED on 4.7.2.

## Executive summary

Jolt became a built-in, experimental 3D engine in 4.4. In 4.6 it lost the experimental label and became the default for new projects, while existing projects keep their setting. 2D still has only GodotPhysics2D built in; Rapier is the main third-party backend. Physics interpolation arrived for 2D in 4.3 and for 3D in 4.4, and its 3D implementation moved into SceneTree in 4.5. It is off by default, and it requires gameplay movement in `_physics_process` plus `reset_physics_interpolation()` after a teleport. The skeleton stack changed release by release: AnimationMixer (4.2), SkeletonModifier3D (4.3), LookAt, SpringBone and Retarget modifiers (4.4), bone constraints (4.5), and the IKModifier3D solvers (4.6). 4.7 added `Tween.tween_await()` and `CollisionShape2D.one_way_collision_direction`. Neither built-in engine guarantees determinism, so headless tests should check positions within a tolerance under `--fixed-fps`, not exact equality.

## 1. Physics engines

- **3D.** `physics/3d/physics_engine` defaults to `"DEFAULT"`, which maps to GodotPhysics3D. The docs add: "Jolt Physics is the default for projects created starting in Godot 4.6." ([ProjectSettings 4.7](https://docs.godotengine.org/en/stable/classes/class_projectsettings.html)) Jolt was built in from 4.4 as an experimental opt-in ([4.4 release](https://godotengine.org/releases/4.4/)). In 4.6 the experimental label was dropped and Jolt became the default for new 3D projects only ([4.6 release](https://godotengine.org/releases/4.6/)). Confidence: high.
- **Jolt behaves differently in these ways** ([Using Jolt Physics, 4.7](https://docs.godotengine.org/en/latest/tutorials/physics/using_jolt_physics.html)):
  - A single-body joint attaches to `node_b`, and `physics/jolt_physics_3d/joints/world_node` controls this.
  - The collision margin shrinks the shape and then adds a shell, with `margin` as an upper bound.
  - Baumgarte stabilization corrects position only (factor 0.2).
  - `face_index` is -1 unless `queries/enable_ray_cast_face_index` is on, which costs about 25% more memory on ConcavePolygonShape3D.
  - Frozen kinematic RigidBody3D bodies get no contacts with static or kinematic bodies unless `simulation/generate_all_kinematic_contacts` is on.
  - Contact impulses are estimates.
  - The WorldBoundaryShape3D plane is smaller (`limits/world_boundary_shape_size` = 2000).
  - Running physics on a separate thread is experimental.
  - These joint properties are unsupported and warn when set: Pin `bias`/`damping`/`impulse_clamp`, Hinge `bias`/`softness`/`relaxation`, Slider `angular_*` and limit softness/restitution/damping, ConeTwist `bias`/`relaxation`/`softness`, and Generic6DOF limit softness/restitution/damping/erp.
- **`physics/3d/solver/*` (and the matching 2D solver keys) only affect GodotPhysics.** They have no effect under Jolt ([ProjectSettings](https://docs.godotengine.org/en/stable/classes/class_projectsettings.html)).
- **2D.** `physics/2d/physics_engine` = `"DEFAULT"` maps to GodotPhysics2D, the only built-in option. Rapier (appsinacup, MIT) is a third-party GDExtension for 2D and 3D. It has a fast SIMD build and a slower cross-platform-deterministic build, and is selected by setting the physics engine to Rapier2D/Rapier3D ([godot-rapier-2d](https://github.com/appsinacup/godot-rapier-2d), [asset library](https://godotengine.org/asset-library/asset/edit/19239)). Confidence: medium (README and asset-library pages).
- UNVERIFIED: the exact string a 4.6+ project writes to `project.godot` for Jolt (expected `physics/3d/physics_engine="Jolt Physics"`). Confirm by creating a scratch project with 4.7.2.

## 2. Body types: when to use each

| Node                | Moves by                                                       | Use for                                                                                      | Source                                                                                                                                                                                              |
| ------------------- | -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| StaticBody2D/3D     | not moved by the engine                                        | walls, floors, level geometry (the only body that can hold concave shapes)                   | [physics intro](https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html), [shapes 3D](https://docs.godotengine.org/en/stable/tutorials/physics/collision_shapes_3d.html) |
| AnimatableBody2D/3D | code or AnimationPlayer; pushes others; `sync_to_physics=true` | moving platforms, doors. Never combine with `move_and_collide()`                             | [AnimatableBody3D](https://docs.godotengine.org/en/stable/classes/class_animatablebody3d.html)                                                                                                      |
| CharacterBody2D/3D  | your code via `move_and_slide`/`move_and_collide`              | player, NPCs; "collision detection, but no physics"                                          | [physics intro](https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html)                                                                                                 |
| RigidBody2D/3D      | the solver (forces, impulses)                                  | props, debris, ragdoll parts. Change state in `_integrate_forces`, not by setting `position` | same                                                                                                                                                                                                |
| Area2D/3D           | not a body                                                     | triggers, hitboxes, gravity/damp overrides                                                   | same                                                                                                                                                                                                |

## 3. move_and_slide

Defaults ([CharacterBody2D](https://docs.godotengine.org/en/stable/classes/class_characterbody2d.html), [CharacterBody3D](https://docs.godotengine.org/en/stable/classes/class_characterbody3d.html), 4.7):

| Property             | 2D              | 3D                |
| -------------------- | --------------- | ----------------- |
| velocity units       | px/s            | m/s ("typically") |
| floor_snap_length    | 1.0             | 0.1               |
| floor_max_angle      | 0.785 rad (45°) | 0.785 rad         |
| max_slides           | 4               | 6                 |
| safe_margin          | 0.08            | 0.001             |
| up_direction         | (0,-1)          | (0,1,0)           |
| wall_min_slide_angle | 15°             | 15°               |
| platform_on_leave    | ADD_VELOCITY    | ADD_VELOCITY      |

The 3D defaults also include `floor_stop_on_slope=true`, `floor_constant_speed=false`, `floor_block_on_wall=true`, `slide_on_ceiling=true`, `platform_floor_layers` = all layers and `platform_wall_layers=0`.

```gdscript
extends CharacterBody2D
const SPEED := 300.0          # px/s
const JUMP := -450.0
var gravity: float = ProjectSettings.get_setting("physics/2d/default_gravity")  # 980

func _physics_process(delta: float) -> void:
	if not is_on_floor():
		velocity.y += gravity * delta      # acceleration * delta is correct
	velocity.x = Input.get_axis("left", "right") * SPEED
	move_and_slide()                       # no delta, no argument
```

- `move_and_slide()` "uses the physics step's delta automatically". Do not pass `velocity * delta`. `move_and_collide(velocity * delta)` does take a motion vector and leaves `velocity` unchanged ([CharacterBody 2D tutorial](https://docs.godotengine.org/en/stable/tutorials/physics/using_character_body_2d.html)).
- `is_on_floor()` and the other `is_on_*` checks reflect the last `move_and_slide()` call and need `MOTION_MODE_GROUNDED` ([class ref](https://docs.godotengine.org/en/stable/classes/class_characterbody3d.html)).
- Floor snap only applies while grounded. Before a jump, set an upward velocity so the body leaves the floor. Use `floor_constant_speed` to keep speed the same on slopes. Riding platforms works through `platform_floor_layers` and an AnimatableBody with `sync_to_physics`.
- Use `MOTION_MODE_FLOATING` for top-down and space movement, where floor and wall have no meaning.

## 4. Fixed timestep and physics interpolation

Settings, from [ProjectSettings 4.7](https://docs.godotengine.org/en/stable/classes/class_projectsettings.html):

| Key                                          | Default   | Note                                                       |
| -------------------------------------------- | --------- | ---------------------------------------------------------- |
| `physics/common/physics_ticks_per_second`    | 60        | read only at project start                                 |
| `physics/common/max_physics_steps_per_frame` | 8         | read only at project start                                 |
| `physics/common/physics_jitter_fix`          | 0.5       | disabled automatically at runtime when interpolation is on |
| `physics/common/physics_interpolation`       | false     |                                                            |
| `physics/2d/default_gravity`                 | 980 px/s² |                                                            |
| `physics/3d/default_gravity`                 | 9.8 m/s²  |                                                            |

- Interpolation was added for 2D in [4.3](https://godotengine.org/releases/4.3/) and for 3D in [4.4](https://godotengine.org/releases/4.4/). In [4.5](https://godotengine.org/releases/4.5/) 3D interpolation moved from RenderingServer into SceneTree with the same API.
- 2D interpolation is server-side. 3D is scene-side, so 3D bodies created through the server need manual interpolation. `get_global_transform_interpolated()` exists only in 3D. 2D interpolates CPUParticles2D but not GPU particles. The docs recommend 20–30 or more ticks per second ([2D and 3D interpolation](https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/2d_and_3d_physics_interpolation.html)).
- The rules from the [quick start](https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/physics_interpolation_quick_start_guide.html):
  - Move objects and run game logic in `_physics_process`, including indirect movement such as moving a parent.
  - Call `reset_physics_interpolation()` after first placing a node and after every teleport.
  - To see the effect, test once with ticks set to 10.
- Code that interpolates by hand can read `Engine.get_physics_interpolation_fraction()` ([intro](https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/physics_interpolation_introduction.html)).

## 5. Collision layers, masks and naming

- Layer names live in `layer_names/2d_physics/layer_1..32` and `layer_names/3d_physics/layer_1..32` as strings, empty by default. Avoidance has its own `layer_names/avoidance/layer_N` ([ProjectSettings](https://docs.godotengine.org/en/stable/classes/class_projectsettings.html)).
- Layer means "what I am" and mask means "what I scan". Toggle single bits with `set_collision_layer_value(n, on)` and `set_collision_mask_value(n, on)`, where n is 1-based ([physics intro](https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html)).
- Suggested convention (opinion, not an official rule): name every layer you use, and give each a single noun such as `world`, `player`, `enemy`, `player_hitbox`, `pickup`. Hard-coded masks in scripts should go through named constants that mirror the project setting.

## 6. Shapes and performance

- Prefer primitive shapes for dynamic bodies, since they are more reliable and usually faster. Several convex shapes, or a convex decomposition, usually beat one concave shape up to some count. Concave shapes are the slowest but the most accurate, are the right choice for level collision, and work only on StaticBody. Keep the shape count low. Don't translate, rotate or scale CollisionShapes, and in particular never scale them in the editor; use the size handles ([collision shapes 3D](https://docs.godotengine.org/en/stable/tutorials/physics/collision_shapes_3d.html), [physics intro](https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html)).
- 4.5 merges TileMapLayer cell shapes into larger shapes ([4.5](https://godotengine.org/releases/4.5/)). 4.6 adds Mesh menu → generate a primitive `CollisionShape3D` ([4.6](https://godotengine.org/releases/4.6/)). 4.7 adds `CollisionShape2D.one_way_collision_direction` ([4.7](https://godotengine.org/releases/4.7/)).

## 7. Ray casts, shape casts and queries

Direct space queries are only safe inside `_physics_process`. Pass global coordinates, and filter with `collision_mask` plus `exclude` ([ray-casting](https://docs.godotengine.org/en/stable/tutorials/physics/ray-casting.html)).

```gdscript
func _physics_process(_d: float) -> void:
	var q := PhysicsRayQueryParameters3D.create(global_position,
		global_position + Vector3.DOWN * 2.0, collision_mask, [get_rid()])
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	if hit: print(hit.position, hit.normal, hit.collider)
```

RayCast2D/3D and ShapeCast2D/3D nodes update once per physics frame. Use `force_raycast_update()` / `force_shapecast_update()` when you need the result in the same tick. UNVERIFIED: not shown on the tutorial page; check the class refs.

## 8. Character controller patterns and game feel

Coyote time, jump buffering, variable jump height, and acceleration curves instead of instant velocity are design practice. No official Godot doc specifies them, so they are opinion.

```gdscript
const COYOTE := 0.1; const BUFFER := 0.12
var coyote_t := 0.0; var buffer_t := 0.0
func _physics_process(delta: float) -> void:
	coyote_t = COYOTE if is_on_floor() else maxf(coyote_t - delta, 0.0)
	buffer_t = BUFFER if Input.is_action_just_pressed("jump") else maxf(buffer_t - delta, 0.0)
	if buffer_t > 0.0 and coyote_t > 0.0:
		velocity.y = JUMP; buffer_t = 0.0; coyote_t = 0.0
	if Input.is_action_just_released("jump") and velocity.y < 0.0:
		velocity.y *= 0.5                      # variable jump height
	velocity.x = move_toward(velocity.x, Input.get_axis("left","right") * SPEED, ACCEL * delta)
	move_and_slide()
```

- Use a state machine (an enum with match, or one node per state) for idle, run, jump, fall and attack. Drive the AnimationTree state machine from that state, not from raw input.
- Read input in `_physics_process` with the `just_pressed` functions, or buffer events from `_unhandled_input`, so a press between ticks is not lost. This is inference from the fixed-tick model.

## 9. Animation system

- **AnimationMixer (4.2)** is the shared base of AnimationPlayer and AnimationTree. The same release added deterministic blending and removed the "capture" update mode ([4.2 article](https://godotengine.org/article/godot-4-2-arrives-in-style/)).
- **AnimationMixer properties and methods** ([AnimationMixer 4.7](https://docs.godotengine.org/en/stable/classes/class_animationmixer.html)):
  - `callback_mode_process`: Idle (default), Physics or Manual. Manual requires calling `advance(delta)`.
  - `deterministic` (default false). When true, weights are not normalized and blending starts from RESET.
  - Libraries: the global library sits under `""`. Use `add_animation_library(name, lib)` and refer to clips as `"lib/clip"`.
- **AnimationTree** ([tutorial 4.7](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html)):
  - Node types: StateMachine, BlendTree (Blend2/3, OneShot, TimeSeek, TimeScale, Transition), BlendSpace1D/2D.
  - Transitions switch Immediate, Sync or At End.
  - Advance conditions are bools. Advance expressions need the Advance Expression Base Node set.
  - `travel()` uses A\* and jumps straight to the target state when no path exists.
  ```gdscript
  var sm: AnimationNodeStateMachinePlayback = $AnimationTree["parameters/playback"]
  sm.travel("run")
  $AnimationTree["parameters/move/blend_position"] = Vector2(vx, vz)
  ```
- **Root motion.** Set `root_motion_track` to a bone track (e.g. `Skeleton3D:Root`), then read `get_root_motion_position()`, `get_root_motion_rotation()` and `get_root_motion_scale()`, or their accumulator variants, and pass the result to `move_and_slide()` ([AnimationTree tutorial](https://docs.godotengine.org/en/stable/tutorials/animation/animation_tree.html)).
  ```gdscript
  var rm := anim_tree.get_root_motion_position()
  velocity = (global_basis * rm) / delta   # convert per-tick delta to velocity
  move_and_slide()
  ```
  The `/ delta` conversion is inference, consistent with move_and_slide expecting a velocity.
- **Retargeting.** Retarget at import with BoneMap plus SkeletonProfileHumanoid, Bone Renamer (Unique Node) and Rest Fixer (Overwrite Axis, Fix Silhouette, Normalize Position Tracks). The reference pose is T-pose facing +Z ([retargeting 4.7](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/retargeting_3d_skeletons.html)). RetargetModifier3D, for runtime retargeting between skeletons, is in the class reference from 4.4 ([4.4 class ref](https://docs.godotengine.org/en/4.4/classes/class_retargetmodifier3d.html)).
- **SkeletonModifier3D family.** Override `_process_modification_with_delta(delta)` (4.5+; `_process_modification()` is deprecated). Do not apply `influence` yourself, because the Skeleton3D blends it ([SkeletonModifier3D 4.7](https://docs.godotengine.org/en/stable/classes/class_skeletonmodifier3d.html)). SkeletonIK3D is deprecated and is partly replaced by LookAtModifier3D, then by IKModifier3D. Class arrivals are listed in the table below.
- **Tweens vs AnimationPlayer vs code.**
  - Tweens are RefCounted, run on the SceneTree and start immediately. Create them with `create_tween()` (`Tween.new()` gives an invalid tween), and avoid more than one tween per property. Use `set_process_mode(Tween.TWEEN_PROCESS_PHYSICS)` when animating physics-relevant values. `tween_await()` is new in 4.7 ([Tween 4.7](https://docs.godotengine.org/en/stable/classes/class_tween.html), [4.7 release](https://godotengine.org/releases/4.7/)).
  - Rule of thumb (opinion): authored, reusable or multi-track motion goes in AnimationPlayer; one-off procedural UI or juice goes in a Tween; continuous gameplay motion goes in code inside `_physics_process`.
- **Sprites.** AnimatedSprite2D plus SpriteFrames suits plain frame swapping. Sprite2D (hframes/vframes/frame) driven by AnimationPlayer suits clips that also animate other properties. `AnimationPlayer.play()` applies on the next process, so call `advance(0)` if it must apply now ([2D sprite animation](https://docs.godotengine.org/en/stable/tutorials/2d/2d_sprite_animation.html)).
- **Cutout and skeletal 2D.** The nodes are Skeleton2D, Bone2D and Polygon2D with UV and weights. Overwrite Rest Pose after adding or removing bones, and animate bones rather than polygons. The docs page is marked work-in-progress and possibly outdated for 4.7 ([2D skeletons](https://docs.godotengine.org/en/stable/tutorials/animation/2d_skeletons.html)). UNVERIFIED: the current status of SkeletonModification2D / 2D IK in 4.7.

## Version table

| Feature                                                                                                                                                               | Version | Source                                                                                                                                               |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| AnimationMixer base class; deterministic blending; capture mode removed                                                                                               | 4.2     | [4.2](https://godotengine.org/article/godot-4-2-arrives-in-style/)                                                                                   |
| 2D physics interpolation                                                                                                                                              | 4.3     | [4.3](https://godotengine.org/releases/4.3/)                                                                                                         |
| SkeletonModifier3D (abstract, scriptable)                                                                                                                             | 4.3     | [4.3](https://godotengine.org/releases/4.3/)                                                                                                         |
| 3D physics interpolation                                                                                                                                              | 4.4     | [4.4](https://godotengine.org/releases/4.4/)                                                                                                         |
| Jolt built in (experimental, opt-in)                                                                                                                                  | 4.4     | [4.4](https://godotengine.org/releases/4.4/)                                                                                                         |
| LookAtModifier3D; SpringBoneSimulator3D; RetargetModifier3D                                                                                                           | 4.4     | [4.4](https://godotengine.org/releases/4.4/), [4.4 class ref](https://docs.godotengine.org/en/4.4/classes/class_skeletonmodifier3d.html)             |
| Animation markers usable in AnimationTree; shape `debug_color`/`debug_fill`                                                                                           | 4.4     | [4.4](https://godotengine.org/releases/4.4/)                                                                                                         |
| BoneConstraint3D, AimModifier3D, CopyTransformModifier3D, ConvertTransformModifier3D, ModifierBoneTarget3D, `_process_modification_with_delta`                        | 4.5     | [4.5](https://godotengine.org/releases/4.5/), [4.5 class ref](https://docs.godotengine.org/en/4.5/classes/class_skeletonmodifier3d.html)             |
| 3D interpolation moved into SceneTree; TileMapLayer merges collision shapes                                                                                           | 4.5     | [4.5](https://godotengine.org/releases/4.5/)                                                                                                         |
| Jolt default for new 3D projects, no longer experimental                                                                                                              | 4.6     | [4.6](https://godotengine.org/releases/4.6/), [ProjectSettings](https://docs.godotengine.org/en/stable/classes/class_projectsettings.html)           |
| IKModifier3D: TwoBoneIK3D, SplineIK3D, FABRIK3D, CCDIK3D, JacobianIK3D; twist and angular-velocity constraints (BoneTwistDisperser3D, LimitAngularVelocityModifier3D) | 4.6     | [4.6](https://godotengine.org/releases/4.6/), [SkeletonModifier3D 4.7](https://docs.godotengine.org/en/stable/classes/class_skeletonmodifier3d.html) |
| `Tween.tween_await()`; `CollisionShape2D.one_way_collision_direction`                                                                                                 | 4.7     | [4.7](https://godotengine.org/releases/4.7/)                                                                                                         |

The twist and angular-velocity class names are absent from the 4.5 class list and present in 4.7. The 4.6 release notes mention these constraints, so 4.6 is the inferred version.

## Determinism

- Godot Jolt makes no determinism guarantee: "may even happen to be deterministic, but this should not be relied upon" ([godot-jolt README](https://github.com/godot-jolt/godot-jolt)).
- UNVERIFIED: an official statement that GodotPhysics is non-deterministic. No docs page was found that says so either way, so treat it as non-deterministic across machines.
- If determinism is required, use Rapier's deterministic build ([godot-rapier-2d](https://github.com/appsinacup/godot-rapier-2d)).
  CONFLICT DETECTED: the Rapier project claims cross-platform determinism, while a [Godot forum thread](https://forum.godotengine.org/t/what-3d-physics-engine-should-i-use-both-integrated-and-plugins-included/105757) reports single-platform determinism only.
- Seed every `RandomNumberGenerator` explicitly. Keep gameplay in `_physics_process` with a fixed tick rate. Never feed `_process` delta into the simulation.

## Testing physics and animation headless

- Useful CLI flags ([command line 4.7](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html)):
  - `--headless`
  - `--fixed-fps N`, which "disables real-time synchronization"
  - `--quit-after N` (iterations)
  - `--time-scale`
  - `--debug-collisions`
- Probe pattern: load the scene, wait N `physics_frame` signals, assert positions within a tolerance, and print one summary line. That matches the project rule of judging a run by its log, not its exit code.

```gdscript
# godot --headless --fixed-fps 60 --path . -s res://tests/probe_fall.gd
extends SceneTree
func _initialize() -> void:
	var s: Node2D = load("res://tests/fixtures/fall.tscn").instantiate()
	root.add_child(s)
	for i in 60: await physics_frame
	var y: float = s.get_node("Body").position.y
	var ok := absf(y - 490.0) < 2.0     # ~0.5*980*1^2; tolerance, not equality
	print("PROBE fall %s y=%.2f" % ["PASS" if ok else "FAIL", y]); quit(0 if ok else 1)
```

- For animation, set `callback_mode_process = Manual` and call `advance(dt)` to step deterministically, then read bone poses or properties.
- UNVERIFIED: that `--fixed-fps 60` with 60 ticks gives exactly one physics step per frame. That follows from the docs' description of the flag but is untested here. The expected `y` above ignores semi-implicit Euler error, so calibrate the value once on 4.7.2.

## Checkable rules an agent should follow

1. Any `move_and_slide()` call sits inside `_physics_process` (grep the enclosing func).
1. Never `move_and_slide(` with an argument, and never `velocity * delta` assigned back into `velocity` right before `move_and_slide()`.
1. `move_and_collide(` arguments include `delta`.
1. A CharacterBody script assigns `position`/`global_position` only for spawn or teleport, and then calls `reset_physics_interpolation()` when interpolation is on.
1. RigidBody scripts change `position`, `linear_velocity` and transforms only in `_integrate_forces`.
1. `direct_space_state` is used only inside `_physics_process` or functions called from it.
1. `PhysicsRayQueryParameters*.create` passes a mask or exclude, not the default all-layers mask, when the caster has its own collider.
1. Every layer bit set on any CollisionObject in a `.tscn` has a name under `layer_names/{2d,3d}_physics/layer_N`.
1. No CollisionShape2D/3D in a `.tscn` has a non-unit `scale`.
1. `ConcavePolygonShape3D` and `ConcavePolygonShape2D` are used only under StaticBody, or under a frozen-static RigidBody.
1. An AnimatableBody with `sync_to_physics=true` is never moved with `move_and_collide`.
1. A moving platform animated by AnimationPlayer is an AnimatableBody, not a StaticBody.
1. If `physics/common/physics_interpolation=true`, no `_process` function moves a physics body or its parent.
1. `physics_ticks_per_second` is at least 20 when interpolation is on, and some rationale is noted when it differs from 60.
1. A project that sets Jolt has no unsupported joint properties at non-default values (list in §1).
1. A Jolt project does not rely on `physics/3d/solver/*` changes, because they are ignored.
1. Tweens come from `create_tween()`, never `Tween.new()`. No two tweens target the same property on the same object.
1. Tweens and AnimationMixers that move physics bodies use the physics process mode.
1. AnimationTree state changes go through `parameters/playback` and `travel()`/`start()`, not by swapping AnimationPlayer clips directly while the tree is active.
1. Root-motion scenes set `root_motion_track` to a bone path, and their scripts call `get_root_motion_position()`.
1. No new code uses `SkeletonIK3D` or overrides `_process_modification()`. Use IKModifier3D subclasses or `_process_modification_with_delta()`.
1. Scripts do not read gravity as a literal. They use `ProjectSettings.get_setting("physics/{2d,3d}/default_gravity")` or `get_gravity()`.
1. Every `RandomNumberGenerator` used in gameplay or tests sets `seed`.
1. Physics probes assert with a tolerance and print a summary line.

## What a tool could check automatically

- **project.godot**
  - Report `physics/3d/physics_engine` and warn when it is unset on a project created on 4.6 or later, since its meaning differs from older projects.
  - Report the tick rate, `max_physics_steps_per_frame`, interpolation, jitter fix and separate-thread settings. Warn when separate-thread is on with Jolt.
  - List the `layer_names/*_physics/*` entries.
- **Layer audit** (parse `.tscn` `collision_layer=`/`collision_mask=` ints)
  - Flag bits with no name.
  - Flag named layers that nothing uses.
  - Flag masks that scan no layer anyone is on.
  - Flag bodies with layer 0.
- **Scene audit**
  - CollisionShape nodes with non-identity scale.
  - Concave shapes on non-static bodies.
  - Physics bodies with no shape child.
  - AnimatableBody with `sync_to_physics` plus `move_and_collide` in its script.
  - Jolt-unsupported joint properties.
  - AnimationTree missing `anim_player`.
  - Empty `root_motion_track` when a script reads root motion.
- **Script lint** (regex or GDScript parse): rules 1–7, 13, 17, 21–23.
- **Headless probes** (`--headless --fixed-fps 60 --quit-after`)
  - Fall test: free-fall distance after N ticks against ½gt².
  - Slope test: a CharacterBody stays on the floor down a 30° ramp with the default snap.
  - Platform test: body velocity matches the platform after it leaves.
  - Animation `advance()` pose snapshot.
  - Run each probe twice and compare logs to detect nondeterminism on the same machine.
- **Version guard**: flag APIs newer than the project's `config/features` version, such as `tween_await` (4.7), IKModifier3D (4.6) and BoneConstraint3D (4.5).

## Pitfalls

- Multiplying by delta twice with `move_and_slide`, which makes movement frame-rate dependent and very slow.
- Reading `is_on_floor()` before any `move_and_slide()` has run this tick. It reports the previous tick.
- Jumping with snap still active, so the body sticks to the floor. Set an upward velocity first.
- Teleporting with interpolation on without `reset_physics_interpolation()`, which causes streaking.
- Moving bodies or cameras in `_process` with interpolation on, which causes jitter.
- Scaled collision shapes, and concave shapes on dynamic bodies.
- Expecting `face_index` or kinematic contacts under Jolt without enabling them.
- Old 4.3–4.5 projects silently keep GodotPhysics while new ones get Jolt, so behaviour differs between projects.
- `Tween.new()` gives an invalid tween. An empty tween errors unless killed. Tweens start immediately.
- `AnimationPlayer.play()` applies one frame late unless followed by `advance(0)`.
- Deterministic replays or rollback built on the built-in engines.
- Space queries outside the physics callback hit a locked space.

## Risks and uncertainties

- 4.7 behaviour was read from docs. Nothing was run against 4.7.2, so every probe value is UNTESTED.
- Rapier and Jolt determinism claims come from extension READMEs, not engine docs.
- Rule thresholds such as the tick-rate minimum and the coyote and buffer windows are design opinion.

## Sources

- https://docs.godotengine.org/en/latest/tutorials/physics/using_jolt_physics.html — Jolt differences and settings
- https://docs.godotengine.org/en/stable/classes/class_projectsettings.html — physics keys, defaults, Jolt default from 4.6, layer_names
- https://godotengine.org/releases/4.3/ , /4.4/ , /4.5/ , /4.6/ , /4.7/ — release feature arrivals
- https://godotengine.org/article/godot-4-2-arrives-in-style/ — AnimationMixer
- https://docs.godotengine.org/en/stable/classes/class_characterbody2d.html , class_characterbody3d.html — move_and_slide defaults and units
- https://docs.godotengine.org/en/stable/tutorials/physics/using_character_body_2d.html — move_and_collide vs move_and_slide
- https://docs.godotengine.org/en/stable/tutorials/physics/physics_introduction.html — body types, layers, RigidBody rules
- https://docs.godotengine.org/en/stable/classes/class_animatablebody3d.html — sync_to_physics
- https://docs.godotengine.org/en/stable/tutorials/physics/collision_shapes_3d.html — shape performance
- https://docs.godotengine.org/en/stable/tutorials/physics/ray-casting.html — queries
- https://docs.godotengine.org/en/stable/tutorials/physics/interpolation/ (quick start, intro, 2d_and_3d) — interpolation rules
- https://docs.godotengine.org/en/stable/classes/class_animationmixer.html , tutorials/animation/animation_tree.html — mixer, tree, root motion
- https://docs.godotengine.org/en/stable/classes/class_skeletonmodifier3d.html (plus the 4.4 and 4.5 versions) — modifier family and its versions
- https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/retargeting_3d_skeletons.html — retargeting
- https://docs.godotengine.org/en/stable/classes/class_tween.html — Tween rules
- https://docs.godotengine.org/en/stable/tutorials/2d/2d_sprite_animation.html , tutorials/animation/2d_skeletons.html — 2D animation
- https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html — headless flags
- https://github.com/godot-jolt/godot-jolt — determinism disclaimer
- https://github.com/appsinacup/godot-rapier-2d , https://godotengine.org/asset-library/asset/edit/19239 — Rapier backend
- https://forum.godotengine.org/t/what-3d-physics-engine-should-i-use-both-integrated-and-plugins-included/105757 — contested Rapier determinism (forum; cited only to surface the conflict)
