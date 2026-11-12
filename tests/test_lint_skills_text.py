"""Skill lint: the text rules, emphasis, placeholders and shipped examples."""

from __future__ import annotations

import json
import re

import lint_skills
import pytest
from lint_skills import HARD_RULES, RULES_END, RULES_START, SkillDocument, SkillLinter
from lint_skills_rig import (
    AVOID,
    LEAD,
    REPO_ROOT,
    SkillSpec,
    SuiteBuilder,
    fenced,
    has_problem,
    line_of,
)
from skill_text_rules import fence_states


class TestRulesText:
    START = "---\nname: x\n---\n"

    @staticmethod
    def marked(rules: str) -> str:
        return f"{RULES_START}\n\n{rules}\n\n{RULES_END}\n"

    def test_the_block_is_written_in_the_form_mdformat_keeps(self) -> None:
        document = SkillDocument(self.START + "\n# Title\n\n## Overview\n")
        rules = "rule one\nrule two"
        expected = f"{self.START}\n# Title\n\n{self.marked(rules)}\n## Overview\n"
        assert document.with_block(HARD_RULES, rules + "\n") == expected

    def test_a_title_on_the_last_line_still_gets_the_block(self) -> None:
        document = SkillDocument(self.START + "# Title\n")
        assert (
            document.with_block(HARD_RULES, "rule")
            == f"{self.START}# Title\n\n{self.marked('rule')}"
        )

    def test_text_straight_after_the_title_is_kept_apart_from_the_block(self) -> None:
        document = SkillDocument(self.START + "# Title\nIntro.\n")
        expected = f"{self.START}# Title\n\n{self.marked('rule')}\nIntro.\n"
        assert document.with_block(HARD_RULES, "rule") == expected

    def test_a_marked_block_is_replaced_in_place(self) -> None:
        old = f"{RULES_START}\nold\n{RULES_END}\n"
        document = SkillDocument(f"{self.START}# Title\n\n{old}\n## Overview\n")
        expected = f"{self.START}# Title\n\n{self.marked('new')}\n## Overview\n"
        assert document.with_block(HARD_RULES, "new") == expected


BREACHES = [
    pytest.param(
        fenced("python3 -m dramakit check"),
        "python3 -m dramakit check",
        "python3 needs -I or -P",
        id="python3",
    ),
    pytest.param(
        fenced("write <unlisted> here"),
        "write <unlisted> here",
        "placeholder <unlisted> is not in the plugin's list",
        id="placeholder",
    ),
    pytest.param(
        ["The summary says 57 ran."],
        "The summary says 57 ran.",
        'literal run count "57 ran"',
        id="run-count",
    ),
]
STALE = "tools/skill_rules.json: plugin 'alpha' lists <old>, which none of its fenced blocks use"


class TestTextRules:
    @pytest.mark.parametrize(("body", "offender", "message"), BREACHES)
    def test_without_a_rules_file_no_plugin_is_held_to_the_rules(
        self, suite: SuiteBuilder, body: list[str], offender: str, message: str
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": body}))
        assert suite.problems() == []

    @pytest.mark.parametrize(("body", "offender", "message"), BREACHES)
    def test_a_plugin_missing_from_the_rules_file_is_not_held_to_them(
        self, suite: SuiteBuilder, body: list[str], offender: str, message: str
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": body}))
        suite.text_rules("beta")
        assert suite.problems() == []

    @pytest.mark.parametrize(("body", "offender", "message"), BREACHES)
    def test_a_listed_plugin_is_held_to_each_rule_and_the_line_is_named(
        self, suite: SuiteBuilder, body: list[str], offender: str, message: str
    ) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": body}))
        suite.text_rules("alpha")
        line = line_of(suite.skill_file(folder), offender)
        (problem,) = suite.problems()
        assert problem.startswith(f"plugins/alpha/skills/demo/SKILL.md: line {line}: {message}")

    @pytest.mark.parametrize(("body", "offender", "message"), BREACHES)
    def test_a_reference_is_held_to_them_and_named_in_the_problem(
        self, suite: SuiteBuilder, body: list[str], offender: str, message: str
    ) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See references/steps.md."]}))
        suite.reference(folder, "steps.md", text="\n".join(["Intro.", *body]) + "\n")
        suite.text_rules("alpha")
        line = line_of(folder / "references" / "steps.md", offender)
        (problem,) = suite.problems()
        assert problem.startswith(
            f"plugins/alpha/skills/demo/SKILL.md: references/steps.md line {line}: {message}"
        )

    def test_a_skill_that_follows_the_rules_passes(self, suite: SuiteBuilder) -> None:
        body = ["See references/steps.md.", *fenced("python3 -P -m dramakit check <slug>")]
        folder = suite.skill(spec=SkillSpec(body={"Techniques": body}))
        steps = [*fenced("python3 -I tool.py <slug>"), "No findings."]
        suite.reference(folder, "steps.md", text="\n".join(steps) + "\n")
        suite.text_rules("alpha", placeholders={"<slug>": "the folder name"})
        assert suite.problems() == []

    def test_only_the_listed_plugins_are_held_to_the_rules(self, suite: SuiteBuilder) -> None:
        body = {"Techniques": fenced("python3 tool.py")}
        suite.skill("one", plugin="alpha", spec=SkillSpec(name="one", body=body))
        suite.skill("two", plugin="beta", spec=SkillSpec(name="two", body=body))
        suite.text_rules("alpha")
        (problem,) = suite.problems()
        assert problem.startswith("plugins/alpha/skills/one/SKILL.md: line ")

    def test_every_skill_of_a_listed_plugin_is_checked(self, suite: SuiteBuilder) -> None:
        body = {"Techniques": fenced("python3 tool.py")}
        suite.skill("one", spec=SkillSpec(name="one", body=body))
        suite.skill("two", spec=SkillSpec(name="two", body=body))
        suite.text_rules("alpha")
        assert len(suite.problems()) == 2

    def test_each_plugin_keeps_its_own_list_of_placeholders(self, suite: SuiteBuilder) -> None:
        body = {"Techniques": fenced("cp <slug> here")}
        suite.skill("one", plugin="alpha", spec=SkillSpec(name="one", body=body))
        suite.skill("two", plugin="beta", spec=SkillSpec(name="two", body=body))
        suite.rules_file(
            json.dumps(
                {
                    "alpha": {"placeholders": {"<slug>": "the folder name"}},
                    "beta": {"placeholders": {}},
                }
            )
        )
        (problem,) = suite.problems()
        assert problem.startswith("plugins/beta/skills/two/SKILL.md: line ")

    def test_a_named_folder_limits_the_report_to_that_skill(self, suite: SuiteBuilder) -> None:
        suite.skill("bad", spec=SkillSpec(name="bad", body={"Techniques": fenced("python3 x.py")}))
        good = suite.skill("good")
        suite.text_rules("alpha")
        assert suite.problems(good) == []

    def test_fix_leaves_a_breach_for_the_author(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": fenced("python3 tool.py")}))
        suite.rules()
        suite.text_rules("alpha")
        SkillLinter(suite.root).fix()
        assert "python3 tool.py" in suite.skill_file(folder).read_text()
        assert has_problem(suite.problems(), "python3 needs -I or -P")


class TestEmphasis:
    SHOUT = "Back up first. NEVER skip it."
    MESSAGE = "emphasis caps 'NEVER': write it in lower case and give the reason"

    def test_every_plugin_is_held_to_it_without_a_rules_file(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(plugin="beta", spec=SkillSpec(body={"Techniques": [self.SHOUT]}))
        line = line_of(suite.skill_file(folder), self.SHOUT)

        assert suite.problems() == [
            f"plugins/beta/skills/demo/SKILL.md: line {line}: {self.MESSAGE}"
        ]

    def test_a_reference_is_named_with_its_line(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See references/steps.md."]}))
        suite.reference(folder, "steps.md", text=f"# Steps\n\n{self.SHOUT}\n")

        assert suite.problems() == [
            f"plugins/alpha/skills/demo/SKILL.md: references/steps.md line 3: {self.MESSAGE}"
        ]

    def test_the_description_is_left_to_its_own_lint(self, suite: SuiteBuilder) -> None:
        shouting = f"{LEAD} a test needs a valid skill and NEVER a bad one. {AVOID}"
        suite.skill(spec=SkillSpec(description=shouting))

        assert suite.problems() == []

    def test_lower_case_with_a_reason_passes(self, suite: SuiteBuilder) -> None:
        calm = "Back up first: **never** skip it, since a write cannot be undone."
        suite.skill(spec=SkillSpec(body={"Techniques": [calm]}))

        assert suite.problems() == []


class TestStalePlaceholders:
    def test_an_entry_no_fenced_block_uses_is_reported_against_the_rules_file(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill()
        suite.text_rules("alpha", placeholders={"<old>": "gone"})
        assert suite.problems() == [STALE]

    def test_an_entry_used_in_a_fence_of_a_skill_is_kept(self, suite: SuiteBuilder) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": fenced("cp <old> here")}))
        suite.text_rules("alpha", placeholders={"<old>": "in use"})
        assert suite.problems() == []

    def test_an_entry_used_in_a_fence_of_a_reference_is_kept(self, suite: SuiteBuilder) -> None:
        folder = suite.skill(spec=SkillSpec(body={"Techniques": ["See references/steps.md."]}))
        suite.reference(folder, "steps.md", text="\n".join(fenced("cp <old> here")) + "\n")
        suite.text_rules("alpha", placeholders={"<old>": "in use"})
        assert suite.problems() == []

    @pytest.mark.parametrize("prose", ["Write <old> in the text.", "Write `<old>` inline."])
    def test_an_entry_used_only_outside_fences_is_stale(
        self, suite: SuiteBuilder, prose: str
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": [prose]}))
        suite.text_rules("alpha", placeholders={"<old>": "prose only"})
        assert suite.problems() == [STALE]

    def test_the_skills_of_another_plugin_do_not_keep_an_entry_alive(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill("one", plugin="alpha")
        body = {"Techniques": fenced("cp <old> here")}
        suite.skill("two", plugin="beta", spec=SkillSpec(name="two", body=body))
        suite.text_rules("alpha", placeholders={"<old>": "elsewhere"})
        assert suite.problems() == [STALE]

    def test_a_run_limited_to_named_skills_does_not_judge_the_list(
        self, suite: SuiteBuilder
    ) -> None:
        folder = suite.skill()
        suite.text_rules("alpha", placeholders={"<old>": "gone"})
        assert suite.problems(folder) == []

    def test_a_listed_plugin_without_skills_reports_every_entry_in_order(
        self, suite: SuiteBuilder
    ) -> None:
        suite.text_rules("alpha", placeholders={"<b>": "second", "<a>": "first"})
        assert [problem.split(" lists ")[1].split(",")[0] for problem in suite.problems()] == [
            "<a>",
            "<b>",
        ]

    def test_an_unlisted_slot_and_a_stale_entry_are_both_reported(
        self, suite: SuiteBuilder
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": fenced("cp <new> here")}))
        suite.text_rules("alpha", placeholders={"<old>": "gone"})
        problems = suite.problems()
        assert has_problem(problems, "placeholder <new> is not in the plugin's list")
        assert STALE in problems


class TestRulesFile:
    def test_a_broken_file_stops_the_run_before_any_skill_is_judged(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill(spec=SkillSpec(name="wrong"))
        suite.rules_file("{")
        assert lint_skills.main(["--root", str(suite.root)]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert captured.err.startswith("lint_skills: tools/skill_rules.json is not usable JSON")
        assert "skill lint:" not in captured.err

    def test_a_broken_file_also_stops_a_fix_run(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = suite.skill()
        suite.rules()
        suite.rules_file('{"ghost": {"placeholders": {}}}')
        before = suite.skill_file(folder).read_text()
        assert lint_skills.main(["--fix", "--root", str(suite.root)]) == 2
        assert "plugins/ghost does not exist" in capsys.readouterr().err
        assert suite.skill_file(folder).read_text() == before

    def test_the_constructor_refuses_a_broken_file(self, suite: SuiteBuilder) -> None:
        suite.rules_file("[]")
        with pytest.raises(ValueError, match="top level must be an object"):
            SkillLinter(suite.root)

    def test_a_breach_exits_one_and_is_listed_on_stderr(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": fenced("python3 tool.py")}))
        suite.text_rules("alpha")
        assert lint_skills.main(["--root", str(suite.root)]) == 1
        assert "skill lint: plugins/alpha/skills/demo/SKILL.md: line " in capsys.readouterr().err

    def test_a_listed_suite_that_follows_the_rules_exits_zero_in_silence(
        self, suite: SuiteBuilder, capsys: pytest.CaptureFixture[str]
    ) -> None:
        suite.skill(spec=SkillSpec(body={"Techniques": fenced("python3 -P tool.py <slug>")}))
        suite.text_rules("alpha", placeholders={"<slug>": "the folder name"})
        assert lint_skills.main(["--root", str(suite.root)]) == 0
        assert capsys.readouterr() == ("", "")


class TestShellTrapsInShippedExamples:
    """The harness refuses a foreground sleep; zsh runs a line that starts with == as a command."""

    @staticmethod
    def shell_lines() -> list[str]:
        found = []
        for path in sorted(REPO_ROOT.glob("plugins/*/skills/**/*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            found += [
                f"{path.relative_to(REPO_ROOT)}:{index + 1}: {line.strip()}"
                for index, line, inside in fence_states(lines)
                if inside and re.match(r"\s*(==|sleep\b|echo\s+['\"]?=)", line)
            ]
        return found

    def test_no_example_starts_a_line_with_a_separator_or_a_sleep(self) -> None:
        # A background timer is `command: sleep N` beside run_in_background, not a line of its own.
        assert self.shell_lines() == []
