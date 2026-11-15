"""artkit register: a fal ledger call becomes an assetkit version of its brief's asset."""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from artfixtures import add_brief, bible_doc, write
from artkit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_SETUP, main
from imagebytes import png

ENDPOINT = "fal-ai/nano-banana-2.1"
LICENSE = ("--license", "LicenseRef-fal-output")
STUB = """
import json, os, sys
from pathlib import Path
state = Path(os.environ["STUB_STATE"])
args = sys.argv[1:]
with (state / "calls.jsonl").open("a") as handle:
    handle.write(json.dumps(args) + "\\n")
store = state / "assets.json"
assets = json.loads(store.read_text()) if store.exists() else {}
if args[0] == "new":
    asset = args[args.index("--title") + 1] + "-a1b2"
    assets[asset] = []
    (state / "kind").write_text(args[args.index("--kind") + 1])
    payload = {"ok": True, "asset": {"id": asset}}
elif args[0] == "status":
    versions = assets.get(args[1], [])
    kind = (state / "kind").read_text() if (state / "kind").exists() else None
    payload = {"ok": True, "assets": [{"kind": kind,
               "current_version": versions[-1] if versions else None}]}
elif os.environ.get("STUB_FAIL"):
    payload = {"ok": False, "reason": "refused", "detail": "stub refusal"}
else:
    assets[args[2]].append("v%d" % (len(assets[args[2]]) + 1))
    payload = {"ok": True, "version": {"id": assets[args[2]][-1]}}
store.write_text(json.dumps(assets))
print(json.dumps(payload))
"""

# Any: the JSON line artkit printed, checked field by field.
Run = Callable[..., tuple[int, dict[str, Any]]]


@pytest.fixture
def stub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    state = tmp_path / "stub"
    state.mkdir()
    script = state / "assetkit"
    script.write_text(f"#!{sys.executable}\n{STUB}", encoding="utf-8")
    script.chmod(0o755)
    monkeypatch.setenv("ASSETKIT", str(script))
    monkeypatch.setenv("STUB_STATE", str(state))
    return state


@pytest.fixture
def art(project: Path) -> Path:
    (project / "art" / "briefs").mkdir(parents=True)
    write(project, "art/bible.json", bible_doc())
    add_brief(project, "scout")
    return project


@pytest.fixture
def run(art: Path, capsys: pytest.CaptureFixture[str]) -> Run:
    def register(ledger_file: Path, request_id: str, *extra: str) -> tuple[int, dict[str, Any]]:
        args = ["--project", str(art), "register", "scout", "--ledger", str(ledger_file)]
        code = main([*args, "--request-id", request_id, *extra])
        return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])

    return register


def calls(stub: Path) -> list[list[str]]:
    lines = (stub / "calls.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def ledger(tmp_path: Path, request_id: str, state: str = "fetched", suffix: str = ".png") -> Path:
    """A falkit ledger export with one call whose file was fetched beside it."""
    out = tmp_path / "fal"
    out.mkdir(exist_ok=True)
    data = png(64, 64, alpha=True) + request_id.encode()
    (out / f"{request_id}{suffix}").write_bytes(data)
    entry = {
        "endpoint": ENDPOINT,
        "request_id": request_id,
        "state": state,
        "usd_charged": 0.059,
        "input_sha256": "ab" * 32,
        "files": [
            {"path": f"{request_id}{suffix}", "bytes": len(data),
             "sha256": hashlib.sha256(data).hexdigest()},
        ],
        "cwd": str(out),
    }  # fmt: skip
    path = out / f"ledger-{request_id}.json"
    path.write_text(json.dumps({"contract_version": 1, "entries": [entry]}), encoding="utf-8")
    return path


class TestRegister:
    def test_first_call_creates_the_asset_and_a_version(
        self, art: Path, stub: Path, tmp_path: Path, run: Run
    ) -> None:
        code, out = run(
            ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", "--prompt", "a scout", *LICENSE
        )
        staged = "registry/staging/scout-a1b2/req1aaaa-01-req1aaaa-01.png"
        assert code == EXIT_OK
        assert out == {"cmd": "register", "ok": True, "asset": "scout-a1b2", "version": "v1",
                       "parent": None, "file": staged, "usd_charged": 0.059}  # fmt: skip
        assert (art / staged).read_bytes() == (tmp_path / "fal" / "req1aaaa-01.png").read_bytes()
        project = ["--project", str(art)]
        assert calls(stub) == [
            ["new", *project, "--family", "unit", "--kind", "image", "--title", "scout",
             "--tag", "brief:scout", *LICENSE],
            ["status", "scout-a1b2", *project],
            ["version", "add", "scout-a1b2", *project, "--file", staged, "--origin", "generated",
             "--digital-source-type", "trainedAlgorithmicMedia", "--provider", "fal",
             "--model", ENDPOINT, "--job-id", "req1aaaa-01", "--prompt", "a scout",
             "--param", "usd_charged=0.059", "--param", f"input_sha256={'ab' * 32}"],
        ]  # fmt: skip
        brief = json.loads((art / "art" / "briefs" / "scout.json").read_text())
        assert brief["asset"] == "scout-a1b2"

    def test_retake_names_its_parent_and_keeps_the_old_file(
        self, art: Path, stub: Path, tmp_path: Path, run: Run
    ) -> None:
        run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", *LICENSE)
        code, out = run(ledger(tmp_path, "req2bbbb-02"), "req2bbbb-02")
        assert (code, out["version"], out["parent"]) == (EXIT_OK, "v2", "v1")
        assert calls(stub)[-1][-6:-4] == ["--parent", "v1"]
        assert sorted(p.name for p in (art / "registry/staging/scout-a1b2").iterdir()) == [
            "req1aaaa-01-req1aaaa-01.png",
            "req2bbbb-02-req2bbbb-02.png",
        ]

    def test_retake_sharing_an_id_prefix_and_file_name_is_a_new_version(
        self, stub: Path, tmp_path: Path, run: Run
    ) -> None:
        """UUIDv7 ids of calls made within about a minute share their first eight characters."""
        first = ledger(tmp_path, "01a1dcf9-5c4c-7c70")
        run(first, "01a1dcf9-5c4c-7c70", *LICENSE)
        retake = json.loads(first.read_text())
        retake["entries"][0]["request_id"] = "01a1dcf9-0000-7c70"
        (tmp_path / "retake.json").write_text(json.dumps(retake), encoding="utf-8")
        code, out = run(tmp_path / "retake.json", "01a1dcf9-0000-7c70")
        assert (code, out["version"], out["parent"]) == (EXIT_OK, "v2", "v1")


class TestRefusals:
    @pytest.mark.parametrize(
        ("state", "asked", "detail"),
        [
            ("fetched", "nope", "request nope is not in"),
            ("failed", "req1aaaa-01", "request req1aaaa-01 is failed; nothing to register"),
        ],
    )
    def test_unknown_or_failed_request(
        self, stub: Path, tmp_path: Path, run: Run, state: str, asked: str, detail: str
    ) -> None:
        code, out = run(ledger(tmp_path, "req1aaaa-01", state), asked, *LICENSE)
        assert (code, out["reason"]) == (EXIT_REFUSED, "refused")
        assert detail in out["detail"]
        assert not (stub / "calls.jsonl").exists()

    def test_changed_file_is_refused(self, stub: Path, tmp_path: Path, run: Run) -> None:
        source = ledger(tmp_path, "req1aaaa-01")
        (tmp_path / "fal" / "req1aaaa-01.png").write_bytes(b"edited")
        assert "does not match the sha256" in run(source, "req1aaaa-01", *LICENSE)[1]["detail"]

    def test_brief_that_fails_lint_is_refused(
        self, art: Path, stub: Path, tmp_path: Path, run: Run
    ) -> None:
        add_brief(art, "scout", roots=["old-root"])
        out = run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", *LICENSE)[1]
        superseded = "root old-root is superseded; brief scout needs another"
        assert out["detail"] == f"brief scout fails lint first: {superseded}"

    def test_new_asset_needs_a_license(self, stub: Path, tmp_path: Path, run: Run) -> None:
        out = run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01")[1]
        assert out["detail"] == "brief scout has no asset yet; pass --license"

    def test_model_of_an_image_brief_is_refused(
        self, art: Path, stub: Path, tmp_path: Path, run: Run
    ) -> None:
        run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", *LICENSE)
        code, out = run(ledger(tmp_path, "req2bbbb-02", suffix=".glb"), "req2bbbb-02")
        assert (code, out["detail"]) == (
            EXIT_REFUSED,
            "brief scout's asset scout-a1b2 holds image files; a model needs a brief of its own",
        )
        assert [p.suffix for p in (art / "registry/staging/scout-a1b2").iterdir()] == [".png"]

    def test_same_request_twice(self, stub: Path, tmp_path: Path, run: Run) -> None:
        source = ledger(tmp_path, "req1aaaa-01")
        assert run(source, "req1aaaa-01", *LICENSE)[0] == EXIT_OK
        code, out = run(source, "req1aaaa-01")
        assert (code, out["detail"].split(" as ")[0]) == (
            EXIT_REFUSED,
            "request req1aaaa-01 is already registered",
        )


class TestAssetKitFailures:
    def test_refused_version_leaves_no_staged_file(
        self, art: Path, stub: Path, tmp_path: Path, run: Run, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("STUB_FAIL", "1")
        code, out = run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", *LICENSE)
        assert (code, out["reason"]) == (EXIT_FAILED, "tool_failed")
        assert list((art / "registry/staging/scout-a1b2").iterdir()) == []

    def test_missing_assetkit_is_a_setup_error(
        self, tmp_path: Path, run: Run, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ASSETKIT", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        code, out = run(ledger(tmp_path, "req1aaaa-01"), "req1aaaa-01", *LICENSE)
        assert (code, out["reason"]) == (EXIT_SETUP, "setup")
