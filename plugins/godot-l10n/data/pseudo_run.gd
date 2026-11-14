extends SceneTree
## Shows one scene in the pseudo locale at each window size and reports its visible text nodes.
## Run by l10nkit pseudo: -- <input json> <output json>


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var translation := Translation.new()
	translation.locale = spec["locale"]
	for message: Dictionary in spec["messages"]:
		if message.has("forms"):
			translation.add_plural_message(message["key"], PackedStringArray(message["forms"]), message["context"])
		else:
			translation.add_message(message["key"], message["text"], message["context"])
	TranslationServer.add_translation(translation)
	TranslationServer.set_locale(spec["locale"])
	var sizes: Array = spec["sizes"]
	if sizes.is_empty():
		sizes = [[ProjectSettings.get_setting("display/window/size/viewport_width"),
			ProjectSettings.get_setting("display/window/size/viewport_height")]]
	# The headless window resets the root size during the first frame.
	await process_frame
	var shots := []
	for size: Array in sizes:
		root.size = Vector2i(size[0], size[1])
		var scene: Node = load(spec["scene"]).instantiate()
		root.add_child(scene)
		for i in int(spec["frames"]):
			await process_frame
		var nodes := []
		_collect(scene, scene, nodes)
		shots.append({"size": size, "nodes": nodes})
		scene.free()
	FileAccess.open(args[1], FileAccess.WRITE).store_string(JSON.stringify({"sizes": shots}))
	print("L10N_PSEUDO done sizes=%d" % shots.size())
	quit(0)


func _collect(scene: Node, node: Node, nodes: Array) -> void:
	if node is Control and node.is_visible_in_tree() and node.get("text") is String and node.text != "":
		var control: Control = node
		var shown: String = control.atr(control.text) if control.can_auto_translate() else control.text
		nodes.append({
			"path": str(scene.get_path_to(control)), "class": control.get_class(), "shown": shown,
			"translatable": control.can_auto_translate(), "rect": _rect(control.get_global_rect()),
			"clipped": _clipped(control, shown),
		})
	for child in node.get_children():
		_collect(scene, child, nodes)


## A Label or Button that cuts its text rather than growing: clip_text or an overrun behavior.
func _clipped(control: Control, shown: String) -> bool:
	var overrun = control.get("text_overrun_behavior")
	var cuts: bool = control.get("clip_text") == true or (overrun != null and overrun > 0)
	if not cuts or control.get("autowrap_mode") not in [null, 0]:
		return false
	var font := control.get_theme_font("font")
	var width := font.get_string_size(shown, HORIZONTAL_ALIGNMENT_LEFT, -1, control.get_theme_font_size("font_size")).x
	return width > control.size.x + 0.5


func _rect(rect: Rect2) -> Array:
	return [rect.position.x, rect.position.y, rect.size.x, rect.size.y]
