# Fast edit → check → feedback loop for agent-driven Godot 4.5-4.7 (web research, 2026-11-12)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## Core insight

Cost is repeated process startup (engine init, first filesystem scan, class registration, autoloads; fresh worktree adds full import), not the checks. Three tiers.

## Startup / import

- Reimport is MD5-gated, not mtime (editor_file_system.cpp `_test_for_reimport`: .import md5, uid, dest files, importer version, source_md5/dest_md5). ⇒ `cp -a --reflink=auto <main>/.godot <wt>/.godot` then `--headless --import` should be a hash-only pass. Never hardlink/symlink .godot. Cross-worktree sharing UNVERIFIED by any source — test it.
- 4.7 import crash/hang workaround: `[editor] import/use_multiple_threads=false` (community; override.cfg use unverified).
- `.uid` churn: guard with `git diff --exit-code -- '*.uid' '*.translation'` after bootstrap import; consider gitignoring generated .translation.
- `--headless` = headless display + Dummy audio; no RenderingDevice since PR #98247. Useful: `--no-header`, `--log-file`, `--fixed-fps` + `--time-scale`, `--quit-after`, `--single-threaded-scene`, `--disable-crash-handler`.
- No per-run autoload toggle; `--check-only -s` false-fails on autoload/class_name refs before import.

## Diagnostics

- Headless editor serves LSP: `godot --editor --headless --path <wt> --lsp-port 6005 --dap-port 6006` (used by official VS Code plugin `godotTools.lsp.headless`, 4.2+). didOpen/didChange → parse_script → publishDiagnostics, full sync, no debounce; didSave reloads script (live reload). Latency unmeasured (likely tens of ms after one-time startup/scan). One editor per worktree, distinct ports (busy port fails silently). Existing wrappers: minimal-godot-mcp, godotlens-mcp.
- `--check-only` per call ≈ full process start (~4 s in AloneGodot).
- GDQuest gdscript-formatter (Rust, v0.26.0): ms per file, `--check`, `--safe`, `lint`. gdck vs gdtoolkit (author numbers, 321 files): parse 4 ms vs 70 ms; format 56 ms vs 802 ms.
- No test daemon in GdUnit4 or GUT. GdUnit4 exit codes: 0 ok, 100 failures, 101 warnings/orphans. DIY TCPServer daemon risky (stale class_name, static state, preload constants) — accelerator only, restart on class_name/autoload/project.godot/.tscn structure changes.

## Test selection & parallelism

- No built-in affected-test detection. Build graph from preload/load strings, extends path/ClassName, ClassName identifiers (global_script_class_cache.cfg or regex), ext_resource path/uid in .tscn/.tres (uid via .uid sidecars). Reverse closure ∩ tests; fall back to all on project.godot/autoload/addons/framework changes.
- Selection: GdUnit4 `-a`, `-i suite[:test]`, `-c`; GUT `-gtest`, `-gselect`, `-gunit_test_name`, `-ginner_class`, `-gjunit_xml_file`, `-gexit`.
- Shard by historical duration (JUnit XML); isolate user:// per shard via XDG_DATA_HOME/HOME (`--user-data-dir` is NOT a Godot 4 flag, silently ignored).
- Judge by log: fail on `SCRIPT ERROR|Parse Error|ERROR:`, require start banner + summary line + check count.

## Human live preview

- Debug > Synchronize Script/Scene Changes; external saves don't trigger it (godot#72825) but LSP didSave → reload_script probably does (unverified end-to-end). Agent preview: headless editor `--debug-server tcp://127.0.0.1:6007`, game `--remote-debug tcp://127.0.0.1:6007` (untested).
- Watcher: watchexec -e gd,tscn,tres, 200-300 ms debounce.
- Web preview: export HTML/wasm shell once, re-export `.pck` (`--export-pack`, or `--export-patch --patches`); single-threaded, no COOP/COEP.

## Visual feedback

- Headless can't render → `xvfb-run -a -s "-screen 0 2560x1440x24" godot --rendering-method gl_compatibility` (llvmpipe) or lavapipe Vulkan.
- Multi-resolution in one process: resize window or SubViewport per size, await frame_post_draw twice, save_png — pays startup once.
- `--write-movie out.png --fixed-fps 30 --quit-after N` for deterministic frame-N, not speed.
- Prefer structured snapshots (node tree + layout rects) over pixels: Beckett numbers — 119-control UI 1.7-2.7 s PNG vs 103 ms snapshot; screenshot 2.7 s → 0.12 s JPEG half-scale.
- Image diff: ImageMagick compare -fuzz, odiff, pixelmatch; per-resolution baselines with tolerance.

## Other toolchains

Bevy BRP → debug-only autoload localhost TCPServer (godot-mcp-runtime, Beckett do this). Bazel-like cache key = hash(test + dep closure + project.godot + Godot version) → skip unchanged passing suites.

## Recommended design

```
Tier 0 (<1 s, every edit, no new Godot): formatter --check + lint on changed .gd; LSP didChange diagnostics
        from long-lived headless editor; cheap greps
Tier 1 (<10 s, per task): affected tests in one fresh headless process on warm .godot; verdict = exit AND
        no error tokens AND summary line; optional daemon
Tier 2 (pre-commit/CI): reflink .godot bootstrap + import (+use_multiple_threads=false on 4.7) + uid churn check;
        full parse gate; N duration-balanced shards with separate user://; background run with --log-file
        (fits 90 s tool timeouts); optional xvfb visual capture + fuzzy diff
```

Estimated savings (from AloneGodot numbers, not sourced): Tier 0 replaces ~4 s check-only with ms; reflinked .godot cuts cold import to hash/scan; affected + shards bring 16.7 s median under 10 s.

## Risks

.godot sharing untested; daemon staleness; LSP memory/ports; 4.7 import crash workaround community-only; llvmpipe vs GPU pixel differences; self-reported numbers (Beckett, gdck); exit-0 traps.

## Key sources

docs.godotengine.org (command_line_tutorial, overview_of_debugging_tools, creating_movies, exporting_for_web); godot source editor_file_system.cpp, gdscript_language_protocol.cpp, gdscript_text_document.cpp; gdUnit4 GdUnitTestCIRunner.gd + cmd docs; gut.readthedocs.io; forum.godotengine.org exit-0 traps (145990), 4.7 reimport crash (141845), Beckett (141177); github.com/godotengine/godot-vscode-plugin; gdquest.com gdscript_formatter; docs.rs gdck; godot#72825.
