# Verifying Godot shaders from the CLI (Godot 4.7)

Source: web research of 2026-11-13 against Godot source at 4.7.2-stable and master, the 4.7 docs, upstream CI and Mesa docs. Every lavapipe/llvmpipe claim is UNTESTED on this machine.

Local probe (2026-11-13): `/usr/share/vulkan/icd.d/lvp_icd.json` (lavapipe ICD) exists alongside nvidia/intel/radeon ICDs; `/usr/bin/vulkaninfo` and `/usr/bin/ffmpeg` exist; no `Xvfb`/`xvfb-run`, ImageMagick, `flip` or `dssim` in `/usr/bin`.

## Executive summary

`--headless` does more than parse shaders. The Dummy renderer runs Godot's full shading-language front end (`ShaderCompiler::compile`) in `shader_set_code`, so syntax, type and unknown-identifier errors surface as `SHADER ERROR:` plus `Shader compilation failed.` in the log with no GPU. That makes it a cheap first gate. It cannot catch backend errors (GLSL to SPIR-V, driver pipeline creation, per-renderer limits), it cannot render, and it cannot run the shader baker. For those, Godot's own CI runs real Vulkan and GLES3 under `xvfb-run` with `mesa-vulkan-drivers` (lavapipe/llvmpipe), so this setup is proven upstream. Its pixel output and stability on this machine are still UNVERIFIED. For screenshots, Movie Maker (`--write-movie x.png --fixed-fps N --quit-after N`) or an `await RenderingServer.frame_post_draw` capture is the deterministic route. Golden-image diffing has no standard Godot addon. Upstream practice uses checksums plus ImageMagick or dssim.

## 1. Shader compile checking

| Mode                                                                | What runs                                                                               | Catches                                                                 | Needs                       |
| ------------------------------------------------------------------- | --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- | --------------------------- |
| `--headless` (Dummy renderer)                                       | `ShaderLanguage` parse + `ShaderCompiler::compile`, output discarded; collects uniforms | syntax, types, unknown identifiers, wrong built-ins for the shader type | nothing                     |
| Forward+/Mobile (`--rendering-driver vulkan`) under Xvfb + lavapipe | front end + GLSL to SPIR-V + Vulkan pipeline creation                                   | the above + backend/SPIR-V/pipeline errors                              | Xvfb, `mesa-vulkan-drivers` |
| Compatibility (`--rendering-driver opengl3`) under Xvfb + llvmpipe  | front end + GLSL ES/GL compile in Mesa                                                  | the above + GLES3-specific failures                                     | Xvfb, Mesa GL               |

Findings:

1. **The Dummy renderer compiles through the front end.** In `servers/rendering/dummy/storage/material_storage.cpp` @ `4.7.2-stable`, `shader_set_code` calls `dummy_compiler.compile(new_mode, p_code, &actions, "", gen_code)` and then `ERR_FAIL_COND_MSG(err != OK, "Shader compilation failed.")`. Supported types: `canvas_item, particles, spatial, sky, fog, texture_blit`. Any other type logs `Shader type <x> not supported in Dummy renderer.` Confidence: high (source read).

1. **Exact log format.** On a front-end error, `ShaderCompiler::compile` (`servers/rendering/shader_compiler.cpp`, master) does two things:

   - It prints a context dump: `--Main Shader--` (or `--<path>--`), then up to 4 lines around the error as `%5d | <line>`, with the error line marked `E%4d-> <line>`.
   - It calls `_err_print_error(..., ERR_HANDLER_SHADER)`.

   `core/error/error_macros.h` maps `ERR_HANDLER_SHADER` to `"SHADER ERROR"`, and the logger prints `"%s: %s\n"` then `"   at: %s (%s:%i)\n"`. Expected log, schematically:

   ```
   SHADER ERROR: Unknown identifier in expression: 'VIEW'.
      at: (<file>:<line>)
   ERROR: Shader compilation failed.
   ```

   The Dummy renderer passes an empty path (`""`), so headless errors likely show `--Main Shader--` and an empty file name, not `res://...`. UNVERIFIED: the exact rendered text of the headless `at:` line (test locally). The error text and `Shader compilation failed.` match a 4.3 user log (forum, community evidence only). Confidence: high for the strings, medium for the layout.

1. **Load time versus first use.** Front-end errors appear when `Shader.code` is set, which happens when a `.gdshader` resource loads, because `Shader::set_code` forwards to `RenderingServer.shader_set_code`. Backend SPIR-V or pipeline compilation on Forward+/Mobile happens later: pipelines are precompiled at load time when the needed pipelines can be detected (4.4+), otherwise on first draw. UNVERIFIED: the exact log text of backend (glslang/driver) failures in 4.7.

1. **No runtime API reports success or failure.** A forum thread (4.2.1) confirms errors only reach the Output panel. Judge by the log, which matches the project rule.

1. **No GPU in CI.** Upstream `.github/actions/godot-project-test/action.yml` (master) runs these steps, and the Linux workflow installs `mesa-vulkan-drivers` on those runners:

   - `xvfb-run $bin --audio-driver Dummy --import --path test_project` ("Vulkan" step)
   - `DRI_PRIME=0 xvfb-run $bin --audio-driver Dummy --rendering-driver opengl3 --import ...` ("GLES3" step)
   - `xvfb-run $bin 40 --audio-driver Dummy --path test_project` ("Run project" step)

   It then scans the log with `misc/scripts/check_ci_log.py`. This is strong evidence that Vulkan (lavapipe) and GLES3 (llvmpipe) start without a GPU. Confidence: high that they start; UNVERIFIED for 4.7.2 on this machine's Mesa.

1. **Pitfalls on software rendering.**

   - Without a display, Vulkan fails with `Required extension VK_KHR_surface not found.` (forum, 4.4.dev, 2024-10). Always wrap the run in Xvfb.
   - In 4.4+, when Vulkan fails, Godot falls back to D3D12 and then Compatibility (the setting is `rendering/rendering_device/fallback_to_opengl3`). A silent fallback would change what is being tested, so disable the fallback and assert the renderer from the log or from `RenderingServer.get_current_rendering_driver_name()`.
   - LLVM 15 llvmpipe crashed running Godot (Launchpad #2072335).
   - CONFLICT DETECTED: Godot's CI runs Vulkan on Mesa without a GPU, but a 2025 forum report (Linux Mint, llvmpipe) says the editor reported Forward+ unsupported and fell back to Compatibility. The Mesa version is likely the deciding factor. UNVERIFIED.

1. **Selecting lavapipe locally.** This desktop also has nvidia/intel ICDs. Force lavapipe with `VK_DRIVER_FILES=/usr/share/vulkan/icd.d/lvp_icd.json` (Vulkan loader variable, from memory; older name `VK_ICD_FILENAMES`), or with `MESA_VK_DEVICE_SELECT`. `--gpu-index` only applies to Forward+/Mobile. For GL, use `LIBGL_ALWAYS_SOFTWARE=true GALLIUM_DRIVER=llvmpipe` (Mesa envvars docs). `LP_NUM_THREADS` sets llvmpipe thread count, and `0` turns threading off, which may help determinism. UNVERIFIED: whether these variables apply to lavapipe.

1. **Shader baker.** It was added in 4.5 and the docs say it is "not supported when exporting a project using the `--headless`". Linux bakes Vulkan only. It is no use as a headless compile check. Confidence: high.

1. **Other flags (4.7 CLI docs).**

   - `--gpu-validation` turns on API validation layers.
   - `--gpu-abort` aborts on GPU errors (debug templates only).
   - `--generate-spirv-debug-info` adds SPIR-V debug info for RenderDoc (debug templates only).
   - `--check-only` applies to GDScript only and does not check shaders.

Recommended gate: (a) headless load of every `.gdshader`/material through a small `--script`, failing on `SHADER ERROR`, `Shader compilation failed`, or `not supported in Dummy renderer`, and requiring an explicit summary line. (b) An optional `doctor`-detected Xvfb+lavapipe run per target renderer to catch backend errors.

## 2. Rendering in CI for screenshots

| Technique         | Facts (source)                                                                                                                                                                                                                                                                                                                                   | Notes                                                                                                                                   |
| ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| `--headless`      | "disables all rendering"; RenderingServer returns "dummy values" (RenderingServer docs, 4.7)                                                                                                                                                                                                                                                     | Viewport capture is useless here. UNVERIFIED: whether `get_image()` returns null or empty                                               |
| Movie Maker       | `--write-movie out.png` (PNG sequence + WAV, lossless, alpha if `transparent_bg`), `.avi` (MJPEG, lossy), OGV (editor-only recording); forces `--fixed-fps`; `--quit-after N` frames; `--resolution WxH`; relative paths resolve against the project; "visual output remains identical" regardless of hardware speed (Creating movies docs, 4.7) | Stop with `get_tree().quit()`; Ctrl+C corrupts AVI/WAV                                                                                  |
| `--fixed-fps N`   | "Forces a fixed number of frames per second... disables real-time synchronization" (CLI docs)                                                                                                                                                                                                                                                    | Makes delta constant                                                                                                                    |
| `--disable-vsync` | Speeds up writing; does not override driver-forced vsync (CLI docs)                                                                                                                                                                                                                                                                              |                                                                                                                                         |
| Script capture    | `await RenderingServer.frame_post_draw` then `get_viewport().get_texture().get_image()`; calling it in `_ready()` gives an empty texture (Viewports docs, 4.7)                                                                                                                                                                                   | `Image.save_png()`                                                                                                                      |
| `TIME`            | Seconds since start, rolls over every 3600 s (`rendering/limits/time/time_rollover_secs`), "affected by time_scale but not by pausing" (canvas_item shader docs)                                                                                                                                                                                 | UNVERIFIED: that `TIME` advances exactly 1/fps per frame under `--fixed-fps`. For full control, drive time with a global shader uniform |
| Particles         | `use_fixed_seed` + `seed` give "visual outcome... consistent across replays"; `restart(keep_seed)`; `request_particles_process` for seeking (GPUParticles2D docs, 4.7)                                                                                                                                                                           | Docs never say "deterministic"                                                                                                          |

Byte-exact determinism holds in single-threaded rendering. Multithreaded rendering "can sometimes change imperceptibly between runs and may require a fuzzy tester" (godot-benchmarks issue #34, 2023, maintainer-adjacent author). Pixel output differs between llvmpipe and a real GPU, and between Mesa versions, so goldens must be per renderer, per driver and per Mesa version. UNVERIFIED (expected, untested).

## 3. Visual regression

| Approach                                                                  | Used by                                                                                         | Metric                               | Status                                                            |
| ------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- | ------------------------------------ | ----------------------------------------------------------------- |
| SHA checksum of PNG frames, then `compare -metric ae` + diff WebP reports | godot-benchmarks #34 (2023-06, closed "not planned" 2024-07-31)                                 | exact / absolute-error pixel count   | script in issue only                                              |
| dssim over `results/` vs `results_master/`                                | Calinou/godot-rendering-tests (MIT)                                                             | DSSIM (lower = closer), no threshold | maintained by a Godot maintainer; last commit date not shown      |
| GDSnap addon                                                              | Asset Library: v0.2, Godot 4.4, MIT; works from GUT; reports differing-pixel count and %        | pixel diff                           | UNVERIFIED (store page returned 403; search snippet only)         |
| NVIDIA FLIP                                                               | NVlabs/flip v1.7, BSD-3; `flip -r ref.png -t test.png`; `pip install flip-evaluator` (Py ≥3.10) | perceptual LDR/HDR error map         | external dependency, optional                                     |
| GdUnit4 / GUT                                                             | none found                                                                                      | none                                 | UNVERIFIED: no built-in image assertion found in either framework |

A stdlib-only option for this project: compare PNGs decoded by Godot itself (`Image.compute_image_metrics(other, use_luma)` exists in the Image API; UNVERIFIED for 4.7 semantics). Alternatively, report per-channel max delta and the percentage of pixels over a threshold. Keep goldens keyed by `{renderer, driver, adapter name}` from `RenderingServer.get_video_adapter_name()`.

## 4. Tooling for `.gdshader`

| Tool                                    | Kind                                                                                   | Licence | Version / activity                                                               | CLI use                                     |
| --------------------------------------- | -------------------------------------------------------------------------------------- | ------- | -------------------------------------------------------------------------------- | ------------------------------------------- |
| Godot itself (headless load, section 1) | authoritative front-end check                                                          | MIT     | 4.7.2                                                                            | yes, through a script                       |
| Godot built-in LSP (`--lsp-port`)       | GDScript only (lives in `modules/gdscript/language_server`)                            | MIT     | n/a                                                                              | UNVERIFIED that it ignores shaders entirely |
| GodOfAvacyn/gdshader-lsp                | Rust LSP: completion, hover, diagnostics, includes; VS Code ext Linux-only             | MIT     | v0.1 only; README (2025) says inactive ~1.5 years, "many bugs", rewrite underway | LSP only, no lint mode                      |
| armsnyder/gdshader-language-server      | Go LSP, "only supports some basic keyword completion"; VS Code ext, brew, `go install` | MIT     | pkg.go.dev shows v0.1.0 to v0.4.1                                                | LSP only                                    |
| airblast-dev/tree-sitter-gdshader       | grammar based on GLSL ES 3.0 (no official spec); crate `tree-sitter-gdshader` 0.4.0    | MIT     | 121 commits                                                                      | parse only                                  |
| GodOfAvacyn/tree-sitter-gdshader        | grammar for Neovim highlighting                                                        | MIT     | 6 commits                                                                        | parse only                                  |
| madwind/simple-gdscript-formatter       | editor addon; formats "the current GDScript or shader file"                            | MIT     | 0.5.0 (2026-09-08, marked unstable)                                              | editor-only, no CLI documented              |
| gdtoolkit, gdstyle, gdck, GDShrapt      | GDScript only                                                                          | various |                                                                                  | no shader support found                     |

There is no maintained standalone gdshader linter or formatter with a CLI. The Godot binary is the only trustworthy checker.

## 5. Performance verification

| API (RenderingServer, 4.7 docs)                                                                     | Meaning                                                                                                                           |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `get_rendering_info(RENDERING_INFO_*)`                                                              | engine-wide stats; "not available until at least 2 frames have been rendered"                                                     |
| `viewport_get_render_info(rid, type, info)`                                                         | per-viewport objects/primitives/draw calls                                                                                        |
| `viewport_set_measure_render_time(rid, true)` then `viewport_get_measured_render_time_cpu/gpu(rid)` | "CPU/GPU time taken to render the last frame in milliseconds"                                                                     |
| `get_frame_setup_time_cpu()`                                                                        | CPU render setup ms; does not need measurement enabled                                                                            |
| Pipeline-compilation monitors (4.4+)                                                                | Canvas/Mesh/Surface/Draw/Specialization counters, only increase; Draw should stay 0 with ubershaders (pipeline_compilations docs) |

The enum names `RENDERING_INFO_TOTAL_{OBJECTS,PRIMITIVES,DRAW_CALLS}_IN_FRAME`, `*_MEM_USED` and `RENDERING_INFO_PIPELINE_COMPILATIONS_*` are partly confirmed: `TOTAL_DRAW_CALLS_IN_FRAME` appears in the docs example, and the rest are UNVERIFIED by name.

Other measurement routes:

- `--gpu-profile` "shows a GPU profile of the tasks that take the longest" (CLI docs). UNVERIFIED: its output format and whether it works under lavapipe.
- `--print-fps` prints FPS to stdout.
- RenderDoc gets source-level SPIR-V debugging via `--generate-spirv-debug-info` (debug templates only). The general optimization docs list Nsight, RGP, PIX, Xcode and Arm tools, plus MangoHud on Linux.

Reproducible shader cost from a script:

1. Fixed resolution, vsync off, no `--fixed-fps` (it removes real-time sync, but GPU ms are still measured; UNVERIFIED).
1. Warm up about 60 frames so pipeline compiles settle (check that the pipeline monitors stop rising).
1. Average GPU ms over N frames for the shader versus a flat baseline material, then report the delta.

GPU timings on llvmpipe/lavapipe measure the CPU rasterizer and should not be used as shader cost. Gate timing only on real hardware, and gate draw calls and primitives anywhere. UNVERIFIED that the timestamp queries even return data on lavapipe.

## 6. Browser preview for a review hub

| Option                               | Status                                                                                                                                                                                                                                                                                                                      |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Godot web export                     | WebGL 2 / Compatibility only; "Forward+/Mobile are not supported on the web platform"; no WebGPU; single-threaded default since 4.3; threads need COOP/COEP + secure context (Exporting for Web, 4.7). A single generic "shader previewer" export can load `.gdshader` text at runtime. Heavy wasm; Compatibility-only look |
| Convert `.gdshader` to GLSL/three.js | No converter found. The language is "similar to GLSL ES 3.0" (shading language docs) but uses Godot built-ins and render modes; a hand port is needed. UNVERIFIED: the editor's "Inspect Native Shader Code" output as a starting point                                                                                     |
| Baked clips                          | Movie Maker PNG sequence, then ffmpeg (present locally) to WebM/MP4/APNG; exact for the chosen renderer; recommended default, matching `docs/research/13-web-review-hub.md`                                                                                                                                                 |

## Risks and uncertainties

- Every llvmpipe/lavapipe statement for 4.7.2 is UNVERIFIED locally, and Xvfb is not installed in `/usr/bin` on this machine. Tests to run: Forward+ startup, absence of silent fallback, `SHADER ERROR` format headless versus Vulkan, PNG determinism across two runs, GPU timer availability.
- The `--headless` path prints errors with an empty file name, so the kit must map errors back to the shader it loaded (load one shader per log section and print a marker line).
- Exit codes are not reliable: a forum report on 4.7.2 (2026-10) lists many failures that exit 0. This is community evidence and is consistent with the project rule.
- Source quotes come from `master` except for the Dummy material storage, which was checked at `4.7.2-stable`.

## Sources

- CLI options (4.7): https://docs.godotengine.org/en/stable/tutorials/editor/command_line_tutorial.html
- Dummy shader compile @4.7.2-stable: https://github.com/godotengine/godot/blob/4.7.2-stable/servers/rendering/dummy/storage/material_storage.cpp
- Error dump + ERR_HANDLER_SHADER: https://github.com/godotengine/godot/blob/master/servers/rendering/shader_compiler.cpp ; https://github.com/godotengine/godot/blob/master/core/error/error_macros.h ; https://github.com/godotengine/godot/blob/master/core/io/logger.cpp
- Upstream CI with Xvfb + Mesa: https://github.com/godotengine/godot/blob/master/.github/actions/godot-project-test/action.yml ; https://github.com/godotengine/godot/blob/master/.github/workflows/linux_builds.yml
- Pipeline compilation, ubershaders, shader baker headless note: https://docs.godotengine.org/en/stable/tutorials/performance/pipeline_compilations.html ; 4.5 release: https://godotengine.org/releases/4.5/
- Renderer fallback (4.4+): https://docs.godotengine.org/ja/4.4/tutorials/rendering/renderers.html
- Movie Maker: https://docs.godotengine.org/en/stable/tutorials/animation/creating_movies.html
- Viewport capture: https://docs.godotengine.org/en/stable/tutorials/rendering/viewports.html
- RenderingServer: https://docs.godotengine.org/en/stable/classes/class_renderingserver.html
- Particles seed: https://docs.godotengine.org/en/stable/classes/class_gpuparticles2d.html ; TIME: https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/canvas_item_shader.html
- Shading language: https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html
- Web export: https://docs.godotengine.org/en/stable/tutorials/export/exporting_for_web.html
- Optimization tools: https://docs.godotengine.org/en/stable/tutorials/performance/general_optimization.html
- Mesa envvars / llvmpipe: https://docs.mesa3d.org/envvars.html ; https://docs.mesa3d.org/drivers/llvmpipe.html ; Mesa 25.0 Vulkan 1.4 incl. lavapipe: https://docs.mesa3d.org/relnotes/25.0.0.html
- Regression scripts: https://github.com/godotengine/godot-benchmarks/issues/34 ; https://github.com/Calinou/godot-rendering-tests ; FLIP: https://github.com/NVlabs/flip
- Tooling: https://github.com/GodOfAvacyn/gdshader-lsp ; https://github.com/armsnyder/gdshader-language-server ; https://github.com/airblast-dev/tree-sitter-gdshader ; https://github.com/GodOfAvacyn/tree-sitter-gdshader ; https://store.godotengine.org/asset/madwind/simple-gdscript-formatter/
- Community (lower confidence): https://forum.godotengine.org/t/how-do-i-track-down-this-error/98336 (4.3 error text); https://forum.godotengine.org/t/how-can-the-official-godot-build-run-in-github-actions-without-encountering-errors-with-the-vulkan-driver/86611 (VK_KHR_surface); https://forum.godotengine.org/t/godot-crashes-on-linux-mint-when-loading-project/118276 (llvmpipe fallback); https://bugs.launchpad.net/bugs/2072335 (LLVM 15 crash); https://forum.godotengine.org/t/things-that-exit-0-in-godot-4-headless-even-though-they-failed-measured-reproducible/145990 (exit-0 traps, 4.7.2); https://forum.godotengine.org/t/how-to-detect-shader-compilation-errors-at-runtime/66687 (no API); https://godotassetlibrary.com/asset/DNVaro/gdsnap (GDSnap, 403)
