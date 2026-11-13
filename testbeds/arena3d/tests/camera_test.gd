extends SceneTree
## The spring-arm camera keeps its full length in the open and pulls in when a wall is behind.

const ARENA: PackedScene = preload("res://scenes/arena.tscn")
const SETTLE_TICKS: int = 3
const NEAR_SOUTH_WALL: Vector3 = Vector3(0, 1, 8.5)

var checks: int = 0
var failures: int = 0
var _arena: Arena
var _arm: SpringArm3D
var _ticks: int = 0
var _open_length: float = -1.0


# The arena starts on the first tick: nodes added during _initialize get _ready only later.
func _physics_process(_delta: float) -> bool:
	_ticks += 1
	if _ticks == 1:
		_arena = ARENA.instantiate() as Arena
		root.add_child(_arena)
		_arena.player.controller = null
		_arm = _arena.player.get_node("CameraArm") as SpringArm3D
	elif _ticks == SETTLE_TICKS:
		_open_length = _arm.get_hit_length()
		_arena.player.global_position = NEAR_SOUTH_WALL
	elif _ticks == SETTLE_TICKS * 2:
		_check(is_equal_approx(_open_length, _arm.spring_length), "full arm in the open (%.2f)" % _open_length)
		var blocked: float = _arm.get_hit_length()
		_check(blocked < _arm.spring_length * 0.5, "wall behind pulls the arm in (%.2f)" % blocked)
		print("%d checks, %d failures" % [checks, failures])
		quit()
	return false


func _check(passed: bool, label: String) -> void:
	checks += 1
	if not passed:
		failures += 1
		printerr("FAIL: %s" % label)
