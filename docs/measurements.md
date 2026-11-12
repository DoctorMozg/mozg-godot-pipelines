# Measurements

Numbers the plugins rely on, each with its source and date. Machine: 16 cores, ext4 NVMe, Godot 4.7.2 stable.

## Import cache (A2, 2026-11-12)

Source: `godotkit worktree new` and `godotkit import` on scratch worktrees of AloneGodot at `4fe4785` (2555 tracked files, 986 `.import` files), each removed after the run.

| Case                                      | Import time | Disk used by `.godot`            | Churn                                                               |
| ----------------------------------------- | ----------- | -------------------------------- | ------------------------------------------------------------------- |
| Cold worktree (no cache)                  | 32.8 s      | 563 MB written                   | 68 files: 65 `.import`, 2 `.translation`, `default_bus_layout.tres` |
| Warm worktree, first import               | 14.1 s      | 3.4 MB copied, 2.4 GB hardlinked | 67 files: the same, less `default_bus_layout.tres`                  |
| Warm worktree, second import (no changes) | 7.1 s       | unchanged                        | none                                                                |

- Godot writes a reimported file to a new inode, so hardlinked entries in `.godot/imported` stay shared until a source changes. The live test `TestRealReimport` in `plugins/godot-core/tests/test_worktree.py` checks this on every `make test-godot`.
- The churn comes from AloneGodot itself: 65 committed images have no `.import` file, and two generated `.translation` files are not ignored. Every fresh checkout recreates them.
- The main checkout's cache (2.3 GB) holds stale entries; a cold import needs 563 MB.

## Parse and boot gates (A3, 2026-11-12)

Source: `godotkit check` and `godotkit boot` on scratch worktrees of AloneGodot with a warm cache, each removed after the run.

| Run                                                               | Time   | Result                                                                 |
| ----------------------------------------------------------------- | ------ | ---------------------------------------------------------------------- |
| `check` at `4fe4785`                                              | 12.8 s | 342 scripts load, 0 failed                                             |
| `boot` at `d1d7760~1` (before "Fix initial root session startup") | 3.0 s  | `input_dead`: main scene cannot process, busy-parent `add_child` error |
| `boot` at `d1d7760` (the fix)                                     | 3.2 s  | `live`: click on the topmost control reaches `gui_input`               |
| `boot` at `4fe4785`                                               | 5.5 s  | `live`                                                                 |

- AloneGodot's own suite of 433 tests was green at `d1d7760~1`; the bug was found by hand at F5.
- `push_input` reports the event as handled even when the scene cannot process, so the probe counts `gui_input` signals instead.
- The probe pushes events in viewport-local coordinates; window coordinates miss under stretch modes and gave a false `input_dead` at `4fe4785`.

## Test runner (A4, 2026-11-13)

Source: `godotkit test` on a scratch worktree of AloneGodot at `4fe4785` with a warm cache, compared with AloneGodot's own runners (`run_save_tests.sh`, `run_sound_tests.sh`, `run_campaign_tests.sh`, and the `smoke` and `card_resources` hooks) on the same worktree. The worktree was removed after the runs. The `godotkit.json` used is an untracked scratch file mirroring those runners: sound arguments, the `--board-layout` and `--timeline-view` variants, the root-startup scene, 9 native entries, `allow_push_error`, and one engine-error pattern for the corrupt-save test.

| Run                                          | Wall time | Result                                                                     |
| -------------------------------------------- | --------- | -------------------------------------------------------------------------- |
| AloneGodot runners, serial                   | 178 s     | 42 summary lines, 43,341 checks (includes 33 `--check-only` passes)        |
| `test --jobs 4`, all headless entries        | 103 s     | 42 entries, 43,341 checks, 0 failures; per-entry counts match exactly      |
| `test --since HEAD --list`, one script edit  | 0.33 s    | strict subsets: 3 of 51 entries (a leaf script), 20 of 51 (`save_file.gd`) |
| `test --since HEAD --jobs 4`, leaf script    | 41 s      | 3 entries                                                                  |
| `test --since HEAD --jobs 4`, `save_file.gd` | 73 s      | 13 run, 7 native skipped                                                   |

- The graph scan takes 0.3 s for 4,159 files.
- `smoke.gd` reaches every file: one of its suites loads `"res://" + str(row["image_path"])`, so the graph cannot narrow it. It also takes 35–58 s, which puts a floor under every affected run. A change selecting a strict subset in under 10 s is therefore not met on AloneGodot: selection meets it, running does not.
- The slowest entries are `transmitter_hint_test.gd` (67 s) and `smoke.gd` (58 s) under 4 jobs.
- Of 144 `ERROR:` lines in the full run, 143 come from AloneGodot's own `push_error` in negative-path tests (location `push_error (core/variant/variant_utility.cpp)`). The other one is engine-raised (`decode_variant`, a deliberately corrupt save). AloneGodot's runners pass on all of them because they look only for `SCRIPT ERROR` and leaks.
- `run_root_startup_test.sh` calls `rg`, which is not installed on this machine, so its error and leak scans silently do nothing.

## Test frameworks (A4b, 2026-11-13)

Source: GdUnit4 v6.2.3 and GUT 9.7.1 tag archives (SHA-256 pinned in `plugins/godot-core/tests/godotkit_rig.py`) on throwaway fixture projects with Godot 4.7.2, headless, stdin closed. The live test `test_real_framework_suites_are_judged` repeats the pass, fail and parse-error cases on every `make test-godot`.

| Case                                                      | GdUnit4 v6.2.3                                                    | GUT 9.7.1                                            |
| --------------------------------------------------------- | ----------------------------------------------------------------- | ---------------------------------------------------- |
| One passing and one failing test                          | exit 100; `results.xml` under `-rd`, `tests="2" failures="1"`     | exit 1; `-gjunit_xml_file`, `tests="2" failures="1"` |
| Suite with a parse error                                  | exit 105, no report                                               | exit 0, report `tests="0" failures="0"`              |
| Folder with no tests                                      | exit 0, no report ("No test cases found")                         | exit 0, report `tests="0"`                           |
| Unexpected `push_error` in a test                         | test passes; only the log shows it                                | test fails                                           |
| `-d --remote-debug tcp://127.0.0.1:0` (from `runtest.sh`) | prints two engine `ERROR:` lines (port 0 is invalid) on every run | not used                                             |

- The GUT parse-error row is why exit codes are never trusted: a broken suite exits 0.
- godotkit runs GdUnit4 without `-d`. Without it a parse error still exits cleanly, and the runs carry no spurious port errors.
