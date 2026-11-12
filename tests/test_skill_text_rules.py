"""Text rules of the skill lint: isolated python3, listed placeholders, no literal run counts."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from skill_text_rules import (
    RULES_FILE,
    Hit,
    PluginRules,
    RulesFileError,
    fence_states,
    load_rules,
    outside_fences,
    placeholders_in,
    scan,
)


def fenced(*lines: str, info: str = "bash") -> list[str]:
    return [f"```{info}", *lines, "```"]


def line_numbers(hits: list[Hit]) -> list[int]:
    return [hit.line for hit in hits]


class TestFenceStates:
    @staticmethod
    def inside(lines: list[str]) -> list[str]:
        return [line for _, line, inside in fence_states(lines) if inside]

    def test_a_fence_hides_its_lines_and_its_markers_belong_to_neither_side(self) -> None:
        text = ["before", "```bash", "inside", "```", "after"]
        assert self.inside(text) == ["inside"]
        assert [line for _, line in outside_fences(text)] == ["before", "after"]

    @pytest.mark.parametrize(
        ("text", "inside"),
        [
            (["~~~", "a", "~~~", "b"], ["a"]),
            (["  ```text", "  a", "  ```", "b"], ["  a"]),
            (["```", "a", "```", "b", "```", "c", "```"], ["a", "c"]),
            (["```", "a", "b"], ["a", "b"]),
            (["````", "```", "a", "```", "````", "b"], ["```", "a", "```"]),
            (["`````", "a", "````", "b", "`````", "c"], ["a", "````", "b"]),
            (["```", "a", "````", "b"], ["a"]),
            (["```", "a", "```text", "b", "```"], ["a", "```text", "b"]),
            (["```", "a", "``", "b", "```"], ["a", "``", "b"]),
            (["~~~", "```", "a", "```", "~~~", "b"], ["```", "a", "```"]),
            (["```", "~~~", "a", "~~~", "```", "b"], ["~~~", "a", "~~~"]),
            ([], []),
        ],
        ids=[
            "tilde",
            "indented-in-a-list",
            "two-fences",
            "never-closed",
            "longer-fence-holds-a-shorter",
            "shorter-marker-does-not-close",
            "longer-marker-closes",
            "info-string-does-not-close",
            "two-backticks-are-not-a-fence",
            "backticks-inside-tildes",
            "tildes-inside-backticks",
            "empty",
        ],
    )
    def test_the_lines_inside_a_fence(self, text: list[str], inside: list[str]) -> None:
        assert self.inside(text) == inside

    def test_the_indexes_are_those_of_the_whole_list_even_from_a_later_start(self) -> None:
        text = ["x", "y", "```", "z", "```", "w"]
        assert list(fence_states(text, 1)) == [(1, "y", False), (3, "z", True), (5, "w", False)]

    def test_a_negative_start_is_refused(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            list(fence_states(["x"], -1))


GOOD_COMMANDS = [
    "python3 -I -m dramakit check",
    "python3 -P -m dramakit check",
    "python3 -B -P -m dramakit check",
    "python3 -BI -c 'print(1)'",
    "python3 -IB -m dramakit check",
    "python3 -I - <<'PY'",
    "PYTHONPATH=src python3 -P -m dramakit health",
    "/usr/bin/python3 -I tool.py",
    ".venv/bin/python3 -P tool.py",
    "python3.12 -P -m dramakit check",
    "python3 -W error -P -m dramakit check",
    "python3 -Werror -I -m dramakit check",
    "python3 -X dev -I -m dramakit check",
    "python3 --check-hash-based-pycs -P tool.py",
    "cd out && python3 -P tool.py",
    "python3 -P a.py && python3 -I b.py",
    "$(python3 -P -c 'print(1)')",
    "timeout 60 python3 -I tool.py",
    "python3 -P tool.py | python3 -I other.py",
    "echo no interpreter here",
]
BAD_COMMANDS = [
    "python3 -m dramakit check",
    "python3 tool.py",
    "python3 -c 'print(1)'",
    "python3",
    "which python3",
    "python3 -B -m dramakit check",
    "python3 -mP",
    "python3 -m dramakit -P",
    "python3 -c 'pass' -P",
    "python3 -c -P",
    "python3 -cP",
    "python3 - -P",
    "python3 tool.py -P",
    "python3 -W error -m dramakit check",
    "python3 -Werror tool.py",
    "python3 -- tool.py",
    "python3 - <<'PY'",
    "python3 -P a.py && python3 b.py",
    "python3 a.py && python3 -P b.py",
    "python3 tool.py   # python3 -P is meant",
    "/usr/bin/python3 tool.py",
    "python3.11 -m dramakit check",
    "PYTHONPATH=src python3 -m dramakit health",
    "timeout 60 python3 -m dramakit check",
    "(python3 tool.py)",
    "python3; echo done",
    "bash -c 'python3 tool.py'",
]
NOT_PYTHON3 = [
    "python3-dev",
    "mypython3 -m x",
    "python3x -m x",
    "python33 -m x",
    "python3_tool.py",
    "python3.pyc",
    "--python3",
    "x.python3",
    "pip3 install x",
    "python -m x",
]


class TestPythonIsolation:
    @pytest.mark.parametrize("command", GOOD_COMMANDS)
    def test_a_command_with_an_isolating_flag_passes(self, command: str) -> None:
        assert scan(fenced(command), []) == []

    @pytest.mark.parametrize("command", BAD_COMMANDS)
    def test_a_command_without_one_is_reported_on_its_line(self, command: str) -> None:
        hits = scan(["intro", *fenced(command)], [])
        assert line_numbers(hits) == [3]
        assert "python3 needs -I or -P" in hits[0].message

    @pytest.mark.parametrize("word", NOT_PYTHON3)
    def test_other_words_are_not_python3(self, word: str) -> None:
        assert scan(fenced(word), []) == []

    @pytest.mark.parametrize("line", ["# python3 -m dramakit check", "    # python3 tool.py"])
    def test_a_commented_out_command_runs_nothing(self, line: str) -> None:
        assert scan(fenced(line), []) == []

    @pytest.mark.parametrize(
        "line",
        [
            "Run `python3 -m dramakit check` first.",
            "python3 tool.py",
            "- python3 -m dramakit check",
            "> python3 -m dramakit check",
        ],
    )
    def test_text_outside_a_fence_is_not_checked(self, line: str) -> None:
        assert scan(["intro", line], []) == []

    @pytest.mark.parametrize(
        "text",
        [
            ["~~~", "python3 tool.py", "~~~"],
            ["  ```bash", "  python3 tool.py", "  ```"],
            ["````markdown", "```", "python3 tool.py", "```", "````"],
            ["```text", "$ python3 tool.py", "```"],
            ["```", "python3 tool.py"],
        ],
        ids=["tilde", "indented", "inside-a-longer-fence", "shell-prompt", "never-closed"],
    )
    def test_every_kind_of_fence_is_checked(self, text: list[str]) -> None:
        assert len(scan(text, [])) == 1

    def test_a_command_continued_with_a_backslash_is_read_as_one(self) -> None:
        assert scan(fenced("python3 \\", "  -P -m dramakit check"), []) == []

    def test_a_continued_command_without_a_flag_is_reported_on_its_first_line(self) -> None:
        text = ["", *fenced("python3 \\", "  -B \\", "  -m dramakit check")]
        assert line_numbers(scan(text, [])) == [3]

    def test_a_trailing_backslash_does_not_join_two_fences(self) -> None:
        text = [*fenced("python3 \\"), *fenced("-P -m dramakit check")]
        assert line_numbers(scan(text, [])) == [2]

    def test_a_line_with_two_calls_is_reported_once(self) -> None:
        assert line_numbers(scan(fenced("python3 a.py && python3 b.py"), [])) == [2]

    def test_each_offending_command_is_reported_on_its_own_line(self) -> None:
        text = fenced("python3 a.py", "python3 -P b.py", "python3 c.py")
        assert line_numbers(scan(text, [])) == [2, 4]


SLOTS = [
    "<slug>",
    "<n>",
    "<N>",
    "<12 hex>",
    "<...>",
    "<package>",
    "<the table of the judge, in full>",
    "<; judged by the writer, not independent>",
    '<its "checks: N ran" line>',
    "<character = voice_id, ...>",
    "<none | list>",
    "<G3+G4+G5 | G4+G5>",
    "<drama-bible | drama-script>",
]
NOT_SLOTS = [
    "cat <<'EOF'",
    "cat <<EOF",
    "cat <<EOF > out.txt",
    "cat <<'EOF' > out.txt",
    "cat <<-EOF",
    "cat <<< word",
    "sort < in.txt",
    "if a <= b",
    "if a <= b and c > d",
    "a < b and c > d",
    "<!-- note -->",
    "</speak>",
    '<break time="1s"/>',
    "<br/>",
    "x <(cmd) y",
    "echo a <> b",
    "a <- b",
    "a <- b -> c",
    "a <-- b",
    "a <-- b --> c",
    "<?xml version='1.0'?>",
    "<&0",
    "<3",
    "a<",
    "> centered <",
]


class TestPlaceholders:
    @pytest.mark.parametrize("slot", SLOTS)
    def test_a_slot_outside_the_list_is_reported_with_its_text(self, slot: str) -> None:
        hits = scan(["", *fenced(f"write {slot} here")], ["<other>"])
        assert line_numbers(hits) == [3]
        assert f"placeholder {slot} is not in the plugin's list" in hits[0].message

    @pytest.mark.parametrize("slot", SLOTS)
    def test_a_listed_slot_passes(self, slot: str) -> None:
        assert scan(fenced(f"write {slot} here"), [slot]) == []

    @pytest.mark.parametrize("text", NOT_SLOTS)
    def test_syntax_that_only_looks_like_a_slot_is_ignored(self, text: str) -> None:
        assert scan(fenced(text), []) == []

    def test_the_list_is_matched_exactly_and_by_case(self) -> None:
        assert line_numbers(scan(fenced("<N> and <n>"), ["<n>"])) == [2]

    def test_a_list_entry_is_not_a_prefix_match(self) -> None:
        assert line_numbers(scan(fenced("<slug-two>"), ["<slug>"])) == [2]

    def test_a_slot_repeated_on_a_line_is_reported_once(self) -> None:
        assert line_numbers(scan(fenced("cp <a> <b> <a>"), ["<b>"])) == [2]

    def test_different_unlisted_slots_of_one_line_are_reported_each(self) -> None:
        hits = scan(fenced("cp <a> <b>"), [])
        assert [hit.message.split()[1] for hit in hits] == ["<a>", "<b>"]

    def test_touching_slots_are_two_slots(self) -> None:
        assert len(scan(fenced("<a><b>"), [])) == 2

    @pytest.mark.parametrize("info", ["json", "text", "markdown", "yaml"])
    def test_a_slot_in_any_kind_of_fence_is_checked(self, info: str) -> None:
        assert len(scan(fenced('{"name": "<slug>"}', info=info), [])) == 1

    @pytest.mark.parametrize(
        "line",
        ["Write <slug> in prose.", "Write `<slug>` inline.", "| <slug> | the folder |"],
    )
    def test_a_slot_outside_a_fence_is_not_checked(self, line: str) -> None:
        assert scan(["intro", line], []) == []

    def test_an_empty_list_lets_no_slot_through(self) -> None:
        assert len(scan(fenced("<slug>"), [])) == 1

    def test_the_slots_of_a_file_are_those_of_its_fences(self) -> None:
        text = ["Prose <outside>.", *fenced("a <one> b <two>", "<one>"), "More <prose>."]
        assert placeholders_in(text) == {"<one>", "<two>"}

    def test_what_is_not_a_slot_is_not_collected(self) -> None:
        assert placeholders_in(fenced("cat <<EOF", "a <= b", "<br/>", "<!-- c -->")) == set()


BAD_COUNTS = [
    "57 ran",
    "5 skipped",
    "57 checks ran",
    "1 check skipped",
    "12  ran",
    "57\tran",
    "checks: 57 ran, 5 skipped, 13 left for later stages; --json lists them",
    "checks: 0 ran",
    "- the line reads checks: 12",
    '{"ran": 57}',
    '"skipped": 5',
    "Expect 57 ran in the summary.",
    "(0 skipped)",
    "- 57 ran",
    "run: 57 ran",
]
GOOD_COUNTS = [
    "no findings",
    "checks: all ran",
    "checks: none skipped",
    "checks:",
    "ran 57 checks",
    "the first rule ran",
    "4 findings: 1 error, 3 warnings, 0 info",
    "A4 ran",
    "7ran",
    "the 3rd rule ran",
    '"ran": true',
    "ran: yes",
    "skipped checks are named in the summary",
    "a list of 57 rules",
    "sixty ran",
    "PKG-007 skipped",
    "SCR-015 skipped until drama-audio",
    "SHT-009 ran",
    "R7 skipped",
]
KINDS = pytest.mark.parametrize("inside", [False, True], ids=["prose", "fence"])


def on_line_two(text: str, *, inside: bool) -> list[str]:
    return fenced(text) if inside else ["intro", text]


class TestRunCounts:
    @KINDS
    @pytest.mark.parametrize("text", BAD_COUNTS)
    def test_a_literal_count_is_reported_wherever_it_stands(self, text: str, inside: bool) -> None:
        hits = scan(on_line_two(text, inside=inside), [])
        assert line_numbers(hits) == [2]
        assert "literal run count" in hits[0].message

    @KINDS
    @pytest.mark.parametrize("text", GOOD_COUNTS)
    def test_a_property_of_the_output_passes(self, text: str, inside: bool) -> None:
        assert scan(on_line_two(text, inside=inside), []) == []

    @pytest.mark.parametrize(
        ("text", "quoted"),
        [
            ("It says 57 ran today.", '"57 ran"'),
            ("5 skipped", '"5 skipped"'),
            ("57 checks ran", '"57 checks ran"'),
            ("checks: 57 ran, 5 skipped", '"checks: 57"'),
            ('{"skipped": 5}', '"skipped": 5'),
        ],
    )
    def test_the_message_quotes_the_count(self, text: str, quoted: str) -> None:
        assert quoted in scan([text], [])[0].message

    def test_a_line_with_several_counts_is_reported_once(self) -> None:
        assert len(scan(["57 ran, 5 skipped, 13 skipped"], [])) == 1

    def test_the_frontmatter_is_read_too(self) -> None:
        assert line_numbers(scan(["---", "description: 57 ran", "---"], [])) == [2]


class TestScan:
    def test_hits_come_in_line_order_whatever_the_rule(self) -> None:
        text = ["57 ran", *fenced("python3 tool.py", "<slug>"), "5 skipped"]
        assert line_numbers(scan(text, [])) == [1, 3, 4, 6]

    def test_a_clean_file_has_no_hits(self) -> None:
        text = ["# Title", "", *fenced("python3 -P -m dramakit check", "<slug>"), "no findings"]
        assert scan(text, ["<slug>"]) == []

    def test_an_empty_file_has_no_hits(self) -> None:
        assert scan([], []) == []


def write_rules(root: Path, content: object, *plugins: str) -> None:
    for plugin in plugins or ("alpha",):
        (root / "plugins" / plugin).mkdir(parents=True, exist_ok=True)
    path = root / RULES_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def entry(**placeholders: str) -> dict[str, dict[str, str]]:
    return {"placeholders": {f"<{name}>": meaning for name, meaning in placeholders.items()}}


class TestLoadRules:
    def test_no_file_holds_no_plugin_to_the_rules(self, tmp_path: Path) -> None:
        assert load_rules(tmp_path) == {}

    def test_each_plugin_gets_its_own_list(self, tmp_path: Path) -> None:
        write_rules(tmp_path, {"alpha": entry(slug="the folder"), "beta": entry()}, "alpha", "beta")
        assert load_rules(tmp_path) == {
            "alpha": PluginRules({"<slug>": "the folder"}),
            "beta": PluginRules({}),
        }

    def test_an_empty_file_object_holds_no_plugin_to_the_rules(self, tmp_path: Path) -> None:
        write_rules(tmp_path, {})
        assert load_rules(tmp_path) == {}

    def test_a_prose_slot_may_be_listed(self, tmp_path: Path) -> None:
        slot = "<the table of the judge, in full>"
        write_rules(tmp_path, {"alpha": {"placeholders": {slot: "the judge's table"}}})
        assert set(load_rules(tmp_path)["alpha"].placeholders) == {slot}

    @pytest.mark.parametrize(
        ("content", "complaint"),
        [
            ("{", "is not usable JSON"),
            ("", "is not usable JSON"),
            ("[]", "top level must be an object"),
            ('"alpha"', "top level must be an object"),
            ('{"alpha": []}', "must be an object with the key 'placeholders'"),
            ('{"alpha": null}', "must be an object with the key 'placeholders'"),
            ('{"alpha": {}}', "needs 'placeholders' as an object"),
            ('{"alpha": {"placeholders": []}}', "needs 'placeholders' as an object"),
            ('{"alpha": {"placeholders": {}, "extra": 1}}', "has the unknown key 'extra'"),
            ('{"alpha": {"placeholders": {"slug": "x"}}}', "'slug' is not a placeholder"),
            ('{"alpha": {"placeholders": {"<>": "x"}}}', "'<>' is not a placeholder"),
            ('{"alpha": {"placeholders": {"<a><b>": "x"}}}', "'<a><b>' is not a placeholder"),
            ('{"alpha": {"placeholders": {"<br/>": "x"}}}', "'<br/>' is not a placeholder"),
            ('{"alpha": {"placeholders": {" <a>": "x"}}}', "' <a>' is not a placeholder"),
            ('{"alpha": {"placeholders": {"<a>": ""}}}', "<a> needs its meaning"),
            ('{"alpha": {"placeholders": {"<a>": "  "}}}', "<a> needs its meaning"),
            ('{"alpha": {"placeholders": {"<a>": 3}}}', "<a> needs its meaning"),
            ('{"alpha": {"placeholders": {"<a>": null}}}', "<a> needs its meaning"),
            ('{"ghost": {"placeholders": {}}}', "plugins/ghost does not exist"),
            ('{"alpha": {"placeholders": {}}, "alpha": {"placeholders": {}}}', "appears twice"),
            ('{"alpha": {"placeholders": {"<a>": "x", "<a>": "y"}}}', "'<a>' appears twice"),
        ],
    )
    def test_a_file_that_cannot_be_used_is_refused_with_the_reason(
        self, tmp_path: Path, content: str, complaint: str
    ) -> None:
        write_rules(tmp_path, content)
        with pytest.raises(RulesFileError, match=complaint):
            load_rules(tmp_path)

    def test_every_refusal_names_the_file(self, tmp_path: Path) -> None:
        write_rules(tmp_path, "[]")
        with pytest.raises(RulesFileError, match=re.escape(str(RULES_FILE))):
            load_rules(tmp_path)

    def test_bytes_that_are_not_utf8_are_refused(self, tmp_path: Path) -> None:
        write_rules(tmp_path, "{}")
        (tmp_path / RULES_FILE).write_bytes(b"\xff\xfe{}")
        with pytest.raises(RulesFileError, match="cannot be read"):
            load_rules(tmp_path)

    def test_a_folder_in_place_of_the_file_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / RULES_FILE).mkdir(parents=True)
        with pytest.raises(RulesFileError, match="cannot be read"):
            load_rules(tmp_path)

    def test_a_refusal_is_a_value_error_so_the_cli_can_report_it(self) -> None:
        assert issubclass(RulesFileError, ValueError)

    def test_a_root_that_is_not_a_folder_is_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="suite root is not a directory"):
            load_rules(tmp_path / "missing")
