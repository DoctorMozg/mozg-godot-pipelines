# LLM and VLM agents that play games (state of the art, November 2026)

Source: web research of 2026-11-13 against arXiv papers (2023–2026), benchmark leaderboards, Anthropic's launch post and pricing docs, and one LessWrong write-up (secondary). Scenario cost and latency are derived, not measured: UNTESTED with Claude on Godot 4.7.2.

## Executive Summary

As of November 2026, frontier models play games well under three conditions:

- the game state is given as structured text,
- the game clock waits for the model,
- actions are semantic (move to a cell, pick a card) rather than raw key timing.

Under raw-pixel, real-time conditions they still mostly fail:

- **VideoGameBench (2025):** the best model completed under 2% of the games.
- **OmniGameArena (June 2026):** the best 3D-parkour score was 0.20.
- **NetHack:** at most 13.2% on the BALROG leaderboard.

Long-horizon successes all came from heavy harnesses: tools, pathfinding, memory notes and context compaction. Two runs show this:

- Gemini 2.5 Pro took about 406 hours to finish Pokémon Blue.
- Claude Opus 4.7 beat Pokémon Red in May 2026, after more than a year of harness work.

For a Godot playtest harness, this points to:

- a JSON state snapshot as the main observation, with a small screenshot only on demand;
- a game paused between decisions;
- semantic actions, with low-level input only as a fallback;
- a short notes file instead of long history;
- hard stopping rules for loops and stalls.

For real-time 3D action and RTS, Claude should write and judge a scripted bot run at full speed rather than steer frame by frame.

## Key Findings

### 1. Benchmarks and scores by genre

**1a. VideoGameBench (Princeton, arXiv 2505.18134, May 2025)** — high confidence (primary paper, tables read directly)

- The test set has 7 public games plus 3 secret ones: Civilization I, Need for Speed, The Incredible Machine, Pokémon Crystal, Doom II, Kirby, and Link's Awakening. Models see raw frames only.

- **Scores on the full test set:**

  | Model             | Full test set |
  | ----------------- | ------------- |
  | Gemini 2.5 Pro    | 0.48%         |
  | GPT-4o            | 0.09%         |
  | Claude 3.7 Sonnet | 0%            |

- **Lite (game paused during inference):** 1.6% for all three models above.

- **Practice tasks:**

  | Task               | Claude 3.7 Sonnet | Gemini 2.5 Pro | GPT-4o |
  | ------------------ | ----------------- | -------------- | ------ |
  | Location clicking  | 100%              | 100%           | 30%    |
  | 2D maze navigation | 80%               | 50%            | 30%    |
  | Mouse dragging     | 10% (others ≤10%) | 0%             | 0%     |

- **Cost per run (Sonnet 3.7):** up to $30, for example Civilization I at $30.00 and Pokémon Crystal at $29.64.

- No 2026 VideoGameBench update with newer models was found. UNVERIFIED: whether current models do better on it.

**1b. BALROG (ICLR 2025; leaderboard at balrogai.com, fetched 2026-11-13)** — medium-high confidence

- Six games: BabyAI, Crafter, TextWorld, Baba Is AI, MiniHack, NetHack. The language-only leaderboard now lists newer models:

  | Model             | Average progress | NetHack | Baba Is AI | BabyAI |
  | ----------------- | ---------------- | ------- | ---------- | ------ |
  | GPT-6-Astra-Max   | 68.3%            | 13.2%   | 100%       | 100%   |
  | Claude-Opus-5-Max | 63.4%            | 7.3%    | 95.8%      | 100%   |
  | Gemini-3.1-Pro    | 56.9%            | 3.0%    | —          | —      |
  | Claude-Opus-4.5   | 43.5%            | 2.0%    | —          | —      |

- Short, discrete, text-described tasks are close to solved. Long-horizon roguelikes are not.

- The VLM board on the site was not updated past 2025 models. UNVERIFIED: frontier vision-mode BALROG scores for 2026 models.

**1c. lmgame-Bench (arXiv 2505.15146, ICLR 2026)** — high confidence

- Six games: Sokoban, Super Mario Bros, Tetris, 2048, Candy Crush, Ace Attorney.
- Without a harness, about 40% of model runs did not beat random play. With perception and memory modules, 86.7% did.
- Examples of the harness effect: o3 on Candy Crush went from 106 to 647, and on Mario from 1955 to 3445.

**1d. Orak (Krafton, arXiv 2506.03610, ICLR 2026)** — high confidence

- 12 games served through MCP, with text-state observations by default.

- **Turn-based and menu-driven games scored high:**

  | Game            | Best score |
  | --------------- | ---------- |
  | Baba Is You     | 100        |
  | Darkest Dungeon | 93.7       |
  | Stardew Valley  | 92.3       |
  | Ace Attorney    | 91.7       |
  | Pokémon Red     | 88.9       |

- **Action games scored low:**

  | Game               | Best score |
  | ------------------ | ---------- |
  | Super Mario        | 38.0       |
  | Street Fighter III | 33.3       |
  | 2048               | 11.5       |
  | Slay the Spire     | 51.9       |

- **StarCraft II (Orak's only real-time test):**

  - Easy, paused: every model scored 100.
  - Easy, real time: only GPT-4o kept 100; others dropped to 0.
  - Hard, real time: every model scored 0.

- Latency per step was 19.6 to 99.2 seconds.

**1e. OmniGameArena (arXiv 2606.09826, 2026-06-09)** — medium-high confidence (read through the Hugging Face paper page)

- 12 new Unreal Engine 5 real-time games, played with chunked keyboard and mouse input.

- Best scores by game:

  | Game                          | Best score | Model             |
  | ----------------------------- | ---------- | ----------------- |
  | ObstacleRun3D (3D parkour)    | 0.200      | Claude Sonnet 4.6 |
  | ObstacleRun2D (2D platformer) | 0.473      | GPT-5.5           |
  | CueChase (3D exploration)     | 0.840      | Claude Opus 4.6   |
  | MonsterShoot (shooter)        | 0.710      | Gemini 3.1 Pro    |
  | Coop games                    | ≤0.368     | —                 |

- Model time per decision was about 4 to 7 seconds for most models and about 16 seconds for GPT-5.5.

- Counting that latency against the game clock cost GPT-5.5 0.408 points on MonsterShoot. In SoloCraft, it got 8 actions per episode under that mode against 43 when paused.

**1f. Pokémon runs** — mixed confidence, see each item

- **Gemini 2.5 Pro finished Pokémon Blue in about 406 hours (2025).** It used a pathfinder tool over an XML map, a boulder-puzzle sub-agent, and a summary every ~100 actions. Source: the PokeAgent paper (arXiv 2603.15563). Medium confidence; the run itself was independent, not Google's.
- **GPT-5 finished Pokémon Red in 6,470 steps.** Per arXiv 2603.15563. Medium confidence.
- **Claude Opus 4.7 beat Pokémon Red, reported 2026-05-16.** The harness was screenshot-based with memory notes, a zoom tool and a screenshot-reference tool. Earlier Opus 4.5 runs took about 29k steps to reach Silph Co. and about 112k steps in Cinnabar Mansion. Medium confidence: the source is a LessWrong write-up, not an Anthropic post. UNVERIFIED by an Anthropic primary source.
- **Claude Fable 5 beat Pokémon FireRed "with a minimal, vision-only harness … using only raw game screenshots", per Anthropic's launch post of 2026-06-09.** The same post says Fable 5 builds a self-running factory in Factorio, and reaches Slay the Spire's final act three times as often as Opus 4.8 when using file-based memory. High confidence that the claim was made. No step count, time, cost or protocol was published, so the result cannot be reproduced.
- **PokeAgent speedrun (Pokémon Emerald, first gym; arXiv 2603.15563, March 2026):** raw frontier VLMs without a harness reached effectively 0%. The organisers' baseline harness used MCP tools for A\* pathfinding, buttons and knowledge lookup, sub-agents, and context compaction. The authors call a harness "a prerequisite, not a marginal optimization", and found vision errors to be the main failure. They also note that CLI agents (Claude Code, Codex CLI, Gemini CLI) "make wrong assumptions about progress" over long non-linear play.

**1g. Real-time 3D with purpose-trained models** — medium confidence

- Lumine (ByteDance, arXiv 2511.08892, Nov 2025) reads pixels at 5 Hz and acts at 30 Hz. It completes Genshin Impact's 5-hour Mondstadt storyline at human-level speed.
- This needed a fine-tuned VLM plus quantisation and speculative decoding. A general API model cannot do the same.
- SIMA 2 (DeepMind, arXiv 2512.04797) reports "substantially closes the gap" with humans but gives no numbers in the abstract. UNVERIFIED: the per-game percentages quoted in the press.

**1h. LLM game testing** — medium confidence

- **GBQA (arXiv 2604.02648, April 2026):** 30 games with 124 planted bugs. The best result was Claude Opus 4.6 (thinking), which found 48.39% of the bugs.
- **TITAN (arXiv 2509.22170, Sept 2025):** an LLM tester for MMORPGs. It uses state abstraction, action prioritisation, an action-trace memory and LLM bug oracles. It reports 95% task completion and use in 8 production QA pipelines. Example find: a quest that needed 6 kills was marked complete after 5.
- **VideoGameQA-Bench (NeurIPS 2025):** VLMs detected glitches in images with 82.8% accuracy and in video with 78.1%. Clipping and body-pose glitches were hard. Bug reports were useful for up to 50% of real glitches.

### 2. Observation: screenshots, structured text, or both

- **Structured text matches or beats screenshots for grid, turn-based and menu games.** High confidence.
  - Orak: image-only input caused "a substantial performance drop". Adding an image to text sometimes hurt: GPT-4o on Ace Attorney fell from 85.3 to 53.5.
  - BALROG: switching to vision lowered GPT-4o from 32.3% to 22.6% and Llama-3.2-11B from 16.8% to 8.4%, but raised Claude 3.5 Sonnet from 32.6% to 35.5%.
  - lmgame-Bench: converting the screen to text coordinates ("Box at (2,3)") removes perception errors.
- **When spatial or visual detail matters, combining both inputs helps.** Medium confidence.
  - Orak, Street Fighter III, Claude 3.7: text 16.7, image 23.3, both 33.3.
- **Which observation works best depends on the model.** Medium confidence; OSWorld data is from 2024.
  - In OSWorld (arXiv 2404.07972), GPT-4V scored 5.26% on screenshots alone, 12.17% with screenshot plus accessibility tree, and 11.77% with set-of-marks. GPT-4o did worse with set-of-marks (4.59%).
  - About 6,000 tokens of accessibility tree covered 90% of observations. Text history helped and image history did not.
- **Vision keeps improving.** Fable 5's vision-only FireRed run (June 2026) shows pixel-only play is now possible over very long horizons for the top model. It is still slow and costly, and no figures were published.

CONFLICT DETECTED: The BALROG paper's text says Claude and Gemini stay "consistent" between modes, while its own table shows both improve with vision (+2.8 and +4.8 points). The table is the more precise source.

**Image cost on Claude (pricing and vision docs, fetched 2026-11-13):**

- Tokens = ⌈w/28⌉ × ⌈h/28⌉. A 640×360 frame is about 299 tokens, 1280×720 about 1,196, and 1920×1080 about 2,691 on Claude 4.7 and later.
- This agrees with the project's earlier result in docs/research/14-web-fast-feedback-loop.md: a snapshot takes about 103 ms against 1.7 to 2.7 s for a PNG.

### 3. Action interface and clock control

- **Pausing the clock is necessary but not enough.** High confidence.
  - VideoGameBench Lite (paused) improved only from 0.48% to 1.6%.
  - Orak's StarCraft II easy level went from 100 for every model when paused to 0 for most models in real time.
  - OmniGameArena runs every game paused during inference and offers a second mode that adds the model's latency back to the game clock. This is a reusable pattern: one mode scores decision quality, the other approximates real-time play.
- **Low-level input is weak.** High confidence.
  - Mouse dragging: ≤10% in VideoGameBench practice.
  - "Knowing-doing gap": a model names the right door but keeps pressing the wrong direction (VideoGameBench, BALROG).
  - SIMA 2 lists imprecise keyboard and mouse control as a limitation. UNVERIFIED in the primary source; reported by The Decoder.
- **Semantic and tool actions are what made long runs succeed.** High confidence.
  - Gemini's pathfinder, PokeAgent's A\* tool, Orak's MCP tools, Voyager's code skill library (3.3× more items, tech tree up to 15.3× faster; arXiv 2305.16291), and Cradle's code-generated input (arXiv 2403.03186).
- **Real time at decision latencies of 4 to 99 seconds is out of reach for API models.** High confidence.
  - Only Lumine-style fine-tuned models reach 30 Hz.
  - RealtimeGym (arXiv 2511.04898) shows that splitting a fast reactive thread from a slower planner helps when the clock keeps running.

### 4. Memory, long horizon and failure modes

**Documented failures:**

- Looping and revisiting the same areas (Doom II, TextWorld, Silph Co.).
- Overwriting the scratchpad, for example GPT-4o forgot it already had its starter Pokémon.
- Believing things that did not happen, for example "I talked to the NPC".
- Shooting dead enemies.
- Spatial errors: getting cornered in corridors, walking into objects, misreading doors.
- "Panic" chains of compounding mistakes, goal oscillation, and corrupted memory (PokeAgent battles).
- Memory clean-ups that delete useful notes (Claude Pokémon).
- Peak skill in the middle of a run followed by decline: OmniGameArena's reflection rounds lost 0.40 to 0.52 for Opus models.

**What helped:**

- Persistent notes files (Fable 5 on Slay the Spire, Claude Pokémon).
- Periodic summaries (Gemini, every ~100 actions).
- A short history window (16 observations in BALROG, 20 steps in VideoGameBench).
- Stuck detectors: VideoGameBench stops a run when the frame is unchanged for 100 steps, after 3 deaths in the same place, or after about 2,000 steps with no checkpoint.
- Stuck reminders (the Claude Pokémon harness).

Giving the agent wiki or web access sometimes hurt, because advice from other game versions contradicted the actual game (PokeAgent).

Confidence: high for the failure taxonomy, medium for the effect sizes of the fixes.

### 5. Cost and speed

**Measured per-turn cost (PokeAgent Table 3, March 2026):**

| Model                     | Input tokens/turn | Output tokens/turn | Cost/turn |
| ------------------------- | ----------------- | ------------------ | --------- |
| Claude Opus 4.6           | about 2,110       | about 137          | $0.014    |
| Claude Sonnet 4.6         | —                 | —                  | $0.0087   |
| GPT-5.2 (reasoning-heavy) | —                 | 4,270              | $0.070    |

Cost is driven mostly by output and reasoning length, not by game length.

**Current Claude prices (2026-11-13):**

| Model                          | Input per M tokens | Output per M tokens | Cache read per M tokens |
| ------------------------------ | ------------------ | ------------------- | ----------------------- |
| Opus 5.5                       | $4                 | $20                 | $0.20                   |
| Sonnet 5.5                     | $2                 | $10                 | $0.10                   |
| Haiku 5.5 (prompts up to 100k) | $0.10              | $0.50               | —                       |

**Wall-clock per decision:**

- 4 to 7 seconds for most frontier models in OmniGameArena (2026), 16 seconds for GPT-5.5.
- 19.6 to 99.2 seconds in Orak's reflection-and-planning agent (2025 models).
- Claude Code adds its own tool-call overhead. UNVERIFIED: no measurement of that overhead was found.

**Estimate for a 2 to 5 minute scenario** (derived here, not measured):

- Semantic actions covering 2 to 5 seconds of game time each give about 30 to 150 decisions.
- Assumed per-decision input: about 3k fresh tokens (JSON snapshot plus an optional 640×360 frame), a cached 10k prefix, and 300 to 1,500 output tokens. That is about $0.02 to $0.045 per decision on Opus 5.5.
- Totals: roughly $0.60 to $7 per scenario run and 3 to 15 minutes of wall-clock.
- If decisions are made every 0.5 seconds of game time with raw keys, a 5-minute scenario needs about 600 decisions and 1 hour or more of wall-clock. This is impractical.
- Confidence: medium. The arithmetic is checkable; the latency figure comes from other harnesses.
- Measured 2026-11-15 (docs/plan.md, P6): Opus 5.5 headless in Claude Code on AloneGodot, 6 steps and 14 turns over 382 s cost $0.65, about $0.05 a turn, with about 52k prompt tokens a turn, nearly all cache reads.

### 6. Which genres are realistic today

**Realistic (high confidence):**

- UI- and menu-heavy games: campaign maps, inventory, crafting, dialogue, shops, settings.
- Turn-based tactics and card games.
- Puzzle games.
- Management and survival loops when driven by structured state and semantic actions.
- Evidence: Orak scores of 88 to 100 on Stardew Valley, Darkest Dungeon, Ace Attorney and Pokémon; BALROG BabyAI and Baba Is AI at about 96 to 100% for Opus 5 / GPT-6 class models; GBQA at about 48% of planted bugs found.

**Partly realistic (medium confidence):**

- 2D platformer or action segments, paused, with semantic actions (`jump_to`, `attack(target)`). Expect scores of about 0.3 to 0.5, not mastery: Orak Mario 38, OmniGameArena 2D platformer 0.47.
- Good for "can the level be completed / is the exit reachable" checks, not for judging difficulty.

**Not realistic for LLM-in-the-loop control (high confidence):**

- **Real-time 3D action** with camera control and dodging: best 0.20 on 3D parkour; VideoGameBench Doom and Quake made no progress.
- **RTS micro at real speed:** StarCraft II hard level scored 0 in real time.
- For these genres, use the LLM to write scripted or behaviour-tree bots and input recordings, run them at full speed headless, and have the LLM read the logs and metrics. This follows the Voyager and Cradle code-as-action pattern.
- An RTS at the strategic layer (paused, with commands like "train 5 units, attack region B") is in the partly realistic tier.

## Trend Analysis

- Scores rose fast on discrete, text-described tasks: BALROG average progress went from about 32% (late 2024) to 63 to 68% (Sept 2026). NetHack and real-time 3D stay low.
- Harnesses are getting thinner as models improve. Claude Pokémon removed its critic and its hints, and Fable 5 needs no navigation tool. A harness built now should keep tools optional and measurable rather than baked in.
- Benchmarks increasingly expose games through MCP or tool interfaces (Orak, PokeAgent) and separate paused decision quality from real-time scoring (OmniGameArena). The mozg harness can use the same split.
- LLM QA/testing research (TITAN, GBQA, VideoGameQA-Bench) is converging on: state abstraction, action prioritisation, trace memory, LLM oracles and structured bug reports.

## Recommended design for an LLM playtest harness (Godot 4.7, Claude Code)

**Observation**

- Primary: a JSON snapshot from the input-bridge autoload containing:
  - a scenario-relevant subset of the node tree (player, enemies within radius, interactables, UI controls that are visible and focusable);
  - global positions, a grid or nav cell, HP and resources, and active dialogue text;
  - a list of "affordances", meaning the valid semantic actions with target ids. Keep it to 6k tokens or less, following the OSWorld guidance.
- Secondary, on demand: a `look` tool that returns a 640×360 JPEG (about 299 tokens) of the viewport or of a zoomed region. Use it for visual-bug checks and for 2D/3D spatial confirmation. Never send it on every step by default.
- Send diffs since the last step ("enemy_3 died", "door_A opened") so the model does not keep acting on things that already changed.

**Actions**

- Semantic tools that map to game verbs: `move_to(node|cell)`, `interact(node)`, `press_ui(control_path)`, `use(ability, target)`, `wait(seconds)`.
- `move_to` should use the game's own navigation, as Gemini's pathfinder and PokeAgent's A\* did.
- A fallback `input(action_name, hold_s)` for raw input-map actions.
- Every action returns `ok`, `invalid` (with a reason) or `interrupted`, plus the frames elapsed. Invalid actions are fed back, as BALROG does.

**Clock control**

- The game is paused between decisions and each action advances a fixed number of physics frames, or runs until the action completes or times out. This matches VideoGameBench Lite and OmniGameArena's paused mode.
- An optional mode adds the measured decision latency back as game time, for a rough real-time difficulty signal.
- For real-time 3D or RTS, the LLM writes a scripted bot or an input timeline and the harness runs it headless at full speed. The LLM only plans and judges.

**Memory**

- A notes file the agent edits itself: goal, facts learned, places visited, open questions. Only append or edit with a reason, and keep a copy of every version, because note overwrites caused memory loss in earlier runs.
- History window of the last 10 to 20 steps in text only.
- Write a summary every N steps, or hand the scenario to a fresh subagent so the main Claude Code context does not grow.
- The scenario spec (goal, success predicate, allowed actions) stays in a cached prefix.

**Stopping rules**

- Stop on the success predicate from the scenario spec (checked by the harness, not claimed by the model), a step budget, a dollar or token budget, a wall-clock budget, or a game time limit.
- Stuck stop: the state hash is unchanged for K steps, or the same (action, state) pair repeats M times. Following VideoGameBench, the defaults are 100 unchanged steps and 3 deaths in the same place, scaled down for 2 to 5 minute scenarios.
- Stop on an error in the Godot log.

**Outputs**

- `playtest.jsonl`: one line per step with snapshot hash, action, result, tokens, latency, and the model's one-line rationale.
- A final summary line in the existing "log plus explicit summary" format: `PLAYTEST RESULT: pass|fail|stuck|budget …`.
- `findings.json`: bug candidates, each with step index, evidence (state excerpt, optional frame path), category (functional, logic, UX friction, visual) and a reproduction action list.
- A replay script (the list of actions) so a failure can be re-run deterministically without the LLM.

## Checkable rules

1. A scenario is judged passed only by a harness-evaluated success predicate over game state, never by the model saying "done". Earlier runs show models making wrong assumptions about their progress (PokeAgent, VideoGameBench).
1. Every playtest run declares a budget: maximum steps, maximum tokens or dollars, maximum wall-clock, and maximum game time. A run without one is rejected.
1. The game clock is paused during model decisions unless the scenario explicitly selects the latency-adjusted mode.
1. Observations default to structured text. Screenshots are sent only through an explicit `look` call and at 1280 px on the long edge or less.
1. A snapshot stays under a token cap (default 6k) and lists the valid actions.
1. Every step is logged with action, result, latency and tokens. A run with missing step records is invalid.
1. Each reported finding carries a reproducible action list and step index.
1. Real-time 3D or RTS scenarios use the scripted-bot mode, not per-frame LLM control.
1. Every shipped number (budget defaults, stuck thresholds) carries a source and date or is marked UNTESTED, per the project rules.

## What a tool could check automatically

- **Scenario spec schema:** goal, success predicate, budgets, mode (`paused`, `latency_adjusted` or `scripted_bot`) and genre tag. Reject `llm_stepped` for genres tagged `realtime_3d` or `rts_micro` unless overridden.
- **Snapshot size:** measure the token count per step from the jsonl. Warn when it goes over the cap or when it grows across steps (leaking history).
- **Stuck detection:** repeated (state hash, action) pairs, an unchanged state hash for K steps, and an oscillation pattern A→B→A→B.
- **Hallucination check:** compare the model's rationale claims ("door opened", "enemy dead") with state diffs. Report mismatches in the rationale-versus-state field.
- **Budget accounting:** total dollars from token counts times the current price table, kept as dated data. The run ends when it goes over budget.
- **Replay check:** re-run the recorded action list without the LLM and confirm the same success or failure. This flags nondeterminism.
- **Log gate:** Godot errors and warnings during the run attach to findings automatically.
- **Image hygiene:** frame dimensions are at most the cap, the format is JPEG or PNG, and the count of `look` calls per run is reported.

## Risks and Uncertainties

- **Model names and leaderboard rows.** The 2026 model names (Claude-Opus-5-Max, GPT-6-Astra-Max, Fable 5) come from official pages fetched on 2026-11-13. The BALROG rows are leaderboard submissions, and the harness settings behind each row were not checked.
- **Vision-only claim cannot be reproduced.** Fable 5's FireRed claim is a primary Anthropic statement, but no protocol, steps or cost were published.
- **Claude Pokémon details are secondary.** The Opus 4.5 and 4.7 details come from LessWrong (dated, named author) and are not Anthropic primary sources.
- **Conflicting Gemini 3 completion times.** CONFLICT DETECTED: a search summary attributes a 173-hour Gemini 3 Pro completion to arXiv 2603.15563, while a forum post reports about 424.5 hours for Gemini 3 on Crystal. The paper text that was read gives no hours for Gemini 3. UNVERIFIED either way.
- **Orak internal mismatch.** CONFLICT DETECTED: Orak's text gives GPT-4o rank values of 3.4, 3.1 and 3.3, while its Table 4 gives 3.3, 3.0 and 3.1. This is minor.
- **Benchmarks use classic or commercial games.** Some of these games may be in training data (lmgame-Bench changed game settings after spotting memorisation). A new Godot game is out-of-distribution, so expect performance at the lower end.
- **Unmeasured cost and latency.**
  - UNVERIFIED: Claude Code tool-call overhead per step.
  - UNVERIFIED: decision latency for Opus 5.5 or Sonnet 5.5 on game snapshots.
  - The scenario cost estimate is derived, not measured, and should be calibrated with a first pilot run.
- **Results with older models.** OSWorld observation results are from 2024 models, and the per-model sensitivity to set-of-marks may have changed.
- **Godot-side mechanics not covered.** Pausing, frame stepping, and navigation-backed `move_to` were not researched here; the sibling harness researcher covers them.
- **LLM bug-finding is limited.** About 48% of planted bugs were found in GBQA, so a clean playtest is weak evidence that no bugs exist.

## Sources

| Source                                                 | URL                                                                                        | Date                  | What it contributed                                                                        |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------ | --------------------- | ------------------------------------------------------------------------------------------ |
| VideoGameBench                                         | https://arxiv.org/abs/2505.18134 (and https://arxiv.org/html/2505.18134v2)                 | May 2025              | Scores, Lite mode, interface, costs, stopping rules, failure modes                         |
| BALROG paper                                           | https://arxiv.org/html/2411.13543v2                                                        | ICLR 2025             | Text vs vision gap, knowing-doing gap, history length 16                                   |
| BALROG leaderboard                                     | https://balrogai.com/                                                                      | fetched 2026-11-13    | 2026 model scores                                                                          |
| lmgame-Bench                                           | https://arxiv.org/html/2505.15146v2                                                        | ICLR 2026             | Harness on/off effect, text perception module                                              |
| Orak                                                   | https://arxiv.org/html/2506.03610v3                                                        | ICLR 2026             | Genre scores, visual-input ablation, real-time StarCraft II, latency per step              |
| OmniGameArena                                          | https://huggingface.co/papers/2606.09826.md                                                | June 2026             | Unreal Engine 5 real-time scores, paused vs latency-adjusted modes, seconds per decision   |
| PokeAgent Challenge                                    | https://arxiv.org/html/2603.15563                                                          | March 2026            | Harness components, tokens and cost per turn, Pokémon completions, CLI-agent failure modes |
| Anthropic, Claude Fable 5 launch                       | https://www.anthropic.com/news/claude-fable-5-mythos-5                                     | 2026-06-09            | Vision-only FireRed, Slay the Spire memory, Factorio                                       |
| LessWrong, "A year late, Claude finally beats Pokémon" | https://www.lesswrong.com/posts/sehJYg5Yny9fvpbpt/a-year-late-claude-finally-beats-pokemon | 2026-05-16, secondary | Opus 4.7 harness and failure modes                                                         |
| Lumine                                                 | https://arxiv.org/abs/2511.08892                                                           | Nov 2025              | 5 Hz / 30 Hz real-time agent from a fine-tuned VLM                                         |
| SIMA 2                                                 | https://arxiv.org/abs/2512.04797                                                           | Dec 2025              | Generalist 3D agent, no numbers in abstract                                                |
| Cradle                                                 | https://arxiv.org/abs/2403.03186                                                           | 2024                  | Screenshots plus code-generated keyboard and mouse in commercial games                     |
| Voyager                                                | https://arxiv.org/abs/2305.16291                                                           | 2023                  | Code-as-action skill library                                                               |
| OSWorld                                                | https://arxiv.org/html/2404.07972                                                          | 2024                  | Screenshot vs accessibility tree vs set-of-marks success rates                             |
| Real-Time Reasoning Gym / AgileThinker                 | https://arxiv.org/abs/2511.04898                                                           | Nov 2025              | Reactive and planning threads under time pressure                                          |
| GBQA                                                   | https://arxiv.org/abs/2604.02648                                                           | April 2026            | LLM bug discovery, 48.39% best                                                             |
| TITAN                                                  | https://arxiv.org/abs/2509.22170                                                           | Sept 2025             | LLM MMORPG testing agent design                                                            |
| VideoGameQA-Bench                                      | https://arxiv.org/abs/2505.15952                                                           | NeurIPS 2025          | VLM glitch detection accuracy                                                              |
| Claude pricing                                         | https://platform.claude.com/docs/en/about-claude/pricing                                   | fetched 2026-11-13    | Model prices                                                                               |
| Claude vision docs                                     | https://platform.claude.com/docs/en/build-with-claude/vision                               | fetched 2026-11-13    | Image token formula and tiers                                                              |
| Local: 14-web-fast-feedback-loop.md                    | docs/research/14-web-fast-feedback-loop.md                                                 | —                     | Snapshot vs screenshot timing                                                              |
