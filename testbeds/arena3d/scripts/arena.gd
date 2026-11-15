class_name Arena
extends Node3D
## One fight: the seed places the enemy and the exit; beat the enemy, then reach the exit.

signal finished(result: String)

const PLAYING: String = "playing"

@export var seed_value: int = 1

var result: String = PLAYING
var ticks: int = 0

@onready var player: Player = $Player
@onready var enemy: Enemy = $Enemy
@onready var exit_area: Area3D = $Exit


func _ready() -> void:
	add_to_group(&"playtest_state")
	add_to_group(&"playtest_observe")
	var rng: RandomNumberGenerator = RandomNumberGenerator.new()
	rng.seed = seed_value
	enemy.position = Vector3(rng.randf_range(-6.0, 6.0), 1.0, rng.randf_range(-7.0, -3.0))
	exit_area.position = Vector3(rng.randf_range(-6.0, 6.0), 0.5, rng.randf_range(5.0, 7.0))
	enemy.target = player
	enemy.died.connect(_on_enemy_died)
	player.died.connect(_finish.bind("lost"))
	exit_area.body_entered.connect(_on_exit_entered)


func _physics_process(_delta: float) -> void:
	if result == PLAYING:
		ticks += 1


func use_controller(controller: PlayerController) -> void:
	add_child(controller)
	player.controller = controller


func summary() -> String:
	return "arena seed=%d result=%s ticks=%d player_health=%d enemy_health=%d" % [
		seed_value, result, ticks, player.health, enemy.health]


# What a playtest bot or agent reads each step: the fight and positions on the floor plane.
func playtest_state() -> Dictionary:
	return {"result": result, "ticks": ticks, "player_health": player.health,
		"enemy_health": enemy.health, "player": _flat(player.global_position),
		"enemy": _flat(enemy.global_position), "exit": _flat(exit_area.global_position)}


# What godotkit replay compares between runs: the fight's outcome and what the player sees.
func state_hash() -> String:
	var context: HashingContext = HashingContext.new()
	context.start(HashingContext.HASH_SHA256)
	context.update(var_to_bytes([ticks, result, player.global_transform, player.velocity,
		player.health, player.animation_state(), enemy.global_transform, enemy.health]))
	return context.finish().hex_encode()


func _flat(at: Vector3) -> Array[float]:
	return [snappedf(at.x, 0.01), snappedf(at.z, 0.01)]


func _on_enemy_died() -> void:
	exit_area.set_deferred(&"monitoring", true)


func _on_exit_entered(body: Node3D) -> void:
	if body == player and not enemy.alive():
		_finish("won")


func _finish(outcome: String) -> void:
	if result != PLAYING:
		return
	result = outcome
	print(summary())
	finished.emit(result)
