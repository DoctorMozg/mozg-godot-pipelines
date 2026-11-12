extends SceneTree
## godotkit parse gate: loads every script under res:// once and prints one summary line.
## Typed throughout, because projects that treat warnings as errors apply that to this file too.


func _init() -> void:
	var scripts: PackedStringArray = PackedStringArray()
	_collect("res://", scripts)
	var failed: int = 0
	for path: String in scripts:
		var script: Script = ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE) as Script
		if script == null or (not script.can_instantiate() and not script.is_abstract()):
			failed += 1
			print("GODOTKIT_PARSE_FAIL " + path)
	print("GODOTKIT_PARSE %d scripts %d failed" % [scripts.size(), failed])
	quit()


func _collect(dir_path: String, out: PackedStringArray) -> void:
	if FileAccess.file_exists(dir_path.path_join(".gdignore")):
		return
	for file: String in DirAccess.get_files_at(dir_path):
		if file.get_extension() == "gd":
			@warning_ignore("return_value_discarded")
			out.append(dir_path.path_join(file))
	for sub: String in DirAccess.get_directories_at(dir_path):
		if not sub.begins_with("."):
			_collect(dir_path.path_join(sub), out)
