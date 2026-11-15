"""Builders for cue sheets and tiny WAV files, shared by the audiokit suites."""

from __future__ import annotations

import json
import math
import struct
import wave
from pathlib import Path
from typing import Any

# Any: JSON documents built for the tests.
Doc = dict[str, Any]

RATE = 48000


def write(project: Path, relative: str, doc: object) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


def tone(path: Path, seconds: float = 0.05, amplitude: float = 0.5, hz: float = 440.0) -> Path:
    """A mono 16-bit sine at 48 kHz; 0.05 s keeps each fixture under 5 KB."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(RATE * seconds)
    peak = int(amplitude * 32767)
    samples = (int(peak * math.sin(2 * math.pi * hz * i / RATE)) for i in range(frames))
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(b"".join(struct.pack("<h", s) for s in samples))
    return path


def cue_doc(**changes: object) -> Doc:
    cue: Doc = {
        "kind": "ui",
        "bus": "UI",
        "files": ["audio/ui/ui_click.wav"],
        "loop": {"mode": "none"},
        "gain_db": -5,
        "source": {"type": "procedural", "generator": "tools/audio/synth.py", "seed": 7},
    }
    return cue | changes


def sheet_doc(**cues: Doc) -> Doc:
    return {
        "mix_rate": RATE,
        "buses": ["Master", "Music", "SFX", "UI"],
        "cues": cues or {"ui_click": cue_doc()},
    }


def audio_project(project: Path) -> Path:
    """A project with one valid cue, ui_click, and its WAV."""
    tone(project / "audio/ui/ui_click.wav")
    write(project, "audio/cues.json", sheet_doc())
    return project
