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
