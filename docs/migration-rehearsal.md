# Migration rehearsal (Phase M)

AloneGodot was moved onto the four kits inside a throwaway `git clone --local` of `78b719d` with its origin removed. AloneGodot itself was not written to. Machine: 16 cores, ext4 NVMe, Godot 4.7.2 stable. Every run dates from 2026-11-14 or 2026-11-15. The clone was deleted after the report, and its commits (adoption `0eef1d6`, lanes `ff80893` and `97a8f06`, merge `add7441`) were never published.

## Survey before adoption

| Step             | Result                                                                                                                            |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `import`, cold   | 77 s, churn 0 (67 files on 2026-11-13: the project has since committed its `.import` files)                                       |
| `check`          | 454 scripts load, 13 s                                                                                                            |
| `lint`           | 499: bare-free 312, get-parent 156, timer-ignores-pause 14, material-duplicate 12, string-signal 4, alpha-write 1                 |
| `arch`           | 3 cycles                                                                                                                          |
| `test`, headless | 68 entries, 754 s: 43 ok, 14 need a renderer, 11 negative-path entries fail only on expected `push_error` lines (0 failed checks) |
| `boot`           | live, 4.6 s                                                                                                                       |
| `baseline write` | lint 499, arch 3, check 0, strict 94, 21 s                                                                                        |

## Milestones

| #   | Result                                                                                                                                                                                                                                                                                                                                                                                      |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | `godotkit.json` marks 14 entries `native` and gives 11 entries 73 allow patterns; `architecture.json` has modules `game` and `tests` with `no_cycles`. First gate passed on unchanged code in 102 s: 54 entries, 118,064 checks.                                                                                                                                                            |
| M2  | An untyped function made the gate fail `check` and `strict`, and the pre-bash hook refused the commit. The typed version passed in 99 s and the commit went through.                                                                                                                                                                                                                        |
| M3  | Strings: 256 keys imported in 258 ms. The CSV export has the same 256 rows, sorted by key. Assets: 318 assets and 530 versions applied in 5.5 s, a second apply refused, `doctor` clean, the hub lists all 318 (251 pending, 41 approved, 26 rejected). Design: 23 balance numbers from `survival.tres` and `health.tres`, `sync` 23/23, and a 120 → 90 edit to one copy reported as drift. |
| M4  | Two lanes (table, jobs) explained the frees and copies they kept: lint baseline 499 → 485. Each lane gate passed, the merge was clean, and the merged gate passed in 119 s (tests 89 s).                                                                                                                                                                                                    |

## Kit findings

Fixed during the rehearsal:

- K1 (`e6f1bc5`): an entry that awaits `RenderingServer.frame_post_draw` under `--headless` sits idle until the 600 s timeout. The timeout now says so and suggests `native`.
- K2 (`e6f1bc5`): keys `godotkit.json` didn't recognise were ignored, so an `entries` list outside `tests` dropped every flag without a word. Unknown keys are now refused, with a pointer to the right place.
- K8 (`5843704`): a design with balance numbers and no progression graph could not validate. The new `numbers` model covers it: `sync` works and `simulate` refuses.
- K9 (`e6f1bc5`): the gate named the failed test entries but not the reason. Each failed entry now carries a one-line `why`.

Open:

- K3: drafting allow patterns took the most hand work, 73 patterns for 11 entries (40 of them for `card_resources_test`). A helper that drafts them from a failing log would replace it. Patterns are matched against the whole log line, so they anchor on `^ERROR: <message>$`.
- K5: without `gdscript-formatter` or a running LSP the post-edit hook says nothing, so an untyped function goes unnoticed until the gate.
- K6: `l10nkit export` writes rows in key order. That is documented, but a project with a hand-ordered CSV sees a one-time reorder diff.
- K7: `.tres` bindings read only the `[resource]` section, so the economy numbers kept in `sub_resource` blocks of `recipes.tres` can't be bound.
- K10: every clean-up lane rewrites `godotkit-baseline.json` when it shrinks, so lanes merged in sequence conflict on that file.
- `domain_query_benchmark` times out headless for a reason not yet found. It is marked `native` for now.

## Lessons for a real migration

- Before a lane removes a material `duplicate()` that looks unused, check whether tests pin the private copy: three suites (smoke, card_resources, save_session) failed both lanes' first gates for exactly that.
- Running two lane gates side by side on one machine raised test time from 75 s to 161 s, so run lane gates one after another.
