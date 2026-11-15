"""audiokit audit: header facts against the mix rate and the first matching policy rule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from audiofixtures import Doc, cue_doc, ogg_bytes, sheet_doc, write
from audiokit.audit import Audit
from audiokit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from audiokit.policy import load_policy
from audiokit.records import CueSheet

UI_RULE = {"glob": "audio/ui/*", "codecs": ["pcm"], "channels": 1, "max_duration_s": 0.04}


def audit(project: Path) -> list[tuple[str, str, str]]:
    report = Audit(CueSheet(project), load_policy(project), None).run()
    return [(f.file, f.rule, f.detail) for f in report.problems]


def test_no_policy_checks_the_mix_rate_only(audio: Path) -> None:
    assert audit(audio) == []


def test_first_matching_rule_applies(audio: Path) -> None:
    write(audio, "audio/policy.json", {"rules": [UI_RULE, {"glob": "audio/*", "channels": 2}]})
    assert audit(audio) == [
        ("audio/ui/ui_click.wav", "duration", "0.050 s, over 0.04 s for audio/ui/*")
    ]


def test_ogg_rate_codec_and_channels(audio: Path) -> None:
    (audio / "audio/music").mkdir(parents=True)
    (audio / "audio/music/theme.ogg").write_bytes(ogg_bytes(44100, 2, 2.0))
    theme = cue_doc(kind="music", bus="Music", files=["audio/music/theme.ogg"])
    write(audio, "audio/cues.json", sheet_doc(theme=theme, ui_click=cue_doc()))
    write(
        audio,
        "audio/policy.json",
        {"rules": [{"glob": "audio/music/*", "codecs": ["mp3"], "channels": 1}]},
    )
    assert [rule for _, rule, _ in audit(audio)] == ["rate", "codec", "channels"]


def test_unreadable_file(audio: Path) -> None:
    (audio / "audio/ui/ui_click.wav").write_bytes(b"not audio")
    assert audit(audio) == [
        ("audio/ui/ui_click.wav", "unreadable", "ui_click.wav is not a RIFF WAVE file")
    ]


@pytest.mark.parametrize(
    ("policy", "detail"),
    [
        ({"rules": [{"codecs": ["pcm"]}]}, "every rule needs a glob"),
        ({"rules": [{"glob": "*", "codecs": ["aac"]}]}, "codecs come from"),
        ({"rules": [{"glob": "*", "max_duration_s": -1}]}, "max_duration_s must be a positive"),
    ],
)
def test_bad_policy_is_refused(
    audio: Path, capsys: pytest.CaptureFixture[str], policy: Doc, detail: str
) -> None:
    write(audio, "audio/policy.json", policy)
    assert main(["--project", str(audio), "audit"]) == EXIT_REFUSED
    assert detail in json.loads(capsys.readouterr().out)["detail"]


def test_cli_reports_files(audio: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--project", str(audio), "audit"]) == EXIT_OK
    out = json.loads(capsys.readouterr().out)
    assert out["files"]["audio/ui/ui_click.wav"] == {
        "codec": "pcm", "rate": 48000, "channels": 1, "bits": 16, "duration_s": 0.05,
    }  # fmt: skip
    write(audio, "audio/policy.json", {"rules": [UI_RULE]})
    assert main(["--project", str(audio), "audit"]) == EXIT_FAILED
