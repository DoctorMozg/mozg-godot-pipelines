# Strict GDScript: static typing and warnings (Godot 4.7)

Source: web research of 2026-11-13 against Godot source at the `4.7` branch (`modules/gdscript/gdscript_warning.h`, `gdscript.cpp`, `gdscript_parser.cpp`, `main/main.cpp`, `core/debugger/local_debugger.cpp`) and docs.godotengine.org 4.3–4.7. The defaults in the 4.7 header and the 4.7 docs match. Claims read from source but not run on 4.7.2 are marked UNTESTED.

## Warning levels

Each warning is `debug/gdscript/warnings/<name>` with 0 = Ignore, 1 = Warn, 2 = Error ([ProjectSettings 4.7](https://docs.godotengine.org/en/4.7/classes/class_projectsettings.html)). 4.7 has 46 emitted warnings.

| Warnings | Default | Strict |
| --- | --- | --- |
| `untyped_declaration`, `unsafe_property_access`, `unsafe_method_access`, `unsafe_cast`, `unsafe_call_argument` | 0 | 2 |
| `missing_await` (key in docs from 4.6) | 0 | 2 |
| `inferred_declaration` (forbids `:=`) | 0 | style choice |
| `return_value_discarded` (noisy on `connect`, Tween) | 0 | 1, or 2 with `@warning_ignore` |
| `unsafe_void_return`, `unassigned_variable`, `unassigned_variable_op_assign` | 1 | 2 |
| `unused_variable`, `unused_local_constant`, `unused_private_class_variable`, `unused_parameter`, `unused_signal` | 1 | 2 |
| `shadowed_variable`, `shadowed_variable_base_class`, `shadowed_global_identifier` | 1 | 2 |
| `unreachable_code`, `unreachable_pattern`, `standalone_expression`, `standalone_ternary`, `incompatible_ternary` | 1 | 2 |
| `integer_division`, `narrowing_conversion`, `int_as_enum_without_cast`, `int_as_enum_without_match`, `enum_variable_without_default` | 1 | 2 |
| `static_called_on_instance`, `missing_tool`, `redundant_static_unload`, `redundant_await`, `assert_always_true`, `assert_always_false`, `empty_file`, `deprecated_keyword` | 1 | 2 |
| `confusable_identifier`, `confusable_local_declaration`, `confusable_local_usage`, `confusable_capture_reassignment`, `confusable_temporary_modification` | 1 | 2 |
| `inference_on_variant`, `native_method_override`, `get_node_default_without_onready`, `onready_with_export` | 2 | 2 |

- Non-level keys: `enable` (true), `renamed_in_godot_4_hint` (true), `directory_rules` (4.6+), `exclude_addons` (4.5 and earlier).
- `property_used_as_function`, `constant_used_as_function` and `function_used_as_property` are never emitted ("migrated from 3.x by mistake").
- `onready_with_cast` exists on master only (UNVERIFIED: probably 4.8).
- The docs recommend `untyped_declaration` for enforcing types and note that "`UNSAFE_*` warnings do not cover all cases that unsafe lines cover" ([static typing 4.7](https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/static_typing.html)).

```ini
[debug]

gdscript/warnings/untyped_declaration=2
gdscript/warnings/unsafe_property_access=2
gdscript/warnings/unsafe_method_access=2
gdscript/warnings/unsafe_cast=2
gdscript/warnings/unsafe_call_argument=2
gdscript/warnings/missing_await=2
gdscript/warnings/return_value_discarded=1
gdscript/warnings/directory_rules={"res://addons": 0, "res://addons/my_own_addon": 1}
```

Only keys that differ from the default are written to `project.godot`.

### directory_rules (4.6+)

- `directory_rules` is a Dictionary with 0 = Exclude and 1 = Include, default `{"res://addons": 0}`. It replaced the `exclude_addons` boolean (commit of 2025-11-12; the 4.5 docs still list `exclude_addons`).
- The deepest rule wins. An excluded script emits no warnings at all, including Error-level ones.
- UNVERIFIED: whether an old `exclude_addons` key is migrated.

## Where warnings surface

| Situation | Behaviour |
| --- | --- |
| Warn level | Never blocks a run ([warning system 4.7](https://docs.godotengine.org/en/4.7/tutorials/scripting/gdscript/warning_system.html)) |
| Error level, debug or editor build | Becomes a parse error `… (Warning treated as error.)`; the script fails to load at runtime too |
| Error level, release template | Compiled out (`#ifdef DEBUG_ENABLED`): gates must use the editor or debug binary |
| `load()` from a `-s` script, CACHE_MODE_IGNORE included | Same parser, prints `Parse Error: … (Warning treated as error.)` |
| Warn level at runtime | Printed only when an engine debugger is active, otherwise dropped |
| `--headless --check-only -s file.gd` | Loads that script and its dependencies; exit code reflects `is_valid()` |

- UNTESTED: `-d` (local stdout debugger) makes headless runs print Warn-level warnings. It may stop at an interactive `debug>` prompt on a script error, so close stdin and keep a timeout.
- Consequence for `godotkit check`: Error-level warnings already fail the parse gate, because it loads every script.
- UNVERIFIED: whether a failed `load()` returns null or an invalid Script.

## Typed collections

- Version history:
  - `Array[T]` since 4.0.
  - `Dictionary[K, V]` since 4.4 ([4.4 release](https://godotengine.org/releases/4.4/)).
  - Nested typed collections (`Array[Array[int]]`) are not supported.
- Performance and checks: typed arrays iterate faster than untyped ones; packed arrays are faster still for primitives. Every insert is type-checked ([Array 4.7](https://docs.godotengine.org/en/4.7/classes/class_array.html)).
- Where the element type applies: `for` variables and `[]`. Methods such as `push_back`, value-returning Dictionary methods and `==` stay untyped.
- Untyped to typed: convert with `typed.assign(untyped)`. `map()` and `filter()` return a plain `Array`.
- Typed arrays are invariant: an `Array[Node2D]` does not assign to `Array[Node]` without `assign()` (forum evidence, medium).

## Typing speed

Typed opcodes are faster ([typed instructions, 2020, 4.0-dev](https://godotengine.org/article/gdscript-progress-report-typed-instructions)). The figures are UNTESTED on 4.7:

- Operators: 25–50 %.
- Native method calls: 70–150 %.
- `for` loops: 10–50 %.

Untyped globals such as `abs()` lose the gain; use `absf()` and `absi()`.

## Annotations and language features

| Item | Since |
| --- | --- |
| `@warning_ignore("name")` (next statement) | 4.0 |
| `@warning_ignore_start` / `@warning_ignore_restore` (string literals; without restore, to end of file) | 4.4 |
| `@export_tool_button` | 4.4 |
| `@abstract` classes and methods; variadic `...args` | 4.5 |
| `directory_rules` | 4.6 |
| Traits | not shipped; PR #107227 closed 2026-07-08 |

- `as` on a class mismatch yields `null` silently; on built-in types it errors. Check with `is` first; casting a `Variant` raises `unsafe_cast`.
- `class_name` registers a global name (a clash raises `shadowed_global_identifier`). `const X = preload(...)` also works as a type without a global name. The choice between them is a style decision (no official recommendation found).
- `@static_unload`: the docs note that scripts are currently never freed.
