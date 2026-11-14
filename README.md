# mozg-godot

Claude Code plugins for Godot 4 game development.

| Plugin       | What it does                                                                              | Status      |
| ------------ | ----------------------------------------------------------------------------------------- | ----------- |
| `godot-core` | `godotkit`: fast, log-judged checks (import, parse, boot, tests), receipts and edit hooks | in progress |

The full plan, with the plugins still to come, is in [docs/plan.md](docs/plan.md).

## Install

```bash
claude plugin marketplace add /path/to/mozg-godot-plugins
claude plugin install godot-core@mozg-godot
```

### Codex

Codex reads `.claude-plugin/marketplace.json` directly, so there is no separate Codex manifest. Verified on Codex CLI 0.169.0 (2026-11-14).

```bash
codex plugin marketplace add /path/to/mozg-godot-plugins
codex plugin add godot-core@mozg-godot   # likewise godot-assets, game-design, godot-l10n
```

- Codex leaves a plugin's `bin/` off PATH. Each skill's hard rules give the kit path (`<plugin>/bin/<kit>`), so agents call kits by path. A shell outside an agent uses the installed copy under `~/.codex/plugins/cache/mozg-godot/<plugin>/<version>/bin/`.
- Plugin hooks (edit guards, post-edit lint, commit-needs-receipt, hub URL at session start) stay skipped until they are trusted in the `/hooks` review. Trust is tied to a hash of the hook, so a plugin update asks again.
- Codex loads no plugin agents. A skill that needs one (the l10n judge) spawns a fresh subagent and hands it the agent file.
- In the workspace-write sandbox, headless Godot runs work. Commands that draw on a display (`godotkit shot`, native tests, `l10nkit shot`) fail with reason `display_unreachable`, and `assetkit hub serve` refuses with `sandboxed_network`. The sandbox blocks the X11 socket and runs commands in a network namespace that the browser cannot reach. Run them outside the sandbox (approve the escalation), or use `assetkit hub build` for a static page.
- Trigger evals (`claude plugin eval`) are Claude Code only.

## Develop

```bash
make check       # lint, types, layout rules, plugin validation, pre-commit, tests
make test-godot  # tests that run a real Godot 4 binary (GODOT_BIN or PATH)
make test-codex  # live Codex test, costs about 9k tokens on the copied login (auth.json; probe 2026-11-14)
```
