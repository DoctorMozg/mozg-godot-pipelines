"""godotkit lint: architecture rules on GDScript text, member order, file selection and CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from godotkit.gates import GD_DIR
from godotkit.lint import ScriptLinter, project_sources
from godotkit_rig import HEALTHY_SCRIPT, CliRunner, FakeGodotFactory, ProjectFactory


def _rules(body: str) -> list[str]:
    source = "extends Node\n\n\nfunc _ready() -> void:\n" + body
    return [finding.rule for finding in ScriptLinter().lint_text(source, "x.gd")]


def _order(source: str) -> list[str]:
    return [finding.message for finding in ScriptLinter().lint_text(source, "x.gd")]


class TestStatementRules:
    @pytest.mark.parametrize(
        ("body", "rule"),
        [
            ("\tget_parent().hide()\n", "get-parent"),
            ('\tvar hud: Node = get_node("../../HUD")\n', "parent-path"),
            ('\tvar hud: Node = $"../HUD"\n', "parent-path"),
            ('\tvar path: NodePath = ^".."\n', "parent-path"),
            ('\tbutton.connect("pressed", _on_pressed)\n', "string-signal"),
            ('\temit_signal(&"died")\n', "string-signal"),
            ("\tchild.free()\n", "bare-free"),
            ("\tawait get_tree().create_timer(1.0).timeout\n", "timer-ignores-pause"),
            ("\tawait get_tree().create_timer(1.0, true).timeout\n", "timer-ignores-pause"),
            ("\tmesh.material_override = base_mat.duplicate()\n", "material-duplicate"),
            ("\tvar m: Material = get_material().duplicate(true)\n", "material-duplicate"),
        ],
    )
    def test_violation_is_reported(self, body: str, rule: str) -> None:
        assert _rules(body) == [rule]

    @pytest.mark.parametrize(
        "body",
        [
            "\tbutton.pressed.connect(_on_pressed)\n",
            "\tdied.emit()\n",
            "\tchild.queue_free()\n",
            '\tvar sprite: Node = get_node("Body/Sprite")\n',
            '\tvar label: Node = $"%Score"\n',
            '\tprint("get_parent() is only text")\n',
            "\t# Freed now: the pool reuses its name this frame.\n\tchild.free()\n",
            "\tchild.free()  # freed now, before the reload\n",
            "\tawait get_tree().create_timer(maxf(delay, 0.1), false).timeout\n",
            "\tvar copy: Dictionary = format.duplicate()\n",
            "\t# One copy for the whole board, made once.\n\tshared = material.duplicate()\n",
        ],
    )
    def test_clean_code_passes(self, body: str) -> None:
        assert _rules(body) == []

    def test_ignore_mark_silences_named_rule_only(self) -> None:
        body = "\t# godotkit:ignore=timer-ignores-pause UI clock runs while paused\n"
        body += "\tawait get_tree().create_timer(1.0).timeout\n\tget_parent().hide()\n"
        assert _rules(body) == ["get-parent"]

    @pytest.mark.parametrize(
        "body",
        [
            # gdformat moves the trailing comment of the last operand behind the closing bracket.
            '\tvar hud: Node = get_node(\n\t\t"../HUD"\n\t)  # godotkit:ignore=parent-path\n',
            '\tvar hud: Node = get_node(  # godotkit:ignore=parent-path\n\t\t"../HUD"\n\t)\n',
            '\tvar hud: Node = get_node(\n\t\t"../HUD",  # godotkit:ignore=parent-path\n\t)\n',
            '\t# godotkit:ignore=parent-path\n\tvar hud: Node = get_node(\n\t\t"../HUD"\n\t)\n',
        ],
    )
    def test_ignore_mark_anywhere_in_the_statement_covers_a_finding_in_it(self, body: str) -> None:
        assert _rules(body) == []

    def test_ignore_mark_does_not_leak_to_other_statements_or_rules(self) -> None:
        body = '\tvar hud: Node = get_node(\n\t\t"../HUD"\n\t)  # godotkit:ignore=get-parent\n'
        body += "\tget_parent().hide()\n"
        assert _rules(body) == ["parent-path", "get-parent"]
        later = "\tvar a: int = 1  # godotkit:ignore=get-parent\n\tget_parent().hide()\n"
        assert _rules(later) == ["get-parent"]

    @pytest.mark.parametrize(
        "body",
        [
            # gdformat 4.5 moved the reason after the group's `)` (AloneGodot, 2026-11-17).
            "\tmesh.material_override = (\n\t\tbase_mat.duplicate()\n\t)  # tinted per spawn\n",
            "\tqueue.append(\n\t\tchild.free()\n\t)  # freed now: the pool reuses its id\n",
            "\t# The pool reuses its id.\n\tchild.free()\n",
        ],
    )
    def test_reason_after_the_group_close_counts(self, body: str) -> None:
        assert _rules(body) == []

    def test_finding_in_a_multiline_lambda_names_its_own_line(self) -> None:
        source = (
            "extends Node\n\n\nfunc _ready() -> void:\n\tbutton.pressed.connect(\n"
            "\t\tfunc() -> void:\n\t\t\t# Plays the click first.\n\t\t\tplay()\n"
            "\t\t\tawait get_tree().create_timer(\n\t\t\t\t1.0, true).timeout\n"
            "\t\t\tchild.free()\n\t)\n"
        )
        findings = ScriptLinter().lint_text(source, "x.gd")
        assert [(finding.rule, finding.line) for finding in findings] == [
            ("bare-free", 11),
            ("timer-ignores-pause", 9),
        ]


class TestMemberOrder:
    def test_official_order_passes(self) -> None:
        source = (
            "@tool\nclass_name Door\nextends Node\n## A door.\n\nsignal opened\n"
            "enum State { SHUT, OPEN }\nconst SPEED := 2.0\nstatic var count: int = 0\n"
            '@export_group("Tuning")\n@export var width: float = 1.0\nvar state: State\n'
            "var _timer: float = [\n\t0.0,\n][0]\n@onready var body: Node = $Body\n\n\n"
            "func _ready() -> void:\n\tvar late: int = 1\n\tprint(late)\n"
        )
        assert _order(source) == []

    @pytest.mark.parametrize(
        "source",
        [
            "class_name Door extends Node\nsignal opened\n",
            "extends Node\n\n\nclass Inner:\n\tvar x: int\n\n\nvar a: int\n",
            "extends Node\nclass One: pass\nsignal hit\n",
            '@icon("res://i.svg")\nextends Node\n@warning_ignore("x")\nconst A := 1\n',
        ],
    )
    def test_gdlint_accepts_it_so_godotkit_does(self, source: str) -> None:
        assert _order(source) == []

    def test_inner_class_members_are_ordered_too(self) -> None:
        source = (
            "extends Node\nvar a: int\n\n\nclass Inner:\n\tvar x: int\n\tsignal hit\n\n\n"
            "\tfunc f() -> void:\n\t\tvar late: int = 1\n\t\tprint(late)\n\n\nconst B := 2\n"
        )
        assert _order(source) == ["signal after public var", "const after public var"]

    @pytest.mark.parametrize(
        ("source", "message"),
        [
            ("extends Node\nvar a: int\nsignal hit\n", "signal after public var"),
            ("extends Node\n@onready var b: Node = $B\nvar a: int\n", "public var after @onready"),
            ("extends Node\nvar _a: int\nvar b: int\n", "public var after private var"),
            ("extends Node\nfunc f() -> void:\n\tpass\nconst X := 1\n", "const after method"),
        ],
    )
    def test_out_of_order_member_is_named(self, source: str, message: str) -> None:
        assert any(found.startswith(message) for found in _order(source))


class TestProjectScripts:
    def test_skips_addons_hidden_and_gdignore_folders(self, tmp_path: Path) -> None:
        for relative in ("a.gd", "src/b.gd", "addons/x/c.gd", ".godot/d.gd", "raw/e.gd"):
            (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
            (tmp_path / relative).write_text("extends Node\n")
        (tmp_path / "raw" / ".gdignore").write_text("")
        found = [
            path.relative_to(tmp_path).as_posix() for path in project_sources(tmp_path, (".gd",))
        ]
        assert found == ["a.gd", "src/b.gd"]

    def test_godotkit_probe_scripts_follow_the_rules(self) -> None:
        assert ScriptLinter().lint_files(GD_DIR, project_sources(GD_DIR, (".gd",))) == []


@pytest.mark.usefixtures("no_gdtoolkit")
class TestLintCli:
    def test_findings_fail_with_path_and_line(
        self, make_project: ProjectFactory, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        project = make_project("extends Node\n\n\nfunc _ready() -> void:\n\tget_parent().hide()\n")
        code, payload = run_cli(["lint", "--project", str(project)], fake_godot())
        assert (code, payload["reason"], payload["counts"]) == (1, "violations", {"get-parent": 1})
        assert payload["findings"] == [
            {
                "path": "main.gd",
                "line": 5,
                "rule": "get-parent",
                "message": "get_parent() couples a node to its parent; signal up instead",
            }
        ]

    def test_clean_file_passes(
        self, make_project: ProjectFactory, run_cli: CliRunner, fake_godot: FakeGodotFactory
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        code, payload = run_cli(
            ["lint", str(project / "main.gd"), "--project", str(project)], fake_godot()
        )
        assert (code, payload["ok"], payload["files"]) == (0, True, 1)

    def test_path_outside_project_is_refused(
        self,
        make_project: ProjectFactory,
        tmp_path: Path,
        run_cli: CliRunner,
        fake_godot: FakeGodotFactory,
    ) -> None:
        project = make_project(HEALTHY_SCRIPT)
        code, payload = run_cli(["lint", str(tmp_path), "--project", str(project)], fake_godot())
        assert (code, payload["reason"]) == (3, "refused")
