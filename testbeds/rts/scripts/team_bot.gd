class_name TeamBot
extends RefCounted
## One side's script: trains whenever ore allows, sends rallied soldiers once a wave is full.

const WAVE_CHECK_TICKS: int = 30

var wave_size: int


func _init(size: int) -> void:
	wave_size = size


func think(sim: MatchSim, t: int) -> void:
	var room: bool = sim.alive(t) < sim.units_per_team
	if room and sim.ore[t] >= MatchSim.SOLDIER_COST and sim.tick % MatchSim.TRAIN_TICKS == 0:
		sim.train(t)
	if sim.tick % WAVE_CHECK_TICKS == 0:
		var rallied: PackedInt32Array = sim.rallied(t)
		if rallied.size() >= wave_size:
			sim.attack(rallied)
