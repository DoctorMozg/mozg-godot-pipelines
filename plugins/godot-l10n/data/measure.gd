extends SceneTree
## Widths of texts in the project's theme font, and characters the font cannot draw.
## Run by l10nkit measure: -- <input json> <output json>


func _initialize() -> void:
	var args := OS.get_cmdline_user_args()
	var spec: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(args[0]))
	var font: Font = ThemeDB.fallback_font
	var size: int = ThemeDB.fallback_font_size
	var source := "fallback"
	var theme_path: String = spec["theme"]
	if theme_path == "":
		theme_path = ProjectSettings.get_setting("gui/theme/custom", "")
	if theme_path != "":
		var theme: Theme = load(theme_path)
		source = theme_path
		if theme.has_default_font():
			font = theme.default_font
		if theme.has_default_font_size():
			size = theme.default_font_size
	if spec["font_size"] > 0:
		size = spec["font_size"]
	var widths := {}
	for item: Dictionary in spec["texts"]:
		widths[item["id"]] = font.get_string_size(item["text"], HORIZONTAL_ALIGNMENT_LEFT, -1, size).x
	var missing := {}
	for locale: String in spec["coverage"]:
		var text: String = spec["coverage"][locale]
		var absent := []
		for i in text.length():
			if not _has_char(font, text.unicode_at(i)):
				absent.append(text[i])
		missing[locale] = absent
	var result := {"theme": source, "font_size": size, "widths": widths, "missing": missing}
	FileAccess.open(args[1], FileAccess.WRITE).store_string(JSON.stringify(result))
	print("L10N_MEASURE done texts=%d" % widths.size())
	quit(0)


func _has_char(font: Font, code: int) -> bool:
	if font.has_char(code):
		return true
	for fallback: Font in font.fallbacks:
		if _has_char(fallback, code):
			return true
	return false
