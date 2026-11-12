"""The log judge decides pass or fail from Godot's output, not from its exit code."""

from __future__ import annotations

import re

import pytest
from godotkit.logjudge import LogJudge

SUMMARY = re.compile(r"(?P<checks>\d+) checks, (?P<failures>\d+) failures")

NULL_CALL_LOG = """Godot Engine v4.7.2.stable.official.ed1daf0bf - https://godotengine.org

SCRIPT ERROR: Cannot call method 'call' on a null value.
          at: _ready (res://main.gd:5)
"""

PARSE_LOG = """SCRIPT ERROR: Parse Error: Unexpected "Indent" in class body.
          at: GDScript::reload (res://main.gd:4)
ERROR: Failed to load script "res://main.gd" with error "Parse error".
   at: load (modules/gdscript/gdscript_resource_format.cpp:46)
"""


class TestFailures:
    def test_script_error_with_exit_zero_fails(self) -> None:
        verdict = LogJudge().judge(NULL_CALL_LOG, exit_code=0, timed_out=False)
        assert not verdict.ok
        assert verdict.reason == "script_error"
        assert verdict.issues[0].location == "_ready (res://main.gd:5)"

    def test_parse_error_outranks_the_engine_error_it_causes(self) -> None:
        verdict = LogJudge().judge(PARSE_LOG, exit_code=0, timed_out=False)
        assert verdict.reason == "parse_error"
        assert verdict.counts == {"parse_error": 1, "engine_error": 1}

    @pytest.mark.parametrize(
        "line",
        [
            "WARNING: 1 ObjectDB instance was leaked at exit (run with `--verbose` for details).",
            "WARNING: 3 ObjectDB instances were leaked at exit (run with `--verbose` for details).",
            "ERROR: 2 resources still in use at exit (run with --verbose for details).",
        ],
    )
    def test_leak_at_exit_fails_even_as_a_warning(self, line: str) -> None:
        verdict = LogJudge().judge(line + "\n", exit_code=0, timed_out=False)
        assert verdict.reason == "leak"
        assert verdict.warnings == 0

    def test_timeout_outranks_everything(self) -> None:
        verdict = LogJudge().judge(NULL_CALL_LOG, exit_code=None, timed_out=True)
        assert verdict.reason == "timeout"

    def test_crash_outranks_exit_code(self) -> None:
        log = "Program crashed with signal 11\n"
        assert LogJudge().judge(log, exit_code=139, timed_out=False).reason == "crash"

    def test_nonzero_exit_with_clean_log_fails(self) -> None:
        assert LogJudge().judge("", exit_code=1, timed_out=False).reason == "exit_code"


class TestSummary:
    def test_missing_summary_fails(self) -> None:
        verdict = LogJudge(SUMMARY).judge("all quiet\n", exit_code=0, timed_out=False)
        assert verdict.reason == "missing_summary"

    @pytest.mark.parametrize(
        ("line", "reason"),
        [
            ("Cards: 0 checks, 0 failures.", "zero_checks"),
            ("Cards: 12 checks, 2 failures.", "test_failures"),
            ("Cards: 12 checks, 0 failures.", "ok"),
        ],
    )
    def test_summary_values_decide(self, line: str, reason: str) -> None:
        verdict = LogJudge(SUMMARY).judge(line + "\n", exit_code=0, timed_out=False)
        assert verdict.reason == reason

    def test_last_summary_wins(self) -> None:
        log = "A: 5 checks, 0 failures.\nB: 7 checks, 1 failures.\n"
        verdict = LogJudge(SUMMARY).judge(log, exit_code=0, timed_out=False)
        assert verdict.summary == {"checks": 7, "failures": 1}

    def test_pattern_without_groups_is_refused(self) -> None:
        with pytest.raises(ValueError, match="named groups"):
            LogJudge(re.compile(r"\d+ checks"))


class TestNoise:
    def test_plain_warnings_are_counted_not_failed(self) -> None:
        log = "WARNING: Shader cache miss\nWARNING: Another one\n"
        verdict = LogJudge().judge(log, exit_code=0, timed_out=False)
        assert verdict.ok
        assert verdict.warnings == 2

    def test_allowed_pattern_is_ignored(self) -> None:
        judge = LogJudge(allow=[re.compile(r"known flaky driver")])
        verdict = judge.judge("ERROR: known flaky driver message\n", exit_code=0, timed_out=False)
        assert verdict.ok
