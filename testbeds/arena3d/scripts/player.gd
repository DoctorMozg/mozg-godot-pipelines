class_name Player
extends CharacterBody3D
## Moves and attacks on its controller's intents; the AnimationTree follows what it does.

signal died

const SPEED: float = 5.0
const REACH: float = 1.8
const ATTACK_COOLDOWN: float = 0.4
const DAMAGE: int = 1
const MOVING_SPEED: float = 0.1

@export var controller: PlayerController
@export var health: int = 100

var _cooldown: float = 0.0

@onready var _playback: AnimationNodeStateMachinePlayback = $AnimationTree.get("parameters/playback")


func _physics_process(delta: float) -> void:
	if health <= 0 or controller == null:
		return
	var intent: Intent = controller.next_intent(self)
	velocity.x = intent.move.x * SPEED
	velocity.z = intent.move.y * SPEED
	if not is_on_floor():
		velocity += get_gravity() * delta
	move_and_slide()
	_cooldown = maxf(_cooldown - delta, 0.0)
	if intent.attack and _cooldown == 0.0:
		_attack()
	elif _playback.get_current_node() != &"attack":
		var moving: bool = Vector2(velocity.x, velocity.z).length() > MOVING_SPEED
		_playback.travel(&"run" if moving else &"idle")


func in_reach(enemy: Enemy) -> bool:
	return enemy.alive() and global_position.distance_to(enemy.global_position) <= REACH


func take_hit(amount: int) -> void:
	if health <= 0:
		return
	health = maxi(health - amount, 0)
	if health == 0:
		died.emit()


func animation_state() -> StringName:
	return _playback.get_current_node()


func _attack() -> void:
	_cooldown = ATTACK_COOLDOWN
	_playback.start(&"attack")
	for node: Node in get_tree().get_nodes_in_group(&"enemies"):
		var enemy: Enemy = node as Enemy
		if enemy != null and in_reach(enemy):
			enemy.take_hit(DAMAGE)
