"""RTS bot for scenario `match`: the in-game team bots play; this one steps 120 frames at a
time and stops at the winner, so the judge sees the match at full speed.

Usage: python3 watch.py GODOTKIT PROJECT [SEED]. Prints the session id on its last line.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

STEP_FRAMES = 120


def play(godotkit: str, project: str, *args: str) -> dict[str, Any]:
    done = subprocess.run(
        [godotkit, "play", *args, "--project", project], capture_output=True, text=True
    )
    # Any: godotkit's JSON replies, read field by field.
    reply: dict[str, Any] = json.loads(done.stdout.strip().splitlines()[-1])
    if not reply.get("ok"):
        raise SystemExit(f"godotkit play {args[0]} failed: {reply}")
    return reply


def main(godotkit: str, project: str, seed: str = "7") -> None:
    started = play(godotkit, project, "start", "--seed", seed, "--max-steps", "60")
    session = str(started["session"])
    for _ in range(59):
        obs = play(godotkit, project, "step", "--session", session, "--frames", str(STEP_FRAMES))
        entities = obs["obs"]["entities"]
        if any(e["state"]["winner"] >= 0 for e in entities):
            break
    play(godotkit, project, "end", "--session", session)
    print(session)


if __name__ == "__main__":
    main(*sys.argv[1:])
