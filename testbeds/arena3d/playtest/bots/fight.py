"""Arena bot for scenario `fight`: walks to the enemy, attacks in reach, then walks to the exit.

Usage: python3 fight.py GODOTKIT PROJECT [SEED]. Prints the session id on its last line.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from typing import Any

# Any: godotkit's JSON replies, read field by field.
Reply = dict[str, Any]
STEP_FRAMES = 6
# The player's reach in data/player.tres is 1.8 m; attacking a little inside it never misses.
REACH = 1.6
CLOSE = 0.3


def play(godotkit: str, project: str, *args: str) -> Reply:
    done = subprocess.run(
        [godotkit, "play", *args, "--project", project], capture_output=True, text=True
    )
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
    chosen: list[Reply] = []
    if fighting and math.hypot(dx, dz) <= REACH:
        return [{"kind": "action", "name": "attack"}]
    if abs(dx) > CLOSE:
        name = "move_right" if dx > 0 else "move_left"
        chosen.append({"kind": "action", "name": name, "hold_frames": STEP_FRAMES})
    if abs(dz) > CLOSE:
        name = "move_back" if dz > 0 else "move_forward"
        chosen.append({"kind": "action", "name": name, "hold_frames": STEP_FRAMES})
    return chosen


def main(godotkit: str, project: str, seed: str = "1") -> None:
    started = play(godotkit, project, "start", "--seed", seed, "--max-steps", "400")
    session, obs = str(started["session"]), started["obs"]
    for _ in range(399):
        state = arena(obs)
        if state["result"] != "playing":
            break
        texts = [part for act in acts(state) for part in ("--act", json.dumps(act))]
        step = ["step", "--session", session, *texts, "--frames", str(STEP_FRAMES)]
        obs = play(godotkit, project, *step)["obs"]
    play(godotkit, project, "end", "--session", session)
    print(session)


if __name__ == "__main__":
    main(*sys.argv[1:])
