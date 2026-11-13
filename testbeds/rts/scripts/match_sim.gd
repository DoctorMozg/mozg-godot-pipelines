class_name MatchSim
extends RefCounted
## Fixed-tick RTS match as plain data: workers mine ore, bases train soldiers, waves attack.

enum Kind { WORKER, SOLDIER }
enum Order { GATHER, MINE, RETURN, RALLY, ATTACK }
enum Route { TO_FIELD, TO_BASE, TO_ENEMY }

const BASES: Array[Vector3] = [Vector3(-24, 0, -24), Vector3(24, 0, 24)]
const START_WORKERS: int = 30
const SOLDIER_COST: int = 20
const TRAIN_TICKS: int = 6
const BASE_HEALTH: int = 3000
const CARRY: int = 5
const MINE_TICKS: int = 40
# Engage range and grid cell are one value, so a 3x3 cell scan covers every enemy in range;
# each team has its own grid, so a scan walks enemies only.
const CELL: float = 8.0
const GRID: int = 8
const HALF_GRID: int = 4
const RETARGET_TICKS: int = 10
const ATTACK_RANGE: float = 1.5
const ATTACK_COOLDOWN: int = 30
const DAMAGE: int = 10
const SPEED: Array[float] = [0.12, 0.1]
const HEALTH: Array[int] = [40, 100]

var tick: int = 0
var winner: int = -1
var peak: int = 0
var units_per_team: int
var base_health: Array[int] = [BASE_HEALTH, BASE_HEALTH]
var ore: Array[int] = [0, 0]
var pos: PackedVector3Array
var team: PackedInt32Array
var kind: PackedInt32Array
var health: PackedInt32Array

var _bots: Array[TeamBot] = []
var _alive: Array[int] = [0, 0]
var _order: PackedInt32Array
var _cooldown: PackedInt32Array
var _target: PackedInt32Array
var _route: PackedInt32Array
var _waypoint: PackedInt32Array
var _offset: PackedVector3Array
var _routes: Array[PackedVector3Array] = []
var _rally: Array[Vector3] = []
var _head: PackedInt32Array
var _next: PackedInt32Array
var _rng: RandomNumberGenerator = RandomNumberGenerator.new()


func _init(seed_value: int, per_team: int, find_path: Callable) -> void:
	_rng.seed = seed_value
	units_per_team = per_team
	for t: int in 2:
		var base: Vector3 = BASES[t]
		var home: float = signf(base.x)
		var field: Vector3 = base + Vector3(_rng.randf_range(-3, 3), 0, -home * _rng.randf_range(8, 12))
		_rally.append(base - Vector3(home, 0, home) * 4.0)
		_routes.append(_path(find_path, base, field))
		_routes.append(_path(find_path, field, base))
		_routes.append(_path(find_path, _rally[t], BASES[1 - t]))
		_bots.append(TeamBot.new(_rng.randi_range(20, 60)))
		for i: int in per_team:
			if i < START_WORKERS:
				_spawn(t, Kind.WORKER, base, Order.GATHER)
			else:
				_spawn(t, Kind.SOLDIER, _rally[t], Order.RALLY)


func step() -> void:
	if winner != -1:
		return
	tick += 1
	_rebuild_grid()
	for t: int in 2:
		_bots[t].think(self, t)
	for i: int in pos.size():
		if health[i] > 0:
			if kind[i] == Kind.WORKER:
				_work(i)
			else:
				_fight(i)
	peak = maxi(peak, _alive[0] + _alive[1])
	for t: int in 2:
		if base_health[t] <= 0:
			winner = 1 - t


func alive(t: int) -> int:
	return _alive[t]


func train(t: int) -> void:
	ore[t] -= SOLDIER_COST
	_spawn(t, Kind.SOLDIER, _rally[t], Order.RALLY)


func rallied(t: int) -> PackedInt32Array:
	var found: PackedInt32Array = []
	for i: int in pos.size():
		if team[i] == t and health[i] > 0 and _order[i] == Order.RALLY:
			found.append(i)
	return found


func attack(soldiers: PackedInt32Array) -> void:
	for i: int in soldiers:
		_go(i, Order.ATTACK, Route.TO_ENEMY)


func state_hash() -> String:
	var context: HashingContext = HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes([tick, pos, health, _order, ore, base_health]))
	return context.finish().hex_encode()


func _path(find_path: Callable, from: Vector3, to: Vector3) -> PackedVector3Array:
	var route: PackedVector3Array = find_path.call(from, to)
	if route.is_empty():
		push_error("no path from %v to %v; the navigation map is not ready" % [from, to])
	return route


func _spawn(t: int, k: Kind, at: Vector3, first: Order) -> void:
	var jitter: Vector3 = Vector3(_rng.randf_range(-1.5, 1.5), 0, _rng.randf_range(-1.5, 1.5))
	pos.append(at + jitter)
	_offset.append(jitter)
	team.append(t)
	kind.append(k)
	health.append(HEALTH[k])
	_order.append(first)
	_cooldown.append(0)
	_target.append(-1)
	_route.append(t * 3 + Route.TO_FIELD)
	_waypoint.append(0)
	_next.append(-1)
	_alive[t] += 1


func _go(i: int, next: Order, route: Route) -> void:
	_order[i] = next
	_route[i] = team[i] * 3 + route
	_waypoint[i] = 0


func _work(i: int) -> void:
	match _order[i]:
		Order.GATHER:
			if _advance(i):
				_order[i] = Order.MINE
				_cooldown[i] = MINE_TICKS
		Order.MINE:
			_cooldown[i] -= 1
			if _cooldown[i] <= 0:
				_go(i, Order.RETURN, Route.TO_BASE)
		Order.RETURN:
			if _advance(i):
				ore[team[i]] += CARRY
				_go(i, Order.GATHER, Route.TO_FIELD)


func _fight(i: int) -> void:
	_cooldown[i] = maxi(_cooldown[i] - 1, 0)
	var enemy: int = _target[i]
	# Staggered scans keep a crowded tick cheap; a fallen target is replaced at once.
	if (tick + i) % RETARGET_TICKS == 0 or (enemy != -1 and health[enemy] <= 0):
		enemy = _nearest_enemy(i)
		_target[i] = enemy
	if enemy != -1:
		var gap: Vector3 = pos[enemy] - pos[i]
		if gap.length() > ATTACK_RANGE:
			pos[i] += gap.normalized() * SPEED[Kind.SOLDIER]
		elif _cooldown[i] == 0:
			_cooldown[i] = ATTACK_COOLDOWN
			_hit(enemy)
	elif _order[i] == Order.ATTACK and _advance(i) and _cooldown[i] == 0:
		_cooldown[i] = ATTACK_COOLDOWN
		base_health[1 - team[i]] = maxi(base_health[1 - team[i]] - DAMAGE, 0)


func _hit(j: int) -> void:
	health[j] = maxi(health[j] - DAMAGE, 0)
	if health[j] == 0:
		_alive[team[j]] -= 1


func _advance(i: int) -> bool:
	var route: PackedVector3Array = _routes[_route[i]]
	if _waypoint[i] >= route.size():
		return true
	var gap: Vector3 = route[_waypoint[i]] + _offset[i] - pos[i]
	gap.y = 0.0
	var speed: float = SPEED[kind[i]]
	if gap.length() > speed:
		pos[i] += gap.normalized() * speed
		return false
	pos[i] += gap
	_waypoint[i] += 1
	return _waypoint[i] >= route.size()


func _cell(at: Vector3) -> Vector2i:
	var x: int = clampi(floori(at.x / CELL) + HALF_GRID, 0, GRID - 1)
	return Vector2i(x, clampi(floori(at.z / CELL) + HALF_GRID, 0, GRID - 1))


func _rebuild_grid() -> void:
	_head.resize(2 * GRID * GRID)
	_head.fill(-1)
	for i: int in pos.size():
		if health[i] > 0:
			var cell: Vector2i = _cell(pos[i])
			var slot: int = (team[i] * GRID + cell.y) * GRID + cell.x
			_next[i] = _head[slot]
			_head[slot] = i


func _nearest_enemy(i: int) -> int:
	var center: Vector2i = _cell(pos[i])
	var enemies: int = (1 - team[i]) * GRID * GRID
	var best: int = -1
	var best_distance: float = CELL * CELL
	for dz: int in range(-1, 2):
		for dx: int in range(-1, 2):
			var cell: Vector2i = center + Vector2i(dx, dz)
			if cell.x < 0 or cell.y < 0 or cell.x >= GRID or cell.y >= GRID:
				continue
			var j: int = _head[enemies + cell.y * GRID + cell.x]
			while j != -1:
				var distance: float = pos[i].distance_squared_to(pos[j])
				# Units killed earlier this tick are still in the grid; skip them.
				if health[j] > 0 and distance < best_distance:
					best = j
					best_distance = distance
				j = _next[j]
	return best
