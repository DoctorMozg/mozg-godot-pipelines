# Scenarios and Game Hooks

A scenario is one JSON file at `<project>/playtest/scenarios/<id>.json`, checked by `godotkit playtest lint` against `playtest-scenario/1` (the schema ships at `<plugin>/data/contracts/playtest-scenario.schema.json`). The harness judges every predicate on observations; the agent never decides that a goal was met.

## An example

```json
{
  "schema": "playtest-scenario/1",
  "id": "first-day",
  "goal": "Start a new game from the main menu and live to day 2",
  "mode": "llm_stepped",
  "persona": "novice",
  "seeds": [1],
  "success": [{"query": "Survival.day", "op": ">=", "value": 2}],
  "invariants": [
    {"id": "oxygen-nonneg", "query": "Survival.oxygen", "op": ">=", "value": 0},
    {"id": "no-script-error", "log_absent": "SCRIPT ERROR"}
  ],
  "milestones": [
    {"id": "in-game", "query": "ui.ClockLabel.text", "op": "!=", "value": "", "expect_within_steps": 5}
  ],
  "budget": {"max_steps": 40, "max_tokens": 400000, "max_wall_seconds": 900, "max_frames": 20000, "stuck_after_steps": 12}
}
```

## Fields

| Field        | Meaning                                                                                                                        |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `goal`       | One sentence the agent plays toward; the persona reads nothing else about the game.                                            |
| `mode`       | `llm_stepped` (this skill) or `scripted_bot` (`godot-bot`).                                                                    |
| `persona`    | `novice`, `speedrunner`, `explorer` or `adversarial`; see the play loop reference.                                             |
| `seeds`      | One run per seed; the seed goes to the bridge's welcome and to `play start --seed`.                                            |
| `success`    | At least one predicate; all must hold on the same observation. A list of only `log_absent` is refused: an idle run would pass. |
| `invariants` | Must hold on every observation; a break is a `bug`. Each has an `id`.                                                          |
| `milestones` | Progress marks with an `id`; `expect_within_steps` turns a late one into a pacing `observation`.                               |
| `budget`     | `max_steps`, `max_tokens`, `max_wall_seconds`, `max_frames` are required; `stuck_after_steps` defaults to 20.                  |

## Predicates

- `{"query": "Node.key", "op": OP, "value": V}` with OP one of `==`, `!=`, `>=`, `<=`, `>`, `<`; ordering ops need numbers on both sides.
- The first part of a query is a `playtest_observe` node's name, then keys of its `playtest_state()` dictionary: `Survival.day`, `Arena.enemy_health`.
- `ui.<ControlName>.<field>` reads a shown Control the bridge listed: fields `text`, `type`, `focus`, `disabled` (buttons), `name` (accessibility name), `rect`. A Control that is not shown makes its predicate false, so `ui.X.text != ""` also means "X is on screen". When names repeat, the first in tree order wins.
- `{"log_absent": "text"}` holds while no engine error line seen so far contains the text.
- A query naming a node or key the game never reports makes the whole run `invalid` (`unknown_query`): fix the scenario, not the run.

## Choosing predicates

- Success is a state the game shows, not an action the agent took: "the clock moved", not "Resume was clicked".
- Prefer `playtest_observe` state over UI text when the game has it: text changes with translation and copy edits.
- An invariant states a rule of the game (health never below 0, gold never negative, unit count under the cap). A rule broken once is a bug with a replay; keep invariants to rules the owner would call a bug.
- Budget `max_tokens` counts measured input plus output tokens of the playing agent; cached prompt tokens count as input.

## Game hooks

A game opts in through three groups; all are optional, and the bridge uses only these methods (no `Expression`, no arbitrary calls).

| Group              | Method                                    | Used by                                                |
| ------------------ | ----------------------------------------- | ------------------------------------------------------ |
| `playtest_observe` | `playtest_state() -> Dictionary`          | observations, predicates, claims                       |
| `playtest_actor`   | `playtest_actions() -> Array[Dictionary]` | the catalogue in the hello: `[{"name", "args"}]`       |
| `playtest_actor`   | `playtest_do(name, args) -> Dictionary`   | `do` acts                                              |
| `playtest_state`   | `state_hash() -> String`                  | hashes in observations, replays and the stuck detector |

```gdscript
func _ready() -> void:
	add_to_group(&"playtest_observe")
	add_to_group(&"playtest_state")


func playtest_state() -> Dictionary:
	return {"day": day, "oxygen": oxygen, "alive": alive}


func state_hash() -> String:
	return "%d:%d:%s" % [day, oxygen, alive]
```

Adding hooks changes the game, so it is the owner's call. On a read-only project (a test bed copy, a scratch clone), scenarios use `ui.` queries and engine errors only.

## Where files go

| Path                                    | Written by                                       |
| --------------------------------------- | ------------------------------------------------ |
| `playtest/scenarios/<id>.json`          | the agent or the owner                           |
| `playtest/bots/<id>.py`                 | `godot-bot`                                      |
| `playtest/runs/<session>/run.json`      | `playtest judge`: result, cost, claims, findings |
| `playtest/runs/<session>/actions.jsonl` | `playtest judge`, copied from the session        |
| `playtest/findings/f-<12 hex>.json`     | `playtest judge`; one file per fingerprint       |
| `playtest/events/<ulid>.json`           | the review hub: the owner's decisions            |

`playtest/.gdignore` keeps Godot from importing any of it. Session folders live under `.godot/godotkit/play/`, which is never committed.
