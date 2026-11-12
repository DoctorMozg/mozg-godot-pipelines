# 03 - Graphics / art pipeline (AloneGodot, Codex era)

Sources: AGENTS.md "Image generation", art/\*\*, docs/g-alone-\*-art-brief.md, shaders/card_face.gdshader,
role digest g-alone-graph.md, `git log` (Nov 8-12 2026), `.png.import` files. Nothing modified.

Scale: 897 PNGs under art/ (3.5 GB; art/progression 1.5 GB, art/cards 1.1 GB), 389 commits, 1 shader,
141 Codex threads under g-alone-graph (1 root + ~140 subagents, many re-spawned with the same prompt).
Tool mix of g-alone-graph: 6214 exec_command, 932 view_image, 338 falkit CLI calls, 88 fal submit_job,
162 chrome_devtools evaluate_script (presentation page checks), 2 image_gen (built-in, then banned).

## 1. Actual pipeline end to end

```
 user prompt ("find a brief")         docs/g-alone-cards-production-brief.md  (roster, categories, 5-step plan)
        |                                          |
        v                                          v
 model pick (recommend_model, 2026-11-08)   master style root: art/references/master_style_v00{2,3}.png
 -> google/nano-banana-2.1 (+ /edit)        (v002 painterly REJECTED -> v003 photoreal/dark)
        |                                          |
        v                                          v
 reference roots (art/references/pilot/ref-*.png): character-identity_v002, thermal-suit_v002,
   habitat-environment_v003, materials-equipment_v001, research-treatment_v003, psychology-treatment_v003
   + art/pilot/colors.json (semantic resource colour legend)
        |
        v
 plan.json -> falkit (fal-media 0.13 -> 0.19.2) -> fal queue (nano-banana-2.1/edit, 2K PNG, 2:3|1:1|3:2)
        |        receipts/<step>/result.json, ledger-final.json (usd_reserved/usd_charged, request_id)
        v
 sources/<id>-vNNN-tK.png  +  <png>.judge.json  (falkit physical judge: Q1 anatomy ... critical/major)
        |
        v
 independent visual QA (art/pilot/reference_review*.json, card_review_a/b.json, item_contrast_review.json)
   - view_image at original detail + actual 120/240 px crops; "technical pass != user approval"
        |
        v
 per-batch manifest (art_manifest.json / progression/*/manifest.json)   <- state lives here
        |
        v
 contact sheets (art/contact_sheets/full_batch_NN.jpg) + art/progression/presentation.html (+validation mode)
        |   user: Approve / Redo; Copy list of redo ids  -> next redraw round (validation-redraw-v001)
        v
 optional: depth map via fal-ai/marigold-v2 (art/depth/cards/*_marigold_*.png 512x768), layer cutouts
        (bria/guided-remove-background) -> art/layers (parked: "keep the old parallax")
        |
        v
 Godot: art/cards/<family>/<id>_v001.png (+ .import) -> typed resource (card_art_*.tres)
        -> shaders/card_face.gdshader (artwork + depth_map parallax) ; tests/card_art_*_suite.gd
```

Roles: g-alone-graph = brief/generation/review; g-alone = orchestration + Godot integration; each
incoming art brief -> subagent with explicit file ownership (AGENTS.md); user = sole final approver.

### State holders (several overlapping schemas, no single contract)

| File                                                                     | Holds                                                                                                                                                                                  |
| ------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| art/pilot/art_manifest.json, art/full/art_manifest.json                  | per-card: image_path, depth_path, status (`approved_by_user`), endpoint, request_id, input (prompt, image_urls, aspect_ratio)                                                          |
| art/progression/\*\*/manifest.json (schema_version 1, ~30 files)         | per-asset provenance: path, source_url, request_id, sha256, dimensions, full input, references[{path,sha256,role}], receipt, physical_judge, plan, technical_review, user_art_approval |
| art/progression/\*/ledger-final.json (contract 0.9.0, from falkit)       | job ledger: request_id, state `verified`, usd_reserved/charged, file sha256, status/cancel URLs                                                                                        |
| art/progression/asset-audit.json                                         | campaign asset list vs reference_roots (id, group, status exact/...)                                                                                                                   |
| art/pilot/reference_manifest\*.json, family_reference_manifest_v003.json | reference roots + review verdicts                                                                                                                                                      |
| art/layers/manifest.json, art/depth/\*\_depth.json                       | layer/depth provenance incl. `user_decision` text and depth-conversion error                                                                                                           |
| art/progression/remaining-queue.json                                     | production queue                                                                                                                                                                       |
| localStorage in presentation.html                                        | Approve/Redo decisions (browser only, not in repo)                                                                                                                                     |

Manifest example (art/progression/habitat-revision/foundation/manifest.json, trimmed; prompt is ~3 KB):

```json
{ "schema_version": 1,
  "assets": [{
    "id": "landing_habitat", "step_id": "habitat-ship-section-v001",
    "path": "art/progression/habitat-revision/foundation/sources/habitat-ship-section-v001-t1.png",
    "provider": "fal.ai", "endpoint": "google/nano-banana-2.1/edit",
    "request_id": "01a1ca2f-3b84-7190-aee0-5384eec4306a",
    "sha256": "c4445b9f...", "dimensions": [2528, 1696],
    "input": {"prompt": "A large SURVIVING HABITABLE SECTION TORN FROM A CRASHED SPACECRAFT ...",
              "aspect_ratio": "3:2", "resolution": "2K", "seed": null, "image_urls": ["..."]},
    "references": [{"path": "art/references/master_style_v003.png", "sha256": "e72a1f...",
                    "role": "master style v003 reference as specified in prompt"}],
    "receipt": ".../receipts/habitat-ship-section-v001/result.json",
    "physical_judge": ".../habitat-ship-section-v001-t1.png.judge.json",
    "technical_review": "pass", "timeout": null, "user_art_approval": "standing-authorized" }],
  "archives": [] }
```

Observations: reference `role` is a boilerplate string, not a real role; `user_art_approval` has values
like `approved_by_user` / `standing-authorized` (free text); `timeout` (card gameplay data) is smeared into
an art manifest (user had to correct what it meant); the old art_manifest.json (pilot) uses different keys
(`image_path`, `status`, `endpoint_id`) than progression manifests (`path`, `endpoint`). Two generations of schema.

## 2. Recurring corrections and failures (quoted)

Art direction / style root

- H4 "No, should be more photorealistic and dark." -> AGENTS.md: "The initial painterly master reference was rejected; do not use it as a style root." Root v002 had already been used for depth/layers demo (art/depth/master_style_v002\_\*), so early demo work was on a rejected root.
- H16 "Pilot is something not a guy not a girl, make it a proper masculine guy." -> identity refs v001 superseded by `ref-character-identity_v002`; AGENTS.md: "Earlier androgynous character references are superseded and must not guide new character images." (identity drift in the seed reference itself).
- H17 "Psychological cards must be more abstract, research cards should be more blueprint-like." Per-family rendering exceptions now written in AGENTS.md.
- H42/H44/H45 habitat: "it's too swmall on the image" / "LArger one" / "It should look like a part of crushed ship" -> a full re-render of habitat and "all affected images" (a dependency fan-out the manifests did not track; asset-audit.json had to be created later). AGENTS.md encodes it as "Habitat identity, corrected by the user on 2026-11-11 ... the old small standalone capsule is superseded."

Readability at card size

- H18 "items must be clearly visible on the backround. For example multitool is grey on grey background." -> AGENTS.md: "separate every item from its background at 120-240px using deliberate value contrast ... Do not place gray tools on similarly gray busy backgrounds." Spawned item_contrast_plan_v002 / item_contrast_review.json. Review done by looking at 120/240 px crops - done manually via view_image.
- H37 "Severe Cold Exposure --- bugged hands. Redo." Anatomy defects (hands) found by the user, not by the pipeline; later falkit's judge Q1 "count heads, arms, legs, hands and fingers" was added.
- H32 "For conditions use parts of the body, not the whole colonist."
- H35 "Each hazard image should tell a story in one frame. It sohuld be interesting to look at." -> a "hook" per hazard in briefs (g-alone-hazard-runtime-art-brief.md).
- H50 batch of 16 redo ids (Micrometeor Shower, Rescue Window, R2D, Never Returned, Surveyor, Pressure Shell ...) "these need fixing and possible prompt changing/redesign." Fixed through validation-redraw-v001 (14 unique redraws; several went v002/v003/v004, e.g. engine-graveyard v004, freight-section v002-fix2). Taste failures are story-readability, not technical.

Text / UI in images

- AGENTS.md: "Exclude text, frames, and UI from final illustrations"; prompts carry "no built-in card frame, gradient border, letters, pseudo writing, text, numbers, logo, UI or watermark". User asked the opposite once (H14 "Some should show text") and then settled: "Compose readable card text separately."
- H19 "each card should have its type in a top-right corner. Just a small simple flat icon." -> "composed in the UI rather than generated into its artwork."
- H28 "No expirty should not be shown on the card" (UI shipped a "No expiry" badge; field semantics `timeout` also clarified through a user question).
- Commit "Require edge to edge artwork" + orchestrator: "Also card images should fully fill card background."

Colour legend

- H12 "oxygen is one color, water is another. If device uses resources - it should also use these resources colors." H13 "Psychology should have its own color map, research too." Result: hex legend inlined into every prompt (water #3B78C8, ice #9AC7DF, oxygen #74C9B0, power #D3A247 ...) and art/pilot/colors.json.

Depth/parallax

- H9 "trace behind the character is too visible, also make a demo image much smaller" -> layered cutout approach (bria + clean background by nano-banana edit) built, then H10 "Let's keep an old parralax for now." (art/layers/manifest.json `user_decision`). Wasted: layer generation. H19 "Blueprint researches doesn't need depth" (cost + visual: static).
- fal-media allowlist lacked Marigold schema/pricing -> blocked, user had to answer a question ("May I use live checks?"), then H8 "Add price rule to json and continue".

Overwriting / preservation

- AGENTS.md: "Preserve accepted originals; never overwrite them with retakes"; README: "Originals and rejected attempts remain preserved." Retakes are new files (`-v002-t1`, `-fix2-t1`). But gallery picks "selected" by path in manifest, so an old PNG staying around causes ambiguity for imports (art/cards/\*\_v001.png still the Godot target).
- H42-class re-renders are expensive: 27 PNGs >8 MB; 14 redraws needed 5 job rounds in one ledger.

Cost / approvals

- H26 retry of two helmet edits: "May I retry ... Estimated cost is $0.13 ($1.04 plan worst case); the failed connection left the previous billing status unconfirmed" -> user "Approved." fal-media's no-double-pay guard worked but required human round trips.
- H39/H41 "Next time a brief comes: start subagent without approval, all coming briefs need to be rendered through fal.ai immediately" and "anything that is scheduled is approved" -> AGENTS.md standing authorization ("Incoming art production briefs ... authorize immediate fal.ai rendering"). Approval friction was the biggest process complaint.
- H51 fal-media wanted explicit user decision to clear a "reference-check flag caused by missing review references" (reference list not recorded -> later false flag).
- Costs seen: 0.06615 USD per nano-banana 2K edit, 0.03 per marigold depth; ~900 images.

Review UX

- H15 "After finishing - create similar HTML presentation"; H21/H46 "don't forget to always update" -> AGENTS.md rule "Always refresh art/progression/presentation.html after accepting new or revised artwork"; H47 validation mode (random order, approve/redo, Copy list). 10 stale `art/full/presentation-NN.html` + fragments + build_presentation.py duplicates; progression/presentation.html has validation.js + validation.test.js (156 lines) - the one tested piece.
- Same delegated prompt appears 10+ times across re-spawned subagents ("Harvey the 2nd", "Planck the 2nd", ...): validation mode took ~15 agent attempts (interruptions/restarts), the question reply "Yes ... use defaults" repeated every time. Evidence of lost state on restart.

## 3. Godot-specific graphics and what went wrong

Textures

- Card art PNGs: 1696x2528 (2K 2:3), ~8 MB each, 157 imported cards, 1.1 GB on disk. All `.import` files use `compress/mode=0` (lossless, no VRAM compression) - 294 depth + 266 progression + 157 cards + others. Inference: ~1696*2528*4\*1.33 = ~23 MB VRAM per card texture uncompressed; never profiled in the logs (no performance work found for art). No size budget was ever enforced; masters are shipped at full 2K for hover-detail.
- Mipmaps: Godot default `mipmaps/generate=false`. Cards are displayed at 120-240 px from a 2K source -> heavy minification aliasing/shimmer. Fix came afterward as a string of one-folder commits, in order: "Enable card resource mipmaps", "Enable card artwork mipmaps", "Enable recovery and condition mipmaps", "Enable supply card mipmaps", "Enable transmitter and strain mipmaps", "Enable tabletop texture mipmaps", "Enable condition card mipmaps", "Enable activity artwork mipmaps" (8 commits), then "Require mipmaps in selected rendering data" (tests/card_art_selected_suite.gd: `image.has_mipmaps()`), then "Enable detail preview mipmap filtering" (scenes/main.tscn: `texture_filter = LINEAR_WITH_MIPMAPS` on DetailArt). Root cause: nothing set import defaults for art at generation time; the check was written only after the visual defect. Current state: art/cards 157/157 mip=true, art/transmitter 12, art/activities 7, art/runtime 7; art/progression 266 mip=false and art/table 16 mip=false (11 true) - not yet integrated or inconsistent; art/depth 294 false (correct for depth maps, linear no mipmaps).
- Filtering is set in two places and both must agree: import mipmaps AND sampler (`filter_linear_mipmap` in shader uniform `artwork`; `TEXTURE_FILTER_LINEAR_WITH_MIPMAPS` on TextureRects). Depth map sampler is `filter_linear` without mipmaps, `source_color` missing -> correct for data textures.
- Import flags handled by hand: no `project.godot` default (grep for texture/mipmap/compress in project.godot found none); each new batch gets a `.import` edited ad hoc. Also gdlintrc/pre-commit hooks (godot-import, godot-smoke, godot-resources ...) exist but 50+ graph commits ran with `SKIP=godot-import,godot-smoke,...`, so the hooks were bypassed to commit art quickly.

Shaders / depth parallax

- Single `shaders/card_face.gdshader` (spatial, unshaded): rounded-corner discard, stock border, cover-fit crop (`image_aspect`/`face_aspect`), depth displacement `offset * depth * depth_strength * edge fade`, clamp to 0.001-0.999. Introduced via commits "Extract shared card face shader resource", "Fill card faces with artwork", "Require edge to edge artwork". All tuning values are in typed Resources (AGENTS.md rule: "All configurable parameters belong in Godot resource files").
- Depth: Marigold v2 returns a colourised (Spectral) depth PNG; conversion back to 8-bit grayscale by nearest-LUT (mean RGB error 1.14, "relative, not metric"). 512x768 depth for 1696x2528 art (low-res, bilinear-sampled). Prototype was Three.js/HTML (demos/card-parallax.html) before the Godot shader - two implementations of the same effect.
- User-driven limits: parallax only for physical cards; research static; psychology debated.
- Not found anywhere: atlases, texture streaming, VRAM compression (S3TC/BPTC/ASTC), 3D-vs-2D profiling, GPU memory test. All textures are individual 2K files. This is the main unaddressed risk.

Process-level problems on the Godot side

- The art->game contract is implicit: art/cards/<family>/<id>\_vNNN.png -> typed resource -> tests ("Validate card artwork before table allocation", "Define typed runtime card art resources", "Select artwork by card definition"). Selection is by path; moving to v002 means editing resources manually.
- `.import` files committed with `dest_files` hashes; 296 .import files under art/depth alone clutter diffs.

## 4. Plugin proposals

Principle: fal-media already owns generation safety (plan.json, ledger, spending guard, judge). The Godot plugin should add art-bible/consistency, manifests, Godot import/integration and review UX, and delegate rendering.

### 4.1 Reuse from fal-media (do not rebuild)

- `fal-plan` (plan.json, price check), `fal-run` (resumable, no double pay, ledger-final.json with request_id/sha256/usd), `fal-assets` (nano banana stills, uploads), `falkit judge sheet`, `physical-judge` (anatomy/support/scale questions), `stills-writer` (prompt writer from brief), `take-pick` (two-way pick).
- Evidence: all 88 submits and 338 falkit calls already went through it; the ledger gave the money/ids provenance. Gaps seen: allowlist blocked marigold depth (user had to intervene), reference roles recorded as boilerplate, reference-check flag needed manual clearing (H51). Ask: add `depth` / `bria` model entries and an explicit per-reference `role` field in plan.json.
- `dramaturgy:drama-bible` already designs cast/props "identical in every shot" and plans reference plates: reuse the idea for the style root and character/prop roots; do not reuse its video-specific parts.

### 4.2 New skills (godot-art plugin)

1. `art-bible` (style root + reference roots). Output: `art/bible.json` + `art/references/*` with sha256. Fields: master_style, per-family rendering mode (photoreal / abstract / blueprint), identity roots (face, suit), palette/legend (semantic colours with hex), banned list ("painterly", "text"), min-subject size at 120/240 px, aspect ratios. Evidence: v002 painterly root rejected after demos had been built on it; identity v001 androgynous; family exceptions only encoded late in AGENTS.md; hex legend pasted into every prompt by hand. Gate: user must approve the root in the review page before any asset batch (brief step 1 existed in docs but was not enforced).
1. `asset-brief` (one asset -> one record). Fields: id, family, hook ("what story in one frame", H35), readable-at-size note, required refs (roots by name, not "previous card"), forbidden content, background/contrast plan (H18), dependents (what else depends on this image, H42 habitat re-render fan-out). Writes to `art/briefs/<id>.json`; a lint rejects briefs without roots (AGENTS.md: "Do not chain only from the previous card").
1. `art-batch-render` (thin wrapper over fal-plan/fal-run): expands briefs -> plan.json with stills-writer prompts, refs with roles, fixed aspect ratio, 2K PNG; runs; writes manifest rows (4.4). Applies the standing-authorization policy from the project config (spend cap per batch) instead of asking for every batch (H39/H41 pain). Never overwrites: output name `<id>-vNNN-tK.png` only.
1. `art-review` (contact sheets + review page): generates contact sheets and the review HTML from the manifest (not hand-built per batch), with validation mode (random order, approve/redo, Copy list, localStorage) taken from art/progression/validation.js, but persisting decisions to `art/review/decisions.json` (export button) so a restarted agent does not lose state. Also renders 120 and 240 px thumbnails of each image side by side. Evidence: 10 stale presentation-NN.html, validation mode re-asked ~15 times, "always update presentation.html" rule in AGENTS.md - should be an automatic output, not a rule.
1. `godot-art-import`: given approved manifest rows, copies into `res://art/<family>/`, writes/validates `.import` settings (below), creates or updates the typed Resource entry (path -> definition id), runs the existing Godot headless art tests. Replaces the 10-commit mipmap saga.
1. `card-shader` / `parallax-depth` (low priority, keep as reference): depth map via marigold-v2 at the art aspect, conversion to relative gray (the LUT script exists in art/depth), card_face.gdshader as a template with uniforms in a Resource. Include the lesson "depth only for physical-world cards; research static".
1. Redraw loop: `art-redraw` consumes the Copy list (id | title | path), re-opens each brief with a user note, renders v+1 and re-adds to review. Evidence: the identical 16-line list was pasted 6 times in different subagents.

### 4.3 Judges (subagents, read-only, return JSON like fal-media judges)

- `readability-judge`: input = 120 px and 240 px downscales + full image; rubric: focal subject silhouette separated by value contrast, subject in safe area (10% margins), no gray-on-gray, hands/anatomy count (reuse physical-judge Q1-Q?), no text/letters/UI/frame. Evidence: H18, H37, "Keep focal subjects readable at card size". Automate the downscale and a pixel-contrast metric (luminance delta between central mask and ring) as a deterministic pre-check, then the LLM judge for what metrics cannot tell.
- `style-consistency-judge`: input = candidate + master root + relevant identity/prop roots, per-family mode; rubric: photoreal vs painterly, palette within legend, face matches identity root (compare against ref), suit, habitat identity (large crashed ship section). Evidence: painterly root, androgynous colonist, habitat "capsule" regressions, Surveyor "reference-check flag". Always record which references were shown (fixes H51).
- `story-hook-judge` (optional, hazard/event scenes): "does the image tell one story in a frame?" (H35, H50).
- Judge verdict is "technical pass", never approval; approval stays a user field (matches existing "Technical passes are not user approvals").

### 4.4 Manifest schema (contract) - single `art/manifest.json` (or per-folder shards merged by a tool)

```json
{ "schema_version": 2, "bible": "art/bible.json",
  "assets": [{
    "id": "ice_survey", "family": "research", "kind": "card_art|scene|reference|depth|ui",
    "brief": "art/briefs/ice_survey.json",
    "status": "draft|rendered|judged|approved|redo|superseded",
    "selected": "art/cards/research/ice_survey_v002.png",
    "versions": [{"path": "...-v001-t1.png", "sha256": "...", "request_id": "...", "endpoint": "...",
                  "input": {"prompt": "...", "aspect_ratio": "2:3", "resolution": "2K", "seed": null},
                  "refs": [{"path": "...", "sha256": "...", "role": "identity|style|prop|geometry"}],
                  "dimensions": [1696, 2528], "usd": 0.06615, "ledger": "...ledger-final.json",
                  "judges": {"physical": "pass", "readability": "pass", "style": "pass"}}],
    "approval": {"by": "user", "at": "2026-11-08", "mode": "explicit|standing"},
    "godot": {"res_path": "res://art/cards/research/ice_survey_v002.png",
              "import": {"mipmaps": true, "compress": "vram|lossless", "max_size": 1024},
              "depth": null, "resource": "resources/card_art/ice_survey.tres"},
    "dependents": ["habitat_exterior", "hrev-*"] }] }
```

Rules: only `selected` is used by Godot; superseded versions are kept, never overwritten; `refs[].role` is mandatory and specific; game data (e.g. `timeout`) stays out of the art manifest.

### 4.5 Deterministic CLI checks (`godot-art check`, no LLM; pre-commit friendly)

Each maps to an observed failure:

1. Every manifest `selected` file exists, sha256 matches, dimensions match record (manifest\<->file consistency; 30 shards today).
1. Every PNG under art/ is referenced by a manifest, or flagged orphan (stale `art/full/presentation-NN.html`, unreferenced sources).
1. Import audit over `.import`: mipmaps/generate=true for everything rendered below native size (cards, UI art), false for depth maps; fail like the 10 mipmap commits; also flag `compress/mode=0` (lossless) above a size budget.
1. Size budget: max texture dimensions and bytes per family (e.g. cards 1696x2528 / 8 MB are 4x oversized for 240 px view); estimate VRAM total (w*h*4\*1.33 per texture or compressed size) and fail when above a configured budget. No such check existed.
1. Aspect ratio per family matches bible (2:3, 1:1, 3:2); no RGBA with unexpected alpha; 8-bit; PNG not truncated.
1. Sampler agreement: scan .gdshader / .tscn for `texture_filter` and `filter_*` on textures whose import has/hasn't mipmaps.
1. Palette lint: sample edge/legend colours vs bible hex (loose delta E) for family border grading.
1. Text-in-image heuristic: OCR pass (tesseract) flagging letters in `kind=card_art` (AGENTS.md "no text").
1. Readability metric: contrast between subject centre and surroundings at 120/240 px; flags gray-on-gray (H18) before the judge.
1. Review page sync: every `approved` selected path appears in the generated review page; page loads in headless Chrome, no broken images (replace the manual chrome_devtools checks: 162 evaluate_script calls).
1. Spend: ledger usd_charged sum vs batch cap; every request_id in manifest exists in a ledger (no unrecorded paid job).
1. Reference existence: every generation lists refs with roles; none points at a superseded/rejected root (bible keeps a `superseded` list: painterly v002, androgynous refs).

### 4.6 Hooks / config

- PostToolUse on art file writes: run `godot-art check` quick subset.
- Project config `art.config.json`: standing-authorization budget per batch (what the user ended up writing in AGENTS.md), default model, texture budgets, family modes.
- Do not skip pre-commit hooks for art commits: make check fast instead (50+ commits used SKIP=godot-import,...).

## 5. Pre-existing issues surfaced (not fixed, per read-only)

- art/progression 266 and art/table 16 imports without mipmaps (unclear if displayed at reduced size).
- All textures lossless 2K; no VRAM-compression or atlas strategy; no profiling.
- Duplicate presentation-NN.html/fragments in art/full; two manifest schemas; `timeout` field inside art manifests.
- Reference `role` fields are boilerplate; AGENTS.md "Image generation" has become a changelog of corrections (should live in bible + checks).
