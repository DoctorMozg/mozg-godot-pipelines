"""Texture import audit: .import settings against art/policy.json, and estimated VRAM."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from artkit.images import ImageError, ImageInfo, read_info
from artkit.policy import POLICY_FILE, Policy
from artkit.records import Finding

log = logging.getLogger(__name__)

DEFAULTS_FILE = Path(__file__).resolve().parents[2] / "data" / "import_defaults.json"
VRAM_MODES = (2, 4)
MB = 1024 * 1024
_LINE = re.compile(r"^([\w/]+)=(.*)$")


@dataclass(frozen=True)
class Texture:
    source: str
    info: ImageInfo
    mode: int
    mipmaps: bool
    high_quality: bool
    size_limit: int

    def size(self) -> tuple[int, int]:
        """Pixels after process/size_limit, which shrinks the longer side and keeps the aspect."""
        width, height = self.info.width, self.info.height
        longest = max(width, height)
        if self.size_limit <= 0 or longest <= self.size_limit:
            return width, height
        scale = self.size_limit / longest
        return max(1, round(width * scale)), max(1, round(height * scale))

    def vram_bytes(self, defaults: dict[str, float]) -> float:
        if self.mode in VRAM_MODES:
            key = "vram_high_quality" if self.high_quality else "vram_opaque"
            key = "vram_alpha" if self.info.alpha else key
        else:
            key = "raw_alpha" if self.info.alpha else "raw_opaque"
        width, height = self.size()
        factor = defaults["mipmap_factor"] if self.mipmaps else 1.0
        return width * height * defaults[key] / 8 * factor


@dataclass
class AuditReport:
    textures: list[tuple[Texture, float]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    problems: list[Finding] = field(default_factory=list)

    @property
    def total_mb(self) -> float:
        return sum(size for _, size in self.textures) / MB


def read_import(path: Path) -> dict[str, str]:
    """Top-level keys of a Godot .import file; multi-line values such as metadata are skipped."""
    values: dict[str, str] = {}
    depth = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if depth:
            depth += line.count("{") - line.count("}")
            continue
        match = _LINE.match(line)
        if match:
            key, value = match.groups()
            values.setdefault(key, value.strip('"'))
            depth = value.count("{") - value.count("}")
    return values


def load_defaults() -> dict[str, float]:
    data = json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))
    return {**data["bits_per_pixel"], "mipmap_factor": data["mipmap_factor"]} | {
        f"max_px_{target}": size for target, size in data["max_px"].items()
    }


class ImportAudit:
    """Every texture import of a project, checked against the policy of its folder."""

    def __init__(self, project: Path, policy: Policy, defaults: dict[str, float]) -> None:
        self.project, self.policy, self.defaults = project, policy, defaults

    def run(self) -> AuditReport:
        report = AuditReport()
        for path in sorted(self.project.rglob("*.import")):
            if any(part.startswith(".") for part in path.relative_to(self.project).parts):
                continue
            values = read_import(path)
            if values.get("importer") != "texture":
                continue
            texture = self._texture(values, report)
            if texture is not None:
                size = texture.vram_bytes(self.defaults)
                report.textures.append((texture, size))
                report.problems += self._check(texture, size)
        budget = self.policy.budget_mb
        if budget is not None and report.total_mb > budget:
            detail = f"textures need about {report.total_mb:.1f} MB of VRAM, budget {budget} MB"
            report.problems.append(Finding(POLICY_FILE.as_posix(), "vram_budget", detail))
        log.info("audited %d textures, %.1f MB", len(report.textures), report.total_mb)
        return report

    def _texture(self, values: dict[str, str], report: AuditReport) -> Texture | None:
        source = values.get("source_file", "").removeprefix("res://")
        path = self.project / source
        if not source or not path.is_file():
            detail = f"the import names {source or 'no source'}, which is not in the project"
            report.problems.append(Finding(source or "?", "missing_source", detail))
            return None
        try:
            info = read_info(path)
        except ImageError as error:
            report.problems.append(Finding(source, "unreadable", str(error)))
            return None
        if info is None:
            report.skipped.append(source)
            return None
        return Texture(
            source,
            info,
            mode=int(values.get("compress/mode", "0")),
            mipmaps=values.get("mipmaps/generate") == "true",
            high_quality=values.get("compress/high_quality") == "true",
            size_limit=int(values.get("process/size_limit", "0")),
        )

    def _check(self, texture: Texture, size: float) -> list[Finding]:
        rule = self.policy.rule_for(texture.source)
        found: list[Finding] = []

        def add(name: str, detail: str) -> None:
            found.append(Finding(texture.source, name, detail))

        default_px = self.defaults.get(f"max_px_{self.policy.target}")
        limit = rule.max_px if rule and rule.max_px else default_px
        longest = max(texture.size())
        if limit is not None and longest > limit:
            add("max_px", f"{longest} px on its longest side, limit {int(limit)} px")
        if rule is None:
            return found
        if rule.mipmaps is not None and texture.mipmaps != rule.mipmaps:
            wanted = "on" if rule.mipmaps else "off"
            add("mipmaps", f"mipmaps/generate should be {wanted} under {rule.glob}")
        if rule.compress_modes is not None and texture.mode not in rule.compress_modes:
            allowed = list(rule.compress_modes)
            add("compress_mode", f"compress/mode={texture.mode}, {rule.glob} allows {allowed}")
        if rule.max_texture_mb is not None and size / MB > rule.max_texture_mb:
            allows = f"{rule.glob} allows {rule.max_texture_mb} MB"
            detail = f"about {size / MB:.1f} MB of VRAM, {allows}"
            add("texture_vram", detail)
        return found
