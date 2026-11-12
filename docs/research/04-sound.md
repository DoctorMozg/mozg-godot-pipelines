# 04 - Sound engineering: what AloneGodot did, and what a Godot plugin should offer

Evidence: AloneGodot repo (docs/sound-design.md, audio/, audio/README.md, audio/asteroid/provenance.json,
default_bus_layout.tres, resources/sound_settings.tres, scripts/sound\_*.gd, tests/sound\_*, tests/run_sound_tests.sh,
.pre-commit-config.yaml, .mz/research/2026_11_10_research_game_audio.md), the g-alone-sd digest, and the sd root
rollout (~/.codex/sessions/2026/11/10/rollout-...01a1c6fd-30b9-...jsonl; I read only user prompts and final answers).
The orchestrator digest (role_g-alone.md) has almost nothing on sound; it is a table-art/fal story, not audio.
Labels: [E] = evidence, [H] = hypothesis (thin evidence).

## 1. How sound was designed and produced

### 1.1 Timeline [E]

1. 2026-11-10 23:45 H0: "You're a sound designer. Research how to make good sound/soundtrack using fal.ai, and can I use my
   Unity Store assets in Godot." Result: 69-source research doc. Recommended ElevenLabs SFX v3 (`elevenlabs/sound-effects/v3`),
   Stable Audio 3 Medium (music), Mirelo SFX 2.0 (long ambience). It states "no samples were generated or auditioned".
   fal was never actually called for audio (the sd thread has 1 `fal__search_models` and 1 `get_model_schema`, nothing run).
1. H2-H4: user asks to download Unity Asset Store purchases. Unity CLI (beta.12) can `assets inspect/import/export` but cannot
   list or download purchases. Agent found 28 cached packs, then 78 packs / 7,424 audio files / 21 GiB after the user queued downloads.
1. H5: "listen to samples, check which are good, create a sound design document". The agent cannot listen. It decoded 24 files with
   ffmpeg, measured active span, peak, RMS, seam-step ratio, and wrote docs/sound-design.md as an *audition shortlist* with
   "listening in gameplay remains pending". Preview target was -24 dBFS RMS, -3 dBFS peak ceiling (a preview rule, not a ship target).
1. H6/H7 "Approve all defaults": implemented the sound system (branch codex/sound-system, merged to main at cf059a3 about 5 hours
   later). Plan went through the /build pipeline's plan-approval gate ("Never proceed to Phase 3 without explicit approval").
1. Follow-up bug: window close leaked audio streams (Godot issue #76745). Fixed with a 250 ms mixer drain; test runners now
   fail on "ObjectDB instances were leaked" / "resources still in use at exit" even if exit code is 0.

### 1.2 Sources actually shipped [E]

- Shipped palette is 100% procedural: provenance.json says "Original deterministic local DSP synthesis. Oscillators, seeded
  synthetic noise, shaped envelopes and circular placement. No input recordings, third-party media, network calls or paid generation."
  13 one-shots + 5 loops, 48 kHz.
- Reason for pivot from Unity/fal to synthesis: licensing. Unity Asset Store terms cover AI inputs, so purchased audio was not sent
  to a model; and repo-redistributable audio needed to be safe in git. Compromise: Unity files are *private overrides* in
  `audio/local/` (gitignored, `.gdignore`'d, must be Ogg named after the cue). 8 of 18 cues were overridden locally in the author's checkout.
- fal.ai ElevenLabs/Stable Audio: researched only. fal-media (the user's plugin) already has `fal-assets` with music beds
  (`elevenlabs/music/v2.5`, `music_length_ms` mandatory, instrumental) and a `references/speech-and-music.md` that mentions SFX/ambience.
  It has no game-loop, no trim/normalise, no Godot output. Not used by Codex here (Codex did have falkit installed, used it for art).
- The synthesis script itself is NOT in the repo (no tools/ dir, `git ls-files | grep synth` empty). The 18 assets are therefore
  not reproducible from the repo: a significant gap [E: absent from tree; script presumably lived in /tmp or the sd worktree].

### 1.3 Formats, loudness, naming [E from provenance.json]

| Kind                                                                                    | Format  | Duration    | Peak dBFS   | RMS dBFS   | Channels |
| --------------------------------------------------------------------------------------- | ------- | ----------- | ----------- | ---------- | -------- |
| UI one-shots (pickup, place, commit, reject, complete)                                  | WAV 48k | 0.19-0.51 s | -15 to -11  | -32 to -25 | mono     |
| Alerts/story (warning, machine_start/stop, discovery, repair, broadcast, rescue, death) | WAV     | 0.9-3.6 s   | -15 to -7.5 | -25 to -17 | mono     |
| Loops (habitat 24 s, machine 16 s, routine 52 s, pressure 40 s, discovery_music 48 s)   | OGG     | 16-52 s     | -21 to -14  | -34 to -27 | stereo   |

- No LUFS target anywhere. The research doc says verbatim "No universal LUFS target is asserted" and defers to listening. Only
  peak/RMS were recorded. Per-cue trims live as `gains_db` in the resource (UI/SFX -5, warnings/story -3, beds -8, music -12).
- Naming: snake_case cue id == filename stem (`placement` cue maps to `place.wav`: one mismatch! local override expects
  `placement.ogg`, shipped file is `place.wav`; the cue id and the file stem differ for `placement`, `machine_loop` -> machine.ogg,
  `discovery_music`). \[E, minor; `audio/README.md` itself says "for example placement.ogg"\]. Suggests a manifest-driven name rule.
- Import settings: WAV importer defaults (`edit/normalize=false`, `force/mono=false`); OGG `loop=false` in .import with the
  loop flag set at runtime in `with_local_overrides()` (`looped.loop = cue_buses[id] in [AMBIENCE, MUSIC]`). Only the
  local-override copy path sets loop; shipped OGGs rely on the same duplicate() so it works, but loop_offset is always 0 (no loop points).
- Loop seams: measured as "seam step / p99.9 internal step" (0.68-0.74 on four loops, 0.22 on discovery_music) and first/last 50 ms
  RMS delta (0.08-1.5 dB). Informational only; nothing asserts a threshold. Researchers' own Unity sample had 2.69x and was flagged.

### 1.4 Bus layout [E: default_bus_layout.tres]

```
Master
 +-- Music      (compressor, sidechain=Warnings)  -> duck music under warnings
 +-- Effects
      +-- UI
      +-- Ambience  (same compressor, sidechain=Warnings)
      +-- Warnings
```

- Music is the only bus on Master besides Effects; UI/Ambience/Warnings route through Effects. Player sliders: Music and Effects,
  stored linear 0..1 in `user://sound_levels.cfg`, defaults 0.55 / 0.8.
- Quirk: one `Compressor_warning` SubResource shared between Music and Ambience buses [E]; Godot shares instances, so tweaking one
  edits both. No limiter on Master, so nothing guards summed peaks. [H] worth a lint.
- The bus layout also ducks via compressor sidechain *and* the code holds UI cues back during warnings (`warning_hold_seconds=0.65`).

### 1.5 Event to sound mapping [E]

- One typed Resource `SoundSettings` (scripts/sound_settings.gd): `streams`, `cue_buses`, `gains_db` dictionaries keyed by StringName
  plus timing knobs (`routine_repeat_seconds`, `warning_hold_seconds`, `fade_seconds`, `machine_cue_spacing_seconds`, `machine_queue_limit`).
  `is_valid()` rejects missing stream/bus/gain for any id. This is already the seed of a cue sheet, but in .tres, not human-editable.
- `SoundPlayback` (258 lines): fixed voices (`_one_shot`, `_warning`, `_story`, `_machine`) + named beds (`set_bed(slot, cue)`),
  prepare/activate lifecycle (staged UI silent until session is live), `cue()` returns bool, emits `cue_started`. Uses volume_linear
  tweens for fades. Dummy audio driver detection for headless.
- `SoundSession` (257 lines) subscribes to committed game events: table actions, survival warnings, purifier machine state,
  transmitter/ending. Rules that are worth copying: audio is downstream of committed events (mute or missing sample can't alter the sim);
  load/restart sets beds from state and suppresses historical one-shots; fast-forward keeps music at 1x and coalesces routine completions
  (35 0 ms spacing, 8-deep queue, drop-oldest).
- Doc says "typed presentation resources" for priority/gain/repeat. Priority is encoded by bus (Warnings > others), not by a number.

## 2. What the user asked, corrections, failures, unfinished

User prompts to sd (complete list, all 8): H0 research + Unity reuse; H1 Approve; H2 get my Unity assets; H3 check Unity CLI;
H4 monitor my scheduled downloads; H5 listen and write the doc; H6 sync with g-alone and implement system "along with all the sounds";
H7 Approve all defaults. No explicit aesthetic corrections from the user exist in this thread. [E] This is itself a finding:
the user steered by approval gates, not by listening feedback, because the agent could not listen.

Failures / friction [E unless marked]

- Agent "listened" by proxy: filenames, active span, peak, RMS. The sound doc is honest about it ("still need listening in context"),
  and the final mix still carries "desktop listening pass for the final mix is still pending" at merge. Never closed.
- Asset acquisition ate half the session: 3 prompts on getting Unity packs; no purchase-listing CLI; sandbox read-only account DB.
- Licensing blocked the best route twice: purchased packs not allowed as AI inputs (so no fal audio-to-audio from them); ElevenLabs
  Music commercial-game rights through fal "unresolved". Result: fell back to synthesis and gitignored overrides.
- Doc shipped with `/tmp` links (audition playlists, measurements.json) that vanish after restart; the doc admits it. Dead links in a
  committed doc. [E]
- Shutdown leak (Godot #76745) only found late; fixed with a drain + test gate.
- Process hazard: abandoned headless Godot audio test process (PID 2423676) had to be found and killed; tests use per-run
  XDG temp dirs (good) but many were left in /tmp.
- Many dupes of the same prompt appear across 10 subagent rollouts (Mill, Banach, ...): parallel sub-threads re-ran H0-H7, i.e. the
  Codex "team" fan-out re-fed the whole human history to each spawn. Cost noise, not audio insight.

Unfinished [E]

- No listening/mix sign-off. No LUFS/true-peak policy. No ship-ready quality bar for synthesized sounds (they may sound like beeps).
- Voice: none. Game has no VO. The user's fal-media voice route unused.
- No variations (round-robin, pitch/gain randomisation) for repeated cards; all one file per cue. \[H: will fatigue after dozens of card drops;
  the research doc planned 3 variants per interaction family for the pilot but only 1 shipped.\]
- Adaptive music: 3 states (routine/pressure/discovery_music) with fades; no stems, no beat/bar-aligned transitions. Pressure release
  has a timer (`pressure_release_seconds=2.0`). Music loops have no tempo metadata.
- No localization of audio; no a11y options beyond two sliders (no master/ambience/warnings sliders, no subtitle/visual cue for sound).
- Generation scripts and original (pre-edit) masters not versioned.

## 3. Audio testing and validation that existed

### 3.1 godot-sound hook [E]

`.pre-commit-config.yaml` id `godot-sound`, `language: system`, `entry: bash tests/run_sound_tests.sh`, `always_run: true`,
`pass_filenames: false` (runs on every commit; one of 8 hooks alongside godot-import/parse/smoke/resources/saves/campaign).
Runner details worth copying:

- Four SceneTree-script suites (playback, session, scenario, controls) = 613 lines, ~154-159 checks.
- Each suite runs `godot --headless --path . --max-fps 120 --quit-after 4800 --script res://tests/sound_X_test.gd -- --enable-headless-audio`
  with isolated `XDG_DATA_HOME/CONFIG/CACHE` in a mktemp dir (trap-cleaned) so tests never touch real `user://sound_levels.cfg`.
- Pass criteria are textual and strict: exit 0, no `SCRIPT ERROR:`, output contains `, 0 failures.`, no
  `ObjectDB instances were leaked at exit`, no `resources still in use at exit`.
- Tests assert behaviour via real AudioStreamPlayer nodes: voice present on the correct bus, repeat suppression, warning preempts routine,
  staged session is silent, load/restart plays no historical cue, all clock speeds (1/10/60), slider persistence, missing cue is silent and safe.
- Tests run twice: with shipped originals and with private Unity overrides installed (the 154/159 numbers).

### 3.2 What is missing [E: absent; H: where proposed]

- No static asset check: loudness (LUFS / true-peak), clipping, DC offset, leading silence, mono/stereo, sample rate, duration bounds.
  Numbers exist only in provenance.json, hand-written by a one-off script; nothing re-measures them. A silent re-render drifts unnoticed.
- No loop-seam gate (threshold exists in prose, not in a check). `loop_offset=0` everywhere.
- No coverage check that every cue id in the doc's table has a stream, bus and gain, and that no file in audio/ is unreferenced
  (`is_valid()` checks ids inside the resource only).
- No `.import` settings audit (loop flags on OGG/WAV, compress mode, normalise, `force/mono` for SFX, `edit/trim`).
- No bus-layout check (cue buses exist, sends are acyclic, Master limiter/volume, shared effect instances).
- No provenance/licence gate: provenance.json lists sha256 but nothing verifies file vs hash; Unity overrides' pack+path were
  supposed to be recorded in `audio/local/` records by hand.
- No test that the committed doc still matches the resource (cue names drifted: `placement`/place.wav, doc says `Plastic_Hit_1.wav` shortlist).
- No subjective check: nobody (agent or user) auditioned the final mix. Headless uses the Dummy driver so nothing is rendered.
- No spectrogram/waveform visual review, no ABX between candidates.

## 4. Plugin proposals

Design stance: Codex's best audio decisions were structural (audio downstream of events, typed resource, isolated headless runs,
strict log scanning, provenance). Its weak spots were production (no real listening, non-reproducible synthesis, no loudness policy).
The plugin should make the structural parts a template and make production deterministic and checkable. [synthesis of E]

### 4.1 Cue-sheet schema (the single source of truth) [proposal, justified by 1.2/1.5/3.2]

One file `audio/cues.yaml` (or `.toml`), human-editable; a generator emits the Godot `SoundSettings`-style `.tres`
and a markdown table for the doc, so doc, resource and tests cannot drift (cf. the `placement`/`place.wav` mismatch).

```yaml
version: 1
buses: {Master: {limiter_ceiling_db: -1.0}, Music: {send: Master}, Effects: {send: Master}, UI: {send: Effects}, ...}
loudness: {sfx_lufs_i: -23, sfx_tp_db: -3, music_lufs_i: -18, bed_lufs_i: -26, tolerance_lu: 2}
cues:
  placement:
    kind: oneshot            # oneshot | loop | stem | stinger | voice
    bus: UI
    file: audio/asteroid/place.wav
    gain_db: -5
    priority: 2              # explicit, not implicit by bus
    cooldown_ms: 350         # replaces routine_repeat_seconds
    variants: [place_a.wav, place_b.wav, place_c.wav]   # round robin + pitch_jitter_cents: 40
    trigger: event:card.placed        # game event name; lint finds unknown events
    max_duration_s: 0.5
    loop: {start_s: null, end_s: null}   # for beds/music
    source: {type: synth|fal|licensed|recorded, ref: ..., prompt: ..., seed: ..., licence: ...}
    status: placeholder | auditioned | approved   # approved only after human listening
```

Why: [E] provenance, measurement, gain and bus info is currently split across provenance.json, sound_settings.tres, doc table,
and audio/README.md. `status` encodes the unclosed "listening pending" loop.

### 4.2 Skills

1. `godot-sound-design` (document + cue sheet). Interviews game events (reads scripts for signals/committed events), proposes cue families,
   writes `docs/sound-design.md` + `audio/cues.yaml`. Rules from the Codex run: no temp-path links in docs; every cue has a trigger,
   bus, priority, repeat rule, load/restart rule; audition shortlist is explicitly marked unauditioned.
   Evidence: H5 produced exactly such a doc, hand-built; the Codex mapping table is a good template.
1. `godot-sfx-generate` (source selection). Decision order, justified by the licensing chain: (a) procedural synthesis for UI/machines
   (deterministic, redistributable, seed-pinned, committed generator under `tools/audio/`), (b) fal ElevenLabs SFX v3 / Stable Audio
   small-sfx for textured sounds (record prompt+seed+endpoint+cost in cues.yaml; use the user's fal-media `falkit` guard for cost),
   (c) licensed packs via private override only with licence note. \[H: fal output quality is untested in this project; the research
   doc says so; plan a 3-sample trial before committing.\] Generate longer than needed then trim (research doc advice); never exact
   alarm rhythm from a generator, sequence one pulse.
1. `godot-music-loop` (loops + adaptive). Take a generated/licensed track, find loop points (zero-crossing + beat-aligned via
   `librosa`/`ffmpeg` silencedetect, or equal-power crossfade tail->head bake), write `loop_offset`/`loop_end` into the .import or
   `AudioStreamOggVorbis.loop_offset` / `AudioStreamWAV.loop_begin/end`, verify with seam metric. Adaptive: reference design
   of `AudioStreamInteractive` (Godot 4.3+) clips + transitions with bar-quantised fade, or `AudioStreamSynchronized` stems for
   layered pressure; note Codex used three independent crossfaded beds (simple, works, but no beat sync). \[H: AudioStreamInteractive
   not seen in the Codex code; I recommend it from Godot docs, not from this project. Verify against Godot 4.7 docs before shipping.\]
1. `godot-audio-loudness` (ffmpeg normalise). Two-pass `loudnorm` (measured I/LRA/TP) per cue-class target from cues.yaml; SFX use
   short-term/RMS rather than LUFS-I because LUFS is unreliable under 0.4 s [H, standard BS.1770 gating caveat]; always keep a `masters/`
   dir of un-normalised sources; write measured values back to cues.yaml (replaces hand-built provenance.json).
1. `godot-audio-integrate` (Godot side). Scaffolds `AudioServer` bus layout (.tres), a `SoundPlayback`-style voice pool with
   priority/cooldown/round-robin, `volume_linear` sliders persisted to `user://`, headless-safe (Dummy driver) code, shutdown drain
   (Godot #76745 workaround), and an event-bus adapter so audio subscribes to committed events only. Include the sidechain-compressor
   ducking recipe and warn about shared SubResource effects.
1. `godot-audio-audition` (human-in-the-loop). Since the agent cannot hear: produce an A/B audition page (artifact or local HTML
   with matched-loudness playback, loop-repeat button, spectrogram), record user's pick into `status`. Closes the exact gap
   (listening pass never done). Vocal/VO variant: wire fal-media ElevenLabs voice lines (`fal-assets`) for barks/narration
   with the same cue-sheet fields (`kind: voice`, `text`, `voice_id`, `locale`), if a game needs VO. [H: this game has none.]

### 4.3 Agents / judges

- `audio-spec-judge` (read-only LLM): reads cues.yaml + doc, flags cues without trigger, overlapping roles (two cues indistinguishable),
  repetition risk (no variants on a high-frequency trigger), alarm/critical cues lacking priority and ducking, missing
  accessibility pair (visual/text). Rubric items follow Codex doc lines: "distinguish placement, accepted input, rejection and urgent
  warning after 20 repeats", "can complete scenario muted".
- `audio-provenance-judge`: checks every non-synth cue has licence, source ref, and not-AI-input note; blocks `licensed` in shipped
  dirs when licence forbids redistribution (use the Codex pattern: private `audio/local` overrides).
- `audio-mix-reviewer` (needs measurement output, not ears): consumes CLI report below and a bus-graph dump; recommends gain changes.
  Must label every recommendation "measured, not heard".

### 4.4 Deterministic CLI (`godot-audio-check`, Python + ffmpeg/ffprobe, no LLM)

Runs in pre-commit next to `godot-sound`; each check returns a file:id-level message. Table = check, how, evidence of need.

| Check                                                                                                                             | How                                                                                                                                                        | Why                                                     |
| --------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Loudness                                                                                                                          | `ffmpeg -af ebur128=peak=true` -> I, LRA, TP; short clips: RMS/peak window                                                                                 | no LUFS gate existed (3.2)                              |
| Peak/clipping                                                                                                                     | astats peak, count of full-scale samples                                                                                                                   | Codex noted -0.1/0 dBFS source peaks                    |
| Leading/trailing silence                                                                                                          | silencedetect                                                                                                                                              | doc: "70 ms measured lead", "1.35 s before active span" |
| DC offset / click at edges                                                                                                        | astats DC, first/last sample magnitude                                                                                                                     | seam steps at 2.69x                                     |
| Loop seam                                                                                                                         | seam step / p99.9 step ratio (\<= 1.0 pass, 1-1.5 warn) + 50 ms RMS delta (\<= 1.0 dB); compare to cues.yaml loop points                                   | metrics already computed by hand, never asserted        |
| Format                                                                                                                            | sample rate, channels vs policy (SFX mono, music stereo, 48k)                                                                                              | all shipped are 48k; no policy file                     |
| Cue coverage                                                                                                                      | cues.yaml vs `.tres` vs `audio/` vs GDScript `cue(&"id")` / `set_bed` grep: missing, unused, unreferenced files, id/filename drift                         | `placement`/place.wav, `machine_loop`/machine.ogg       |
| Event coverage                                                                                                                    | cue `trigger` names vs signals/event ids in scripts                                                                                                        | docs say "every cue in scenario"; no enforcement        |
| Import audit                                                                                                                      | parse `*.import`: importer, `loop`, `loop_offset`, `edit/normalize`, `force/mono`, compress                                                                | loop set only at runtime in Codex code                  |
| Bus lint                                                                                                                          | parse `default_bus_layout.tres`: all cue buses exist, sends acyclic, Master limiter present, no shared effect SubResource across buses, `volume_db` bounds | shared Compressor_warning; no limiter                   |
| Provenance                                                                                                                        | sha256 vs provenance.json/cues.yaml; licence present for non-synth                                                                                         | hash recorded but unchecked                             |
| Doc drift                                                                                                                         | regenerate md table from cues.yaml, diff                                                                                                                   | doc links to /tmp; stale cue names                      |
| Headless runtime                                                                                                                  | keep Codex runner pattern: isolated XDG, fail on `SCRIPT ERROR`, `, 0 failures.`, leak strings; add `--audio-driver Dummy` note                            | already the best-proven piece                           |
| Optional runtime assertion in a Godot test: iterate all cues in the resource, play each in a headless `AudioStreamPlayer`, assert |                                                                                                                                                            |                                                         |
| `get_stream_playback()` non-null and `stream.get_length()` within `max_duration_s`. [H]                                           |                                                                                                                                                            |                                                         |

### 4.5 Hook / workflow

- PreCommit/PostToolUse hook: when `audio/**` or `default_bus_layout.tres` or cues.yaml changes, run `godot-audio-check`; failure blocks.
  Keep the existing "always_run" for runtime tests but split static (fast, file-filtered) and runtime (slow) so edits to scripts do not
  re-measure audio and vice versa. [H: the always_run cost is untracked in the evidence.]
- `/godot-sound` command: cue-sheet -> generate (synth or fal) -> trim/normalise -> import -> check -> audition page -> mark status.
  Cost-gate fal calls with the user's fal-media estimate/guard (music bills per started minute; `music_length_ms` required).

## 5. Priorities, confidence, caveats

Ranked by evidence strength:

1. Cue-sheet schema + doc/resource/test generator and coverage check (strong: drift and split sources visible in repo).
1. Static audio CLI: loudness, peak, silence, loop-seam asserts, import audit, bus lint (strong: metrics were computed but never gated).
1. Reproducible generation (committed synth script or fal job record with seed) + provenance gate (strong: script missing from repo).
1. Godot integration skill/template: bus layout, voice pool, sliders, shutdown drain, headless test runner (strong: proven, copyable).
1. Audition/human loop (medium: absence of listening pass is clear; the right UI is a hypothesis).
1. Adaptive music via AudioStreamInteractive/Synchronized, VO via fal-media, round-robin variants (hypotheses; this game did not exercise them).
   Caveats: I did not read the g-alone-sd rollout tool outputs beyond prompts and final answers; the synth script content and how
   the 18 sounds actually sound are unverified. Quality of synthesized sound has no listening evidence. The sd digest's 899 exec commands
   (190 python) are consistent with ad-hoc DSP and measurement scripts that were never committed. Loudness numbers above are the agent's
   own ffmpeg decodes, not independently verified.
