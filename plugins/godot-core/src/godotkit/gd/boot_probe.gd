extends Node
## godotkit boot probe, added as the last autoload: waits for the real main scene, clicks the
## topmost clickable control, and prints one GODOTKIT_BOOT line saying whether input arrived.

const MAX_WAIT_FRAMES: int = 300
const SETTLE_FRAMES: int = 2

var _hits: int = 0


func _ready() -> void:
	var tree: SceneTree = get_tree()
	var waited: int = 0
	while tree.current_scene == null and waited < MAX_WAIT_FRAMES:
		await tree.process_frame
		waited += 1
	for i: int in SETTLE_FRAMES:
		await tree.process_frame
	print("GODOTKIT_BOOT " + JSON.stringify(_inspect(tree.current_scene)))
	tree.quit()


func _inspect(scene: Node) -> Dictionary:
	var report: Dictionary = {
		"scene": "", "can_process": false, "paused": get_tree().paused,
		"controls": 0, "receivers": 0, "clicked": false, "target": "",
	}
	if scene == null:
		return report
	report["scene"] = scene.scene_file_path
	report["can_process"] = scene.can_process()
	# Whole tree, not only the scene: an autoload overlay on top may be the one taking the click.
	var nodes: Array[Node] = get_tree().root.find_children("*", "", true, false)
	var controls: Array[Control] = []
	var receivers: int = 0
	for node: Node in nodes:
		if node.can_process() and (node.is_processing_input() or node.is_processing_unhandled_input()
				or node.is_processing_unhandled_key_input() or node.is_processing_shortcut_input()):
			receivers += 1
		var control: Control = node as Control
		if control != null and control.is_visible_in_tree() \
				and control.mouse_filter != Control.MOUSE_FILTER_IGNORE \
				and control.get_global_rect().has_area():
			controls.append(control)
	report["controls"] = controls.size()
	report["receivers"] = receivers
	if controls.is_empty():
		return report
	for control: Control in controls:
		@warning_ignore("return_value_discarded")
		control.gui_input.connect(_on_gui_input)
	var target: Control = _topmost_in(scene, controls)
	var point: Vector2 = target.get_global_rect().get_center()
	report["target"] = str(scene.get_path_to(target))
	for pressed: bool in [true, false]:
		var event: InputEventMouseButton = InputEventMouseButton.new()
		event.button_index = MOUSE_BUTTON_LEFT
		event.pressed = pressed
		event.position = point
		event.global_position = point
		# Local coordinates: control rects are in canvas space, which stretch modes scale.
		get_viewport().push_input(event, true)
	report["clicked"] = _hits > 0
	return report


func _topmost_in(scene: Node, controls: Array[Control]) -> Control:
	var target: Control = controls[controls.size() - 1]
	for control: Control in controls:
		if scene.is_ancestor_of(control) or control == scene:
			target = control
	return target


func _on_gui_input(_event: InputEvent) -> void:
	_hits += 1
