# mozg-godot — implementation plan

Status: DRAFT for approval (2026-11-12). Research behind every item: `docs/research/01-14`.

## Goals (from the user)

1. A Claude Code marketplace for Godot 4 game development, shaped like `mozg-video-plugins`.
1. **Fast feedback**: per-edit checks under 1 s, per-task checks under 10 s, full gate only before commit.
1. **One review hub in the browser** for every resource — 2D, sprites, 3D, audio, UI screenshots, shaders (as clips), design graphs — where each item can be approved or **marked for redo** with a note, and the decision reaches the agent automatically.
1. **Game-design tools**: progression graphs with analysis (reachability, chain length per playstyle, pacing, duration), balance simulation, and sourced web research on reference games and mechanics.

## Assumptions

- Python 3.11 stdlib for every kit; heavy or optional tools are detected, never required (`godotkit doctor` reports them).
- Godot 4.7.2 at `/home/drmozg/Tools/Godot_v4.7.2-stable_linux.x86_64` is the test engine; support floor 4.4 (UID files) is checked by fixtures later, not promised now.
- AloneGodot is a **read-only** test bed: kits run against a scratch worktree of it, never commit to it.
- Browser libraries are vendored into the plugin (offline, pinned), not loaded from a CDN at runtime.
- Disk is ext4: `cp --reflink=auto` falls back to a real copy of `.godot` (still avoids reimport). Disk is 95 % full — fixtures stay small, scratch worktrees are cleaned.

## Structure (approved, plus one addition)

```
plugins/
  godot-core/      godotkit   fast loop tiers, gates, receipts, hooks, init/verify/test/scene skills
  godot-review/    reviewkit  NEW: browser review hub + decisions → agent   (every plugin writes into it)
  game-design/     designkit  design data, graph analysis, simulation, views, interview/canon/research skills
  godot-studio/               team orchestration on mz-dev-pipe
  godot-art/       artkit     2D + 3D assets via fal-media, import/VRAM audits
  godot-ui/        uikit      brief → HTML prototype → Godot handoff, theme, multi-res capture, i18n
  godot-audio/     audiokit   cue sheet, synth/fal SFX, loudness, buses, listening
  mozg-godot-suite/           dependencies only
```

**Why a separate `godot-review`**: art, audio, UI, design and 3D all need the same viewer, the same decision file and the same redo hook. One owner, one contract (`review-item`, `review-decisions`), every other plugin only writes items.

## Fast loop (godot-core)

```
Tier 0  <1 s   every edit (PostToolUse hook)   no new Godot process
        gdscript formatter/lint on the changed file  +  LSP diagnostics from a long-lived
        `godot --editor --headless --lsp-port P` per worktree  +  .tscn/.tres reference lint
Tier 1  <10 s  per task (`godotkit check --affected`)
        affected tests from a dependency graph (preload/extends/class_name/ext_resource),
        one fresh headless process on a warm .godot, verdict from log tokens + summary line
Tier 2  gate   before commit (`godotkit gate` → receipt)
        warm-cache import + uid churn check, full parse gate, boot gate with real input,
        duration-balanced shards with isolated user://, optional native capture
```

Every command prints one JSON line; exit code of Godot is never trusted alone.

## Review hub (godot-review)

```
plugins write  review/items/<section>.json  (contract review-item: id, kind, group, versions[{n,file,sha256,thumb,meta}])
reviewkit build  → review/index.html + manifest (thumbs cached by hash; audio LUFS; glb stats)
reviewkit serve  → 127.0.0.1:random, token, Host/Origin checks, path sandbox
browser: grid with status pills (pending/approved/redo/stale), filters in URL hash, keyboard A/R/J/K,
         per-kind viewer: image + 120/240 px + before/after | sprite frames + onion skin |
         3D model-viewer (+three.js inspect) | audio waveform + loop seam + A/B | video/clip |
         UI per resolution | graph (design) ; region notes on images
POST /api/decisions → .review/decisions.json (atomic, keyed id@version + sha256) + decisions.log.jsonl
hook (SessionStart + UserPromptSubmit): injects unconsumed redo items into the agent's context
fallback without server: localStorage + "Download decisions" + "Copy list"
```

## Game design (game-design)

```
design/progression.yaml  economy.yaml  balance.yaml   (single source of truth)
designkit validate | analyze | simulate | sync | render
  analyze : reachability, dead ends, cycles, critical path, depth per playstyle, pacing gaps, coverage matrix
  simulate: Monte-Carlo campaign duration (P10/50/90 vs target band), economy pools, hazards (seeded)
  sync    : drift between YAML and .tres / CSV / doc number blocks
  render  : review-hub items of kind graph/chart (Cytoscape + ELK layout precomputed, charts) → per-node redo
skills: gd-interview (numbered questions → decision log), gd-canon, gd-contracts/handoff (OPEN rows block code),
        gd-balance, gd-review (judge), gd-research (web: reference games/mechanics, sourced, via pipeline-web-researcher)
```

## Milestones

Each milestone ≤ 10 files / 400 changed lines (mechanical ports excepted), ends with `make check` green and one commit. Later plugins get a detailed milestone breakdown when reached; outlines below.

### Phase A — repo and godot-core

| #   | Milestone                                                                                                                                                                            | verify                                                                                                                   |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------ |
| A0  | Scaffold: marketplace.json, CLAUDE.md, Makefile, pyproject, pre-commit, CI; port `tools/` (lint_skills, repo_rules, skill rules, commit-msg, sync_contracts) from mozg-video-plugins | `make check` green; `claude plugin validate --strict` passes on the empty marketplace                                    |
| A1  | godotkit skeleton: launcher, `doctor`, Godot locator, log judge; fixture projects `ok`, `parse_error`, `exit0_trap`                                                                  | pytest with real Godot: `exit0_trap` returns `ok:false` while Godot exits 0                                              |
| A2  | `import` + `worktree new`: warm `.godot` copy, `use_multiple_threads=false` option, uid/translation churn report                                                                     | on an AloneGodot scratch worktree: warm import measured faster than cold (numbers recorded); churn listed, not committed |
| A3  | `check` parse gate + `boot` gate with injected temporary input bridge                                                                                                                | fixture reproducing AloneGodot's dead-input startup bug fails `boot` with `input_dead`; healthy fixture passes           |
| A4  | `test`: adapters for custom summary-line harness and GdUnit4 JUnit, dependency graph, `--affected`, shards with isolated XDG                                                         | on AloneGodot: full run matches existing runner check counts; one changed script selects a strict subset in < 10 s       |
| A5  | Tier 0: formatter/lint wrapper + LSP client (\`lsp start                                                                                                                             | diag                                                                                                                     |
| A6  | `gate` + receipts (\`receipt write                                                                                                                                                   | verify\`)                                                                                                                |
| A7  | Hooks: PostToolUse Tier 0 on .gd/.tscn/.tres, 280-line warning, SKIP guard, commit-needs-receipt                                                                                     | hook unit tests; hook adds < 1 s per edit on AloneGodot                                                                  |
| A8  | Skills: godot-init, godot-verify, godot-test, godot-scene (+ evals)                                                                                                                  | lint_skills clean; ≥ 3 eval cases per skill pass                                                                         |
| A9  | `native` + `shot`: real renderer run, multi-resolution capture in one process, UI node/rect snapshot JSON                                                                            | fixture captured at 3 resolutions from one process; snapshot lists controls with rects                                   |

### Phase B — godot-review

| #   | Milestone                                                                                                                   | verify                                                                                                                     |
| --- | --------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| B1  | Contracts `review-item`, `review-decisions`; `reviewkit build` (2D images) + `serve` with security                          | pytest: token/Host/Origin/path-traversal rejected; headless Chrome approve/redo writes decisions.json; stale on sha change |
| B2  | Viewers: sprite frames, audio (waveform, seam, A/B), 3D (model-viewer, three.js inspect), video, UI multi-res, region notes | one fixture per kind renders in headless Chrome with no console errors                                                     |
| B3  | Redo hook + \`reviewkit pending                                                                                             | consume`+ skill`review-hub\`; adapters for AloneGodot's existing manifests                                                 |

### Phase C — game-design

| #   | Milestone                                                                                                           | verify                                                                       |
| --- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| C1  | Schemas + \`designkit validate                                                                                      | analyze\`                                                                    |
| C2  | `simulate` (duration, economy, hazards) + `render` into the review hub (graph, pacing, duration, coverage, economy) | seeded runs reproducible; views render; per-node redo reaches decisions.json |
| C3  | `sync` drift check + skills gd-interview, gd-canon, gd-contracts/handoff, gd-review judge                           | drift fixture catches stale number (oxygenPerDay case); evals pass           |
| C4  | gd-research skill (web research on reference games/mechanics, cited) + gd-balance skill                             | evals pass; sample research report has a source per claim                    |

### Phase D–G — outlines (detailed when reached)

- **D godot-studio**: role map → subagents, ownership manifest + hook, delegation template, frozen-test lock, worktree lifecycle, risk-based depth on mz-dev-pipe.
- **E godot-art**: art-bible, asset-brief with dependents, art-batch via fal-media (2D and 3D: Trellis/Hunyuan GLB with decimation), import/mipmap/VRAM audit, review-hub items, readability + style judges.
- **F godot-ui**: ui-brief, HTML prototype template, handoff template, tokens → Theme, multi-res capture into hub, i18n checks.
- **G godot-audio**: cues.yaml, synth/fal SFX, music loop points, loudness checks, bus lint, audition in hub.

## Decisions needed now

1. **Approve adding `godot-review`** as its own plugin (above).
1. **Approve dependencies** (vendored, pinned; licences permissive unless noted):
   - Browser: Cytoscape.js + cytoscape-elk/elkjs (graphs), Apache ECharts (charts), @google/model-viewer + three.js (3D), wavesurfer.js 8 (audio), Annotorious 3 (region notes), img-comparison-slider 8.
   - External tools, detected not required: GDQuest gdscript-formatter (Tier 0 lint/format; gdtoolkit as fallback), Xvfb (`apt install xvfb`) for display-less renders — until then native runs use the X11 display.
   - In user projects only when chosen: GdUnit4 addon.
1. **Approve the plan**; after that, phases run milestone by milestone without stopping, pausing only for hard-to-reverse or outward-facing steps.
