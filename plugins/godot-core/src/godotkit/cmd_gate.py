"""`gate` writes a receipt; `receipt verify` checks the newest one against the tree."""

from __future__ import annotations

import argparse
import subprocess
from dataclasses import asdict

from godotkit.gaterun import Gate, GateRequest
from godotkit.output import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, EXIT_SETUP, emit
from godotkit.receipts import ReceiptStore, tree_hash
from godotkit.runner import GodotRunner
from godotkit.worktree import GitError


def gate(args: argparse.Namespace, runner: GodotRunner) -> int:
    project = args.project.resolve()
    try:
        receipt = Gate(runner, GateRequest(project, args.timeout, args.jobs)).run()
    except (ValueError, GitError) as error:
        emit({"cmd": "gate", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        emit({"cmd": "gate", "ok": False, "reason": "tool_failed", "detail": str(error)})
        return EXIT_SETUP
    path = ReceiptStore(project).write(receipt)
    failed = [step.name for step in receipt.steps if step.status == "fail"]
    emit(
        {
            "cmd": "gate",
            "ok": receipt.ok,
            "reason": "ok" if receipt.ok else "steps_failed",
            "failed": failed,
            "receipt": str(path),
            "tree": receipt.tree,
            "steps": [asdict(step) for step in receipt.steps],
        }
    )
    return EXIT_OK if receipt.ok else EXIT_FAILED


def receipt_verify(args: argparse.Namespace) -> int:
    project = args.project.resolve()
    try:
        latest = ReceiptStore(project).latest("gate")
        current = tree_hash(project)
    except GitError as error:
        emit({"cmd": "receipt verify", "ok": False, "reason": "refused", "detail": str(error)})
        return EXIT_REFUSED
    if latest is None:
        reason, path = "no_receipt", None
    else:
        path = latest[0]
        receipt = latest[1]
        reason = "stale" if receipt.tree != current else "ok" if receipt.ok else "gate_failed"
    emit(
        {
            "cmd": "receipt verify",
            "ok": reason == "ok",
            "reason": reason,
            "receipt": str(path) if path else None,
            "tree": current,
        }
    )
    return EXIT_OK if reason == "ok" else EXIT_FAILED
