"""audiokit register: fal calls and synth files become versions through a stand-in assetkit."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from audiofixtures import Doc, cue_doc, sheet_doc, tone, write
from audiokit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main

ASSETKIT = """
import json, os, sys
from pathlib import Path
state = Path(os.environ["STUB_STATE"])
args = sys.argv[1:]
with (state / "calls.jsonl").open("a") as handle:
    handle.write(json.dumps(args) + "\\n")
versions = state / "versions"
done = int(versions.read_text()) if versions.exists() else 0
if args[0] == "new":
    payload = {"ok": True, "asset": {"id": "boom-a1b2"}}
elif args[0] == "status":
    kind = os.environ.get("STUB_KIND", "audio")
    current = f"v{done}" if done else None
    payload = {"ok": True, "assets": [{"kind": kind, "current_version": current}]}
elif os.environ.get("STUB_REFUSE") or ("--seed" in args and "--provider" not in args):
    payload = {"ok": False, "detail": "refused"}
else:
    versions.write_text(str(done + 1))
    payload = {"ok": True, "version": {"id": f"v{done + 1}"}}
print(json.dumps(payload))
"""
ENDPOINT = "elevenlabs/sound-effects/v3"
REQUEST = "01a1dcf9-5c4c-7c70-a74d-08eb465651d9"


@pytest.fixture
def kit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "stub"
    state.mkdir()
    script = state / "assetkit"
    script.write_text(f"#!{sys.executable}\n{ASSETKIT}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("ASSETKIT", str(script))
    monkeypatch.setenv("STUB_STATE", str(state))
    return state


@pytest.fixture
def fal(audio: Path, tmp_path: Path) -> Path:
    """A fal cue `boom` and a ledger export holding one fetched WAV."""
    boom = cue_doc(
        kind="sfx",
        bus="SFX",
        files=["audio/sfx/boom.wav"],
        source={"type": "fal", "endpoint": ENDPOINT},
    )
    write(audio, "audio/cues.json", sheet_doc(boom=boom, ui_click=cue_doc()))
    fetched = tone(tmp_path / "fal/out/boom.wav", seconds=0.5)
    digest = hashlib.sha256(fetched.read_bytes()).hexdigest()
    entry = {
        "request_id": REQUEST,
        "endpoint": ENDPOINT,
        "state": "fetched",
        "cwd": str(tmp_path / "fal"),
        "usd_charged": 0.001,
        "files": [{"path": "out/boom.wav", "sha256": digest}],
    }
    write(tmp_path, "ledger.json", {"entries": [entry]})
    return audio


def register(project: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Doc]:
    code = main(["--project", str(project), "register", *args])
    return code, json.loads(capsys.readouterr().out)


def calls(state: Path) -> list[list[str]]:
    return [json.loads(line) for line in (state / "calls.jsonl").read_text().splitlines()]


def fal_args(tmp_path: Path) -> tuple[str, ...]:
    return ("boom", "--ledger", str(tmp_path / "ledger.json"), "--request-id", REQUEST)


def test_fal_call_becomes_a_measured_version(
    fal: Path, kit: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = register(
        fal,
        capsys,
        *fal_args(tmp_path),
        "--prompt",
        "a dull boom",
        "--license",
        "LicenseRef-unreviewed",
    )
    assert (code, out["asset"], out["version"], out["usd_charged"]) == (
        EXIT_OK,
        "boom-a1b2",
        "v1",
        0.001,
    )
    assert out["files"] == ["registry/staging/boom-a1b2/01a1dcf9/boom.wav"]
    added = calls(kit)[-1]
    for pair in (
        ["--model", ENDPOINT],
        ["--job-id", REQUEST],
        ["--prompt", "a dull boom"],
        ["--param", "usd_charged=0.001"],
        ["--media", "duration_s=0.5"],
        ["--media", "lufs_i=-9.72"],
    ):
        assert any(added[i : i + 2] == pair for i in range(len(added))), pair
    assert json.loads((fal / "audio/cues.json").read_text())["cues"]["boom"]["asset"] == "boom-a1b2"


def test_repeat_and_changed_file_are_refused(
    fal: Path, kit: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    register(fal, capsys, *fal_args(tmp_path), "--license", "LicenseRef-unreviewed")
    code, out = register(fal, capsys, *fal_args(tmp_path))
    assert (code, out["detail"]) == (
        EXIT_REFUSED,
        "registry/staging/boom-a1b2/01a1dcf9 exists: this result is already registered",
    )
    (tmp_path / "fal/out/boom.wav").write_bytes(b"changed")
    assert "does not match the sha256" in register(fal, capsys, *fal_args(tmp_path))[1]["detail"]


@pytest.mark.parametrize(
    ("env", "code", "detail"),
    [
        ({"STUB_KIND": "image"}, EXIT_REFUSED, "asset boom-a1b2 holds image files, not audio"),
        ({"STUB_REFUSE": "1"}, EXIT_FAILED, "assetkit version add boom-a1b2"),
    ],
)
def test_assetkit_says_no_and_nothing_stays_staged(
    fal: Path,
    kit: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    env: dict[str, str],
    code: int,
    detail: str,
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    result = register(fal, capsys, *fal_args(tmp_path), "--license", "LicenseRef-unreviewed")
    assert (result[0], result[1]["detail"][: len(detail)]) == (code, detail)
    assert not (fal / "registry/staging/boom-a1b2/01a1dcf9").exists()


def test_unknown_request(
    fal: Path, kit: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("boom", "--ledger", str(tmp_path / "ledger.json"), "--request-id", "nope")
    assert (
        register(fal, capsys, *args)[1]["detail"]
        == f"request nope is not in {tmp_path / 'ledger.json'}"
    )


def test_synth_files_register_with_seed_and_parent(
    audio: Path, kit: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = {
        "type": "procedural",
        "generator": "audiokit:blip",
        "seed": 3,
        "params": {"seconds": 0.05, "hz": 880, "peak_dbfs": -6},
    }
    write(audio, "audio/cues.json", sheet_doc(ui_click=cue_doc(source=source)))
    (audio / "audio/ui/ui_click.wav").unlink()
    assert main(["--project", str(audio), "synth", "ui_click"]) == EXIT_OK
    capsys.readouterr()
    code, out = register(audio, capsys, "ui_click", "--license", "LicenseRef-project")
    assert (code, out["parent"]) == (EXIT_OK, None)
    added = calls(kit)[-1]
    assert added[added.index("--origin") + 1] == "procedural"
    assert added[added.index("--seed") + 1] == "3"
    assert added[added.index("--file") + 1].startswith("main=registry/staging/boom-a1b2/")


def test_fal_cue_without_ledger(fal: Path, kit: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        register(fal, capsys, "boom")[1]["detail"]
        == "boom comes from fal; register it with --ledger"
    )
