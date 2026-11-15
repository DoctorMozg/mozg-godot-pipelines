"""Image headers, .import parsing, the per-folder policy and the VRAM estimate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from artkit.audit import ImportAudit, load_defaults, read_import
from artkit.cli import EXIT_FAILED, EXIT_OK, EXIT_REFUSED, main
from artkit.policy import Policy, load_policy
from imagebytes import png

DEFAULTS = load_defaults()


def write_texture(project: Path, source: str, data: bytes, **params: object) -> None:
    """The source file and an .import laid out as Godot 4.7.2 writes it."""
    path = project / source
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    values = {"compress/mode": 0, "compress/high_quality": "false", "mipmaps/generate": "false"}
    values |= {"process/size_limit": 0} | {k.replace("__", "/"): v for k, v in params.items()}
    lines = [
        "[remap]",
        "",
        f'importer="{values.pop("importer", "texture")}"',
        'metadata={\n"vram_texture": false\n}',
        "",
        "[deps]",
        "",
        f'source_file="res://{source}"',
        "",
        "[params]",
        "",
        *(f"{key}={str(value).lower()}" for key, value in values.items()),
    ]
    path.with_name(path.name + ".import").write_text("\n".join(lines) + "\n", encoding="utf-8")


def set_policy(project: Path, policy: dict[str, object]) -> None:
    (project / "art").mkdir(exist_ok=True)
    (project / "art" / "policy.json").write_text(json.dumps(policy), encoding="utf-8")


def audit(project: Path) -> list[tuple[str, str]]:
    report = ImportAudit(project, load_policy(project), DEFAULTS).run()
    return [(f.file, f.rule) for f in report.problems]


class TestImportFile:
    def test_reads_params_and_skips_metadata(self, project: Path) -> None:
        write_texture(project, "a.png", png(4, 4), compress__mode=2, mipmaps__generate="true")
        values = read_import(project / "a.png.import")
        assert values["importer"] == "texture"
        assert values["source_file"] == "res://a.png"
        assert (values["compress/mode"], values["mipmaps/generate"]) == ("2", "true")
        assert "metadata" in values
        assert '"vram_texture": false' not in values.values()


class TestVram:
    @pytest.mark.parametrize(
        ("params", "alpha", "expected"),
        [
            ({"compress__mode": 2}, False, 32768),
            ({"compress__mode": 2}, True, 65536),
            ({"compress__mode": 2, "compress__high_quality": "true"}, False, 65536),
            ({"compress__mode": 3}, False, 196608),
            ({"compress__mode": 0}, True, 262144),
            ({"compress__mode": 2, "mipmaps__generate": "true"}, False, 32768 * 1.334),
            ({"compress__mode": 3, "process__size_limit": 128}, True, 65536),
        ],
    )
    def test_matches_the_measured_ctex_payloads(
        self, project: Path, params: dict[str, object], alpha: bool, expected: float
    ) -> None:
        write_texture(project, "t.png", png(256, 256, alpha=alpha), **params)
        report = ImportAudit(project, Policy(), DEFAULTS).run()
        assert report.textures[0][1] == pytest.approx(expected)


POLICY_RULES = (
    {"glob": "models/*", "mipmaps": True, "compress_modes": [2]},
    {"glob": "pixel/*", "mipmaps": False, "compress_modes": [0]},
    {"glob": "cards/*", "max_texture_mb": 4},
)


class TestPolicy:
    def test_each_rule_reports_its_own_finding(self, project: Path) -> None:
        set_policy(project, {"rules": list(POLICY_RULES)})
        write_texture(project, "models/crate.png", png(512, 512), compress__mode=2)
        write_texture(project, "pixel/hero.png", png(32, 32), mipmaps__generate="true")
        write_texture(project, "cards/scout.png", png(1696, 2528, alpha=True))
        write_texture(project, "models/barrel.png", png(512, 512), compress__mode=0,
                      mipmaps__generate="true")  # fmt: skip
        assert audit(project) == [
            ("cards/scout.png", "texture_vram"),
            ("models/barrel.png", "compress_mode"),
            ("models/crate.png", "mipmaps"),
            ("pixel/hero.png", "mipmaps"),
        ]

    def test_mobile_target_limits_the_longest_side(self, project: Path) -> None:
        set_policy(project, {"target": "mobile"})
        write_texture(project, "sky.png", png(5000, 100))
        write_texture(project, "limited.png", png(5000, 100), process__size_limit=2048)
        assert audit(project) == [("sky.png", "max_px")]

    def test_total_over_budget(self, project: Path) -> None:
        set_policy(project, {"vram_budget_mb": 1})
        write_texture(project, "a.png", png(1024, 1024))
        assert audit(project) == [("art/policy.json", "vram_budget")]

    def test_missing_source_and_other_importers(self, project: Path) -> None:
        write_texture(project, "gone.png", png(4, 4))
        (project / "gone.png").unlink()
        write_texture(project, "font.ttf", b"\0", importer="font_data_dynamic")
        assert audit(project) == [("gone.png", "missing_source")]


class TestAuditCli:
    def test_reports_totals_and_largest(
        self, project: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        write_texture(project, "a.png", png(1024, 1024, alpha=True))
        write_texture(project, "icon.svg", b"<svg/>")
        assert main(["--project", str(project), "audit"]) == EXIT_OK
        out = json.loads(capsys.readouterr().out)
        assert (out["textures"], out["vram_mb"], out["skipped"]) == (1, 4.0, ["icon.svg"])
        assert out["largest"] == [{"file": "a.png", "mb": 4.0}]

    def test_problems_fail_and_bad_policy_refuses(self, project: Path) -> None:
        set_policy(project, {"vram_budget_mb": 1})
        write_texture(project, "a.png", png(1024, 1024))
        assert main(["--project", str(project), "audit"]) == EXIT_FAILED
        set_policy(project, {"target": "console"})
        assert main(["--project", str(project), "audit"]) == EXIT_REFUSED
