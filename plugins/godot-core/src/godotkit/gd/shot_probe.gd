extends Node
## godotkit shot probe, added as the last autoload: sizes the window to each requested size, writes
## the visible controls with their rects (and a PNG when rendering) and prints one line per size.

const MAX_WAIT_FRAMES: int = 300
const ARG_PREFIX: String = "--godotkit-shot="


func _ready() -> void:
	var config: Dictionary = _config()
	var tree: SceneTree = get_tree()
	var waited: int = 0
	while tree.current_scene == null and waited < MAX_WAIT_FRAMES:
		await tree.process_frame
		waited += 1
	var scene: Node = tree.current_scene
	print("GODOTKIT_SHOT_INFO " + JSON.stringify({
		"scene": scene.scene_file_path if scene != null else "",
		"display": DisplayServer.get_name(),
		"renderer": RenderingServer.get_current_rendering_method(),
		"adapter": RenderingServer.get_video_adapter_name(),
	}))
	if scene != null:
		var pixels: bool = config["pixels"]
		var frames: int = config["frames"]
		var out: String = config["out"]
		var sizes: Array = config["sizes"]
		for pair: Array in sizes:
			var width: int = pair[0]
			var height: int = pair[1]
			var size: Vector2i = Vector2i(width, height)
			get_window().size = size
			await _settle(frames, pixels)
			print("GODOTKIT_SHOT " + JSON.stringify(_capture(size, out, pixels)))
	tree.quit()


func _config() -> Dictionary:
	for arg: String in OS.get_cmdline_user_args():
		if arg.begins_with(ARG_PREFIX):
			var parsed: Variant = JSON.parse_string(arg.trim_prefix(ARG_PREFIX))
			if parsed is Dictionary:
				return parsed
	push_error("godotkit shot probe: no valid %s argument" % ARG_PREFIX)
	return {"sizes": [], "frames": 1, "out": "", "pixels": false}


func _settle(frames: int, pixels: bool) -> void:
	# Headless never draws, so frame_post_draw would never come; layout settles on process frames.
	for i: int in frames:
		if pixels:
			await RenderingServer.frame_post_draw
		else:
			await get_tree().process_frame


func _capture(size: Vector2i, out: String, pixels: bool) -> Dictionary:
	var stem: String = "%s/%dx%d" % [out, size.x, size.y]
	var window: Vector2i = get_window().size
	var controls: Array[Dictionary] = _controls()
	var layout: Dictionary = {
		"size": [size.x, size.y],
		"window": [window.x, window.y],
		"canvas": _vector(get_viewport().get_visible_rect().size),
		"controls": controls,
	}
	var report: Dictionary = {
		"size": [size.x, size.y], "window": [window.x, window.y], "controls": controls.size(),
		"layout": stem + ".json", "png": null, "image": null,
	}
	var file: FileAccess = FileAccess.open(stem + ".json", FileAccess.WRITE)
	if file == null:
		push_error("godotkit shot probe: cannot write %s.json" % stem)
		return report
	@warning_ignore("return_value_discarded")
	file.store_string(JSON.stringify(layout, "  "))
	file.close()
	if pixels:
		var image: Image = get_viewport().get_texture().get_image()
		if image != null and image.save_png(stem + ".png") == OK:
			report["png"] = stem + ".png"
			report["image"] = [image.get_width(), image.get_height()]
	return report


func _controls() -> Array[Dictionary]:
	var root: Window = get_tree().root
	var found: Array[Dictionary] = []
	# The whole tree, so an autoload overlay drawn over the scene is listed too.
	for node: Node in root.find_children("*", "Control", true, false):
		var control: Control = node as Control
		if control == null or not control.is_visible_in_tree():
			continue
		# Canvas rects move with stretch settings; window pixels are what a screenshot shows.
		var to_window: Transform2D = get_viewport().get_final_transform() \
				* control.get_global_transform_with_canvas()
		var entry: Dictionary = {
			"path": str(root.get_path_to(control)),
			"class": control.get_class(),
			"rect": _vector(control.global_position) + _vector(control.size),
			"rect_px": _vector(to_window.origin) + _vector(to_window.basis_xform(control.size)),
		}
		var text: Variant = control.get("text")
		if text is String:
			entry["text"] = text
		found.append(entry)
	return found


func _vector(value: Vector2) -> Array[float]:
	return [snappedf(value.x, 0.01), snappedf(value.y, 0.01)]
