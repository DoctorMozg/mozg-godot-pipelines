extends SceneTree
## godotkit parse gate: compiles every shader and shader material, loads every script, prints summaries.
## Typed throughout, because projects that treat warnings as errors apply that to this file too.

const SHADER_HEADERS: PackedStringArray = ['type="Shader"', 'type="ShaderMaterial"', 'type="VisualShader"']


func _init() -> void:
	var scripts: PackedStringArray = PackedStringArray()
	var shaders: PackedStringArray = PackedStringArray()
	var materials: PackedStringArray = PackedStringArray()
	_collect("res://", scripts, shaders, materials)
	# Shaders first: a script preloading a material would otherwise compile it outside any section.
	for path: String in shaders + materials:
		_compile(path)
	var failed: int = 0
	for path: String in scripts:
		var script: Script = ResourceLoader.load(path, "", ResourceLoader.CACHE_MODE_IGNORE) as Script
		if script == null or (not script.can_instantiate() and not script.is_abstract()):
			failed += 1
			print("GODOTKIT_PARSE_FAIL " + path)
	print("GODOTKIT_SHADERS %d files" % (shaders.size() + materials.size()))
	print("GODOTKIT_PARSE %d scripts %d failed" % [scripts.size(), failed])
	quit()


## Headless errors carry no file name, so each load sits between marker lines.
func _compile(path: String) -> void:
	print("GODOTKIT_SHADER_BEGIN " + path)
	var resource: Resource = ResourceLoader.load(path)
	var shader: Shader = resource as Shader
	var material: ShaderMaterial = resource as ShaderMaterial
	if material != null:
		shader = material.shader
	# A shader compiles on first use; asking for its uniforms is that use.
	if shader != null:
		@warning_ignore("return_value_discarded")
		shader.get_shader_uniform_list()
	print("GODOTKIT_SHADER_END " + path)


func _collect(
	dir_path: String,
	scripts: PackedStringArray,
	shaders: PackedStringArray,
	materials: PackedStringArray,
) -> void:
	if FileAccess.file_exists(dir_path.path_join(".gdignore")):
		return
	for file: String in DirAccess.get_files_at(dir_path):
		var path: String = dir_path.path_join(file)
		match file.get_extension():
			"gd":
				@warning_ignore("return_value_discarded")
				scripts.append(path)
			"gdshader":
				@warning_ignore("return_value_discarded")
				shaders.append(path)
			"tres":
				if _holds_shader(path):
					@warning_ignore("return_value_discarded")
					materials.append(path)
	for sub: String in DirAccess.get_directories_at(dir_path):
		if not sub.begins_with("."):
			_collect(dir_path.path_join(sub), scripts, shaders, materials)


func _holds_shader(path: String) -> bool:
	var file: FileAccess = FileAccess.open(path, FileAccess.READ)
	if file == null:
		return false
	var header: String = file.get_line()
	for marker: String in SHADER_HEADERS:
		if header.contains(marker):
			return true
	return false
