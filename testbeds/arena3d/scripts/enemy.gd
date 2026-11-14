class_name Enemy
extends CharacterBody3D
## Chases the player along the floor and strikes on a cooldown when close.

signal died

const STATS: UnitStats = preload("res://data/enemy.tres")

var health: int = STATS.health

var target: Player
var _cooldown: float = 0.0


func _physics_process(delta: float) -> void:
	if not alive() or target == null or target.health <= 0:
		return
	var offset: Vector3 = target.global_position - global_position
	offset.y = 0.0
	var close: bool = offset.length() <= STATS.reach
	var chase: Vector3 = Vector3.ZERO if close else offset.normalized() * STATS.speed
	velocity.x = chase.x
	velocity.z = chase.z
	if not is_on_floor():
		velocity += get_gravity() * delta
	move_and_slide()
	_cooldown = maxf(_cooldown - delta, 0.0)
	if close and _cooldown == 0.0:
		_cooldown = STATS.attack_cooldown
		target.take_hit(STATS.damage)


func alive() -> bool:
	return health > 0


func take_hit(amount: int) -> void:
	if not alive():
		return
	health = maxi(health - amount, 0)
	if health == 0:
		# Out of the way of the player once dead; deferred because hits land mid-physics.
		$CollisionShape3D.set_deferred(&"disabled", true)
		hide()
		died.emit()
