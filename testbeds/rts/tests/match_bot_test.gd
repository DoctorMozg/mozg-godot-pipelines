extends SceneTree
## Two scripted bots play one seed twice: a base must fall within the budget, both runs alike.

const MATCH: PackedScene = preload("res://scenes/match.tscn")
const SEED: int = 7
const TICK_BUDGET: int = 6000
const RUNS: int = 2
const MIN_PEAK: int = 450
const OBSTACLE_HALF: float = 5.0
const TEAM_VIEWS: Array[NodePath] = [^"TeamA", ^"TeamB"]

var checks: int = 0
var failures: int = 0
var _match: Match
var _finishes: Array[String] = []


# Scenes start on the first tick: nodes added during _initialize get _ready only later.
func _physics_process(_delta: float) -> bool:
	if _finishes.size() == RUNS:
		return false
	if _match == null:
		_match = MATCH.instantiate() as Match
		_match.seed_value = SEED
		root.add_child(_match)
		return false
	var sim: MatchSim = _match.sim
	if sim == null:
		return false
	if sim.tick == 2:
		_check_drawing()
		if _finishes.is_empty():
			_check_detour()
	if sim.winner == -1 and sim.tick < TICK_BUDGET:
		return false
	_end_run(sim)
	if _finishes.size() == RUNS:
		_check(_finishes[0] == _finishes[1], "one seed gives one match: %s vs %s" % _finishes)
		print("%d checks, %d failures" % [checks, failures])
		quit()
	return false


func _end_run(sim: MatchSim) -> void:
	if sim.winner == -1:
		print(_match.summary())
	_check(sim.winner != -1, "a base falls within %d ticks" % TICK_BUDGET)
	_check(sim.peak >= MIN_PEAK, "about 500 units fight (peak %d)" % sim.peak)
	_finishes.append("%d %s" % [sim.tick, sim.state_hash()])
	root.remove_child(_match)
	_match.queue_free()
	_match = null


# Each team's MultiMesh draws exactly its living units; none have died by tick 2.
func _check_drawing() -> void:
	for t: int in 2:
		var view: MultiMeshInstance3D = _match.get_node(TEAM_VIEWS[t]) as MultiMeshInstance3D
		var drawn: int = view.multimesh.visible_instance_count
		_check(drawn == _match.sim.alive(t), "team %d draws %d of %d units" % [t, drawn, _match.sim.alive(t)])


func _check_detour() -> void:
	var map: RID = _match.get_world_3d().navigation_map
	var path: PackedVector3Array = NavigationServer3D.map_get_path(map, MatchSim.BASES[0], MatchSim.BASES[1], true)
	_check(path.size() >= 3, "the base-to-base path bends (%d points)" % path.size())
	for point: Vector3 in path:
		var inside: bool = absf(point.x) < OBSTACLE_HALF and absf(point.z) < OBSTACLE_HALF
		_check(not inside, "path point %v stays off the obstacle" % point)


func _check(passed: bool, label: String) -> void:
	checks += 1
	if not passed:
		failures += 1
		printerr("FAIL: %s" % label)
