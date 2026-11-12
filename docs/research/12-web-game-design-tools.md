# Game design analysis & visualization tools for designkit (web research, 2026-11-12)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## Summary

No existing tool does reachability / chain-length / pacing analysis over a progression graph AND renders it as data-driven static HTML. Machinations is closest for economy but is closed SaaS with no documented export/API (Unity-only sync plugin). Narrative tools (articy, Arcweave, ink, Twine, Yarn, Dialogue Manager, Dialogic) export readable formats but model dialogue, not unlock DAGs. designkit should own: (1) canonical YAML design data as single source of truth, (2) pure-Python analysis core (DAG algorithms + seeded Monte Carlo), (3) single-file HTML views.

## Narrative/progression tools

| Tool                                                                              | Format                                     | Writable            | Godot 4                                   | License                           |
| --------------------------------------------------------------------------------- | ------------------------------------------ | ------------------- | ----------------------------------------- | --------------------------------- |
| articy:draft X                                                                    | JSON export rulesets                       | no (proprietary DB) | community importers (unverified)          | commercial                        |
| Arcweave                                                                          | JSON "Export for Godot"; Web API Team-only | via SaaS            | official plugin MIT                       | freemium SaaS                     |
| ink                                                                               | .ink text → inklecate runtime JSON         | yes                 | community ports                           | MIT                               |
| Twine/Twee 3                                                                      | formal plain-text spec                     | yes                 | indirect                                  | open                              |
| Yarn Spinner                                                                      | .yarn text                                 | yes                 | C# 4.1+; GDScript version alpha/beta 2026 | MIT / Yarn Spinner Public License |
| Dialogue Manager 3                                                                | .dialogue text                             | yes                 | 4.x; v4 for 4.6+ in dev                   | MIT (README)                      |
| Dialogic 2                                                                        | text timelines                             | yes                 | 4.x                                       | MIT (unverified)                  |
| Machinations                                                                      | no export/API                              | no                  | none                                      | SaaS                              |
| Optionally ingest .dialogue/.yarn/.ink as extra nodes for dialogue-gated unlocks. |                                            |                     |                                           |                                   |

## JS graph libraries (single static HTML, 200-1000 nodes)

- **Cytoscape.js 3.3x** (recommended): UMD CDN, layered DAG via cytoscape-elk / cytoscape-dagre, attribute selectors for playstyle filtering, compound nodes for acts, built-in BFS/Dijkstra, experimental WebGL renderer (3.31).
- ELK.js: best layered layout, Web Worker capable; precompute positions offline for determinism/speed.
- dagre: fast, unmaintained but stable.
- React Flow: needs React globals → poor no-build fit. vis-network hierarchical: unsafe for non-tree DAGs. Mermaid 11: maxEdges 500 / maxTextSize 50k → only small diagrams in GDD markdown. D3: flexible, more code. sigma.js: force networks, no layered layout.

## Economy/balance simulation

- Machinations: reference visual language (pools, sources, drains, converters, gates), not agent-drivable.
- cadCAD 0.5.3: heavyweight for single-player campaign. No mature OSS Machinations clones.
- Recommended: ~300-line Python discrete-step simulator over YAML flow schema (pools/sources/sinks/converters/gates), seeded RNG, N=1000 Monte Carlo.

## Analyses to automate

| Analysis                                                                        | Answers                              | Method                                                     |
| ------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------- |
| Reachability, dead ends, orphans                                                | can every item/ending be reached     | BFS from starts                                            |
| Cycles                                                                          | prerequisite bugs                    | Kahn topological sort                                      |
| Critical path                                                                   | min steps/time to ending             | longest path in DAG weighted by est. minutes               |
| Chain length per playstyle                                                      | "why does everything end at step 15" | depth histogram per playstyle subgraph                     |
| Unlock pacing curve                                                             | dry spells                           | cumulative unlocks vs time, flag gaps                      |
| Campaign duration                                                               | 7-8 h target                         | triangular per-node time + Monte Carlo → P10/P50/P90       |
| Resource flow balance                                                           | inflation/starvation                 | source−sink per act + simulated pools                      |
| Coverage matrix                                                                 | playstyle × act served?              | pivot, highlight empty cells                               |
| Interest/difficulty curve                                                       | pacing rhythm                        | designer-tagged intensity vs time (Schell)                 |
| Hazard Monte Carlo                                                              | death/softlock rates                 | seeded sim over path                                       |
| Drift check                                                                     | duplicated numbers                   | extract from .tres/CSV/GDD markers, diff vs canonical YAML |
| Precedent: RPGBench (arXiv 2502.00595) verifies reachability of events/endings. |                                      |                                                            |

## Telemetry

GameAnalytics Godot SDK (MIT, 4.5), Talo (OSS), Quiver, Aptabase, PostHog, Framedash; GhostTrail path recorder. No Godot heatmap vendor. Recommended: tiny autoload appending JSONL events (t, event, pos, node_id) to user:// → designkit funnels, time-per-node (calibrates duration), 2D density heatmaps.

## AI design tooling

Claude Code Game Studios (Donchitos): GDD/design-review/balance-check prompts, no data analysis — mine for templates/checklists. Gap = deterministic analysis + visualization: LLM authors/explains YAML, code computes numbers.

## Recommended designkit

```
design/ progression.yaml (nodes{id,kind,act,playstyles[],est_min{min,mode,max},intensity,requires[]})
        economy.yaml (pools/sources/sinks/converters/gates)  balance.yaml (all tunables)
designkit validate | analyze → analysis.json | simulate | sync (.tres/CSV/GDD drift) | render
views/ graph.html (Cytoscape+ELK, playstyle chips, act compounds, critical path)
       pacing.html  duration.html (MC histogram vs 7-8h band)  coverage.html  economy.html
```

Charts: Vega-Lite / ECharts / Observable Plot (CDN, unverified this session). Mermaid for small inline diagrams. Python stdlib core; networkx/numpy optional; no cadCAD.

## Risks

Duration only as good as per-node estimates (calibrate with telemetry); ELK speed at 1000 nodes unbenchmarked (precompute); CDN offline failure (`--inline-libs` vendoring, pinned versions); .tres parser needed; several secondary-source claims.

## Key sources

js.cytoscape.org; github.com/cytoscape/cytoscape.js-dagre; cytoscape-elk README; mermaid.js.org config; machinations.gitbook.io; pypi cadCAD; arcweave godot plugin; yarnspinner.dev; ink JSON runtime format; IFTF Twee 3; docs.gameanalytics.com godot; github.com/TaloDev/godot; arXiv 2502.00595, 2509.24730; github.com/Donchitos/Claude-Code-Game-Studios.
