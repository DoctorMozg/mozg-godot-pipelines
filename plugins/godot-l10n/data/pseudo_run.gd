extends SceneTree
## Shows one scene in the pseudo locale at each window size and reports its visible text nodes.
## Run by l10nkit pseudo: -- <input json> <output json>


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var locale: String = spec["locale"]
	var translation := Translation.new()
	translation.locale = locale
	# Typed locals throughout: a project with unsafe-access warnings as errors must still parse this.
	for message: Dictionary in spec["messages"]:
		var key: String = message["key"]
		var context: String = message["context"]
		if message.has("forms"):
			var forms: Array = message["forms"]
			translation.add_plural_message(key, PackedStringArray(forms), context)
		else:
			var text: String = message["text"]
			translation.add_message(key, text, context)
	TranslationServer.add_translation(translation)
	TranslationServer.set_locale(locale)
	var sizes: Array = spec["sizes"]
	if sizes.is_empty():
		sizes = [[ProjectSettings.get_setting("display/window/size/viewport_width"),
			ProjectSettings.get_setting("display/window/size/viewport_height")]]
	# The headless window resets the root size during the first frame.
	await process_frame
	var scene_path: String = spec["scene"]
	var frames: int = spec["frames"]
	var shots := []
	for size: Array in sizes:
		var width: int = size[0]
		var height: int = size[1]
		root.size = Vector2i(width, height)
		var packed: PackedScene = load(scene_path)
		var scene := packed.instantiate()
		root.add_child(scene)
		for _frame in frames:
			await process_frame
		var nodes := []
		_collect(scene, scene, nodes)
		# Rects are canvas units; under stretch the canvas differs from the window size.
		var canvas := root.get_visible_rect().size
		shots.append({"size": size, "canvas": [canvas.x, canvas.y], "nodes": nodes})
		scene.free()
	FileAccess.open(args[1], FileAccess.WRITE).store_string(JSON.stringify({"sizes": shots}))
	print("L10N_PSEUDO done sizes=%d" % shots.size())
	quit(0)


func _collect(scene: Node, node: Node, nodes: Array) -> void:
	var control := node as Control
	var text: Variant = node.get("text")
	if control != null and control.is_visible_in_tree() and text is String and text != "":
		var source: String = text
		var shown: String = control.atr(source) if control.can_auto_translate() else source
		nodes.append({
			"path": str(scene.get_path_to(control)), "class": control.get_class(), "shown": shown,
			"translatable": control.can_auto_translate(), "rect": _rect(control.get_global_rect()),
			"clipped": _clipped(control, shown),
		})
	for child in node.get_children():
		_collect(scene, child, nodes)


## A Label or Button that cuts its text rather than growing: clip_text or an overrun behavior.
func _clipped(control: Control, shown: String) -> bool:
	var overrun: Variant = control.get("text_overrun_behavior")
	var cuts: bool = control.get("clip_text") == true or (overrun != null and overrun > 0)
	if not cuts or control.get("autowrap_mode") not in [null, 0]:
		return false
	var font := control.get_theme_font("font")
	var width := font.get_string_size(shown, HORIZONTAL_ALIGNMENT_LEFT, -1, control.get_theme_font_size("font_size")).x
	return width > control.size.x + 0.5


func _rect(rect: Rect2) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
