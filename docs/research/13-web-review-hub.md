# Local review hub for Godot assets (web research, 2026-11-12)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## Architecture

Static SPA (vendored JS, no CDN at runtime) + ~150-line Python stdlib `review_server.py` on 127.0.0.1:0 with token. file:// breaks ES modules, fetch of GLB/audio, and web exports → server is primary path; fallback = localStorage write-ahead + "Download decisions.json" + "Copy list".

```
batches/*/manifest.json + assets ─▶ build_review.py (merge manifests, WebP thumbs 128/256 hash-cached,
                                     audio LUFS/peak, glb tris/materials/textures)
                                 ─▶ index.html grid (pills, filters, version stack) + per-type detail viewer
browser ── POST /api/decisions (X-Review-Token) ─▶ review_server.py ─▶ .review/decisions.json (atomic) + decisions.log.jsonl
agent/hooks ◀── read .review/decisions.json
Godot (optional): GLTFDocument .tscn→.glb; Movie Maker turntables/shader clips; UI screenshots at N resolutions
```

## decisions.json

Key `asset_id@version`, store sha256 (file changed after decision → "stale"). Fields: asset_id, family, version, path, sha256, status (approve|redo), note, regions[] (W3C Web Annotation, percent FragmentSelector), frame, decided_at, consumed_at. One writer per file: only the server writes decisions; agent marks handled via POST /api/consume or separate consumed.json. SessionStart/UserPromptSubmit hook can inject pending redo items (verify hook output contract).

## Server essentials

Bind 127.0.0.1 explicitly (default is all interfaces), port 0; ThreadingHTTPServer; resolve paths and reject outside root (SimpleHTTPRequestHandler follows symlinks); token in URL fragment → header on POST; check Host (DNS rebinding) and Origin; no CORS; body cap + schema validation; tmp + os.replace. COOP/COEP only for threaded web exports.

Persistence: server POST (recommended) > File System Access API (Chromium only) > download > localStorage/copy list.

## Viewers per asset type

| Type          | Approach                                                                                                                                                                                                               |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 2D            | native img/canvas; img-comparison-slider 8.0.7 (slot first/second); fixed 120/240 px boxes; pixelated + checkerboard; CSS pan-zoom; versions[] stack                                                                   |
| Sprite sheets | canvas drawImage on rAF; FPS slider, step, onion skin, ping-pong, frame N saved in decision                                                                                                                            |
| 3D            | @google/model-viewer 4.3.0 (turntable, auto-rotate, toBlob) for default; three.js (0.186.x) GLTFLoader+OrbitControls on "Inspect" (wireframe, tris, textures); precompute stats at build; one WebGL context            |
| Audio         | wavesurfer.js 8.0.x (+regions; breaking vs 7.12.x); loop seam via Web Audio AudioBufferSourceNode loopStart/End + "last 1 s + first 1 s" button; A/B via two GainNodes; LUFS/TP/LRA computed at build (ffmpeg ebur128) |
| Shaders       | Godot shading language ≠ GLSL → bake clips with Movie Maker; optional single-threaded Godot web-export "shader previewer" (Compatibility renderer only; untested)                                                      |
| UI            | Godot captures at several resolutions, tabs, decision records resolution                                                                                                                                               |
| Video         | native video + requestVideoFrameCallback; transcode Movie Maker AVI (MJPEG) → MP4/WebM                                                                                                                                 |
| Region notes  | Annotorious 3.8.x (BSD-3, W3C format); marker.js 3 is linkware — avoid; or ~100-line rect/pin overlay                                                                                                                  |

## Tools to copy patterns from (not reuse)

Kitsu (AGPL, Postgres — too heavy): playlists, compare. AYON Review: compare modes (side-by-side, split, wipe). SyncSketch: frame-anchored notes, All Notes panel. ftrack/ShotGrid: status pills (WIP/Pending/Retake/Approved). OpenRV/xSTUDIO desktop only.
Patterns: status pills (pending/approved/redo/stale), version stack + compare to previous, playlists = saved filters in URL hash, wipe/side-by-side, All Notes panel, keyboard-first (J/K, A, R+note), progress counter.

## Godot in browser

Web export: Compatibility (WebGL2) only, single-threaded default since 4.3 (no COOP/COEP), must be HTTP. Build one generic previewer, not per-scene exports. Scene→glTF: GLTFDocument.append_from_scene + write_to_filesystem (headless may lose textures → Xvfb). Turntables: `--write-movie out.avi --fixed-fps 30 --quit-after 120` under Xvfb (headless can't render). Batch many assets per run.

| Approach                 | Fidelity                     | Build cost    | Browser cost | Use                       |
| ------------------------ | ---------------------------- | ------------- | ------------ | ------------------------- |
| GLB → model-viewer/three | approx PBR, no Godot shaders | low           | light        | props, characters         |
| Movie Maker clips        | exact                        | medium (Xvfb) | trivial      | shaders, VFX, full scenes |
| Web-export previewer     | Compatibility only           | high once     | heavy wasm   | live shader tweaks        |

## Large libraries

Build-time WebP thumbs cached by hash; EditorResourcePreview for Godot-native resources (needs editor). `loading="lazy"` + `content-visibility: auto` handles ~2,000 cards; virtualize beyond. In-memory filtering; filters in URL hash; viewers loaded on first use via dynamic import().

## Risks

Versions from registry mirrors (run npm view before pinning); wavesurfer 8 breaking changes; headless rendering/texture readback → Xvfb; web export fidelity; FSA API Chromium-only; localhost security (token/Host/Origin); licenses (marker.js linkware, Kitsu AGPL). Not researched: pan-zoom lib, hook JSON contract, WebGL context cap, web export size/time.

## Key sources

docs.godotengine.org (exporting_for_web, GLTFDocument, creating_movies, EditorResourcePreview, converting GLSL); docs.python.org http.server; web.dev (lazy loading, content-visibility, FSA); model-viewer, three.js, wavesurfer.xyz, annotorious.dev, img-comparison-slider READMEs; Kitsu, AYON, SyncSketch docs.
