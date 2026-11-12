# GDScript lint, format, check and test tooling

Source: web research of 2026-11-13 (PyPI, GitHub repos, changelogs and issues, docs.rs, Godot 4.7 docs and master source). Star counts were scraped on that date. Release years marked UNVERIFIED were inferred from day and month only.

## Summary

| Need               | Choice for godotkit                                                              | Why                                                                         |
| ------------------ | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------- |
| Lint               | gdlint (gdtoolkit 4.5.0)                                                         | Mature; AloneGodot already pins it in pre-commit                            |
| Format             | gdformat (gdtoolkit 4.5.0), GDQuest `gdscript-formatter` as the fast alternative | One formatter per project; the two disagree on some output                  |
| Script errors      | `godotkit check` (load every script)                                             | Error-level warnings fail `load()` too ([17](17-gdscript-strict-typing.md)) |
| Editor diagnostics | Godot LSP, one `didOpen` per file                                                | No workspace-wide publish                                                   |
| Tests              | Custom summary-line harnesses, GdUnit4 6.2.x, GUT 9.7.x                          | Judged by log and report, never by exit code alone                          |

## gdtoolkit (gdlint, gdformat, gdradon)

- 4.5.0, 2025-10-09, MIT ([PyPI](https://pypi.org/pypi/gdtoolkit/json)); pin with `gdtoolkit==4.*`; about 1.6k stars, 41 open issues.
- Syntax support from the [CHANGELOG](https://github.com/Scony/godot-gdscript-toolkit/blob/master/CHANGELOG.md):
  - Typed dictionaries and multi-statement lambdas since 4.3.2 (2024-10-20).
  - `@abstract` and variadic functions since 4.5.0.
  - UNVERIFIED: whether 4.6 or 4.7 grammar breaks it.
- Open bugs ([issues](https://github.com/Scony/godot-gdscript-toolkit/issues)):
  - #430: `@abstract func …;` is rejected.
  - #425: static functions escape the `max-returns`, `function-arguments-number` and `max-public-methods` checks.
  - #424, #404, #374: gdformat can emit indentation that Godot rejects.
  - #394: `@warning_ignore_start` is a parse error.
- gdlint rules ([linter defaults](https://raw.githubusercontent.com/Scony/godot-gdscript-toolkit/master/gdtoolkit/linter/__init__.py)):
  - Naming regexes for every kind of name.
  - `duplicated-load`, `expression-not-assigned`, `unnecessary-pass`, `unused-argument`, `comparison-with-itself`.
  - `class-definitions-order`.
  - `max-returns` 6, `max-public-methods` 20, `function-arguments-number` 10, `max-file-lines` 1000, `max-line-length` 100.
  - `tab-characters`, `trailing-whitespace`, `mixed-tabs-and-spaces`, `no-elif-return`, `no-else-return`.
  - There is no function-length rule.
- Configuration:
  - `gdlint -d` dumps `gdlintrc` (`key: value`; `disable: [rule]`).
  - In code: `# gdlint:ignore = rule`, or `# gdlint: disable=rule` … `# gdlint: enable=rule`.
  - Output format: `file:line: Error: message (rule-id)`.
- gdformat:
  - Flags: `--check`, `--diff`, `--line-length`, `--use-spaces`; config in `gdformatrc`.
  - Exit 1 means it would reformat; files are processed serially.
  - The README warns that formatting "may lead to data loss".
- Speed: parse 433 ms, format 683 ms, lint 657 ms on 327 files ([gdck benchmark](https://docs.rs/crate/gdck/latest), a competitor's figure, UNVERIFIED).
- `gdradon cc` gives cyclomatic complexity per function: the only complexity tool found.

## Alternatives

| Tool                                                                        | Version (date)                       | Notes                                                                                                                        |
| --------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| [GDQuest GDScript-formatter](https://github.com/GDQuest/GDScript-formatter) | 0.28.0 (2026-10-31), MIT, ~492 stars | Rust and tree-sitter; `--check`, `--stdout`, `.editorconfig`; `lint` subcommand with 17 rules; self-reported few ms per file |
| [gdck](https://docs.rs/crate/gdck/latest)                                   | 0.8.0 (2026-08-25)                   | Rust port of gdtoolkit; reads `gdlintrc`/`gdformatrc`; "complete but young"                                                  |
| [gdstyle](https://github.com/atelico/gdstyle)                               | v0.7.0                               | 57 rules (function length 50, nesting 4, branches 8, parameters 5); JSON output; hook builds with cargo                      |
| [gdeye](https://docs.rs/crate/gdeye/latest)                                 | 0.1.3 (2026-03-14)                   | Dead-function removal (`--unsafe`), experimental LSP                                                                         |
| Built-in formatter                                                          | not in 4.7                           | PR [#97383](https://github.com/godotengine/godot/pull/97383) open, approved 2026-08-15                                       |

All the Rust tools are below 1.0. Adding any of them is a dependency decision for the owner.

## Engine flags and LSP

- From the [command line docs](https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html):
  - `--check-only` parses one script per call.
  - `--import` builds the class cache in a fresh clone.
  - `--doctool --gdscript-docs` dumps docs from `##` comments.
  - `--lsp-port` sets the LSP port; `--log-file` writes the log to a path.
- LSP:
  - Port 6005; it needs a running editor on the project ([external editor](https://docs.godotengine.org/en/stable/tutorials/editor/external_editor.html)).
  - It parses every script on `initialize`, but publishes diagnostics only for files the client opened (`gdscript_language_protocol.cpp`, `gdscript_workspace.cpp`, master). N files need N `didOpen` calls; there is no pull diagnostics.
  - UNVERIFIED: that `--editor --headless` starts the server, and whether warnings are included.

## Test frameworks

|            | GdUnit4                                                                                                                                                       | GUT                                                                    |
| ---------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| Repo       | [godot-gdunit-labs/gdUnit4](https://github.com/godot-gdunit-labs/gdUnit4), MIT, ~1.3k stars                                                                   | [bitwes/Gut](https://github.com/bitwes/Gut), MIT, ~2.8k stars          |
| For 4.7    | v6.2.x (4.5–4.7.1; v6.2.3 "01 Nov", year UNVERIFIED); master v7 targets 4.7 and 4.8                                                                           | 9.7.1 (9.7.0 added 4.7)                                                |
| CLI        | `addons/gdUnit4/runtest.sh -a res://test`, which runs `GdUnitCmdTool.gd` with `-d --remote-debug tcp://127.0.0.1:0`, so a parse error cannot hang at `debug>` | `godot -s addons/gut/gut_cmdln.gd -d --path . -gdir=res://test -gexit` |
| Report     | `res://reports/report_N/results.xml` (JUnit); `-rd` sets the folder, `-rc` keeps 20                                                                           | `-gjunit_xml_file=<path>`                                              |
| Exit codes | 0 ok (also when no tests are found), 100 failures, 101 orphans only, 103 headless refused, 104 version, 105 script errors in discovery                        | 0 or 1                                                                 |
| Headless   | v6.2.3 needs `--ignoreHeadlessMode`; v7 only warns                                                                                                            | `--headless` works but is undocumented                                 |
| Orphans    | Per test with stack traces (v6.2.0)                                                                                                                           | Per test and at the end; `assert_no_new_orphans`, `autofree`           |

Sources: [GdUnit4 CLI docs](https://godot-gdunit-labs.github.io/gdUnit4/latest/advanced_testing/cmd/), `GdUnitTestSessionRunner.gd` and `GdUnitTestCIRunner.gd` at v6.2.3, [GUT command line](https://gut.readthedocs.io/en/latest/Command-Line.html), [GUT memory](https://gut.readthedocs.io/en/latest/Memory-Management.html). WAT is Godot 3 only.

Consequences for the adapters:

- GdUnit4 exits 0 when no tests are found, so `results.xml` is the summary and a missing or empty report fails.
- GdUnit4 needs `--ignoreHeadlessMode` up to 6.2.x.

## Pre-commit

```yaml
repos:
  - repo: https://github.com/Scony/godot-gdscript-toolkit
    rev: 4.5.0
    hooks: [{id: gdlint}, {id: gdformat}]
```

The GDQuest repo offers the `gdscript-formatter` and `gdscript-linter` hooks; use one formatter only.
