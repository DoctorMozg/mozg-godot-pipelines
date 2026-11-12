# LLM playtesting: scenarios, oracles and findings

Source: web research of 2026-11-13 against arXiv papers (2018–2026), CHI/ASE/FSE/NeurIPS proceedings, Google Research and EA SEED posts and vendor pages. Cost figures are from GPT-4o studies; nothing is tested with Claude or Godot 4.7.2 (UNTESTED).

## Executive summary

From 2024 to 2026, LLM playtesting research has settled on one architecture: the agent works on an abstracted, text-like game state and calls macro actions. Memory and reflection keep it moving, and bugs are found by mechanical oracles (crash, stuck, timeouts) plus an LLM triage step. The strongest published result, TITAN in 2025, reports a 30% false-alarm rate. Vision-language models still hallucinate glitches, so a finding should only count as a bug when game-side evidence backs it.

LLMs do well at reaching goals and at ranking difficulty relative to other content (r up to 0.87 against human win rates). They are weak at reporting human-like confusion: one CHI '26 study found 3 failure points against 10 found by humans. Their experience signals should be treated as hypotheses for a human playtest, not as results.

LLM agents are slow and costly, about 12 s and $0.05–0.06 per action with GPT-4o. They suit turn-based or pausable play: UI flows, tutorials and RTS macro decisions. For reflex play, coverage sweeps and long soak tests, scripted bots, RL/curiosity agents and random input remain the better tools.

## Key findings

### 1. Academic and industry work

**F1. TITAN (Wang et al., arXiv 2509.22170, 26 Sep 2025) is the most complete LLM game-testing system published.** Confidence: high for the design, medium for the numbers.

- **State.** Game state is abstracted into text by feature selection and bucketing, e.g. "Low HP < 20%". Per-game templates take "less than five minutes per game".
- **Oracles.**
  - Crash monitor.
  - Stuck monitor: 20 consecutive actions without progress.
  - Time-anomaly monitor: action or task duration far above the recorded average. It is disabled on the first run.
  - Expert logic checks.
  - An LLM reflection prompt asks for the cause, the next actions, and whether this is a bug, with its type and evidence.
- **Reports.** Each report holds the goal, a summary of the actions, why the task looks stuck, and evidence (abstract state, screenshots). Reports are saved for human review.
- **Results.** 95% task completion. Bugs found were crashes, hangs and logic bugs, for example "a six-kill quest completes after five kills". Overall false-alarm rate is 30%, mostly blamed on imperfect state abstraction. It ran at temperature 0 on GPT-4o and is deployed in "eight real-world game QA pipelines".
- **Not reported:** cost and token use.
- CONFLICT DETECTED: the TITAN abstract says it found 4 previously unknown bugs, the introduction and Table 3 say 15 detections, and the recall text says "82% of the nine bugs". The denominator is unclear.

**F2. MIMIC (Chen, Habchi, Wei; McGill/Cohere; arXiv 2510.01635, 2 Oct 2025) and the MIMIC-Py tool (arXiv 2604.07752, 9 Apr 2026) add personas.** Confidence: high.

- **Method.** Personas use the 7 PathOS traits: Achievement, Adrenaline, Aggression, Caution, Completion, Curiosity, Efficiency. The agent has a hybrid planner, RAG memory and code "skills".
- **Behaviour.** Personas do change behaviour in measurable ways. In Minecraft the aggressive persona spent about 21.5% of its actions on combat and took 102 minutes for the diamond task, against 25–35 minutes for the other personas. The cautious persona avoided combat.
- **Coverage.**
  - Small RPG: 95.67% line coverage in 35 minutes, about 1.16× the coverage of a monkey baseline.
  - Large roguelike (Shattered Pixel Dungeon): 30.5% line coverage against about 60% for human testers, and 14% navigation coverage against 47% for humans.
- **Costs and limits.** 12.4 s and about $0.06 per action. The authors call it impractical for real-time games. Personas were not validated against real players, and bug detection is weak: the summariser misses in-game bugs.

**F3. Lap (Zhao and Tang, FSE Companion '25, arXiv 2507.09490) tested a match-3 game through screenshots, OpenCV and ADB.** Confidence: medium (one game, inconsistent naming in the paper).

- Results: 79% line coverage and 5 crashes. Rule-based testing reached 75% and 1 crash, RL reached 46%, and Monkey reached 3–5%.
- The LLM produced invalid moves (hallucinations).
- Rule prompts combined with few-shot examples worked best.

**F4. Bug reproduction from reports.** BugCraft (ASE'25, arXiv 2503.20036) turns a Minecraft crash report into steps to reproduce, then runs them with a vision LLM agent and a macro API. It reproduced 34.9% of crash bugs end to end (GPT-4.1), and agents got stuck in loops. Confidence: high. This shows that LLM-written repro steps are often wrong unless they are replayed.

**F5. Detecting glitches with vision models.** Confidence: high.

- GlitchBench (CVPR 2024): GPT-4V reached 43.4% (v1 figure).
- VideoGameQA-Bench (NeurIPS 2025 D&B, Sony/UAlberta, v2 Dec 2025), best scores:
  - image glitch detection: 82.8% (GPT-4o);
  - UI unit tests: 40.0%;
  - visual regression: 45.2%;
  - bug-report generation: about 52–54%;
  - finding the bug frame in a long video: about 36%.
- "High false-positive rates... continue to pose a significant issue." The most common false positive is hallucinated clipping. One model labelled almost everything as a glitch, with under 2% specificity.

**F6. Human-AI collaboration.** Zhang, Xu, Pan (arXiv 2501.11782, v2 Apr 2026) ran 276 participants on 800 test cases. AI assistance improves defect identification, most of all when testers also have design documents. "AI errors can negatively affect human decision-making." Confidence: medium (abstract only).

**F7. Difficulty measurement.** Xiao and Yang (arXiv 2410.02829, Oct 2024) report Pearson r between GPT-4 chain-of-thought results and human difficulty. Confidence: high.

| Game                  | GPT-4 CoT | Comparison                                |
| --------------------- | --------- | ----------------------------------------- |
| Wordle                | 0.624     | optimal solver r = 0.075, not significant |
| Slay the Spire, Act 1 | 0.871     | rule-based expert AI 0.742                |
| Slay the Spire, Act 2 | 0.710     | rule-based expert AI 0.482                |

- The LLMs play worse than humans, so the signal is relative, not absolute.
- The authors had to compensate for the weaker play: a higher guess cap and a stronger deck.

**F8. Industry and vendors.** These are vendor claims; confidence medium to low.

- **modl.ai** (site, 2026): tasks in plain language ("Complete the tutorial"), step lists with expected outcomes, or open exploration. Each task is pass/fail. Reports carry screenshots, video, logs and an AI severity score that QA can edit. Detects softlocks, broken menus and crashes. Uses LLMs plus vision, OCR and a custom per-game model. No engine SDK is needed, and Godot is not named.
- **nunu.ai:** natural-language test cases with multimodal agents. Pre-seed $2M (2024), seed $6M. UNVERIFIED: the "up to 50% QA cost reduction" claim and the "$200" pricing (directories only).
- **Razer QA Companion-AI** (Wyvrn docs; GDC 2025 and 2026 blog, 9 Mar 2026): generates a title, description, severity guess, repro steps and footage, and testers edit before export to Jira. 2026 preview agents run a test, compare expected with actual, and return pass/fail. No accuracy numbers are published.
- **King** (Gudmundsson et al. 2018): a CNN imitates human players on Candy Crush to predict level difficulty; the bots "mimic" humans rather than beat them. UNVERIFIED: the figure of 95% fewer manual level adjustments (trade-press interview only).

**F9. Earlier non-LLM work in the same lineage.** Confidence: high for existence, medium for details.

- **EA SEED:**
  - curiosity-driven RL for map coverage (CoG 2021, arXiv 2103.13798);
  - RL with a user-defined reward for exploits and map difficulty (arXiv 2103.15819);
  - CCPT, curiosity around expert trajectories (arXiv 2202.10057).
- **Google (Jun 2021 blog):** an ensemble of agents trained by imitation learning, each on a gameplay loop of a few minutes, in "less than an hour on a single game instance". Developers describe state and actions through a high-level API (entities, raycasts) instead of pixels.
- **Stadia/Google (Mar 2021):** millions of simulated matches to balance the card game Chimera.
- **NetEase Wuji (ASE 2019):** evolutionary RL that balances winning against exploration; found 3 bugs the developers confirmed.
- **iv4XR/aplib (Prasetya, Utrecht; AAMAS 2020, ICST 2023):** a test is a goal structure plus invariants. It supports reachability assertions, invariants and LTL properties. This maps directly onto scenario files.
- **Procedural personas (Holmgård et al., 2018/2019):** personas are utility functions driving MCTS or Q-learning agents, compared with human playstyles in MiniDungeons. These are the PathOS and persona roots of MIMIC.
- **Rare, *Sea of Thieves* (GDC 2019, Vault 1026366):** large suites of deterministic scripted gameplay tests. Login-gated; content taken from the session abstract.

**F10. Developers stay sceptical.** Politowski et al. (GAS '22, arXiv 2202.12777): "game developers are skeptical about using automated agents to test games." The authors recommend that research focus on "the testing goal and testing oracle". Confidence: high, from the abstract; sample size not retrieved.

### 2. Scenario design

**F11. Published systems converge on the same scenario shape.** Confidence: high, with modl.ai, TITAN, iv4XR and Razer agreeing.

- a natural-language goal;
- a machine-checkable success condition;
- preconditions;
- a step or time budget;
- an optional persona.

**F12. Persona prompts change behaviour, but nothing shows they match real player populations.**

- MIMIC states its personas are unvalidated.

- MeepleLM (arXiv 2601.07251, Jan 2026) fine-tuned Qwen3-8B on 150K reviews. Its rank agreement with real ratings stays low (Kendall τ 0.28), and its user study had 10 people.

- Recommendation: limit personas to 3–4 behavioural policies that a policy prompt can enforce and that produce measurably different traces:

  - novice: follows on-screen prompts only, no prior genre knowledge;
  - speedrunner: shortest path, skips text;
  - explorer: maximises visited states and interactable elements;
  - adversarial: invalid inputs, cancels, back-navigation.

  Confidence: medium.

**F13. Budgets should be in actions, not wall time, because LLM latency varies.** TITAN stalls after 20 no-progress actions, and Lap ran 150 iterations. Short loops work best: Google trained per "few-minute gameplay loop" rather than end to end. Seeded starts or save states give the same preconditions across runs. Confidence: medium; the numbers are paper settings, not general norms.

**F14. Real-time genres need a pausable or stepped harness.** MIMIC (12.4 s per action) and Lap both state real-time games are out of scope.

- **3D arena:** the LLM picks macro intents ("engage nearest enemy", "retreat to cover"), executed by a scripted controller. Raw input from the LLM is ruled out.
- **RTS:** macro decisions at a fixed tick with the game paused.
- **UI survival campaign:** the best fit, since it is turn-like and textual.

Confidence: medium. This is an inference from the papers' stated limitations.

### 3. Oracles

**F15. Most confirmed bugs come from mechanical oracles, not from LLM judgement.** In TITAN, 11 of 15 bugs were crashes and 2 were hangs. Logic bugs (2) needed expert rules. Lap's results were crashes. Recommended order of trust: Confidence: high.

1. crash or engine error in the log;
1. game-side assertion or invariant violation;
1. goal unmet within budget, with the state diff;
1. stuck or no-progress detector;
1. time or perf anomaly against a baseline;
1. LLM-only observation.

**F16. Unconfirmed LLM-authored findings are unreliable.**

- TITAN: 30% false alarms.
- VideoGameQA-Bench: hallucinated clipping.
- BugCraft: 34.9% reproduction.
- Zhang et al.: AI errors mislead human testers.

Rule: a finding is "bug" only with game-side evidence or a successful replay. Otherwise it is "observation" and needs human confirmation in the hub. Confidence: high.

**F17. Comparing the agent's claim against ground-truth state catches hallucinations.** When the agent says "I built 3 barracks", the harness queries the true count. iv4XR assertions and TITAN abstract state both rely on ground truth from the game API. Confidence: high for the principle.

**F18. Reproducibility needs:** a fixed RNG seed, a recorded action log replayed without the LLM, the build ID, and temperature 0. TITAN still reports non-determinism at temperature 0, so a finding is confirmed by replaying the action log, not by re-running the LLM. Confidence: medium. Replay determinism in Godot physics is UNVERIFIED and left to the sibling harness research.

### 4. Experience signals

**F19. LLMs under-report confusion.** Synthetic Cognitive Walkthrough (Zhong, McDonald, Hsieh; CHI '26, arXiv 2512.03568, Dec 2025):

- LLMs completed 97–100% of tasks against 88% for humans, and took about 7.5 steps against 10.4.
- They found 3 failure points against 10 from humans: they "pick the most plausible option" and do not treat competing options as confusing.
- Asked directly with full history, they did predict human-flagged failure points (odds ratio about 2–7.5, inter-run κ about 0.63).
- Without history, their judgements were inconsistent.

Confidence: high (one study, 10 humans, mobile apps).

**F20. Signals ranked by trust:**

- **Relative difficulty across levels** (Xiao and Yang): medium–high.
- **Asking with context "where might a novice fail?"**: medium.
- **Self-reported confusion during play**: low; it under-reports.
- **Fun or rating prediction** (MeepleLM τ 0.28): low.
- **Behaviour-derived signals**: likely more trustworthy, but UNVERIFIED (no paper validates them directly). Examples: retries, back-navigation, a UI element ignored for N steps, budget overrun on a tutorial step.

Every experience finding should be routed to a human playtest as a hypothesis (see doc 32, section 5).

### 5. Reporting

**F21. The report fields that recur across sources** (TITAN, modl.ai, Razer, VideoGameQA-Bench):

- title;
- goal;
- action summary or steps to reproduce;
- expected vs actual;
- evidence (state snapshot, screenshot or video, log excerpt);
- severity (AI-suggested, human-editable);
- tags or type (crash, hang, logic, UI, visual).

Confidence: high.

**F22. No game-specific study on deduplicating findings was found.** Tools from mobile apps exist (TANGO, ICSE 2021: top-2 accuracy 83%; JANUS, ICSE 2024) but are video-based and untested on games. For this suite, deterministic fingerprints are recommended over LLM similarity: oracle type, scene path, failing assertion ID, top stack frame and normalised error text. UNVERIFIED as a published game practice.

**F23. Cost per scenario.** The only published per-action figure is MIMIC's: $0.05–0.06 with GPT-4o (2025 prices), 12.4 s per action, and "thousands of USD" for the whole study. Derived estimate for a 150-action scenario: about $8–9 and about 31 minutes. UNTESTED for Claude models and for a compact text state. The tool should record measured token use per run instead of shipping this estimate.

### 6. When non-LLM bots are the better tool

| Tool                                   | Best for                                                                     | Weak at                                                                                          | Evidence                                                                     |
| -------------------------------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| Scripted or deterministic tests        | regressions, known flows, CI gate, invariants                                | new paths                                                                                        | Rare GDC 2019; iv4XR                                                         |
| Random or monkey input                 | crash and fuzz soak in UI, cheap                                             | deep goals (Monkey 0 score, 3–5% coverage in Lap)                                                | Lap 2025                                                                     |
| Curiosity or coverage RL               | 3D map reachability, stuck spots, falling out of the world                   | training cost, goal-directed tasks                                                               | EA SEED 2021–22; Google 2021                                                 |
| Imitation or human-like bots           | difficulty and balance at scale                                              | need player data                                                                                 | King 2018; Google 2021                                                       |
| Mass simulation (MCTS or RL self-play) | RTS or card balance                                                          | UX                                                                                               | Stadia Chimera 2021                                                          |
| LLM agent                              | language goals, UI flows, tutorials, logic quests, triage and report writing | real-time control, cost, hallucination, coverage of large spaces (half of human coverage in SPD) | TITAN, MIMIC, Lap                                                            |
| Hybrid LLM-guided RL                   | coverage of changed code                                                     | setup                                                                                            | SMART, arXiv 2512.12706 (Dec 2025): over 94% branch coverage of changed code |

## Trend analysis

- **Shift since 2024.** RL coverage agents (2019–2022) are giving way to LLM agents with explicit oracles and human triage (2025–2026).
- **Vendors converge on one product.** modl.ai, nunu.ai and Razer all offer natural-language test tasks, pass/fail results and auto-written bug reports for humans to edit.
- **Hybrids are emerging.** Examples are LLM-guided RL (SMART) and macro-action executors.
- **Personas move from utility functions to prompts,** still without validation against real players.
- **Vision benchmarks improve, but specificity remains the bottleneck.**

## Recommended scenario file format (JSON)

```json
{
  "schema": "mozg.playtest.scenario/1",
  "id": "survival-tutorial-complete",
  "genre": "ui_survival",
  "goal": "Complete the tutorial and reach day 2.",
  "persona": "novice",
  "persona_rules": ["Use only information visible on screen", "Do not use debug commands"],
  "preconditions": {
    "build": "required; filled by runner",
    "save_state": "res://test/saves/tutorial_start.tres",
    "seed": 1234,
    "settings": {"locale": "en", "difficulty": "normal"}
  },
  "success": [{"query": "game.day", "op": ">=", "value": 2},
              {"query": "tutorial.completed", "op": "==", "value": true}],
  "invariants": [{"id": "hp_nonneg", "query": "player.hp", "op": ">=", "value": 0},
                 {"id": "no_script_error", "log_absent": "SCRIPT ERROR"}],
  "milestones": [{"id": "built_shelter", "query": "buildings.shelter.count", "op": ">=", "value": 1,
                  "expect_within_actions": 40}],
  "budget": {"max_actions": 150, "max_wall_seconds": 1800, "max_tokens": 400000,
             "stuck_after_no_progress_actions": 20},
  "action_space": "ui_and_macro",
  "observe": {"state_queries": ["ui.visible_controls", "player", "inventory", "game.day"],
              "screenshot_every_n_actions": 10},
  "experience_probes": ["After each milestone: name any UI element whose purpose was unclear, with its node path."],
  "repeat": {"runs": 3, "seeds": [1234, 1235, 1236]}
}
```

Notes on the format:

- `query` names refer to a state API exposed by the harness, which the sibling researcher covers.
- `success` and `invariants` are evaluated by the harness, never by the LLM.
- Arena and RTS scenarios use `action_space: "macro"` with the game paused between decisions.

## Oracle rules

1. **Pass:** every `success` predicate is true according to the harness query, no invariant was violated, and the log has no `SCRIPT ERROR` or crash, all within budget. The run ends with an explicit summary line (project rule: never judge by exit code alone).
1. **Fail-bug:** a crash, engine error, or invariant violation. The finding class is `bug`, with confidence `confirmed` once the action log replays it.
1. **Fail-stuck:** N actions in a row (default 20, from TITAN 2025) with no change in the progress vector (milestones met, distance to goal, new UI states). Class `suspected_softlock`. It is only promoted to `bug` when a scripted or second-persona run from the same snapshot also fails.
1. **Fail-budget:** budget exhausted with the goal unmet and no stuck signal. Class `difficulty_or_agent_limit`, never `bug`.
1. **Milestone late:** a milestone met after `expect_within_actions`. Class `observation:pacing`.
1. **Claim check:** every factual claim in the agent's report ("built 3 barracks", "button X does nothing") is checked against a state query. Claims that contradict state are dropped and counted as `hallucination` in the run metrics.
1. **Experience:** LLM experience output is class `ux_hypothesis` and needs a node path or screenshot reference. It is never shown with `bug` severity.
1. **Reproduce:** a `bug` is confirmed by replaying the recorded action log with the same seed, save state and build, without the LLM.

## Finding schema

```json
{
  "schema": "mozg.playtest.finding/1",
  "id": "f-<sha1 of fingerprint>",
  "fingerprint": {"oracle": "invariant", "scene": "res://ui/build_menu.tscn",
                  "assertion_id": "hp_nonneg", "top_frame": "build_menu.gd:88", "error_norm": "..."},
  "class": "bug | suspected_softlock | difficulty_or_agent_limit | observation | ux_hypothesis",
  "confidence": "confirmed | replay_failed | unreplayed",
  "severity_suggested": "S1-S4",
  "title": "...",
  "scenario_id": "survival-tutorial-complete",
  "run_ids": ["r-2026-11-13-001"],
  "build": "git sha / version",
  "seed": 1234,
  "persona": "novice",
  "expected": "...", "actual": "...",
  "repro": {"action_log": "runs/r-001/actions.jsonl", "from_action": 0, "to_action": 57},
  "evidence": {"state_before": "...json", "state_after": "...json", "state_diff": {},
               "screenshot": "runs/r-001/057.png", "log_excerpt": "..."},
  "agent_report": "free text, kept verbatim, never used as evidence",
  "occurrences": 3,
  "cost": {"actions": 57, "tokens_in": 0, "tokens_out": 0, "wall_s": 0},
  "hub": {"status": "new | confirmed | rejected | redo", "note": ""}
}
```

Findings with the same `fingerprint` hash merge into one entry, and `occurrences` and `run_ids` grow.

## Checkable rules

1. Every scenario has at least one machine-checkable `success` predicate. A goal given only in natural language is rejected.
1. Every scenario declares `seed`, `save_state` or an explicit "fresh start", and `budget.max_actions`.
1. A finding of class `bug` carries oracle evidence (log, assertion or state diff) and a replay result.
1. `agent_report` text is never the only evidence for any class except `ux_hypothesis`.
1. Every finding names its build, seed, persona and scenario ID (extends doc 32 rule 23).
1. Each run records tokens, actions and wall time; a run without cost data is invalid.
1. Real-time scenarios (arena) use macro actions or a paused or stepped harness. The LLM issues no per-frame input.
1. A `ux_hypothesis` references a node path or screenshot and is shown in the hub as "needs human playtest".
1. A `suspected_softlock` is reported as a bug only after a second, independent policy from the same snapshot also fails.
1. A scenario is run at least 3 times (with seeds or personas) before its pass rate is reported; a single-run pass/fail is labelled as such.

## What a tool could check automatically

- **Scenario lint:** schema validation; success and invariant queries resolve against the harness's query list; budgets present; persona drawn from the allowed set.
- **Run validation:** the summary line is present; the action log parses; seed and build are recorded; cost fields are filled.
- **Claim checker:** extract numeric or state claims from the agent's report with a regex or a structured output field, query the state, and count contradictions as a hallucination rate per run.
- **Replay confirmer:** re-run the action log headless and mark `confirmed` or `replay_failed`.
- **Dedup:** fingerprint hash, merge occurrences, and show in the hub a count per fingerprint over the last N builds (regression detection).
- **Stuck detector:** compare progress vectors and loops in the visited-state hash (the same state hash 3 or more times in a window).
- **Flakiness:** a scenario passing under 100% on fixed seeds marks the scenario or the game as non-deterministic; report it.
- **Cost report:** mean and p90 tokens, and dollars per scenario across runs. Alert when a run exceeds `max_tokens`.
- **Coverage side-channel (optional):** visited scenes, opened UI screens and pressed controls against the full lists in the project; report controls never reached.

## Risks and uncertainties

- **Few papers, few games.** The evidence base is small and young: TITAN covers 2 games, Lap 1, MIMIC 3, and the CHI walkthrough study apps rather than games. Numbers will move with model releases.
- **Unknown false-alarm rate here.** The 30% figure is for MMORPGs with GPT-4o; the rate for Claude on Godot is unknown (UNTESTED).
- **Vendor claims are unaudited.** modl.ai, nunu.ai and Razer publish no accuracy figures.
- **Cost estimate is not from this stack.** The per-scenario cost comes from GPT-4o 2025 pricing and MIMIC's action granularity. Measure it instead.
- **Godot determinism and replay fidelity is UNVERIFIED** (physics, timers, threads). If replay is not deterministic, the "confirmed" class weakens.
- **Experience signals may mislead designers.** They under-report confusion (F19), and AI errors bias human testers (F6).
- **GDC talks are mostly login-gated.** Only abstracts were used (Rare 2019, La Forge).
- **Some numbers were read from abstracts only:** Wuji, the EA SEED papers, Zhang et al., BugCraft failure modes, and Politowski's sample size.
- **Data quality issues:**
  - CONFLICT DETECTED: TITAN bug counts (4 / 9 / 15), as noted in F1.
  - CONFLICT DETECTED: VideoGameQA-Bench v1 says frontier models produce useful bug reports for "up to 50%" of glitches; v2 gives 52–54% on its bug-report task. The difference is likely the version and the metric.
  - Lap names its tool and model inconsistently.

## Sources

**Papers**

- TITAN, LLM agents for automated video game testing (Sep 2025): https://arxiv.org/abs/2509.22170 and the full HTML at https://arxiv.org/html/2509.22170v1 (architecture, oracles, 30% false alarms, report format)
- MIMIC (Oct 2025): https://arxiv.org/html/2510.01635v1 (personas, coverage, cost per action, limits)
- MIMIC-Py (Apr 2026), via an aggregator summary: https://www.emergentmind.com/papers/2604.07752
- Lap, Towards LLM-Based Automatic Playtest (FSE Companion '25): https://arxiv.org/html/2507.09490v1
- Xiao and Yang, LLMs measuring game difficulty (Oct 2024): https://arxiv.org/html/2410.02829v1
- Bug detection in LLM-powered text games (ACL Findings 2024): https://arxiv.org/abs/2406.04482
- BugCraft (ASE'25): https://arxiv.org/abs/2503.20036
- SMART (Dec 2025): https://arxiv.org/abs/2512.12706
- Human-AI collaborative game testing with VLMs (2025/2026): https://arxiv.org/abs/2501.11782
- GlitchBench (CVPR 2024): https://openaccess.thecvf.com/content/CVPR2024/html/Taesiri_GlitchBench_Can_Large_Multimodal_Models_Detect_Video_Game_Glitches_CVPR_2024_paper.html and https://arxiv.org/html/2312.05291v2
- VideoGameQA-Bench (NeurIPS 2025): https://arxiv.org/html/2505.15952v2
- Synthetic Cognitive Walkthrough (CHI '26): https://arxiv.org/html/2512.03568v1
- MeepleLM (Jan 2026): https://arxiv.org/html/2601.07251v1
- EA SEED, curiosity coverage agents (CoG 2021): https://arxiv.org/abs/2103.13798 and https://www.ea.com/seed/news/cog2021-curiosity-driven-rl-agents
- EA SEED, deep RL for game testing: https://arxiv.org/pdf/2103.15819
- EA SEED, CCPT: https://arxiv.org/pdf/2202.10057v1.pdf
- Wuji (ASE 2019): https://2019.ase-conferences.org/details/ase-2019-papers/39/Wuji-Automatic-Online-Combat-Game-Testing-Using-Evolutionary-Deep-Reinforcement-Lear
- iv4XR/aplib (AAMAS 2020): https://ifmas.csc.liv.ac.uk/Proceedings/aamas2020/pdfs/p1972.pdf and the iv4XR framework report at https://zenodo.org/record/7503905/files/D2.3%20-%20Final%20version%20of%20iv4xr%20Framework-final.pdf
- Procedural personas: https://arxiv.org/pdf/1802.06881
- King, human-like playtesting (2018): https://www.Gwern.net/doc/reinforcement-learning/imitation-learning/2018-gudmundsson.pdf
- Politowski et al., developer survey (GAS '22): https://arxiv.org/abs/2202.12777
- Politowski et al., literature survey (2021): https://arxiv.org/pdf/2103.06431
- Duplicate video bug reports in mobile apps (JANUS, ICSE 2024): https://arxiv.org/html/2407.08610v1

**Vendor and industry pages**

- Google Research blog, quickly training game-playing agents (Jun 2021): https://research.google/blog/quickly-training-game-playing-agents-with-machine-learning/
- Google Research blog, leveraging ML for game development (Mar 2021): https://research.google/blog/leveraging-machine-learning-for-game-development/
- modl.ai: https://modl.ai/
- nunu.ai on Y Combinator: https://www.ycombinator.com/companies/nunu-ai
- nunu.ai seed round coverage: https://gamesbeat.com/nunu-ai-raises-6m-for-ai-agents-dubbed-unembodied-minds-for-game-testing/
- Razer QA Companion-AI at GDC 2026 (Mar 2026): https://www.razer.com/blog/ai-that-plays-to-test-razer-qa-companion-ai-at-gdc-2026/
- Wyvrn QA documentation: https://doc.wyvrn.com/docs/razer-ai-gaming-tools/razer-qa-co-ai/
- Rare, GDC 2019 talk (abstract only): https://gdcvault.com/play/1026366/Automated-Testing-of-Gameplay-Features
- Ubisoft La Forge publications: https://www.ubisoft.com/en-us/studio/laforge/publications

**Secondary (used for leads only)**

- Emergent Mind topic page: https://www.emergentmind.com/topics/llm-agents-as-game-testers
