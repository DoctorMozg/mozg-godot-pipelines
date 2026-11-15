"""What the agent says after a run: claims checked against the game's state, and remarks that
become ux hypotheses for a human playtest. None of it is evidence for a bug."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from godotkit.contracts import Json
from godotkit.oracle import Finding, Kind, Text, TraceStep, normalize
from godotkit.scenario import Unresolved, resolve


@dataclass(frozen=True)
class ClaimCheck:
    claims: int
    contradicted: int
    wrong: tuple[str, ...]


@dataclass(frozen=True)
class AgentReport:
    text: str = ""
    claims: tuple[Mapping[str, Json], ...] = ()
    remarks: tuple[Mapping[str, Json], ...] = ()

    @classmethod
    def read(cls, path: Path) -> AgentReport:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path}: a report is an object with text, claims and remarks")
        claims, remarks = raw.get("claims", []), raw.get("remarks", [])
        if not isinstance(claims, list) or not all(
            isinstance(c, dict) and isinstance(c.get("query"), str) for c in claims
        ):
            raise ValueError(f'{path}: claims is a list of {{"query": "Node.key", "value": ...}}')
        if not isinstance(remarks, list) or not all(
            isinstance(r, dict) and isinstance(r.get("title"), str) for r in remarks
        ):
            raise ValueError(f'{path}: remarks is a list of objects with a "title"')
        return cls(str(raw.get("text", "")), tuple(claims), tuple(remarks))

    def check_claims(self, state: Mapping[str, Json]) -> ClaimCheck:
        """Each claim against the last observed state; the contradicted ones count as made up."""
        wrong: list[str] = []
        for claim in self.claims:
            query = str(claim["query"])
            try:
                if resolve(state, query) != claim.get("value"):
                    wrong.append(query)
            except Unresolved:
                # A claim about state the game does not have is as false as a wrong number.
                wrong.append(query)
        return ClaimCheck(len(self.claims), len(wrong), tuple(wrong))

    def remark_findings(self, last: TraceStep) -> list[Finding]:
        """Remarks that name a node path or a screenshot; others cannot be checked by a person."""
        found: list[Finding] = []
        for remark in self.remarks:
            where = str(remark.get("node_path") or remark.get("screenshot") or "")
            if not where:
                continue
            evidence = {key: remark[key] for key in ("node_path", "screenshot") if key in remark}
            title = str(remark["title"])
            text = Text(title, "", str(remark.get("text", "")))
            kind = Kind("agent", where, "ux_hypothesis")
            found.append(last.found(kind, text, error_norm=normalize(title), evidence=evidence))
        return found
