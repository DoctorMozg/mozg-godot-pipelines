"""uikit capture: godotkit shot at the brief's sizes, then one assetkit version per run."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from uifixtures import Doc, screen_doc, write
from uikit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main

GODOTKIT = """
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
out = Path(args[args.index("--out") + 1])
out.mkdir(parents=True)
captures = []
for size in args[args.index("--sizes") + 1].split(","):
    w, h = (int(n) for n in size.split("x"))
    png = out / f"{size}.png"
    png.write_bytes(b"png")
    image = [w, h - int(os.environ.get("STUB_SHRINK", "0"))]
    captures.append({"size": [w, h], "png": str(png), "image": image})
print(json.dumps({"cmd": "shot", "ok": True, "captures": captures}))
"""
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
    payload = {"ok": True, "asset": {"id": "hud-main-a1b2"}}
elif args[0] == "status":
    payload = {"ok": True, "assets": [{"current_version": f"v{done}" if done else None}]}
elif os.environ.get("STUB_REFUSE_VERSION") or ("--param" in args and "--provider" not in args):
    payload = {"ok": False, "detail": "/generation: missing required 'provider'"}
else:
    versions.write_text(str(done + 1))
    payload = {"ok": True, "version": {"id": f"v{done + 1}"}}
print(json.dumps(payload))
"""


@pytest.fixture
def kits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "stub"
    state.mkdir()
    for name, body in (("godotkit", GODOTKIT), ("assetkit", ASSETKIT)):
        script = state / name
        script.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        script.chmod(0o755)
        monkeypatch.setenv(name.upper(), str(script))
    monkeypatch.setenv("STUB_STATE", str(state))
    return state


@pytest.fixture
def screen(ui: Path) -> Path:
    (ui / "ui/hud.tscn").write_text("[gd_scene format=3]\n", encoding="utf-8")
    write(ui, "ui/screens/hud/main.json", screen_doc(scene="res://ui/hud.tscn"))
    return ui


def capture(ui: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> tuple[int, Doc]:
    code = main(["--project", str(ui), "capture", "hud/main", *extra])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def calls(state: Path) -> list[list[str]]:
    return [json.loads(line) for line in (state / "calls.jsonl").read_text().splitlines()]


def test_first_capture_makes_the_asset_and_a_version(
    screen: Path, kits: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = capture(screen, capsys, "--license", "LicenseRef-project")
    assert (code, out["asset"], out["version"], out["parent"]) == (
        EXIT_OK,
        "hud-main-a1b2",
        "v1",
        None,
    )
    files = out["files"]
    assert sorted(files) == ["1280x720", "1920x1080"]
    assert files["1280x720"].startswith("registry/staging/ui/hud-main/")
    added = calls(kits)[-1]
    assert added[:6] == ["version", "add", "hud-main-a1b2", "--project", str(screen), "--origin"]
    assert ["--file", f"1920x1080={files['1920x1080']}"] == added[9:11]
    assert added[13:15] == ["--media", "sizes=1280x720,1920x1080"]
    record = json.loads((screen / "ui/screens/hud/main.json").read_text())
    assert record["capture"] == "hud-main-a1b2"


def test_second_capture_names_its_parent(
    screen: Path, kits: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    capture(screen, capsys, "--license", "LicenseRef-project")
    (kits / "versions").write_text("1")
    monkeypatch.setattr("uikit.capture.time.strftime", lambda *_: "20261115T000001")
    code, out = capture(screen, capsys)
    assert (code, out["version"], out["parent"]) == (EXIT_OK, "v2", "v1")
    assert calls(kits)[-1][-2:] == ["--parent", "v1"]


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"STUB_SHRINK": "8"}, "1280x720: the PNG is 1280x712, so the window did not resize"),
        ({}, "screen hud/main has no capture asset yet; pass --license"),
    ],
)
def test_refusals(
    screen: Path,
    kits: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, str],
    detail: str,
) -> None:
    for key, value in change.items():
        monkeypatch.setenv(key, value)
    extra = ("--license", "LicenseRef-project") if change else ()
    code, out = capture(screen, capsys, *extra)
    assert (code, out["detail"]) == (EXIT_REFUSED, detail)
    recorded = calls(kits) if (kits / "calls.jsonl").exists() else []
    assert [call[0] for call in recorded if call[0] == "version"] == []
    assert staged_shots(screen) == []


def staged_shots(project: Path) -> list[Path]:
    folder = project / "registry/staging/ui/hud-main"
    return list(folder.iterdir()) if folder.is_dir() else []


def test_refused_version_leaves_no_shots(
    screen: Path, kits: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("STUB_REFUSE_VERSION", "1")
    code, out = capture(screen, capsys, "--license", "LicenseRef-project")
    assert (code, out["reason"]) == (EXIT_FAILED, "tool_failed")
    assert staged_shots(screen) == []


def test_screen_without_a_scene(ui: Path, kits: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = capture(ui, capsys)
    assert (code, out["detail"]) == (EXIT_REFUSED, "screen 'hud/main' needs a record with a scene")
