# Maintainable GDScript architecture (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org/en/stable (serving 4.7). Links point at `/en/stable/`; pin them to `/en/4.7/` when quoting in shipped skills. Confidence per claim: [high] official docs, [medium] well-known community source, UNVERIFIED as marked.

## Style guide

[gdscript_styleguide](https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/gdscript_styleguide.html) [high]

- Naming:
  - Files are snake_case and match the snake_case form of their `class_name`.
  - Classes and nodes are PascalCase; functions and variables are snake_case.
  - Signals are past-tense snake_case (`door_opened`).
  - Constants and enum members are CONSTANT_CASE; enum names are singular PascalCase.
  - Private members and virtual methods start with `_`.
- Member order:
  1. `@tool`, `@icon`, `@static_unload`, then `class_name`, `extends`, `##` doc.
  1. Signals, enums, constants, static vars, `@export` vars, vars, `@onready` vars.
  1. `_static_init`, static methods.
  1. Virtuals: `_init`, `_enter_tree`, `_ready`, `_process`, `_physics_process`, others.
  1. Overridden custom methods, remaining methods, inner classes; public before private in every group.
- Formatting:
  - Tabs; continuation lines take 2 indent levels in calls and 1 in arrays, dictionaries and enums.
  - Lines under 100 characters (ideally 80); 2 blank lines around functions and classes.
  - Trailing comma in multi-line collections; double quotes; `and`/`or`/`not` over `&&`/`||`/`!`.
- Typing: `:=` when the type is obvious on the line, an explicit type otherwise (`get_node()`). A failed `as` cast returns `null` silently.
- `Dictionary[K, V]` exists since 4.4 ([4.4 dev 2](https://godotengine.org/article/dev-snapshot-godot-4-4-dev-2/)) [high].

## Architecture

- [Scene organization](https://docs.godotengine.org/en/stable/tutorials/best_practices/scene_organization.html) \[high\]:
  - "Design scenes to have no dependencies"; siblings never talk directly, "an ancestor mediates".
  - Five injection forms: a signal (responds to behaviour, never starts it), a method name, a Callable property, an Object reference, a NodePath.
  - Remaining dependencies are declared through `@tool` plus `_get_configuration_warnings()`.
- Call down, signal up: "If you're using get_parent() or get_node("..") then you're probably headed for trouble." ([Godot Recipes 4.x](https://kidscancode.org/godot_recipes/4.x/basics/node_communication/index.html)) [medium]. The official docs do not use the phrase.
- [Scenes vs scripts](https://docs.godotengine.org/en/stable/tutorials/best_practices/scenes_versus_scripts.html) \[high\]: game concepts are scenes; reusable tools are `class_name` scripts. UNVERIFIED: no official "composition over inheritance" statement.
- [Autoloads](https://docs.godotengine.org/en/stable/tutorials/best_practices/autoloads_versus_regular_nodes.html) \[high\]:
  - Three named problems: global state, global access, global allocation.
  - Fit only for systems that manage their own data.
  - Alternatives: `static func`/`static var` (4.1+), a per-scene `class_name` node, a shared custom Resource.
- Event bus (signal-only autoload): decouples distant and runtime-spawned nodes, but signals pile up and tracing needs a project search; "You don't want to use this all over the place" ([GDQuest, 2021, Godot 3 syntax](https://www.gdquest.com/tutorial/godot/design-patterns/event-bus-singleton/)) [medium].
- [References](https://docs.godotengine.org/en/stable/tutorials/best_practices/godot_interfaces.html) \[high\]:
  - A typed `@export var target: Node` is fastest and survives moves; cache `get_node` in `@onready`.
  - Groups and `has_method` as informal interfaces need documentation.
- [`%Name`](https://docs.godotengine.org/en/stable/tutorials/scripting/scene_unique_nodes.html) [high] resolves only within the same owner scene; reach into an instance through it.
- [Resources](https://docs.godotengine.org/en/stable/classes/class_resource.html) \[high\]:
  - Loads of one path share one instance, so a runtime change leaks to every user.
  - `resource_local_to_scene` copies per instance; `duplicate(true)` fails when `_init()` has required parameters.
- `duplicate(true)` copies only internal subresources since 4.5; `duplicate_deep(Resource.DEEP_DUPLICATE_ALL)` restores the old behaviour ([upgrading to 4.5](https://docs.godotengine.org/en/stable/tutorials/migrating/upgrading_to_godot_4.5.html)) [high].
- Pure logic in `RefCounted` or `Resource` classes with no SceneTree, unit-testable headless ([node alternatives](https://docs.godotengine.org/en/stable/tutorials/best_practices/node_alternatives.html)) [high].

## Signals and coroutines

- `sig.connect(callable)` is checked at compile time; `connect("name", …)` is not ([Signal](https://docs.godotengine.org/en/stable/classes/class_signal.html)) [high].
- Connection rules:
  - `.bind()` arguments come after the emitted ones.
  - A duplicate connect returns `ERR_INVALID_PARAMETER`; disconnecting a missing connection errors, so guard with `is_connected()`.
  - Freeing the target drops the connection.
- Flags: `CONNECT_ONE_SHOT`, `CONNECT_DEFERRED`, `CONNECT_PERSIST` (no lambdas), `CONNECT_APPEND_SOURCE_OBJECT`.
- Typed signal parameters parse, but "it's up to you to emit the correct values" (gdscript_basics). UNVERIFIED: argument types are not enforced on emit.
- Lambdas capture locals by value at creation [high].
- `await` yields the single argument, an Array for several, `null` for none [high]. UNVERIFIED (forums): a coroutine whose node is freed never resumes.
- `SceneTree.create_timer(t)` keeps counting during pause unless `process_always` is `false` ([SceneTree](https://docs.godotengine.org/en/stable/classes/class_scenetree.html)) [high].
- `SceneTree.create_tween()` outlives nodes; `Node.create_tween()` dies with its node [high].

## Lifecycle

[Node](https://docs.godotengine.org/en/stable/classes/class_node.html), [Object](https://docs.godotengine.org/en/stable/classes/class_object.html) [high]

- `_enter_tree` runs parent first; `_ready` runs children first and only once, unless `request_ready()` is called.
- `@export` combined with `@onready` "doesn't work as you might expect".
- `add_child` during the parent's setup fails with "Parent node is busy setting up children"; use `add_child.call_deferred(child)` (error text from the forum [medium]; AloneGodot `d1d7760~1` reproduces it).
- `call_deferred` runs at idle time and returns `null`.
- `queue_free()` is safe to call twice; access after `free()` is a runtime error; `is_instance_valid()` is false after `free`.
- [Pause](https://docs.godotengine.org/en/stable/tutorials/scripting/pausing_games.html) \[high\]:
  - `process_mode` defaults to INHERIT.
  - Paused nodes get no process or input callbacks, but their signal handlers still run.
  - A pause menu uses `PROCESS_MODE_WHEN_PAUSED`.

## Errors

- `assert` runs only in debug builds; its condition must have no side effects ([gdscript_basics](https://docs.godotengine.org/en/stable/tutorials/scripting/gdscript/gdscript_basics.html)) [high].
- `push_error`/`push_warning` log with a stack trace and continue ([@GlobalScope](https://docs.godotengine.org/en/stable/classes/class_@globalscope.html)) [high].
- No exceptions: failing functions return `Error` (`OK == 0`); `error_string(err)` names it.
- Boundary checks use `push_error` plus a return so they also run in release; `assert` guards internal invariants.

## Anti-patterns

| Anti-pattern                                          | Instead                                                            |
| ----------------------------------------------------- | ------------------------------------------------------------------ |
| `get_node("../../HUD")`, `get_parent().foo`           | A signal up, or a dependency injected by the parent                |
| Long `$A/B/C` paths                                   | `%UniqueName` or a typed `@export` reference                       |
| Untyped `{"hp": 10}` game data                        | A `class_name` Resource with typed exports, or `Dictionary[K, V]`  |
| A god autoload mutating other systems' data           | One small autoload per system owning its own state; static helpers |
| An event bus for parent/child traffic                 | Direct signals; the bus only for cross-tree events                 |
| Mutating a shared `.tres` at runtime                  | `resource_local_to_scene` or `duplicate_deep()`                    |
| UI writing game state directly (UNVERIFIED synthesis) | UI listens to model signals and sends intents                      |

## Checkable rules

1. File names are snake_case and match their `class_name`.
1. Signals are past tense; constants and enum members are CONSTANT_CASE.
1. Members follow the official order.
1. Tabs, lines under 100 characters, 2 blank lines between functions.
1. Every variable, parameter and return is typed; `untyped_declaration` is an error.
1. No `get_parent()`, and no `get_node`/`$` path containing `..`.
1. Own-scene nodes come through `%Name` or typed `@export`, cached in `@onready`.
1. No string `connect("…")` or `emit_signal("…")`.
1. An autoload owns only its own state; an event-bus autoload declares only signals.
1. A `.tres` changed at runtime is local to scene or duplicated first.
1. Code relying on deep external copies uses `duplicate_deep(DEEP_DUPLICATE_ALL)` (4.5+).
1. Game rules live in `RefCounted`/`Resource` classes with headless tests.
1. Children added during setup use `add_child.call_deferred`.
1. Nodes are deleted with `queue_free()`; a plain `free()` carries a comment.
1. An `await` that can outlive its node is followed by an `is_instance_valid(self)` or `is_inside_tree()` check; gameplay timers use `create_timer(t, false)`.
1. Tweens come from `Node.create_tween()` unless meant to outlive the node.
1. `PROCESS_MODE_ALWAYS` in gameplay carries a comment.
1. `assert` conditions have no side effects; boundary checks use `push_error` and a return.
1. Fallible functions return `Error` or a typed result, and callers check it.
1. `@export` and `@onready` never share a variable.

## Gaps

- No open-source Godot 4 production codebase was surveyed.
- Typed-signal enforcement and `await` on freed nodes rest on forum sources only.
