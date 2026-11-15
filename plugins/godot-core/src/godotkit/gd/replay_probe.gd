extends Node
## godotkit replay probe, added as an autoload: presses the recorded actions and replays clicks and
## semantic calls on their physics frames, records action changes when asked, and prints the hash
## of the `playtest_state` node every K frames and on the frames a recording hashed.
## With a feel subject it also prints, every frame, where the subject is and whether the camera clips.

const ARG_PREFIX: String = "--godotkit-replay="
const STATE_GROUP: StringName = &"playtest_state"
const ACTOR_GROUP: StringName = &"playtest_actor"
# Movers the camera ray looks past before it gives up on finding level geometry behind them.
const MAX_MOVERS: int = 4

var _frames: int = 0
var _every: int = 1
var _record: bool = false
var _acts: Dictionary[int, Array] = {}
var _gestures: Dictionary[int, Array] = {}
var _at: Dictionary[int, bool] = {}
var _held: Dictionary[StringName, float] = {}
var _frame: int = 0
var _hashes: int = 0
var _state_path: String = ""
var _reported: bool = false
var _subject: String = ""


func _ready() -> void:
	# Physics callbacks run by priority, then tree order; this probe goes before every game node.
	process_physics_priority = -1000000
	var config: Dictionary = _config()
	_frames = config.get("frames", 0)
	var every: int = config.get("every", 1)
	_every = maxi(1, every)
	_record = config.get("record", false)
	_subject = config.get("subject", "")
	var acts: Array = config.get("acts", [])
	for act: Array in acts:
		var frame: int = act[0]
		if not _acts.has(frame):
			_acts[frame] = []
		_acts[frame].append(act)
	var gestures: Array = config.get("gestures", [])
	for gesture: Dictionary in gestures:
		var at: int = gesture["f"]
		if not _gestures.has(at):
			_gestures[at] = []
		_gestures[at].append(gesture)
	var hashed: Array = config.get("at", [])
	for frame: int in hashed:
		_at[frame] = true
	# Headless windows are 64x64 px; the project's size keeps clicks and layout as designed.
	if DisplayServer.get_name() == "headless":
		var width: int = ProjectSettings.get_setting("display/window/size/viewport_width")
		var height: int = ProjectSettings.get_setting("display/window/size/viewport_height")
		get_window().size = Vector2i(width, height)


# At the start of physics frame n the game has completed n - 1 frames: hash first, then press.
func _physics_process(_delta: float) -> void:
	_frame += 1
	var done: int = _frame - 1
	if done > 0 and (done % _every == 0 or done == _frames or _at.has(done)):
		_print_hash(done)
	if done > 0 and not _subject.is_empty():
		_print_feel(done)
	if done >= _frames:
		_report(done)
		get_tree().quit()
		return
	for act: Array in _acts.get(_frame, []):
		var event: InputEventAction = InputEventAction.new()
		event.action = act[1]
		event.pressed = act[2]
		event.strength = act[3]
		Input.parse_input_event(event)
	# Buffered events would reach the game a frame late; the recording counts this frame.
	Input.flush_buffered_events()
	for gesture: Dictionary in _gestures.get(_frame, []):
		if gesture.has("click"):
			var path: String = gesture["click"]
			_click(path)
		else:
			var action: String = gesture["do"]
			var args: Dictionary = gesture.get("args", {})
			_call(action, args)
	if _record:
		_record_changes()


func _exit_tree() -> void:
	_report(maxi(0, _frame - 1))


func _print_hash(done: int) -> void:
	var state: Node = get_tree().get_first_node_in_group(STATE_GROUP)
	if state == null or not state.has_method(&"state_hash"):
		return
	_state_path = str(state.get_path())
	var value: String = str(state.call(&"state_hash"))
	_hashes += 1
	print("GODOTKIT_REPLAY_HASH " + JSON.stringify({"f": done, "hash": value}))


func _print_feel(done: int) -> void:
	var scene: Node = get_tree().current_scene
	var subject: Node3D = scene.get_node_or_null(_subject) as Node3D if scene else null
	var camera: Camera3D = get_viewport().get_camera_3d()
	var clip: bool = false
	if camera != null:
		clip = _camera_clips(camera, subject)
	var at: Array = []
	if subject != null:
		at = [subject.global_position.x, subject.global_position.y, subject.global_position.z]
	print("GODOTKIT_FEEL " + JSON.stringify({"f": done, "pos": at, "clip": clip}))


# The camera clips when it sits inside a body or level geometry stands between it and the
# subject; a character or rigid body crossing the view is a passing occluder, not a camera fault.
func _camera_clips(camera: Camera3D, subject: Node3D) -> bool:
	var space: PhysicsDirectSpaceState3D = camera.get_world_3d().direct_space_state
	var point: PhysicsPointQueryParameters3D = PhysicsPointQueryParameters3D.new()
	point.position = camera.global_position
	if not space.intersect_point(point, 1).is_empty():
		return true
	if subject == null:
		return false
	var ray: PhysicsRayQueryParameters3D = PhysicsRayQueryParameters3D.create(
		camera.global_position, subject.global_position)
	var excluded: Array[RID] = []
	var body: CollisionObject3D = subject as CollisionObject3D
	if body != null:
		excluded.append(body.get_rid())
	for attempt: int in MAX_MOVERS:
		ray.exclude = excluded
		var hit: Dictionary = space.intersect_ray(ray)
		if hit.is_empty():
			return false
		var collider: Object = hit["collider"]
		if not (collider is PhysicsBody3D and not collider is StaticBody3D):
			return true
		excluded.append(hit["rid"])
	return false


func _click(path: String) -> void:
	var control: Control = get_node_or_null(NodePath(path)) as Control
	if control == null or not control.is_visible_in_tree():
		push_error("godotkit replay: no visible Control at %s on frame %d" % [path, _frame])
		return
	var centre: Vector2 = control.get_global_transform_with_canvas() * (control.size * 0.5)
	var at: Vector2 = get_viewport().get_final_transform() * centre
	var motion: InputEventMouseMotion = InputEventMouseMotion.new()
	motion.position = at
	motion.global_position = at
	Input.parse_input_event(motion)
	for down: bool in [true, false]:
		var button: InputEventMouseButton = InputEventMouseButton.new()
		button.button_index = MOUSE_BUTTON_LEFT
		button.pressed = down
		button.position = at
		button.global_position = at
		Input.parse_input_event(button)
	Input.flush_buffered_events()


func _call(action: String, args: Dictionary) -> void:
	var actor: Node = get_tree().get_first_node_in_group(ACTOR_GROUP)
	if actor == null or not actor.has_method(&"playtest_do"):
		push_error("godotkit replay: no %s node for %s on frame %d" % [ACTOR_GROUP, action, _frame])
		return
	actor.call(&"playtest_do", action, args)


func _record_changes() -> void:
	for action: StringName in InputMap.get_actions():
		var strength: float = Input.get_action_raw_strength(action) if Input.is_action_pressed(action) else 0.0
		var before: float = _held.get(action, 0.0)
		if is_equal_approx(strength, before):
			continue
		_held[action] = strength
		print("GODOTKIT_REPLAY_ACT " + JSON.stringify(
			{"f": _frame, "action": str(action), "pressed": strength > 0.0, "strength": strength}))


func _report(done: int) -> void:
	if _reported:
		return
	_reported = true
	print("GODOTKIT_REPLAY " + JSON.stringify({"frames": done, "hashes": _hashes, "state": _state_path}))


func _config() -> Dictionary:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with(ARG_PREFIX):
			var text: String = FileAccess.get_file_as_string(arg.trim_prefix(ARG_PREFIX))
			var parsed: Variant = JSON.parse_string(text)
			if parsed is Dictionary:
				return parsed
	push_error("godotkit replay probe: no readable %s config file" % ARG_PREFIX)
	return {}
