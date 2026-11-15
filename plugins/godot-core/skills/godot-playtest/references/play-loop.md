# The Play Loop

<!-- toc:start -->

## Contents

- Commands
- Observation
- Acts
- Deciding a step
- Personas
- The report file
- A measured run
- What the bridge cannot do

<!-- toc:end -->

## Commands

```bash
godotkit play start --project P [--scene res://...] [--seed N] [--max-steps 200] [--timeout 120]
godotkit play step  --project P --session ID [--act JSON]... [--frames N] [--look]
godotkit play end   --project P --session ID
godotkit playtest judge --project P --session ID --scenario FILE [--report FILE] \
    (--usage FILE | --tokens-in N --tokens-out N [--usd X]) [--no-replay] [--timeout 120]
```

- `start` prints `session`, `hello` (`actions`: input actions without `ui_*`; `catalogue`: the game's semantic actions) and the first `obs`.
- Each `step` applies the acts on the step's first frame, runs `--frames` physics frames (default 1) and prints the observation after them. Game time only passes inside a step: thinking costs no frames.
- `end` releases held actions, prints `MOZG_PLAY_SUMMARY`, judges the log and writes the session's `actions.jsonl`. A session also ends after `--idle` seconds (900) without a step, or at `--max-steps`.
- Every command prints one JSON line; exit 0 ok, 1 failed, 2 setup, 3 refused input.

## Observation

| Field      | Meaning                                                                                                                     |
| ---------- | --------------------------------------------------------------------------------------------------------------------------- |
| `frame`    | Physics frames since the scene started                                                                                      |
| `hash`     | `state_hash()` of the `playtest_state` node, or null                                                                        |
| `scene`    | The current scene's path                                                                                                    |
| `ui`       | Shown Controls that are interactive or carry text: `path`, `type`, `text`, `rect`, `focus`, `disabled`, `name`; at most 100 |
| `entities` | `{path, state}` for each `playtest_observe` node                                                                            |
| `held`     | Actions still held, with frames left                                                                                        |
| `acts`     | The acts applied, as actions-file rows                                                                                      |
| `rejected` | Acts refused, with a reason: `unknown_action`, `no_visible_control`, `unknown_semantic_action`                              |
| `results`  | What `playtest_do` returned                                                                                                 |
| `errors`   | Engine error lines logged during the step                                                                                   |
| `look`     | A PNG path natively, `no_renderer` headless                                                                                 |

A rejected act was not played and is not recorded. Read `rejected` and `errors` after every step before deciding the next one.

## Acts

```json
{"kind": "action", "name": "move_forward", "hold_frames": 12, "strength": 1.0}
{"kind": "click", "target": "/root/GameScreen/Margin/Content/Header/SaveButton"}
{"kind": "do", "name": "build", "args": {"kind": "farm"}}
```

- `action`: an input action from the hello, pressed on the step's first frame and released `hold_frames` later (1 to 3600), across steps if needed. Strength is above 0 and at most 1.
- `click`: a mouse press and release at the centre of a shown Control, by its full `path` from `ui`. Buttons, tabs, list items and line edits take it.
- `do`: a catalogue entry by `name` with its `args`; the game's `playtest_do` decides and `results` reports.
- Several acts in one step are applied in order on the same frame.

## Deciding a step

- One decision a step: what to try and why, in a line, then the acts. Keep these lines for the report's `text`; claims are checked later, the text is not.
- Size `--frames` by what the act needs to show: 1 to 10 for a click on a menu, 30 to 120 for an animation or a timer, longer only when waiting is the decision.
- After each observation, compare with the goal and the last few observations. Same hash and same UI text for several steps means no progress: try something different, not the same act again.
- Stop when a success state is visible, when the budget is near, or when nothing new happens after a different approach. The judge decides pass or fail; the agent only stops playing.

## Personas

| Persona       | Plays like                                                                                                                  |
| ------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `novice`      | Reads every label, follows the most prominent hint, never guesses hidden controls, gives up on a dead end after a few tries |
| `speedrunner` | Takes the shortest path to the goal, skips text, chains acts per step                                                       |
| `explorer`    | Opens every menu and button before pursuing the goal; notes what each does                                                  |
| `adversarial` | Clicks out of order, repeats acts, cancels midway, enters odd values: hunting crashes and broken states                     |

## The report file

Written after `play end`, passed to `playtest judge --report`.

```json
{
  "text": "Opened the activity picker; Resume never started the clock.",
  "claims": [{"query": "ui.ClockLabel.text", "value": "Day 1 · 00:00"}],
  "remarks": [
    {"title": "Resume does nothing until a job is planned", "node_path": "/root/GameScreen/Margin/Content/PersonalSchedule/@PanelContainer@38/@HFlowContainer@39/PauseResume", "text": "The button stays enabled and gives no feedback."}
  ]
}
```

- A claim is a query and the value the agent believes the game ended with. The judge checks each against the last observation; a wrong value or a query the game cannot answer counts as contradicted and is reported as made up.
- A remark becomes a `ux_hypothesis` finding only when it names a `node_path` or a `screenshot`; a person can check those. Other impressions go in `text`.
- Nothing in the report is evidence for a bug. Bugs come from engine errors and broken invariants, confirmed by a replay without the agent.

## A measured run

A run counts toward the scenario's cost only with measured tokens. An interactive session cannot read its own usage, so a scored run is played by a fresh headless agent:

```bash
claude -p "Use the godot-playtest skill: play scenario playtest/scenarios/first-day.json in project P as its persona, up to play end, then write playtest/runs/report-first-day.json. Do not run playtest judge." \
  --plugin-dir <plugin> --output-format json --max-budget-usd 5 \
  --allowedTools "Bash(godotkit:*)" "Read" "Write" > usage.json
godotkit playtest judge --project P --session ID --scenario playtest/scenarios/first-day.json \
  --report playtest/runs/report-first-day.json --usage usage.json
```

- `--usage` reads `usage.input_tokens`, the two cache token counts and `usage.output_tokens`, and `total_cost_usd`.
- The session id is in the headless agent's `play start` reply; `ls -t P/.godot/godotkit/play | head -1` finds it too.
- A run judged without cost is `invalid` (`no_cost`), but its findings are still recorded.

## What the bridge cannot do

- Drag, scroll wheel and keyboard text entry are not acts. A flow that needs them stops there; report the step and what it needed.
- Headless runs have no picture: `look` answers `no_renderer`. 3D objects, sprites and anything not a Control are invisible unless the game reports them through `playtest_observe`.
- Clicks reach Controls only. A 3D board, a world map or a canvas drawn in `_draw` takes no `click` act.
- Observed on AloneGodot (2026-11-15, a scratch clone): 23 Controls and about 5,000 characters an observation; `Resume` takes the click (`pressed` fires) but the clock stays at `Day 1 · 00:00` until a job is planned by dragging a card onto the 3D table, which the bridge cannot do.
