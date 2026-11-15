class_name Match
extends Node3D
## Runs the seeded bot-vs-bot match on the navigation map; each team is drawn by one MultiMesh.

signal finished(winner: int)

@export var seed_value: int = 1
@export var units_per_team: int = 250

var sim: MatchSim

@onready var _teams: Array[MultiMeshInstance3D] = [$TeamA, $TeamB]
@onready var _navigation: NavigationRegion3D = $Navigation


func _ready() -> void:
	add_to_group(&"playtest_state")
	add_to_group(&"playtest_observe")
	for view: MultiMeshInstance3D in _teams:
		view.multimesh.instance_count = units_per_team
		view.multimesh.visible_instance_count = 0


func _physics_process(_delta: float) -> void:
	if sim == null:
		var map: RID = get_world_3d().navigation_map
		# The region's polygons reach the map a sync or two after it starts; paths are empty before.
		if NavigationServer3D.map_get_iteration_id(map) == 0:
			return
		if NavigationServer3D.map_get_closest_point_owner(map, MatchSim.BASES[0]) != _navigation.get_rid():
			return
		var find_path: Callable = func(from: Vector3, to: Vector3) -> PackedVector3Array:
			return NavigationServer3D.map_get_path(map, from, to, true)
		sim = MatchSim.new(seed_value, units_per_team, find_path)
	if sim.winner != -1:
		return
	sim.step()
	if sim.winner != -1:
		print(summary())
		finished.emit(sim.winner)


func _process(_delta: float) -> void:
	if sim == null:
		return
	var counts: Array[int] = [0, 0]
	for i: int in sim.pos.size():
		if sim.health[i] <= 0:
			continue
		var t: int = sim.team[i]
		var size: float = 0.6 if sim.kind[i] == MatchSim.Kind.WORKER else 1.0
		var place: Transform3D = Transform3D(Basis.from_scale(Vector3.ONE * size), sim.pos[i])
		_teams[t].multimesh.set_instance_transform(counts[t], place)
		counts[t] += 1
	for t: int in 2:
		_teams[t].multimesh.visible_instance_count = counts[t]


# What a playtest bot reads each step; before the navigation map syncs there is no match yet.
func playtest_state() -> Dictionary:
	if sim == null:
		return {"winner": -1, "tick": 0, "peak_units": 0, "base_a": 0, "base_b": 0}
	return {"winner": sim.winner, "tick": sim.tick, "peak_units": sim.peak,
		"base_a": sim.base_health[0], "base_b": sim.base_health[1]}


# The navigation map syncs a few ticks after start; the match exists only after that.
func state_hash() -> String:
	return sim.state_hash() if sim else "navigation-pending"


func summary() -> String:
	return "rts seed=%d winner=%d ticks=%d peak_units=%d base_health=%d/%d mined=%d@%d hash=%s" % [
		seed_value, sim.winner, sim.tick, sim.peak, sim.base_health[0], sim.base_health[1],
		sim.mined_early, MatchSim.MINED_BY_TICK, sim.state_hash().left(12)]
