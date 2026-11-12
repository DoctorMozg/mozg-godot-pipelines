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

## Develop

```bash
make check       # lint, types, layout rules, plugin validation, pre-commit, tests
make test-godot  # tests that run a real Godot 4 binary (GODOT_BIN or PATH)
```
