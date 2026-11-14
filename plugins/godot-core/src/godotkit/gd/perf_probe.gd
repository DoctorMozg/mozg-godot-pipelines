extends Node
## godotkit perf probe, added as an autoload: starts the scene again with the scale property set
## before its _ready, then times every frame and prints one summary line.

const ARG_PREFIX: String = "--godotkit-perf="
# Godot refreshes its TIME_* monitors once per real second, too rarely for a lockstep run.
const COUNTERS: Dictionary[String, Performance.Monitor] = {
	"draw_calls": Performance.RENDER_TOTAL_DRAW_CALLS_IN_FRAME,
	"objects": Performance.RENDER_TOTAL_OBJECTS_IN_FRAME,
	"nodes": Performance.OBJECT_NODE_COUNT,
}

var _config: Dictionary = {}
var _scene: Node
var _started: bool = false
var _frame: int = 0
var _last_frame_usec: int = 0
var _process_usec: int = 0
var _physics_usec: int = 0
var _physics_ms: float = 0.0
var _samples: Dictionary[String, PackedFloat64Array] = {}


func _ready() -> void:
	_config = _read_config()
	# The tree's frame signals start each timing; these callbacks run after every game node's.
	process_priority = 1000000
	process_physics_priority = 1000000
	get_tree().process_frame.connect(_on_process_start)
	get_tree().physics_frame.connect(_on_physics_start)
	_restart.call_deferred()


func _on_physics_start() -> void:
	_physics_usec = Time.get_ticks_usec()


func _physics_process(_delta: float) -> void:
	_physics_ms += (Time.get_ticks_usec() - _physics_usec) / 1000.0


func _on_process_start() -> void:
	var now: int = Time.get_ticks_usec()
	if _measuring() and _last_frame_usec > 0:
		_add("frame_ms", (now - _last_frame_usec) / 1000.0)
	_last_frame_usec = now
	_process_usec = now


func _process(_delta: float) -> void:
	if not _started:
		return
	_frame += 1
	if _measuring():
		_add("process_ms", (Time.get_ticks_usec() - _process_usec) / 1000.0)
		_add("physics_ms", _physics_ms)
		for key: String in COUNTERS:
			_add(key, Performance.get_monitor(COUNTERS[key]))
		for key: StringName in Performance.get_custom_monitor_names():
			var value: float = Performance.get_custom_monitor(key)
			_add(str(key), value)
	_physics_ms = 0.0
	var warmup: int = _config.get("warmup", 0)
	var frames: int = _config.get("frames", 1)
	if _frame >= warmup + frames:
		_report(frames)


func _measuring() -> bool:
	var warmup: int = _config.get("warmup", 0)
	return _started and _frame > warmup


# A scale property such as a unit count is read in _ready, so the scene starts again with it set.
func _restart() -> void:
	var tree: SceneTree = get_tree()
	_scene = tree.current_scene
	var property: String = _config.get("property", "")
	if _scene != null and not property.is_empty():
		var packed: PackedScene = load(_scene.scene_file_path)
		var fresh: Node = packed.instantiate()
		if property in fresh:
			fresh.set(property, _config.get("size", 0))
		tree.root.remove_child(_scene)
		# Freed at once, so the old scene's nodes never reach the measured frames.
		_scene.free()
		tree.root.add_child(fresh)
		tree.current_scene = fresh
		_scene = fresh
	_started = true


func _report(frames: int) -> void:
	var property: String = _config.get("property", "")
	var report: Dictionary = {
		"scene": _scene.scene_file_path if _scene else "",
		"frames": frames,
		"size_set": property.is_empty() or (_scene != null and property in _scene),
		"renderer": RenderingServer.get_current_rendering_method(),
	}
	for key: String in _samples:
		report[key] = _stats(_samples[key])
	print("GODOTKIT_PERF " + JSON.stringify(report))
	get_tree().quit()


func _add(key: String, value: float) -> void:
	if not _samples.has(key):
		_samples[key] = PackedFloat64Array()
	_samples[key].append(value)


func _stats(values: PackedFloat64Array) -> Dictionary:
	var sorted: PackedFloat64Array = values.duplicate()
	sorted.sort()
	var last: int = sorted.size() - 1
	return {"p50": sorted[int(last * 0.5)], "p95": sorted[int(last * 0.95)], "max": sorted[last]}


func _read_config() -> Dictionary:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with(ARG_PREFIX):
			var parsed: Variant = JSON.parse_string(arg.trim_prefix(ARG_PREFIX))
			if parsed is Dictionary:
				return parsed
	push_error("godotkit perf probe: no valid %s argument" % ARG_PREFIX)
	return {}
