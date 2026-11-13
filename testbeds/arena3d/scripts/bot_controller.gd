class_name BotController
extends PlayerController
## Scripted player: closes in on the enemy, attacks within reach, then walks into the open exit.

var arena: Arena


func next_intent(player: Player) -> Intent:
	var intent: Intent = Intent.new()
	var target: Vector3 = arena.exit_area.global_position
	if arena.enemy.alive():
		target = arena.enemy.global_position
		intent.attack = player.in_reach(arena.enemy)
	var offset: Vector3 = target - player.global_position
	if not intent.attack:
		intent.move = Vector2(offset.x, offset.z).normalized()
	return intent
