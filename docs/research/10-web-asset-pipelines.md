# AI asset pipelines for a Godot plugin (web research, Nov 2026)

Condensed from the pipeline-web-researcher hand-back (agent had no write tools).

## 2D art on fal

- Base: nano-banana-pro, nano-banana-2, gpt-image-2. Consistency: nano-banana-pro/edit, nano-banana-2/edit (up to 14 refs). Style lock: LoRA (flux-2-trainer, flux-lora-fast-training is_style, 9-50 imgs) → fal-ai/flux-lora.
- Sprite sheets: edit models with 2x2 grid prompt; no dedicated fal model. Prior art: github.com/fal-ai-community/skills skills/fal-gamedev (directional sheets, 3-layer parallax, bg removal; generate attack-down first as reference).
- Transparent: ideogram/v3/generate-transparent (native); bria/background/remove (licensed data, sync only), birefnet v2, ideogram/remove-background, imageutils/rembg. Bg removal eats glows/outlines → native transparent for VFX.
- Pixel: image2pixel (post-process); PixelLab API + MCP (8-dir characters, animations, tilesets, ~$0.03-0.04); Retro Diffusion (rd_plus, RD Animation, RD Tile; not on fal). Snap/quantize to grid always. Never generative-upscale pixel art.
- Upscale: esrgan (faithful), clarity/crystal (generative), seedvr/upscale/image/seamless (keeps tiling), topaz transparent (keeps alpha).
- Vector/icons: recraft v4.1 text-to-vector, recraft/vectorize.

## Depth / normals / 3D

- Depth: image-preprocessors/depth-anything/v2, marigold-v2, imageutils/marigold-depth. Use for Parallax2D layers or displacement shader.
- Normals: no fal endpoint found (UNVERIFIED). Use Laigter CLI (GPL, flaky) or Sobel-from-depth in Python. Godot: CanvasTexture normal/specular, only visible under Light2D; 2D expects +Y convention.
- Image-to-3D (GLB): trellis-2 ($0.25-0.35; always set decimation_target ~20-50k, default 500k), hunyuan3d-v3 (+PBR, multi-view), Hunyuan 3.1 Pro; Meshy API (only one with auto-rig + animation). Godot prefers glTF 2.0; set scale/up-axis, generate collision separately. Hunyuan3D license historically excluded EU/UK/KR.

## Audio

- SFX: ElevenLabs eleven_text_to_sound_v3 (v2 deprecated, removal 2027-03-01), 0.1-30 s; loop semantics conflicting in docs. fal: fal-ai/elevenlabs/sound-effects/v2.
- Music: stable-audio-25 (~$0.20, licensed training), lyria2 ($0.10/30 s), minimax-music v2.5/2.6, ElevenLabs Music. None seamless → post-process: zero-crossing/beat loop point, crossfade, OGG, Godot ResourceImporterOggVorbis loop/loop_offset (OGG/MP3 loop start only; WAV carries loop metadata).
- Voice: ElevenLabs text-to-dialogue v3 (fal), 2,000 chars, [laughs] cues; paid plan for commercial; prefer Voice Design voices.
- Loudness (secondary sources): Sony console −24 LUFS ±2, −1 dBTP; portable −18; mobile −16. Indie PC default −18 LUFS integrated, ≤ −1 dBTP; two-pass ffmpeg loudnorm.
- Procedural: AudioStreamGenerator, sfxr-style (not researched deeply).

## UI & fonts

- Icons: recraft vector or nano-banana with icon-sheet ref + palette, style LoRA for sets. Generated UI mockups = reference only; rebuild as Control/Theme.
- Fonts: SIL OFL bundling OK commercially; avoid AI-generated fonts.

## Design tooling

- No standard GDD template; ship own skeleton. Balance: Machinations (no Python API), cadCAD, or simplest NumPy Monte Carlo over exported Resource/JSON tables.
- Telemetry: etodd playtest-telemetry-godot (MIT), GameAnalytics SDK, Talo (OSS), Forge Logger; 4.6 compat unverified.

## Licensing

- Steam (Jan 2026 rewrite): disclose Pre-Generated content consumed by players; Live-Generated needs guardrails description; efficiency tools not the focus. (remio.ai per-asset tag claim uncorroborated.)
- itch.io: mandatory gen-AI disclosure tags (graphics/sound/text/code); untagged dropped from browse.
- ElevenLabs Music self-serve excludes "Studio Games" (multi-platform commercial) → Enterprise required. Big trap. TTS/SFX commercial on paid plans.
- Open-weight 3D model output licenses unverified.

## Trends / risks

- Multi-reference edit models replace per-character LoRAs; LoRA still best for whole-game style. Vendors ship agent-native MCPs (fal, PixelLab, Retro Diffusion). Resolve endpoints/prices at runtime via recommend_model, don't hardcode.

## Key sources

fal llms.txt pages per endpoint; github.com/fal-ai-community/skills; api.pixellab.ai/v2/llms.txt; elevenlabs.io docs + eleven-music-model-specific-terms; partner.steamgames.com/doc/gettingstarted/contentsurvey; PC Gamer/Engadget on itch.io; Godot docs (CanvasTexture, glTF, OggVorbis import); github.com/azagaya/laigter; Talo, GameAnalytics, Machinations, cadCAD.
