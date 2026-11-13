extends Camera3D
## Overview camera: the mouse wheel moves it closer or further along its view.

const STEP: float = 2.0
const NEAREST: float = 10.0
const FARTHEST: float = 80.0


func _unhandled_input(event: InputEvent) -> void:
	var wheel: InputEventMouseButton = event as InputEventMouseButton
	if wheel == null or not wheel.pressed:
		return
	var direction: float = 0.0
	match wheel.button_index:
		MOUSE_BUTTON_WHEEL_UP:
			direction = -1.0
		MOUSE_BUTTON_WHEEL_DOWN:
			direction = 1.0
		_:
			return
	var moved: Vector3 = position + global_basis.z * STEP * direction
	if moved.y >= NEAREST and moved.y <= FARTHEST:
		position = moved
