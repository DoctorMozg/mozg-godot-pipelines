# mozg-godot-plugins

Plugin marketplace `mozg-godot` for Godot 4 game development. The plan, its milestones and the decisions behind them are in `docs/plan.md`; the research it rests on is in `docs/research/`. A plugin-level `CLAUDE.md` is not loaded by Claude Code, so rules for work on the suite live here.

## Layout

- `.claude-plugin/marketplace.json` — registry of the plugins. Entries carry no version; `plugin.json` is the only source.
- `plugins/<name>/` — one self-contained plugin each: `.claude-plugin/plugin.json`, `skills/`, `agents/`, `hooks/`, `bin/`, `src/<kit>/`, `data/`, `tests/`.
- `contracts/` — shared schemas, once two plugins exchange files.
- `tools/` — repo checks: skill lint, layout rules, commit-message rule.
- `docs/` — plan, research, review queue.
- `.mz/` — working notes (git-ignored).

## Commands

```bash
make check        # ruff, mypy --strict, skill lint, layout rules, plugin validate, pre-commit, pytest
make test-godot   # tests marked live_godot, which run the real Godot binary
make test-codex   # the live_codex smoke test, which drives the codex CLI on the owner's login
make fmt          # format and auto-fix Python
python3 tools/lint_skills.py [--fix]
```

The Godot binary is found through `GODOT_BIN`, then `PATH`; on this machine it is `/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64`.

## Rules

- A milestone touches at most 10 files and 400 changed lines (a mechanical port may exceed it), ends with `make check` green, then one commit.
- Commit messages: at most 6 words, one line, no AI attribution. Never push; the owner publishes.
- Plugins never import each other. They share only files in `contracts/`. A test enforces it.
- Kits are Python 3.11 stdlib. An optional tool (formatter, Xvfb, ffmpeg) is detected and reported by `doctor`, never required.
- A Godot run is judged by its log and an explicit summary line, never by its exit code alone.
- AloneGodot is a read-only test bed: kits run against a scratch worktree of it and never commit to it.
- Every number a plugin ships carries a source and a date. Untested claims stay marked UNTESTED.
- Disk is nearly full: fixtures stay tiny and scratch worktrees are removed after use.

## Code style

- Python 3.11+, strict typing, `Protocol` for structural typing, classes for related logic and plain functions for stateless helpers.
- Comments explain why, not what, in one or two lines. No section banners.
- Explicit error handling with specific messages; log decisions and boundaries, not hot paths.
- Public functions validate their inputs. More than four parameters take a params object.
- Tests check behavior and corner cases, are grouped by feature and reuse fixtures. `live_claude` and `live_godot` tests stay out of `make check`.
- Skills follow the mozg anatomy (`mz-base:construct-skill`): `SKILL.md` of 100 to 150 lines, at most 20,000 characters, references of at most 400 lines, description of at most 250 characters shaped as capability, "Use when", then "Not for ... (use name)". No emphasis caps; `tools/lint_skills.py` enforces it.
- Text in docs, comments and commit messages is impersonal: no first person.
