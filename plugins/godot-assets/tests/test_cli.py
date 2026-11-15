"""assetkit CLI: the review flow end to end, refusals, the launcher and a two-worktree merge."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from assetkit import cli
from assetkit_rig import CliRunner

PLUGIN = Path(__file__).resolve().parents[1]
GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


@pytest.fixture
def asset(run_cli: CliRunner) -> str:
    code, payload = run_cli(
        "new", "--family", "ui", "--kind", "image", "--title", "Play", "--license", "CC0-1.0"
    )
    assert code == 0, payload
    return str(payload["asset"]["id"])


def _version(run_cli: CliRunner, asset: str) -> str:
    code, payload = run_cli("version", "add", asset, "--file", "art/hero.png", "--origin", "human")
    assert code == 0, payload
    return str(payload["version"]["id"])


def test_review_flow_reaches_final(run_cli: CliRunner, asset: str) -> None:
    version = _version(run_cli, asset)
    assert run_cli("decide", asset, "retake", "--body", "too dark")[0] == 0
    newer = _version(run_cli, asset)
    assert run_cli("decide", asset, "approve")[0] == 0
    code, payload = run_cli("status", asset, "--set", "final")
    assert code == 0, payload
    [row] = payload["assets"]
    assert (row["status"], row["current_version"], row["versions"]) == ("final", newer, 2)
    assert [(e["type"], e["version_id"]) for e in payload["events"]][:1] == [("decision", version)]


@pytest.mark.parametrize(
    ("setup", "command", "message"),
    [
        (0, ("decide", "{asset}", "approve"), "no version to decide on"),
        (1, ("status", "{asset}", "--set", "final"), "pending_review, which cannot become final"),
        (2, ("decide", "{asset}", "approve", "--version", "{first}"), "is not the current version"),
        (1, ("note", "{asset}", "--body", "x", "--reply-to", "{first}"), "no event"),
        (0, ("decide", "ghost-0000", "approve"), "no asset 'ghost-0000'"),
        (
            0,
            ("version", "add", "{asset}", "--file", "art/hero.png", "--origin", "generated"),
            "missing required 'generation'",
        ),
    ],
)
def test_refusals_name_the_reason(
    run_cli: CliRunner, asset: str, setup: int, command: tuple[str, ...], message: str
) -> None:
    versions = [_version(run_cli, asset) for _ in range(setup)]
    filled = [part.format(asset=asset, first=versions[0] if versions else "") for part in command]
    code, payload = run_cli(*filled)
    assert (code, payload["reason"]) == (3, "refused"), payload
    assert message in payload["detail"]


def test_version_records_media_measurements(run_cli: CliRunner, asset: str) -> None:
    add = ("version", "add", asset, "--file", "art/hero.png", "--origin", "human")
    code, payload = run_cli(
        *add, "--media", "hframes=4", "--media", "fps=12.5", "--media", "loop=pingpong"
    )
    assert (code, payload["version"]["media"]) == (
        0,
        {"hframes": 4, "fps": 12.5, "loop": "pingpong"},
    )
    assert run_cli(*add, "--media", "hframes")[1]["reason"] == "refused"


def test_version_records_generation_params(run_cli: CliRunner, asset: str) -> None:
    add = ("version", "add", asset, "--file", "art/hero.png", "--origin", "generated")
    made = ("--provider", "fal", "--model", "fal-ai/hunyuan-3d/v3.1/pro/image-to-3d")
    params = ("--param", "usd_charged=0.675", "--param", "face_count=40000")
    code, payload = run_cli(*add, *made, *params)
    assert (code, payload["version"]["generation"]["params"]) == (
        0,
        {"usd_charged": 0.675, "face_count": 40000},
    )
    assert run_cli(*add, *made, "--param", "=1")[1]["detail"] == "--param takes KEY=VALUE, got '=1'"


def test_note_with_a_region(run_cli: CliRunner, asset: str) -> None:
    version = _version(run_cli, asset)
    note = ("note", asset, "--body", "seam", "--version", version, "--region", "t=0.5,0.75")
    code, payload = run_cli(*note, "--region-file", "main", "--frame", "2")
    assert (code, payload["event"]["region"]) == (
        0,
        {"selector": "t=0.5,0.75", "file": "main", "frame": 2},
    )


def test_folder_without_project_godot_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["status", "--project", str(tmp_path)]) == 3
    assert "not a Godot project" in capsys.readouterr().out


def test_launcher_runs_from_the_plugin_folder(project: Path) -> None:
    done = subprocess.run(
        [str(PLUGIN / "bin" / "assetkit"), "status", "--project", str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (done.returncode, done.stdout.startswith('{"cmd": "status", "ok": true')) == (0, True), (
        done
    )


def test_two_worktrees_merge_without_conflict(project: Path, tmp_path: Path) -> None:
    def git(*args: str, cwd: Path = project) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, check=False
        )

    def kit(where: Path, *args: str) -> None:
        at = 2 if args[0] == "version" else 1
        command = [*args[:at], "--project", str(where), "--author", "t", *args[at:]]
        done = subprocess.run(
            [str(PLUGIN / "bin" / "assetkit"), *command],
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, done.stdout + done.stderr

    git("init", "-q", "-b", "main")
    kit(project, "new", "--family", "ui", "--kind", "image", "--title", "Play", "--license", "MIT")
    [asset] = [p.name for p in (project / "registry" / "assets" / "ui").iterdir()]
    kit(project, "version", "add", asset, "--file", "art/hero.png", "--origin", "human")
    git("add", "-A")
    git("commit", "-q", "-m", "v1")
    lanes = {name: tmp_path / name for name in ("lane_a", "lane_b")}
    for name, path in lanes.items():
        assert git("worktree", "add", "-q", "-b", name, str(path)).returncode == 0
    kit(lanes["lane_a"], "version", "add", asset, "--file", "art/hero.png", "--origin", "human")
    kit(lanes["lane_a"], "note", asset, "--body", "lighter")
    kit(lanes["lane_b"], "decide", asset, "approve")
    kit(lanes["lane_b"], "note", asset, "--body", "approved v1")
    for name, path in lanes.items():
        git("add", "-A", cwd=path)
        git("commit", "-q", "-m", name, cwd=path)
    assert git("merge", "-q", "lane_a").returncode == 0
    merged = git("merge", "-q", "--no-edit", "lane_b")
    assert merged.returncode == 0, merged.stdout + merged.stderr
    assert git("diff", "--name-only", "--diff-filter=U").stdout == ""
    events = list((project / "registry" / "assets" / "ui" / asset / "events").glob("*.json"))
    versions = list((project / "registry" / "assets" / "ui" / asset / "versions").glob("*.json"))
    assert (len(events), len(versions)) == (3, 2)
    status = subprocess.run(
        [str(PLUGIN / "bin" / "assetkit"), "status", asset, "--project", str(project)],
        capture_output=True,
        text=True,
        check=False,
    )
    # Lane B approved v1; lane A's v2 reopens review whichever came first.
    assert '"status": "pending_review"' in status.stdout
    assert '"versions": 2' in status.stdout
