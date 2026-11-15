extends Node
## godotkit play bridge, an autoload a `godotkit play` session injects: connects to the session on
## loopback, plays each step's acts on fixed physics frames and answers with an observation.
## Between steps it blocks the main loop, so thinking time never becomes game time.

const ARG_PREFIX: String = "--godotkit-play="
const STATE_GROUP: StringName = &"playtest_state"
const OBSERVE_GROUP: StringName = &"playtest_observe"
const ACTOR_GROUP: StringName = &"playtest_actor"
const PROTOCOL: int = 1
const MAX_CONTROLS: int = 100
const CONNECT_MS: int = 10000
# The session ends idle runs itself; this only stops a bridge whose session vanished silently.
const WAIT_MS: int = 3600000


class ErrorLog extends Logger:
	var count: int = 0
	var _lock: Mutex = Mutex.new()
	var _lines: Array[String] = []

	func _log_error(function: String, file: String, line: int, code: String, rationale: String,
			_editor_notify: bool, error_type: int, _script_backtrace: Array[ScriptBacktrace]) -> void:
		var kind: String = "WARNING" if error_type == ERROR_TYPE_WARNING else "ERROR"
		var text: String = rationale if not rationale.is_empty() else code
		_lock.lock()
		_lines.append("%s: %s (%s:%d in %s)" % [kind, text, file, line, function])
		if error_type != ERROR_TYPE_WARNING:
			count += 1
		_lock.unlock()

	func take() -> Array[String]:
		_lock.lock()
		var lines: Array[String] = _lines
		_lines = []
		_lock.unlock()
		return lines


var _peer: StreamPeerTCP = StreamPeerTCP.new()
var _buffer: PackedByteArray = PackedByteArray()
var _token: String = ""
var _port: int = 0
var _greeted: bool = false
var _frame: int = 0
var _remaining: int = 0
var _step_id: int = 0
var _steps: int = 0
var _look: String = ""
var _holds: Dictionary[StringName, int] = {}
var _applied: Array[Dictionary] = []
var _rejected: Array[Dictionary] = []
var _results: Array[Dictionary] = []
var _scene_changed: bool = false
var _errors: ErrorLog = ErrorLog.new()


func _ready() -> void:
	# A shipped build has no editor_runtime feature; the bridge never opens a socket there.
	if not OS.has_feature("editor_runtime") or not _read_config():
		set_physics_process(false)
		return
	process_physics_priority = -1000000
	OS.add_logger(_errors)
	# Headless windows are 64x64 px; the project's size keeps clicks and layout as designed.
	if DisplayServer.get_name() == "headless":
		var width: int = ProjectSettings.get_setting("display/window/size/viewport_width")
		var height: int = ProjectSettings.get_setting("display/window/size/viewport_height")
		get_window().size = Vector2i(width, height)
	get_tree().scene_changed.connect(func() -> void: _scene_changed = true)


# At the start of physics frame n the game has completed n - 1 frames: observe, then act.
func _physics_process(_delta: float) -> void:
	_frame += 1
	if not _greeted:
		_greeted = true
		if not _greet():
			_finish("no_session")
			return
	if _remaining == 0:
		_send(_observation())
		var message: Dictionary = _receive()
		if message.get("t", "") != "step":
			_finish("ended" if message.get("t", "") == "end" else "disconnected")
			return
		_steps += 1
		_step_id = message.get("id", 0)
		var frames: int = message.get("frames", 1)
		_remaining = maxi(1, frames)
		var look: Variant = message.get("look")
		_look = look if look is String else ""
		_release_due(true)
		var acts: Array = message.get("act", [])
		_play(acts)
	else:
		_release_due(false)
	_remaining -= 1


func _greet() -> bool:
	_peer.connect_to_host("127.0.0.1", _port)
	var deadline: int = Time.get_ticks_msec() + CONNECT_MS
	while _peer.get_status() == StreamPeerTCP.STATUS_CONNECTING and Time.get_ticks_msec() < deadline:
		_peer.poll()
		OS.delay_msec(1)
	if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
		push_error("godotkit play bridge: no session on port %d" % _port)
		return false
	var actions: Array[String] = []
	for action: StringName in InputMap.get_actions():
		if not str(action).begins_with("ui_"):
			actions.append(str(action))
	_send({"t": "hello", "v": PROTOCOL, "token": _token, "godot": Engine.get_version_info()["string"],
		"physics_tps": Engine.physics_ticks_per_second, "actions": actions, "catalogue": _catalogue()})
	var welcome: Dictionary = _receive()
	if welcome.get("t", "") != "welcome":
		return false
	var number: int = welcome.get("seed", 0)
	seed(number)
	return true


func _play(acts: Array) -> void:
	var gestures: Array[Dictionary] = []
	# Presses first, then clicks and calls in order: the replay probe plays a frame the same way.
	for act: Dictionary in acts:
		if act.get("kind", "") != "action":
			gestures.append(act)
			continue
		var action: StringName = StringName(str(act.get("name", "")))
		if not InputMap.has_action(action):
			_rejected.append({"act": act, "reason": "unknown_action"})
			continue
		var strength: float = act.get("strength", 1.0)
		var hold: int = act.get("hold_frames", 1)
		_press(action, true, strength)
		_holds[action] = _frame + hold
	Input.flush_buffered_events()
	for act: Dictionary in gestures:
		if act.get("kind", "") == "click":
			_click(str(act.get("target", "")), act)
		elif act.get("kind", "") == "do":
			var args: Dictionary = act.get("args", {})
			_call(str(act.get("name", "")), args, act)
		else:
			_rejected.append({"act": act, "reason": "unknown_kind"})


func _release_due(step_start: bool) -> void:
	var due: Array[StringName] = []
	for action: StringName in _holds:
		if _holds[action] <= _frame or _scene_changed:
			due.append(action)
	_scene_changed = false
	for action: StringName in due:
		_holds.erase(action)
		_press(action, false, 0.0)
	if not due.is_empty() or step_start:
		Input.flush_buffered_events()


func _press(action: StringName, pressed: bool, strength: float) -> void:
	var event: InputEventAction = InputEventAction.new()
	event.action = action
	event.pressed = pressed
	event.strength = strength
	Input.parse_input_event(event)
	_applied.append({"f": _frame, "action": str(action), "pressed": pressed, "strength": strength})


func _click(path: String, act: Dictionary) -> void:
	var control: Control = get_node_or_null(NodePath(path)) as Control
	if control == null or not control.is_visible_in_tree():
		_rejected.append({"act": act, "reason": "no_visible_control"})
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
	_applied.append({"f": _frame, "click": path})


func _call(action: String, args: Dictionary, act: Dictionary) -> void:
	var actor: Node = get_tree().get_first_node_in_group(ACTOR_GROUP)
	var known: bool = false
	for entry: Dictionary in _catalogue():
		known = known or entry.get("name", "") == action
	if actor == null or not known:
		_rejected.append({"act": act, "reason": "unknown_semantic_action"})
		return
	var result: Variant = actor.call(&"playtest_do", action, args)
	_results.append({"name": action, "result": result})
	_applied.append({"f": _frame, "do": action, "args": args})


func _catalogue() -> Array[Dictionary]:
	var actor: Node = get_tree().get_first_node_in_group(ACTOR_GROUP)
	if actor == null or not actor.has_method(&"playtest_actions"):
		return []
	var listed: Array[Dictionary] = []
	var declared: Array = actor.call(&"playtest_actions")
	listed.assign(declared)
	return listed


func _observation() -> Dictionary:
	var done: int = _frame - 1
	var state: Node = get_tree().get_first_node_in_group(STATE_GROUP)
	var hash_value: Variant = null
	if state != null and state.has_method(&"state_hash"):
		hash_value = str(state.call(&"state_hash"))
	var held: Dictionary[String, int] = {}
	for action: StringName in _holds:
		held[str(action)] = _holds[action] - _frame
	var scene: Node = get_tree().current_scene
	var obs: Dictionary = {"t": "obs", "id": _step_id, "frame": done, "hash": hash_value,
		"scene": scene.scene_file_path if scene else "", "ui": _controls(), "entities": _entities(),
		"held": held, "acts": _applied, "rejected": _rejected, "results": _results,
		"errors": _errors.take(), "look": _take_look(done)}
	_applied = []
	_rejected = []
	_results = []
	return obs


func _controls() -> Array[Dictionary]:
	var found: Array[Dictionary] = []
	var pending: Array[Node] = [get_tree().root]
	while not pending.is_empty() and found.size() < MAX_CONTROLS:
		var node: Node = pending.pop_front()
		pending.append_array(node.get_children())
		var control: Control = node as Control
		if control == null or not control.is_visible_in_tree():
			continue
		var text: String = ""
		if "text" in control and control.get("text") is String:
			text = control.get("text")
		var interactive: bool = (control is BaseButton or control is LineEdit or control is TextEdit
			or control is Range or control is ItemList or control is TabBar)
		if not interactive and text.is_empty():
			continue
		var rect: Rect2 = control.get_global_rect()
		var entry: Dictionary = {"path": str(control.get_path()), "type": control.get_class(),
			"text": text, "rect": [rect.position.x, rect.position.y, rect.size.x, rect.size.y],
			"focus": control.has_focus()}
		if control is BaseButton:
			entry["disabled"] = (control as BaseButton).disabled
		if not str(control.accessibility_name).is_empty():
			entry["name"] = str(control.accessibility_name)
		found.append(entry)
	return found


func _entities() -> Array[Dictionary]:
	var found: Array[Dictionary] = []
	for node: Node in get_tree().get_nodes_in_group(OBSERVE_GROUP):
		if node.has_method(&"playtest_state"):
			found.append({"path": str(node.get_path()), "state": node.call(&"playtest_state")})
	return found


func _take_look(done: int) -> Variant:
	if _look.is_empty():
		return null
	var path: String = _look
	_look = ""
	if DisplayServer.get_name() == "headless":
		return "no_renderer"
	var image: Image = get_viewport().get_texture().get_image()
	if image == null or image.save_png(path) != OK:
		push_error("godotkit play bridge: could not save the look of frame %d to %s" % [done, path])
		return "failed"
	return path


func _finish(status: String) -> void:
	for action: StringName in _holds:
		Input.action_release(action)
	_holds.clear()
	print("MOZG_PLAY_SUMMARY status=%s steps=%d frames=%d errors=%d" % [
		status, _steps, maxi(0, _frame - 1), _errors.count])
	_peer.disconnect_from_host()
	set_physics_process(false)
	get_tree().quit()


func _send(message: Dictionary) -> void:
	_peer.put_data((JSON.stringify(message) + "\n").to_utf8_buffer())


func _receive() -> Dictionary:
	var deadline: int = Time.get_ticks_msec() + WAIT_MS
	while Time.get_ticks_msec() < deadline:
		var newline: int = _buffer.find(10)
		if newline >= 0:
			var line: String = _buffer.slice(0, newline).get_string_from_utf8()
			_buffer = _buffer.slice(newline + 1)
			var parsed: Variant = JSON.parse_string(line)
			return parsed if parsed is Dictionary else {}
		_peer.poll()
		if _peer.get_status() != StreamPeerTCP.STATUS_CONNECTED:
			return {}
		var available: int = _peer.get_available_bytes()
		if available > 0:
			var got: Array = _peer.get_partial_data(available)
			var bytes: PackedByteArray = got[1]
			_buffer.append_array(bytes)
		else:
			OS.delay_msec(1)
	return {}


func _read_config() -> bool:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with(ARG_PREFIX):
			var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(arg.trim_prefix(ARG_PREFIX)))
			if parsed is Dictionary:
				var config: Dictionary = parsed
				_port = config.get("port", 0)
				_token = config.get("token", "")
				return _port > 0 and not _token.is_empty()
	return false
