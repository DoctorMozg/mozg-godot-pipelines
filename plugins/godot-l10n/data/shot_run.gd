extends SceneTree
## Draws one scene in each locale at each window size, saves the picture and lists the keys shown.
## Run by l10nkit shot on a display: -- <input json> <output json>


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var source: Dictionary = spec["source"]
	# The window takes the project's size during the first frame; a resize before it is lost.
	await process_frame
	var shots := []
	var shown := ""
	for run: Dictionary in spec["runs"]:
		if run["locale"] != shown:
			_use(source, run)
			shown = run["locale"]
		var size: Array = run["size"]
		root.size = Vector2i(size[0], size[1])
		var scene: Node = load(spec["scene"]).instantiate()
		root.add_child(scene)
		for i in int(spec["frames"]):
			await RenderingServer.frame_post_draw
		var image := root.get_texture().get_image()
		var png: String = run["png"]
		DirAccess.make_dir_recursive_absolute(png.get_base_dir())
		if image.save_png(png) != OK:
			push_error("l10nkit shot: cannot write %s" % png)
		var keys := []
		_keys(scene, keys)
		shots.append({"image": [image.get_width(), image.get_height()], "keys": keys})
		scene.free()
	FileAccess.open(args[1], FileAccess.WRITE).store_string(JSON.stringify({"shots": shots}))
	print("L10N_SHOT done shots=%d" % shots.size())
	quit(0)


## Only the store's text: the project's own registered translations may be older builds.
func _use(source: Dictionary, run: Dictionary) -> void:
	TranslationServer.clear()
	TranslationServer.add_translation(load(source["po"]))
	if run["locale"] != source["locale"]:
		TranslationServer.add_translation(load(run["po"]))
	TranslationServer.set_locale(run["locale"])


func _keys(node: Node, keys: Array) -> void:
	if node is Control and node.is_visible_in_tree() and node.get("text") is String and node.text != "":
		var control: Control = node
		if control.can_auto_translate():
			keys.append(control.text)
	for child in node.get_children():
		_keys(child, keys)
