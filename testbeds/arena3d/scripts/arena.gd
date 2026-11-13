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
