# 02 - Game design dimension (AloneGodot / g-alon-gd)

Scope: design artifacts, the user\<->GD-agent workflow, design->code handoff, plugin proposals.
Sources: `role_g-alon-gd.md` (77 human prompts H0-H76, 11 forked subagents), `role_g-alone.md` (orchestrator), and the project at `/home/drmozg/Work/Petproj/AloneGodot` (`docs/`, `resources/`, `i18n/game.csv`, `demos/progression-data.js`, `tests/`, `.pre-commit-config.yaml`, `.mz/memory/lessons.md`).
Caveat: the digest records only the user's side of the GD thread. The GD agent's numbered questions are not visible; they are inferred from the answers ("1 - Yes 2 - Yes ..."). Digest D-entries repeat the same prompts under 10 subagent names (Rawls, Copernicus, Volta, Maxwell, Bernoulli, Schrodinger, Lagrange, Gibbs, Planck, Herschel). These are context forks replaying history, not 10 separate requests.

______________________________________________________________________

## 1. Design artifacts: what exists, how they relate

Inventory: 40 markdown files in `docs/` (about 4,400 lines), one 354-line GDD, a 34-episode discovery set, a self-contained HTML/JS progression graph (`demos/campaign-progression.html` + `demos/progression-data.js`), 25 typed `.tres` files in `resources/` (about 1,600 lines), and a 259-row `i18n/game.csv` (`keys,en,_comment`).

### Layered structure (as it actually grew)

```
user decisions (chat, numbered Q&A)
        |
        v
asteroid-survival-gdd.md  (v1.6, 354 lines; now mostly a "start here" index with
        |                  stacked "Latest approved update" banners + historical prototype text)
        v
campaign-rules-canon.md   (155 lines; the real entry point)
   - status vocabulary: Agreed direction / Initial test baseline / Open contract /
     Prototype record / Deferred
   - "Topic owners" table: subject -> single authoritative doc
   - rule: "Latest explicit user corrections prevail ... If two topic owners still conflict,
     report the conflict before implementing it. A graph node, generated card description,
     asset manifest or proposed API cannot silently approve gameplay."
        |
        +-- topic designs (what/why):  campaign-and-endings-design (415), day-planner-and-mental-survival,
        |     crash-opening-and-habitat, physical-progression-and-expeditions, campaign-discoveries-and-playstyles (268),
        |     magnetic-slots, card-lifecycle-and-construction, random-hazards-design, sound-design
        +-- numbers:  campaign-balance-v1.md (header says 0.3), campaign-pacing-v2, campaign-route-timing,
        |     campaign-hazard-catalog (deterministic trigger table), campaign-depth-art-brief
        +-- classification: card-classification-matrix (426 lines), full-card-descriptions
        +-- CONTRACT REGISTERS (executable-gap tracking):
        |     episode-contract-register (34 rows), thought-contract-register,
        |     expedition-hazard-machine-contracts, planner-occurrences-and-bindings
        +-- briefs to other agents: g-alone-*-art-brief.md (9 files), g-alone-cards-ui-ux-brief,
        |     g-alone-events-ui-brief, sound-design  (design -> graphics/UI/sound handoff)
        +-- docs/ideas/expedition-transport.md  (parking lot: H69-H70 "Save this to ideas but let's not implement it yet")
        v
demos/progression-data.js  (editable machine-readable catalog: locations, discoveries, research prereqs,
        |                   recipes, devices, endings; "rules": {researchRate:10, benchRate:15, oxygenPerDay:12 ...})
        v
resources/*.tres  (typed Resource: recipes.tres, cards.tres, survival.tres, timeline.tres, ...)
        +  i18n/game.csv (all player-facing text)
```

### Which proved most useful (evidence)

1. **`campaign-rules-canon.md`**: the only doc that solves the "which doc wins" problem. Its status vocabulary ("Initial test baseline ... not measured balance or separate user approval of every number") stops placeholder numbers hardening into law. Its topic-owner table is what the orchestrator needed to answer "can I implement X?".
1. **Contract registers** (`episode-contract-register.md`, `thought-contract-register.md`): they turn prose into a gap list. Each of the 34 episodes gets a "Missing executable details" column ("Exact emergency-stock quantities and actual production batches; isolation-handle identity; safe interruption procedure"). The shared rule is "Missing fields are OPEN, never zero-cost or empty-participant defaults." This is the nearest thing to a design->code handoff artifact, and it is explicitly anti-invention. The thought register ends: "A strict review must reject activation of narrative-only rows."
1. **Hazard catalog** (`campaign-hazard-catalog.md`): the one doc with deterministic, testable trigger semantics ("No seed, weighted draw ... Advancing time in larger steps must visit the same boundaries"). It is the only campaign doc with matching tests (`tests/campaign_hazard_{identity,leaf}_test.gd`, run by the `godot-campaign` hook).
1. **Interactive progression graph** (H37, H43, H68): the user asked for it ("a full html with progression graph ... research leads to which research") and re-asked for updates three times. It is the user's real review surface for pacing and playstyle coverage (it exposed "playstyle-specific things end around step 15", H45).
1. **Numbered-question decision log**: not an artifact but the working technique. Most binding rules in the docs trace to a single-word answer in a numbered batch.

### Weaknesses in the artifact set

- **Supersession by banner, not by edit.** `asteroid-survival-gdd.md` opens with 6+ stacked "Latest approved update" paragraphs; `campaign-rules-canon.md` opens "Latest approved override: Magnetic slots ... supersedes older two-hour breathing rules"; `campaign-balance-v1.md` has "Oxygen baseline superseded ... historical and must be recalculated before reuse". 13 of 40 docs contain "supersede". Old numbers stay in the file, so a reader (or agent) can pick up a dead value.
- **Filename drift:** `campaign-balance-v1.md` is balance 0.3; the graph data says baseline 0.4. Version lives in prose, not in a machine-checkable field.
- **Derived numbers are stale after a rule change.** The magnetic-slots decision (H75: oxygen 1 at 06:00 and 18:00) invalidated the oxygen ledger; the docs say "Oxygen balance/graph calculations require migration" while `progression-data.js` still has `oxygenPerDay:12`. Nothing detects this.
- **Balance numbers are hand-authored in three places** (balance md, `progression-data.js`, `recipes.tres`/`survival.tres`) with no cross-check. The user asked the GD agent to "Figure out initial balance quantities yourself" (H37) and "Estimate average campaign duration" (H39), then required "7-8 hours is a must" (H40), but duration is a hand estimate; `campaign-pacing-v2` says "measured validation still pending".
- **Only hazards have an executable check** (`run_campaign_tests.sh` has just two suites). Episodes, thoughts, endings, 426-row card matrix and balance have no validator.

______________________________________________________________________

## 2. The workflow the user ran with the GD agent

### Shape of the loop (very regular)

```
user:  one-line goal   ("Do a research on game design approaches" H0 / "Let's discuss endings" H18 /
                         "What does our GDD lack?" H29 / "Are there any GDD things we're missing?" H50)
GD:    research or proposal + 5 numbered questions
user:  "1 - Yes 2 - Yes, also researching them may be difficult psychologically 3 - Yes 4 - Dissolve 5 - Uncertain"
GD:    folds answers into docs, asks next 5            (H3 -> H4 -> H5 -> ... -> H16: 14 consecutive rounds)
user:  "Proceed" / "Go" / "Agreed" / "Okay, proceed with finalization"
GD:    writes docs, then "notify @g-alone" (H17, H65, H76)
```

About 55 of 77 prompts are bare numbered answers or one-word approvals. The user is doing decision-making, not writing; the GD agent does the thinking and drafting.

### Recurring request types

| Type                                      | Examples (prompt ids)                                                                                                                         |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Research then propose                     | H0 "research on game design approaches" -> `.mz/research/2026_11_10_research_asteroid_survival_design.md`                                     |
| Decision interview (5 numbered questions) | H3-H16 (planner, mental survival, meals, routines), H19-H26 (endings), H32-H35 (opening)                                                      |
| Gap audit                                 | H29 "what does our GDD lack", H50 "Are there any GDD things we're missing or it's complete?", H57 "So GDD is finished?", H65 "Check for gaps" |
| Consolidate + notify orchestrator         | H17, H65, H76 ("Yes, save it into GDD. And notify @g-alone agent")                                                                            |
| Deliverable for review                    | H37 progression HTML; H43 playstyle highlight; H68 refresh graph                                                                              |
| Brief other agents                        | H34/H37/H40 "give @g-alone-graph a brief", H46 "Are there any missing artworks? ask again"                                                    |
| Quantify                                  | H37 "initial balance quantities yourself", H39 "average campaign duration", H40 "7-8 hours is a must"                                         |
| Depth/variety push                        | H40/H41/H47/H48 (playstyles, Spiritualist route, devices, distinct places)                                                                    |

### Corrections, rejections, friction (quoted)

- **Misread of a proposal:** H35 "I meant place card and some resources, structure should be constructed again from the blueprint." The GD had gotten the construction-refund/place model wrong after H34.
- **Deliverable bug:** H38 "Can't scroll right." Orchestrator-side repeat: "Update our graph" (H43, H68). The lesson L-0017 says "WHEN a graph has large horizontal overflow -> keep navigation visible", so this class reappeared in the memory lessons.
- **Art pipeline failure leaking into GD thread:** H44 "Ask for more tries." H46 "Are there any missing artworks still? If yes, ask again to generate them." The GD agent was acting as a relay to graphics; nothing tracked brief status.
- **Content depth shortfall, caught by the user, not by the agent:** H45 "Why all playstyle-specific things end around step 15?"; H47 "Also later phases lack special devices, advanced construction projects ... otherwise it's just solving a story through research."; H48 "And more distinct places to visit with some powerful artefacts/resources."; H40 "7-8 hours is a must."
- **Self-completeness claims not trusted:** H50 and H57 ("So GDD is finished?") appear after the agent presumably declared it done; H65 "Check for gaps"; H66 and H59-H64 kept producing 3-5 new unresolved interaction questions each. The registers later made this visible (34 rows PARTIAL).
- **Complexity pushback:** H73 "This a little bit convoluted. I feel more and more we should maybe remove card system - it's too hard to handle." Design had accumulated mental-card/fear-on-location mechanics (H72) that the user then replaced with a simpler "magnetic slots" (H74-H75).
- **Decision fatigue / delegation of tie-breaks:** H61 "When several actions start - do as you recommend."; H59-H60 "1 - Agree 2 - Agree 3 - Agree 4 - Agree 5 - Agree"; H67 "Agreed". The GD agent asked many questions that had a clear recommended default.
- **Determinism as a standing constraint** the agent had to be told: H25 "avoid, everything should be 100% deterministic". This shaped the whole hazard catalog (no seeds/weights).
- **Orchestrator-side corrections (design-adjacent):** health cards (H "health cards ... 0 health cards means death"), "Permanently reduce capacity; expired health cannot be restored" (answer to a question), "Use 1 January 2200 as the fixed prototype date" (the design had no calendar), the transmitter quest ("Propose provisional values based on the current balance"). Each was a design gap discovered while coding.
- **Process rule born from failure:** orchestrator H188 "If something is not in the docs - don't yet implement it - consult with @g-alon-gd" (also now in `CLAUDE.md`: "consult the game-design agent before implementing undocumented gameplay"). This indicates code agents were implementing gameplay that was never designed.

### Friction summary

1. Decisions live only in chat; the numbered-answer format is lossy (answer "1 - Yes" depends on a question the doc may not preserve).
1. Docs record answers as prose, and later answers overwrite earlier ones through banners.
1. No test that the GD claims "complete" (three completeness audits were needed).
1. No quantitative check for the stated acceptance target (7-8 h).
1. Notifications to the orchestrator and requests to graphics are manual thread messages (`send_message_to_thread` 90 calls, `read_thread` 38 calls in the GD role's tool log), with no tracking of "brief sent / delivered / accepted".
1. The role did a lot of `python` (175) and `sed`/`cat` (about 400 total) over docs, i.e. manual grep-and-patch consistency work, plus 127 `chrome_devtools evaluate_script` + screenshots to verify its own HTML graph.

______________________________________________________________________

## 3. Design -> code handoff

What the project actually did:

1. **Doc authority + "do not implement undocumented" rule.** `CLAUDE.md`: "consult the game-design agent before implementing undocumented gameplay". `campaign-rules-canon.md` status table (Open contract = "dependent implementation must wait for its clarification and technical review").
1. **Typed Resources for rules.** `AGENTS.md`: "All configurable parameters belong in Godot resource files rather than hardcoded GDScript values. Use typed resources for game rules and presentation tuning, keep mutable runtime state separate, and retain player-facing text in CSV localization files." Example `resources/recipes.tres`: `ActionStage` (id, duration_minutes, costs) -> `ActionRecipe` (id, verb_id, enabler_id, inputs, outputs, stages) -> `RecipeCatalog`, with `_title_key = "ACTION_STAGE_SALVAGE_OUTBOUND_NAME"` pointing into the CSV.
1. **Contract registers as pre-implementation checklists.** `episode-contract-register.md`: "Before activating a branch, supply an explicit mapping for: actual location; exact colonist/tool/device/evidence participants; stages and when their existing bill is committed; produced/transferred objects and quantity; learned evidence; installed state; pause/cancel/return behavior; later task predicate; repeat policy; and save/load ownership."
1. **Test baselines marked as such.** Docs say "initial test baseline ... not playtested tuning".
1. **Progress via lessons.** `.mz/memory/lessons.md` I-0049/I-0063 are design-contract guards discovered in review ("WHEN scenario has one canonical device -> prohibit recipes consuming it", "validate required card references at initialization").

Failures in this handoff:

- The "OPEN" status is prose-only (about 52 matches of "OPEN" in docs); no machine can tell which `.tres` rows correspond to PARTIAL episodes. 34 episodes are PARTIAL while 34 discovery graph nodes exist, so the graph shows content the code cannot execute.
- Hazard tests exist because someone wrote them; nothing forces "every design contract row has a test or an OPEN marker".
- `resources/` has no campaign content yet (no episode, ending, thought, location or research .tres; all 25 are core/presentation). So all campaign design lives only in markdown + JS graph, and the three "balance" sources can diverge silently.
- The GD agent's output is Markdown tables; the coder re-types them into `.tres`. No generator, no schema, no round-trip.
- Cross-agent comms (briefs to graph/UI/sound; "notify @g-alone") are free-text, with no ownership/status fields.

______________________________________________________________________

## 4. Plugin proposals (each tied to evidence)

Organized as a `godot-design` plugin (skills + agents + a deterministic CLI, `gdkit`, in the same style as the user's existing `falkit`/`dramakit`/`pubkit` pattern: sheet -> judge -> JSON).

### 4.1 Skills

| #   | Skill                     | What it does                                                                                                                                                                                                                                                                                                                                  | Evidence                                                                                                                                                                                                                                                                                                               |
| --- | ------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| S1  | `gd-interview`            | Runs the 5-numbered-questions loop. Each question has a recommended default, an options list and the "why it matters"; answers are parsed ("1 - Yes", "3 - Offer") and appended to a **decision log** (`docs/decisions/NNNN.md`: question, options, chosen, date, superseded-by). Supports "do as you recommend" (H61) and "agree all" (H59). | H3-H16, H19-H26, H59-H67: 55/77 prompts are numbered answers. Prose banners later lost the question text. H61 shows fatigue; defaults reduce it.                                                                                                                                                                       |
| S2  | `gd-gdd` (writer/updater) | Writes/updates the GDD with the **status vocabulary** from the canon (Agreed direction / Initial test baseline / Open contract / Prototype record / Deferred) as required frontmatter or tags per section; refuses to leave "supersede" banners and instead edits the old section into a "History" stub linking the decision id.              | Canon status table is the most useful artifact; 13 docs patched by banner; `oxygenPerDay:12` stale after H75.                                                                                                                                                                                                          |
| S3  | `gd-canon`                | Builds/maintains `campaign-rules-canon.md`-style topic-owner table (subject -> one owning doc) and detects topic overlap/conflict.                                                                                                                                                                                                            | "Use topic ownership below rather than treating whichever document was edited last as universally authoritative."                                                                                                                                                                                                      |
| S4  | `gd-contracts`            | Generates a **contract register** for any feature set (episodes, thoughts, hazards, planner): per row, the fixed field checklist (location, participants, stages, bill commit, outputs, learned evidence, installed state, pause/cancel/return, task predicate, repeat policy, save/load ownership) with OPEN as the default.                 | `episode-contract-register.md` checklist is verbatim reusable; "Missing fields are OPEN, never zero-cost".                                                                                                                                                                                                             |
| S5  | `gd-balance-sim`          | Reads recipe/survival/economy data and runs a **deterministic headless simulation** of the baseline route (resource ledger by hour, starvation/oxygen floors, research time, expedition cost), outputs campaign duration estimate per playstyle and a ledger. Checks against targets (e.g. 7-8 h).                                            | H37 "Figure out initial balance quantities yourself", H39 "Estimate average campaign duration", H40 "7-8 hours is a must"; `campaign-pacing-v2` "measured validation still pending"; oxygen change H75 needed manual recalculation. Determinism is a hard rule (H25), so a pure simulator is feasible, no Monte Carlo. |
| S6  | `gd-content-table`        | Generates content tables (research tree, episodes, locations, devices, endings, hazards) from a short outline into the typed schema (YAML/CSV) and the matching `.tres` + `game.csv` keys; fills only declared fields and marks others OPEN.                                                                                                  | H47/H48 (user had to ask for more devices/places); 34 episodes x two branches written by hand; `card-classification-matrix.md` 426 rows.                                                                                                                                                                               |
| S7  | `gd-review`               | Design critique with fixed lenses: depth-per-playstyle, pacing curve, complexity budget ("too convoluted" test), determinism, dead-ends, economy sinks/sources, narrative/theme coherence. Uses the existing perfectionist/pragmatist two-view style.                                                                                         | H45 "Why all playstyle-specific things end around step 15?", H47, H73 "convoluted"; the user, not the agent, was the reviewer.                                                                                                                                                                                         |
| S8  | `gd-gap-audit`            | Replaces "Are there any GDD things we're missing?" with a checklist-driven audit (systems list x contract status x test coverage), outputs a ranked gap list, never claims "complete" unless the checklist is empty.                                                                                                                          | H29, H50, H57, H65: four manual completeness audits.                                                                                                                                                                                                                                                                   |
| S9  | `gd-brief`                | Produces briefs for graphics/UI/sound from a design section, with required fields (asset ids, count, status, acceptance criteria, owner, thread/ticket) and writes a brief tracking row.                                                                                                                                                      | 9 `g-alone-*-art-brief.md`; H44/H46 re-asks; "give a brief" appears in H34, H37, H40.                                                                                                                                                                                                                                  |
| S10 | `gd-handoff`              | Given a design section with contract status = Ready, emits a coder task: affected `.tres` rows, schema delta, tests to write (from contract fields), forbidden extras. Refuses sections with OPEN fields (unless the user overrides).                                                                                                         | `CLAUDE.md` consult rule; H188; thought register "reject activation of narrative-only rows".                                                                                                                                                                                                                           |
| S11 | `gd-playstyle-map`        | Maintains playstyle -> tech chain coverage and highlights where chains end early; feeds the graph.                                                                                                                                                                                                                                            | H43 highlight by playstyle; H45 "end around step 15"; H41 Spiritualist addition.                                                                                                                                                                                                                                       |
| S12 | `gd-graph`                | Generates/updates the self-contained progression HTML from the data file and verifies it (scroll, responsive) with a headless browser step.                                                                                                                                                                                                   | H37, H38 "Can't scroll right", H43, H68; L-0017. 127 devtools evaluate_script calls spent verifying it by hand.                                                                                                                                                                                                        |

### 4.2 Agents (judges and workers)

| Agent                                                                                | Role                                                                                                                                                                               | Evidence                                                                                                                  |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `gd-designer` (opus-class)                                                           | Owner of docs; only agent allowed to change Agreed/Baseline status; asks via S1.                                                                                                   | The g-alon-gd role itself.                                                                                                |
| `gd-consistency-judge` (read-only, JSON verdict, sheet-based like `dramakit review`) | Per round, answers numbered rules: Does section X contradict canon owner Y? Does a number in doc A differ from doc B or the data file? Is any "superseded" value still referenced? | Banner-based supersession; stale `oxygenPerDay`; 3-way number duplication.                                                |
| `gd-playtest-judge`                                                                  | Reads simulator output and judges pacing/engagement vs. targets (flat stretches, idle waits, dead resource, forced grind).                                                         | "Consider pacing, campaign length, engagement" (H27); pacing doc validation pending.                                      |
| `gd-contract-auditor`                                                                | For each register row, decides if the contract is complete enough for code (all fields non-OPEN).                                                                                  | Register fields.                                                                                                          |
| `gd-narrative-lens` (could reuse `dramaturgy` plugin: bible/canon/drama-review)      | Story canon/endings/alien-mind consistency (Solaris-like communication, H32; eight endings, H19).                                                                                  | `dramaturgy:drama-series` already has "canon, retcons, rulings"; endings/responder cards need the same retcon discipline. |
| Do NOT fork 10 identical GD subagents                                                | The digest shows 10 forks replaying the same history. A plugin should pass a decision-log summary, not full history.                                                               | D0-D62 duplicates.                                                                                                        |

### 4.3 Artifact schemas

1. **Decision record** (`docs/decisions/NNNN-slug.md`, frontmatter): `id, date, topic, question, options[], chosen, rationale, status: agreed|baseline|open|deferred, supersedes[], superseded_by, owner_doc`. Source: S1. Solves banner-supersession.
1. **Topic owner table** (`docs/canon.yaml`): `subject, owner_doc, status, last_decision`. Source: canon's table.
1. **Contract row** (YAML per episode/thought/hazard/ending): fields from the episode checklist; each field `value | OPEN | N/A(reason)`. Plus `tres_ids[]` and `test_ids[]` links.
1. **Balance source of truth**: one `resources/campaign_balance.tres` (typed) or a YAML that generates it; docs and the graph data read from it. Status per number: `baseline|measured|approved`. Applies "One Source of Truth" from the user's rules, since three copies exist today.
1. **Content tables** as CSV/YAML: `research.csv`, `episodes.csv`, `locations.csv`, `devices.csv`, `endings.csv` with ids, prerequisites (all-of / any-of, mirroring the graph's solid/dashed edges), costs, durations, playstyle tags.
1. **Brief record**: `id, kind (art|ui|sound), source_section, asset_ids[], status (draft|sent|delivered|accepted|retake), owner_agent, notes`.

### 4.4 Deterministic CLI checks (`gdkit`)

All should be pure scripts, headless, runnable from pre-commit alongside the existing `godot-*` hooks.

| Check               | What                                                                                                                                                                                                                      | Evidence                                                                                                               |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `gdkit ids`         | Every id referenced in docs/graph/contracts/tres/csv exists exactly once; every `_title_key` resolves in `game.csv`; no orphan CSV keys.                                                                                  | `recipes.tres` uses `_title_key = "ACTION_STAGE_..."`; L I-0063 "validate required card references at initialization". |
| `gdkit graph`       | Prerequisite graph: no cycles, no unreachable nodes, every node reachable per playstyle, longest-chain length per playstyle (flag "ends at step 15"); all-of vs any-of edges.                                             | H45; `progression-data.js` solid/dashed semantics; H43.                                                                |
| `gdkit budget`      | Resource ledger across the baseline route: sums of produced vs consumed, floors never negative, no resource without sink or source, "limited resource shared between devices" invariant.                                  | H28 "limited resources ... same thing for another ending", balance ledger in graph Balance tab.                        |
| `gdkit duration`    | Computes total minimum/typical campaign hours per playstyle from stage durations + travel; asserts within [7, 8] h band.                                                                                                  | H40 "7-8 hours is a must"; pacing-v2 "validation pending".                                                             |
| `gdkit numbers`     | Extract numbers from docs tagged `<!-- n:oxygen_per_day=2 -->` and compare to resources/data; fail on mismatch.                                                                                                           | Stale oxygen (docs vs `oxygenPerDay:12`).                                                                              |
| `gdkit status`      | Fails if a doc section marked Ready references a contract row with OPEN fields, or a `.tres` row exists for a PARTIAL row without an override flag; lists "implemented but undocumented" `.tres` ids (reverse direction). | CLAUDE.md "consult before implementing undocumented gameplay"; H188.                                                   |
| `gdkit determinism` | Greps data/scripts for `randi/randf/RandomNumberGenerator` outside an allow-list, and flags `seed`/`weight`/`probability` columns in content tables.                                                                      | H25 "everything should be 100% deterministic"; hazard catalog "No seed, weighted draw".                                |
| `gdkit supersede`   | Fails when a doc contains words "superseded" next to a number still present elsewhere, or when a decision's `superseded_by` is set but the owner doc still carries the old value.                                         | 13 docs with banners.                                                                                                  |
| `gdkit tres-schema` | Parses `.tres` (text format) and validates against the typed script's exported fields and the content-table schema (types, positive costs, durations > 0, no zero-cost default).                                          | I-0048 "bills accept positive costs only"; L-0010 validate, don't assert.                                              |
| `gdkit i18n`        | Checks CSV keys vs uses; no player-facing literals in docs-derived data; placeholder consistency.                                                                                                                         | AGENTS.md: "retain player-facing text in CSV localization files".                                                      |

Run `gdkit` via `pre-commit run --files ...` to match the user's rule (pre-commit-conventions.md).

______________________________________________________________________

## 5. Priorities for a first release

1. `gdkit` core: `ids`, `graph`, `status`, `numbers`, `tres-schema`, `determinism` (cheap, high value, deterministic).
1. Skills `gd-interview` + decision-record schema + `gd-gdd`/`gd-canon` (fixes the lossy numbered-answer workflow and banner supersession).
1. `gd-contracts` + `gd-handoff` + the "no implementation of OPEN rows" check (formalizes the CLAUDE.md rule).
1. `gd-balance-sim` + `gdkit duration` (turns "7-8 hours" into a gate).
1. `gd-review` / `gd-gap-audit` with the consistency judge (replaces four manual "is it complete?" rounds).
1. `gd-graph` + `gd-brief` tracking (relieves the repeated "ask again / update graph / can't scroll" loops).

## 6. Notes / pre-existing issues surfaced (not acted on)

- `campaign-balance-v1.md` is balance 0.3 while graph reports baseline 0.4; filenames carry stale versions.
- Several docs exceed what an agent can reason about in one read (`campaign-and-endings-design.md` 415 lines, `card-classification-matrix.md` 426); mentioned, not split.
- `resources/` contains no campaign content, so campaign design is not yet machine-checkable at all; any plugin check must first define where campaign data lives.
- Only 2 campaign test suites exist in `tests/run_campaign_tests.sh` (hazard identity + leaves).
