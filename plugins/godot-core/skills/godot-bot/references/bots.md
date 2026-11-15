# Bots

A bot is a script that drives `godotkit play` with no model in the loop. It starts a session, reads each observation, picks acts by rule, steps, and ends the session; `godotkit playtest judge` then scores the trace exactly as it scores an agent's run. Python 3 with the standard library is enough: the bot only calls the godotkit command and parses its JSON lines.

Bots live at `<project>/playtest/bots/<scenario id>.py` beside their scenario, take `GODOTKIT PROJECT [SEED]` as arguments, and print the session id on their last line.

<!-- toc:start -->

## Contents

- A reactive bot
- A watching bot
- Writing one
- Judging a bot run
- When a bot is the wrong tool

<!-- toc:end -->

## A reactive bot

The arena test bed's bot (`testbeds/arena3d/playtest/bots/fight.py` in the mozg-godot repository) walks to the enemy, attacks in reach, then walks to the exit. Its decisions read the `Arena` node's `playtest_state()`: positions on the floor plane and both health values.

```python
import json, math, subprocess, sys
from typing import Any

Reply = dict[str, Any]  # godotkit's JSON replies, read field by field
STEP_FRAMES = 6
REACH = 1.6  # the player's reach in data/player.tres is 1.8 m
CLOSE = 0.3


def play(godotkit: str, project: str, *args: str) -> Reply:
    done = subprocess.run([godotkit, "play", *args, "--project", project],
                          capture_output=True, text=True)
    reply: Reply = json.loads(done.stdout.strip().splitlines()[-1])
    if not reply.get("ok"):
        raise SystemExit(f"godotkit play {args[0]} failed: {reply}")
    return reply


def arena(obs: Reply) -> Reply:
    return next(e["state"] for e in obs["entities"] if e["path"].endswith("/Arena"))


def acts(state: Reply) -> list[Reply]:
    fighting = state["enemy_health"] > 0
    px, pz = state["player"]
    tx, tz = state["enemy"] if fighting else state["exit"]
    dx, dz = tx - px, tz - pz
    if fighting and math.hypot(dx, dz) <= REACH:
        return [{"kind": "action", "name": "attack"}]
    chosen: list[Reply] = []
    if abs(dx) > CLOSE:
        chosen.append({"kind": "action", "name": "move_right" if dx > 0 else "move_left",
                       "hold_frames": STEP_FRAMES})
    if abs(dz) > CLOSE:
        chosen.append({"kind": "action", "name": "move_back" if dz > 0 else "move_forward",
                       "hold_frames": STEP_FRAMES})
    return chosen


def main(godotkit: str, project: str, seed: str = "1") -> None:
    started = play(godotkit, project, "start", "--seed", seed, "--max-steps", "400")
    session, obs = str(started["session"]), started["obs"]
    for _ in range(399):
        state = arena(obs)
        if state["result"] != "playing":
            break
        texts = [part for act in acts(state) for part in ("--act", json.dumps(act))]
        obs = play(godotkit, project, "step", "--session", session, *texts,
                   "--frames", str(STEP_FRAMES))["obs"]
    play(godotkit, project, "end", "--session", session)
    print(session)


if __name__ == "__main__":
    main(*sys.argv[1:])
```

Measured 2026-11-15 on Godot 4.7.2 headless: 36 steps, 216 frames, 8.1 s wall time, judged `pass` with no findings.

## A watching bot

When the game plays itself (a bot-versus-bot match, a simulation, a soak test), the bot only lets frames pass and stops at the end state. The RTS test bed's `watch.py` steps 120 frames at a time until `Match.winner` is set: 14 steps, 1,680 frames, 2.9 s wall time, `pass`, with the 500-unit cap held (2026-11-15).

```python
for _ in range(59):
    obs = play(godotkit, project, "step", "--session", session, "--frames", "120")
    if any(e["state"]["winner"] >= 0 for e in obs["obs"]["entities"]):
        break
```

## Writing one

- Read the game's input actions from the `hello` and its state from `playtest_observe` nodes before writing rules; a bot cannot see what the game does not report.
- Hold movement for the whole step (`hold_frames` equal to `--frames`), so the character moves for the frames the step lets pass and stops after.
- Tap one-shot actions (attack, jump, confirm) with the default hold of one frame.
- Pick the step size from the game's pace: 4 to 10 frames for steering, 60 to 300 for watching. Each step is one process call of about 0.2 s, so step count, not frame count, sets the wall time.
- Bound every loop by the scenario's `max_steps` and break on the game's own end state; the session also stops itself at `--max-steps`.
- Seed the bot's own randomness from the scenario seed, so a rerun plays the same acts.

## Judging a bot run

```bash
SESSION=$(python3 -I playtest/bots/fight.py godotkit . 1 | tail -1)
godotkit playtest judge --project . --session "$SESSION" --scenario playtest/scenarios/fight.json \
  --tokens-in 0 --tokens-out 0 --usd 0
```

- The bot spends no model tokens while it plays, so its measured cost is zero. The tokens spent writing the bot are a one-off and belong in the report, not in the run.
- Scenario budgets for bots set `max_tokens` to 1: any token use would mean a model took part.
- A bug found by a bot is replayed from the session's actions file like any other; a bot's run is deterministic, so a bug that does not replay points at the game's nondeterminism (`godotkit replay --runs 3` checks it).

## When a bot is the wrong tool

- Goals in language ("find the settings and turn off the music") with no state to steer by: `godot-playtest`.
- Coverage of a large space (every room, every dialogue branch): a bot follows its rules, so it finds what the rules reach.
- Feel and readability: a bot cannot judge them; `godotkit feel` measures response frames and camera faults, and a person judges the rest.
