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
