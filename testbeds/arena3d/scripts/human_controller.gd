class_name HumanController
extends PlayerController
## Keyboard play: WASD moves, Space attacks. Actions are registered here to keep project.godot short.

const KEYS: Dictionary[String, Key] = {
	"move_left": KEY_A,
	"move_right": KEY_D,
	"move_forward": KEY_W,
	"move_back": KEY_S,
	"attack": KEY_SPACE,
}

var _attack_queued: bool = false


func _ready() -> void:
	for action: String in KEYS:
		if InputMap.has_action(action):
			continue
		InputMap.add_action(action)
		var event: InputEventKey = InputEventKey.new()
		event.physical_keycode = KEYS[action]
		InputMap.action_add_event(action, event)


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("attack"):
		_attack_queued = true


func next_intent(_player: Player) -> Intent:
	var intent: Intent = Intent.new()
	intent.move = Input.get_vector("move_left", "move_right", "move_forward", "move_back")
	intent.attack = _attack_queued
	_attack_queued = false
	return intent
