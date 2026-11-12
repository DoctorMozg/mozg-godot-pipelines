# 06 - UI/UX dimension: lessons from AloneGodot (Codex) and plugin proposals

Sources: Codex digests (role_g-alone-ui.md, role_g-alone.md), project docs (AGENTS.md, docs/g-alone-cards-ui-ux-brief.md,
docs/salvaged-instruments-visual-direction.md), art/uiux/{SPEC,FLOWS,GODOT_HANDOFF,REVIEW}.md, art/{events-ui,timeline-ui}/v001,
.mz/task/2026_11_11_build_native_ui/plan.md, .mz/task/2026_11_12_build_ui_shell/{review,verification}.md, and a targeted read of the
g-alone-ui rollout (01a1c702-..., 88 MB). Read-only; nothing modified.

## 0. Shape of the problem (important for plugin design)

AloneGodot is NOT a classic Control-tree UI game. It is a 3D tabletop (Node3D world, physical card meshes, tilted camera,
depth-parallax shader) with a thin Control/Container HUD overlay (header, inspector, schedule/timeline, task editor).
Consequences that a generic "Godot UI" plugin would miss:

- Most "UI" bugs are input-routing / picking / camera problems (GUI vs `_input` vs 3D ray), not Theme or anchor problems.
- UI is built in code (20 hits of `Label.new`/`add_theme_*`/`StyleBoxFlat`), `scenes/main.tscn` is the only scene, and there is
  no shared Theme resource for the HUD (only `resources/table_ui.tres`, `timeline_visual.tres`, `result_style.tres`, etc. as typed
  tuning Resources). So the "Theme/StyleBox system" must be a typed-Resource style system, not just `.theme` files.
- Strings: `i18n/game.csv` (259 rows, key,en,\_comment), registered as `.translation` in project.godot; 174 `tr(` call sites.
  Only English shipped. Zero language picker. Layout expansion / plural / font coverage never tested (admitted in verification.md).

## 1. How UI was designed (pipeline actually used)

Observed chain, in order, with who did what:

1. Research (g-alone-ui H0): "You're a ui/ux designer for this game. Do a research on UI/UX for this type of games, gather tips
   and ideas." -> sub-agents x5 (Lagrange, Einstein, Beauvoir, Raman, Ampere) ran the same prompt; user said "Approve".
   Also `.mz/task/2026_11_10_deep_research_game_uiux`. web\_\_run x99 in the UI thread.
1. Brief written by orchestrator (g-alone) for the UI thread: `docs/g-alone-cards-ui-ux-brief.md` (85 lines) - ownership
   ("Own art/uiux/; do NOT edit scripts/tests/scenes/project.godot/i18n"), product+visual direction, "primary UX problem",
   established interaction rules, resolutions list (1920x1080, 1440x900, 1280x720, 1024x768, 2560x1080), deliverables with
   acceptance, and "Review against real interactions and real sizes, not just a large attractive composition".
1. Clarification loop via `request_user_input_async` questions with 4-5 numbered defaults ("my proposed defaults are in
   parentheses"); user answers terse ("1 - Try strip first 2 - Yes 3 - Adj 4 - 1-hour snapping 5 - local index.html").
   This pattern repeated for timeline, glimpse images, task setup, supplies, scope. Strong, reusable UX: batch of \<=5
   defaulted questions, user overrides by number.
1. Interactive HTML/CSS/JS prototype per surface, served by local `python -m http.server 87xx`
   (art/uiux, art/timeline-ui/v001, art/events-ui/v001, art/task-setup/v001). User asked "Start server so i can open".
   Each prototype: index.html + app.js + style.css + localization CSV + fixtures/scenario selector + native-size PNG screenshots
   - SPEC.md + FLOWS/COVERAGE.md + GODOT_HANDOFF.md + REVIEW/VALIDATION.md + tokens.json + verify.mjs + browser-results.json.
1. fal.ai concept images only AFTER the user said the HTML UI was "too heavy" (H20: "current UI looks too heavy - too much
   panels, not much of stylization etc."). 3 concepts (A Instruments / B Projection / C Field board) in art/ui-concepts/v001 with
   gallery served on :8792, manifest.json, judge.json per image, receipts. User picked
   `salvaged-instruments-v001-t1.png` "for all (card design, table design UI etc.)" -> written up as
   docs/salvaged-instruments-visual-direction.md (materials, HUD, timeline, task setup, "Correct the concept during
   implementation": the generated image has a 5th slot, duplicated labels, garbled microcopy = generation errors; rebuild text
   from game state).
1. Implementation plan by UI agent (`.mz/task/2026_11_11_build_native_ui/plan.md`): batches of \<=5 files, each with `verify:`
   rows; reviewed by independent sub-agents; sent to g-alone (orchestrator). Architectural decision recorded: "native
   Control/Container overlays over the retained Node3D world; all-mesh GUI rejected (text scaling, clipping, focus); separate
   SubViewport rejected (input routing)", citing Godot docs.
1. Implementation (`2026_11_12_build_ui_shell`): UI agent itself coded a bounded shell in an isolated copy (/tmp/alone-ui-shell),
   TDD (RED 568/8 -> GREEN 568/0 native UI assertions, 62 input checks), then handed g-alone a patch set
   (handoff.patch, ci-registration.patch, fixture-followup.patch, file-hashes.json, orchestrator-handoff.md, verification.md,
   review.md, previews/\*.png). Orchestrator integrates.

Handoff format (the real artefact, GODOT_HANDOFF.md): table "Existing component -> observed responsibility -> design binding"
(maps mock to real files/scripts), then priorities P0/P1 with a `**Verify:**` line each (e.g. "native 1920x1080, 1440x900,
1280x720, 1024x768 and 2560x1080 captures have no control overflow"), asset+copy section, explicit "Unresolved items and review
boundaries" (what the browser cannot certify: native 3D collision, Godot font scaling, controller nav, localization expansion).
It also embeds an honest conflict note (two readings of the user's "No expiry should not be shown on the card").
Key discipline worth copying: "Mockup scenario state is illustrative; the Godot model owns all playable quantities".

Tool footprint of g-alone-ui (inner calls): exec_command 2476, apply_patch 371, chrome_devtools evaluate_script 187 /
take_screenshot 77 / resize_page 49 / navigate_page 53 / drag 15 / list_console_messages 12 / take_snapshot 12 (HTML prototype
verification), view_image 94 (looking at own screenshots), fal 8, mcp\_\_godot\_\_get_godot_version 2 (the Godot MCP was barely
used), cross-thread send_message 215 / read_thread 73 (team coordination). Pre-commit with SKIP=godot-\* for HTML-only batches (90x).
`falkit` CLI x33 for concept generation. google-chrome headless x10 for native-size captures.

## 2. User corrections and failures (evidence)

All quotes are verbatim from user prompts in the digests.

A. Layout/placement corrections of the glimpse + task editor prototypes (UI thread):

- "Only colonist actions are shown on the center, automatic are shown in a smaller image on the corner." (H9)
- "Yes, almost, but should be below cards, not round but square smooth, also around 1/2 of the table and always randomly
  centered, not a small in the center" (H10) -> size/z-order/shape/placement all wrong on first prototype.
- "No, SLOTS should be card-shaped. On hover available card highlights. Periodic switch should be just a button like 'Daily'." (H13)
- "Oxygen and other resouces should be set in advance, also with drag'n'drop, time is specified by dropping action card on
  timeline, so no need for 2 other tabs." (H14) -> agent invented tabs; user wanted fewer surfaces.
- "Background task doesn't need a column - we can just specify them in the main timeline. Just show differently." (H5)
- Also from H12 answer: "make sure it's not too huge, so we can drag'n'drop from table" (modal editor must not cover the
  drag sources).
  Lesson: spatial/shape/z-order intent is communicated badly in prose; first prototype misses 2-3 points each round.

B. Aesthetic rejection: "Try using fal.ai to generate some game UIs - current UI looks too heavy - too much panels, not much of
stylization etc." (H20). The standing brief said "not a generic neon HUD" and still produced a panel-heavy dashboard.
Lesson: concept-art step must come BEFORE the HTML build, not after.

C. Orchestrator-thread UI corrections of the 3D/HUD runtime (role_g-alone.md):

- "Now much better but still: cards are being dragged to the top, so you can't see what's happening." (active work scrolled
  off the top of the timeline; became P0 in brief: "fixed work band near Now").
- "Action lanes should resemble a timeline, so it should flow from top to bottom ... like in calendar and moves slowly."
- "Also card images should fully fill card background." (-> repeated as a hard rule in brief, SPEC, handoff: edge-to-edge,
  aspect-preserving crop, no letterbox/footer).
- "Also resolution should be adaptive." -> user confirmed "native window resolution and responsive layout, ultrawide".
- "we need to pre-highlight available slots and its types when creating a job. And on hovering on this slot we should highlight
  possible card options on the table."
- "I think we need VERBS ... These activity serve as templates. So I'm not just put a colonist and trying to figure out what to
  put next of all, but it provides me a template with slots I need to fill." (UX discoverability problem, not visual)
- "Activities should also be cards with 6-gon design ... abstract, color-encoded flat icons" (later built as 8-sided).
- "Also we should give hints on what can be done."
- "Also if cards are stacked we should display each card as separate in a stack, also a number of stacked on top."
- "Cards should also differ by size, each card is an image. On hover it shows details and description."
- z-fighting on table, WASD pan "not eased", parallax "should happen when camera moves all the time, not by hovering. And make it more visible",
  "when taken a card should face more to the camera" -> motion/feel, all found by user playing, not by any check.

D. Rules the user had to restate and that were then hard-coded into AGENTS.md (this is the clearest evidence of repeated
failures; dated 2026-11-08):

- Card expiry: "`timeout` ... Use `null` ... hide its card badge; do not show 'No expiry' on the card." Misread twice; GODOT_HANDOFF
  ends up documenting two readings and choosing "inspector-only" variant pending review. Ambiguous correction -> unresolved.
- Category icon: "Put a small, simple flat category icon in the top-right corner of every card, composed in the UI rather than
  generated into its artwork."
- Item readability: "separate every item from its background at 120-240px using deliberate value contrast ... Do not place gray
  tools on similarly gray busy backgrounds."
- Never bake text/frames/UI into generated art ("Exclude text, frames, and UI from final illustrations"); salvaged-instruments
  concept shipped with garbled microcopy and an extra 5th slot - had to be written down as "generation errors, rebuild from state".
- Card badges/icons/overlays are UI composition (localized), never part of the image.

E. Process failures visible in UI thread:

- Prototype review (REVIEW.md) found the first wide activity faces clipped their square glyphs -> redone as square faces.
- Two screenshots (`health-1920x1080.png`, `boundary-1920x1080.png`) are explicitly "historical", no longer depict current UI ->
  stale screenshots remain in repo. Need a screenshot freshness check.
- Known unfixed after the native shell: "Small 960px text/targets, idle rail space and world timeline labels remain whole-UI
  follow-ups" (build_ui_shell/review.md). Min text size / hit-target size is a recurring gap; REVIEW only used visual inspection.
- Research icon prompt asked 3 nodes, got 4: raw formal judge marks it "critical", left open; accepted by owner as "fits direction"
  (judge vs taste conflict, no policy for who wins).
- Headless Godot uses the Dummy renderer: it zeros MultiMesh instance data, so rendering tests that pass/fail differ from native.
  The UI agent found 346 failures only on native; fix was DISPLAY=:0 runs with separate XDG dirs (see 3).
- Localization batch (build_i18n): "Native GUI interaction probe ... No screenshot or recording taken"; verification says
  "font coverage, plural rules, and expansion need validation when actual target languages are selected". Never done.
- An agent (UI) had to be told to align with prototype later: orchestrator H184 "Make sure it aligns with the prototype made by
  g-alone-ui" -> handoff to implementer relied on the human to remember the link between prototype and runtime.

## 3. How UI was verified

Two completely separate verification worlds:

(1) Browser prototypes (art/\*-ui/v001):

- headless Chrome at native DPR 1, capture "waits for image decoding, fonts and completed animation frames"; Pillow confirms PNG
  sizes; screenshots never resized (REVIEW.md). Seven sizes: 1920x1080, 1440x900, 1280x720, 1024x768, 2560x1080 + scenario shots.
- chrome_devtools MCP: resize_page (49 calls), evaluate_script (187; DOM readbacks: element counts, overflow, bounding boxes),
  real DragEvent/DataTransfer click-drag-drop, console messages, take_snapshot.
- Node scripts: `verify.mjs`, `browser-checks.js`, `browser-results.json`, `layout-results.json` (document overflow, top-controls
  in viewport, gaps in px per viewport), CSV key/link checks, SHA256 of selected art, `node --check app.js`, Prettier through a
  temporary pre-commit hook. Table of overflow results in REVIEW.md.
- Limits explicitly stated: cannot certify 3D collision, camera, PBR, Godot font scaling, controller nav, localization expansion.

(2) Godot native:

- Headless `--script res://tests/*_suite.gd` + `tests/run_checked_script.sh` greps a PASS regex from output (smoke, resources,
  saves, sound, campaign) wired as pre-commit hooks (godot-import/parse/smoke/resources/saves/sound/campaign/review-fixes).
- UI-specific: `tests/workbench_shell_test.gd` with 568 native UI assertions + 62 input checks, exercised on the REAL Main scene
  (no mocks "fabricate the missing UI"), TDD RED then GREEN, run in an isolated project copy with isolated XDG\_{DATA,CONFIG,CACHE}\_HOME
  to avoid clobbering the user's editor state / concurrent runs.
- Native renderer: `DISPLAY=:0 XAUTHORITY=/run/user/1000/gdm/Xauthority XDG_RUNTIME_DIR=/run/user/1000 godot --display-driver x11 --rendering-method gl_compatibility --path ... --script ...` (22 uses in the UI thread). Needed because headless Dummy renderer
  gives wrong data (MultiMesh colors, 16-bit precision issue .7 -> .6997 discovered only natively).
- Screenshots: a temporary `.mz/ui-capture.gd` captures only the game's own rendered viewport ("viewport-local InputEvents avoid
  double window-stretch conversion"), producing 1280x720 and 960x540 PNGs (idle / selected), reviewed by sub-agent with view_image
  and by parent.
- Model reviews: independent plan reviewer, test-coverage reviewer, test-craft reviewer, simplicity reviewer, completeness checker
  (the mz-dev-pipe build flow). Most UI review verdicts are PASS with "small text at 960px remains follow-up".
- NOT done: no automated screenshot comparison/golden images, no contrast calculation on rendered pixels (SPEC says "test final
  rendered pairs and hit rectangles rather than claiming compliance from token values" but no tool does), no pseudo-localization,
  no font-size/hit-target audit, no check that every tr() key exists in CSV (only a one-off audit "47 unique nonempty entries, no
  missing/orphan keys or scene text literals" in the first i18n batch, 259 rows now).

## 4. Plugin proposals (godot-ui plugin; names are suggestions)

Principle: put deterministic stuff in scripts (GDScript/Python run via Bash, no LLM), put taste in judge agents with a rubric,
and put the browser\<->Godot handoff in a contract file. Everything below traces to evidence above.

### 4.1 Skills

S1. `ui-brief` (interview + brief writer)

- Why: H0-H14 show the best results came from numbered-default questions; and the orchestrator brief (85 lines) was the
  highest-leverage artifact. Failures C/D came from missing hard rules at brief time.
- Does: interview \<=5 defaulted questions per round (scope, surfaces, resolutions, input devices, text languages, art direction
  locked?), then writes docs/<surface>-ui-brief.md from a template with MANDATORY sections: ownership (files NOT to touch),
  hard rules inventory (copied from AGENTS.md "corrected by user" bullets), resolution matrix, state matrix
  (available/selected/hover/occupied/locked/blocked/running/paused/completed), acceptance with `verify:` per item, "what the
  browser cannot certify".
- Output also a machine-readable `ui-contract.json` (see 4.3).

S2. `ui-concept-first` (visual direction before HTML)

- Why: H20 "too heavy" after full HTML build; gallery of 3 fal concepts then one pick unlocked the work.
- Does: generate N concepts (fal via the existing fal-media plugin), build comparison gallery, record selection in
  manifest.json, write visual-direction doc with a REQUIRED section "Correct the concept during implementation" listing
  generated-image errors (extra slots, garbled text). Rule: concept images are references only; text/icons/slot counts rebuilt
  from game state; never ship text baked into art.

S3. `ui-html-prototype` (design artefact, with the exact structure that worked)

- Template dir: index.html + app.js + style.css + localization.csv (same key scheme as game.csv) + fixtures.json (scenario
  selector) + tokens.json + verify.mjs + README/SPEC/FLOWS/GODOT_HANDOFF/REVIEW. Rule: copy comes from the CSV, never inline;
  prototype fixtures are "illustrative, model owns state". Serve with a script (python http.server on a fixed port) because CSV
  fetch needs HTTP.
- Tie to existing tool: chrome-devtools/Claude-in-Chrome for native-size screenshots + DOM readbacks; checklist from REVIEW.md.

S4. `ui-godot-handoff` (wireframe/prototype -> Godot scene plan)

- Why: GODOT_HANDOFF.md's component table was the actual bridge; H184 shows the link was forgotten otherwise.
- Does: scans scenes/scripts, produces "Existing component -> responsibility -> design binding" table, P0/P1 with `verify:` lines,
  unresolved list, and a batch plan (\<=5 files, \<=300 lines, RED test first). Emits Control-tree sketch per screen
  (Container choice, size flags, anchors, focus order, mouse_filter per node: decorative = IGNORE, panels = STOP/PASS) and the
  input-routing decision (GUI vs `_input` vs 3D ray) - the project's own plan identifies "`_input` precedes GUI handling".
- Not a converter: HTML->.tscn conversion is brittle; generate code-builder or scene with typed Resource style instead.

S5. `ui-style-resources` (Theme/StyleBox as typed Resources)

- Why: AGENTS.md demands "all configurable parameters in .tres typed resources; text in CSV"; 35 font_size/theme uses sit
  in scripts. Provide a pattern: `UiStyle` Resource (colors from tokens.json, spacing 4px scale, font sizes, StyleBoxFlat
  recipes, min target sizes), one Theme built from it, test that no script contains literal colors/sizes. SPEC.md already defines
  tokens (surface #11181B..., 4px space, body 14-16, calendar >=13). Skill generates Theme + style resource from tokens.json.

S6. `ui-responsive-check` (native screenshot matrix)

- Why: brief required 5 resolutions; shell shipped at 1280x720/960x540 with "small text at 960" left as follow-up.
- Does: runs the game (or one scene) at a resolution matrix via a capture script (viewport capture, DISPLAY on, fallback
  xvfb), stores PNG + layout JSON (every Control: global_rect, clipped?, overflow?, below min font?, hit target < 32px?),
  then spawns the screenshot-review judge. Includes ultrawide and an explicit "late in a long action" scenario (brief item 4:
  "so disappearing/overlapping content cannot be hidden by an idealized initial screen").

S7. `ui-localization` (extract + pseudo-loc + lint)

- Why: only English exists; admitted risk. CSV with stable UPPER keys, named placeholders, `_comment` column worked well.
- Does: extract literals into game.csv (key proposal rules: AREA_THING), add locale columns, generate pseudo-locale (+40%
  expansion, accented, bracketed) as an extra translation file for the responsive check, check placeholders parity per row
  (`{count}` in every column), live refresh via NOTIFICATION_TRANSLATION_CHANGED. Delegates actual translation to mz-research-pipe
  translate.

S8. `ui-screenshot-review` (look and critique)

- Why: view_image x94 by the UI agent; reviews are the only visual check. Formalize: given PNG set + brief, produce findings
  using the judge in 4.2 and open issues as a checklist. Include "compare against concept reference" mode (native visual
  comparison named in salvaged-instruments doc step 2) and "stale screenshot" detection (REVIEW.md 'historical' shots).

S9. `ui-input-routing` (3D+Control hybrid; project-specific insight)

- Checklist skill for overlay UI above a 3D world: mouse_filter on decorative Controls, `_gui_input` + accept_event, `_input`
  gating when modals/Results own input, SubViewport forwarding, drag-from-table into HUD slots, hover highlight lookup,
  focus order, keyboard alternative to drag. Evidence: many tests (timeline_input_handoff_suite, workbench_shell_test,
  picking fixture fix for Oxygen/Food pile ray hit).

### 4.2 Judges (agents with a rubric and JSON verdicts, modelled on dramaturgy drama-judge / fal physical-judge)

J1. `ui-readability-judge`: input = PNG + resolution + layout JSON; rubric = text >= min size at given res, contrast pairs
(SPEC target 4.5:1 / 3:1), item-vs-background separation at 120-240px (AGENTS: gray tools on gray busy bg), no overlap
between active work and history labels, no clipping, no text over busy art without support gradient.
Output {pass, findings[{where, rule, severity, evidence}]}. Hybrid: numbers come from the script, judge only interprets.
J2. `ui-state-language-judge`: checks state matrix is distinct without color alone (icon+label+structure), each of the 10
states reachable and consistently styled (from SPEC "Never rely on category color alone").
J3. `ui-brief-conformance-judge`: reads the brief's hard-rule list (edge-to-edge art, top-right category icon, no "No expiry"
badge, text not in image) and a screenshot; flags violations. This is the automated version of AGENTS.md "corrected by the user".
J4. `ui-concept-vs-impl-judge`: compares reference concept image and native screenshot on material, hierarchy, density
("too heavy / too many panels"), ignoring generation errors listed in the direction doc.
J5. `ui-ux-heuristics-judge` (fresh-eyes, per user's own rule "Fresh Eyes Pass"): walks the flow as a new player using the
flows doc, flags undiscoverable steps ("give hints on what can be done", VERBS complaint). Needs flow scripts as input.
Policy needed: when judge (critical) and owner (taste) disagree (research icon 3 vs 4 nodes), record a waiver in a
`waivers.json` with reason - currently left "open" forever.

### 4.3 Contracts (files that glue roles together)

C1. `ui-contract.json` per surface, produced by the brief and consumed by prototype, implementation and checks:
{ surface, resolutions[], min_font_px, min_target_px, states[], hard_rules[{id,text,check}], tokens_ref, strings_csv,
owners{files_allowed, files_forbidden}, authority: "model owns state; prototype fixtures illustrative" }.
C2. `ui-handoff.md` fixed schema: component table, P0/P1 with verify, unresolved list, "cannot certify in browser" list.
C3. `tokens.json` single source -> generates CSS vars (prototype) and Godot UiStyle .tres (runtime). Avoids the "one source of
truth" violation (palette duplicated: pilot/colors.json vs CSS vs .tres; SPEC says "do not maintain a second palette").
C4. `string-catalog contract`: keys stable UPPER_SNAKE, `{named}` placeholders, `_comment` meaning column (already game.csv);
prototype CSV and runtime CSV share the key scheme so merge is mechanical ("Merge appropriate keys ... through the
runtime owner's workflow").
C5. `ui-screenshot-manifest.json`: {file, size, scenario, godot_commit_or_hash, generated_at, current:true|historical}; check
that README/REVIEW only cite current ones.
C6. Ownership contract (from CLAUDE.md/AGENTS.md): UI role may not edit scripts/scenes/i18n runtime; runtime owner integrates a
patch set. Enforce with a hook (4.4 H1).

### 4.4 Deterministic checks (scripts / hooks; no LLM)

Static (GDScript/scene/CSV parsing, Python script run via pre-commit or PostToolUse):
D1. Hardcoded player strings: scan `.gd` for `.text = "..."`, `Label.new()` then `.text`, `tooltip_text = "`, `title = "`, `tr("...")`
with non-key literals; scan `.tscn` for `text = "` with non-key values. Allowlist for "" and debug. (Evidence: i18n audit was
done once manually; 174 tr sites and growth.)
D2. Missing/orphan translation keys: all `tr("KEY")`/key-metadata exist in game.csv; all CSV keys referenced; duplicated keys;
placeholder parity across columns; empty cells for shipped locales; `.translation` newer than CSV (stale import).
(Note: repo has `.csv.import`; a stale `.translation` is a real silent failure mode.)
D3. Anchors/containers misuse in `.tscn` and code builders: Control inside Container with manual `position`/anchors set
(ignored), `set_anchors_preset` after parent add, `size_flags` missing on expanders, ScrollContainer child without
custom_minimum_size, Label with `autowrap_mode` but no minimum width (collapses to 1 char), TextureRect without
`expand_mode`/`stretch_mode` (image doesn't fill: the edge-to-edge card rule), decorative nodes lacking
`mouse_filter = IGNORE` (AGENTS: "Decorative overlays should ignore input"), panels over world without STOP/PASS decision.
D4. Min font size: resolve `font_size` literals + theme/Resource values `< min_font_px` (SPEC: body 14-16, calendar >= 13, secondary 12).
Check Resource `.tres` values, not only code (project keeps tuning in Resources).
D5. Min hit target: from the layout JSON dump (S6) any interactive Control with size < 32x32 (24 absolute floor).
D6. Hardcoded colors/sizes in scripts (`Color(` literals, magic px) outside style Resources - enforces AGENTS "all configurable
parameters belong in Godot resource files".
D7. Contrast calc: from tokens or sampled pixels of screenshot regions: fg/bg ratio vs 4.5/3.0. Tokens-level as a static check,
pixel-level in S6.
D8. Layout dump invariants at each resolution: no Control outside viewport, no sibling overlap except allowed pairs, clipped
text (Label.get_line_count\*height vs rect), ScrollContainer content exceeding without scrollbar, focus chain complete
(every interactive control has `focus_neighbor` or is in an ordered container) and visible focus style exists.
D9. Screenshot hygiene: size equals declared size; not stale vs contract manifest (C5); no sub-pixel resizing; PNG dimensions
match filename (REVIEW used Pillow already).
D10. Pseudo-loc run: switch to pseudo locale, rerun D8 and fail on new overflow/clipping.
D11. Art composition rules: card art rendered via UI overlay, source images contain no text (cheap OCR or judge), `art` fills
card (aspect crop) - test asserts TextureRect stretch mode.
D12. 300-line source cap and "no .tscn bloat" (already AGENTS rule; make it a hook): applies equally to UI controllers.

Hooks:
H1. PreToolUse: block UI-designer role from editing `scripts/ tests/ scenes/ project.godot i18n/` (ownership contract C6).
H2. PostToolUse on edits to `i18n/game.csv` or `.gd`: run D1/D2 in \<2 s.
H3. Stop hook: if UI files changed this turn and no native screenshot exists newer than the change, remind (not block).
H4. SessionStart: detect display availability (DISPLAY=:0/xvfb) and warn that headless Dummy renderer cannot verify rendering.

### 4.5 Runner / MCP-style helpers

R1. `godot-native-run` wrapper script encapsulating the incantation (isolated XDG dirs, DISPLAY/XAUTHORITY/XDG_RUNTIME_DIR,
`--display-driver x11 --rendering-method gl_compatibility`, log to file, grep PASS regex) - this exact command was
hand-rebuilt dozens of times; also `--headless` variant for logic tests. Include a ui-capture.gd template (viewport image
save, window-size override, viewport-local InputEvents).
R2. `prototype-serve` script (python http.server on free port, prints URL) for user "Start server so i can open".

## 5. Priority order for the marketplace

1. D1/D2/D4/D3 static checks + H1/H2 hooks (cheap, deterministic, directly address "all text in CSV" and "all tuning in Resources").
1. R1 native-run + S6 responsive capture with layout JSON (turns the manual `DISPLAY=:0` knowledge into a tool; unlocks D5/D7/D8).
1. S1 ui-brief + C1 contract + J3 conformance judge (addresses repeated user restatements in AGENTS.md).
1. S2 concept-first before S3 HTML prototype (the "too heavy" failure) and S4 handoff template (works already).
1. J1 readability judge fed by numbers from S6; S7 pseudo-loc; S9 input-routing checklist (3D+HUD hybrids).

## 6. Risks / caveats

- Evidence is from one project and one UI agent; the 3D-tabletop shape may not generalise. Keep 3D-picking guidance in an
  optional skill (S9), core plugin = Control-based UI.
- Taste calls (heavy vs light UI) cannot be judged by a script; J4 only compares against an approved reference.
- The browser prototype phase consumed most effort (2476 shell calls, 187 evaluate_script) and was partly redone after style
  change; the plugin should make HTML prototypes optional/cheap for pure layout questions and push concept art earlier.
- No data on mobile/gamepad: SPEC mentions controller focus as unverified; keep as backlog.
- Pre-existing issues to surface to the user: stale `health-1920x1080.png`/`boundary-1920x1080.png`; 960px small-text follow-up;
  open judge finding on Research icon; non-null expiry badge decision unresolved; no UI Theme resource; locale expansion untested.
