"""The godotkit-actions/1 file: presses on physics frames and the hashes a replay must reach."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.actions import Gesture, Recording

HEADER = '{"schema": "godotkit-actions/1", "frames": 20, "every": 10}\n'
WALK = (
    '{"f": 3, "action": "walk", "pressed": true}\n'
    '{"f": 6, "action": "walk", "pressed": false, "strength": 0}\n'
)


class TestRecording:
    def test_acts_hashes_and_header_defaults_are_read(self, tmp_path: Path) -> None:
        path = tmp_path / "walk.jsonl"
        path.write_text(HEADER + WALK + '{"f": 10, "hash": "abc"}\n')
        recording = Recording.read(path)
        assert recording.acts == ((3, "walk", True, 1.0), (6, "walk", False, 0.0))
        assert recording.hashes == {10: "abc"}
        assert (recording.frames, recording.every, recording.scene) == (20, 10, None)

    @pytest.mark.parametrize(
        ("text", "message"),
        [
            ("", "empty"),
            ('{"schema": "other/1"}\n', "schema"),
            (HEADER + '{"f": 0, "action": "walk", "pressed": true}\n', "frame"),
            (HEADER + '{"f": 2, "action": "walk", "pressed": "yes"}\n', "pressed"),
            (HEADER + '{"f": 2, "action": "walk", "pressed": true, "strength": 2}\n', "strength"),
            (HEADER + "not json\n", "not JSON"),
            (HEADER + '{"f": 2, "click": ""}\n', "click"),
            (HEADER + '{"f": 2, "do": "build", "args": [1]}\n', "args"),
        ],
    )
    def test_a_malformed_file_is_refused_with_its_line(
        self, tmp_path: Path, text: str, message: str
    ) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text(text)
        with pytest.raises(ValueError, match=message):
            Recording.read(path)

    def test_a_written_recording_reads_back_and_is_never_replaced(self, tmp_path: Path) -> None:
        gestures = (
            Gesture(4, "click", "/root/Main/Start"),
            Gesture(5, "do", "build", {"kind": "farm", "at": [3, 4]}),
        )
        made = Recording(
            "res://main.tscn", 20, 10, ((3, "walk", True, 1.0),), {10: "a", 20: "b"}, gestures
        )
        target = tmp_path / "out" / "rec.jsonl"
        made.write(target)
        assert Recording.read(target) == made
        with pytest.raises(ValueError, match="never replaces"):
            made.write(target)
