extends SceneTree
## A scripted bot plays the arena twice on one seed: it must win both runs, tick for tick alike.

const ARENA: PackedScene = preload("res://scenes/arena.tscn")
const SEED: int = 7
const TICK_BUDGET: int = 1800
const RUNS: int = 2

var checks: int = 0
var failures: int = 0
var _arena: Arena
var _states: Dictionary[StringName, bool] = {}
var _finishes: Array[String] = []


func _initialize() -> void:
	var engine: String = ProjectSettings.get_setting("physics/3d/physics_engine")
	_check(engine == "Jolt Physics", "Jolt runs the physics (got %s)" % engine)


# Scenes start on the first tick: nodes added during _initialize get _ready only later.
func _physics_process(_delta: float) -> bool:
	if _finishes.size() == RUNS:
		return false
	if _arena == null:
		_start()
		return false
	_states[_arena.player.animation_state()] = true
	if _arena.result == Arena.PLAYING and _arena.ticks < TICK_BUDGET:
		return false
	_end_run()
	if _finishes.size() == RUNS:
		_report()
	return false


func _start() -> void:
	_arena = ARENA.instantiate() as Arena
	_arena.seed_value = SEED
	root.add_child(_arena)
	var bot: BotController = BotController.new()
	bot.arena = _arena
	_arena.use_controller(bot)


func _end_run() -> void:
	if _arena.result == Arena.PLAYING:
		print(_arena.summary())
	_check(_arena.result == "won", "bot wins within %d ticks (got %s)" % [TICK_BUDGET, _arena.result])
	_check(not _arena.enemy.alive(), "the enemy is down")
	var position: Vector3 = _arena.player.global_position
	_finishes.append("%d %.4v" % [_arena.ticks, position])
	root.remove_child(_arena)
	_arena.queue_free()
	_arena = null


func _report() -> void:
	_check(_finishes[0] == _finishes[1], "one seed gives one run: %s vs %s" % _finishes)
	for state: StringName in [&"idle", &"run", &"attack"]:
		_check(_states.has(state), "AnimationTree entered %s" % state)
	print("%d checks, %d failures" % [checks, failures])
	quit()


func _check(passed: bool, label: String) -> void:
	checks += 1
	if not passed:
		failures += 1
		printerr("FAIL: %s" % label)
