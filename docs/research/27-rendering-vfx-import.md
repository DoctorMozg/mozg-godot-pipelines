# Rendering, lighting, VFX and asset import (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org (4.7) and the 4.3–4.7 release notes with PR numbers. Checks are UNTESTED on 4.7.2.

## Executive summary

The renderer choice drives everything else. Forward+ is the only renderer with VoxelGI, SDFGI, SSIL, SSR, volumetric fog, TAA/FSR2 and auto-exposure. Mobile drops all of those but keeps decals, particle collision and compositor effects. Compatibility is the only option on web. It adds SSAO (simplified, since 4.6) and LightmapGI (since 4.3), but has no HDR output, trails, decals or particle collision. From 4.4 to 4.7 the main changes were AgX (4.4, made tunable in 4.6), SMAA (4.5), glow blending before tonemapping with Screen as the default (4.6), octahedral reflection probes and a reworked SSR (4.6), and HDR output plus AreaLight3D (4.7). Texture import defaults are safe for 3D (Detect 3D switches to VRAM Compressed with mipmaps). They are a trap for pixel art and for mobile/web exports unless ETC2/ASTC import is enabled. A CLI kit can check most of this from `project.godot`, `*.import` and `.tscn` text without running Godot.

Source pages are the stable docs at docs.godotengine.org/en/stable/..., whose header reads "Godot Engine 4.7 documentation" (checked 2026-11-13). In the citations below, "docs:" stands for `https://docs.godotengine.org/en/stable/`.

## 1. Renderer choice

|                                                        | Forward+        | Mobile                                 | Compatibility                                       |
| ------------------------------------------------------ | --------------- | -------------------------------------- | --------------------------------------------------- |
| Target                                                 | desktop only    | mobile and desktop (default on mobile) | low-end, the only choice on web                     |
| VoxelGI / SDFGI / SSIL / SSR / volumetric fog          | yes             | no                                     | no                                                  |
| SSAO                                                   | yes             | no                                     | yes (simplified, 4.6+)                              |
| TAA, FSR2, auto-exposure, SSS, PCSS                    | yes             | no                                     | no                                                  |
| Decals, particle collision, compute, CompositorEffects | yes             | yes                                    | no                                                  |
| MSAA                                                   | 2D and 3D       | 2D and 3D                              | 3D only                                             |
| Omni/Spot lights per mesh                              | 512 per cluster | 8 (256 per view)                       | 8 (`rendering/limits/opengl/max_lights_per_object`) |
| ReflectionProbes per mesh                              | unlimited       | 8                                      | 2                                                   |
| HDR output (4.7)                                       | yes             | yes                                    | no                                                  |

Sources: docs: tutorials/rendering/renderers.html (4.7). Project setting defaults (class_projectsettings, 4.7): `rendering/renderer/rendering_method="forward_plus"`, `.mobile="mobile"`, `.web="gl_compatibility"`. Since 4.4, if Vulkan/D3D12/Metal is unavailable, the engine falls back to Compatibility (godotengine.org/releases/4.4, PR #97142). Since 4.6, D3D12 is the default on Windows for new projects (godotengine.org/releases/4.6, PR #113213).

## 2. 3D lighting and GI

| Technique                     | Cost rank (1 = cheapest) | Strengths and failure modes                                          | Renderers                                 |
| ----------------------------- | ------------------------ | -------------------------------------------------------------------- | ----------------------------------------- |
| ReflectionProbe (update Once) | 1                        | good reflections, poor GI; Always mode is much more expensive        | all                                       |
| LightmapGI                    | 2                        | excellent baked indirect light; static only; needs UV2               | all (baking needs RD; no web-editor bake) |
| VoxelGI                       | 3                        | real-time, needs a bake, light leaks                                 | Forward+                                  |
| SSIL                          | 4                        | secondary indirect light only, no reflections                        | Forward+                                  |
| SDFGI                         | 5 (slowest)              | no setup, works for procedural levels; leaks, visible cascade shifts | Forward+                                  |

Source: docs: tutorials/3d/global_illumination/introduction_to_global_illumination.html (4.7). Recommendations: SDFGI for desktop with an off switch in settings; mobile can use only LightmapGI and ReflectionProbes; procedural levels use SDFGI or probes, never LightmapGI.

LightmapGI facts (docs: tutorials/3d/global_illumination/using_lightmap_gi.html, 4.7):

- Meshes need GI mode Static and UV2.
- Default texel size is 0.2; Max Texture Size is 16384 by default, and oversized textures can crash the engine.
- Light bake modes are Disabled, Dynamic (the default; indirect only) and Static.
- Shadowmask modes are None, Replace and Overlay (4.4, PR #85653). Bicubic sampling is on by default (`rendering/lightmapping/lightmap_gi/use_bicubic_filter=true`, 4.4, PR #89919).
- At most 8 LightmapGI nodes render at once.
- Save the bake to an external `.lmbake` instead of embedding it in a `.tscn`.
- Denoiser is JNLM by default; OIDN is optional.

Other lighting changes:

- `AreaLight3D` (4.7, PR #108219).
- Octahedral reflection and radiance probes, which are cheaper and use less memory (4.6, PR #107902).
- Reworked SSR with full- and half-resolution modes (4.6, PR #111210).
- Specular occlusion (4.5, PR #106145; `rendering/reflections/specular_occlusion/enabled=true`).
- Bent normal maps (4.5, PR #89988).
- Shadow caster mask on lights (4.4, PR #85338).

Sources: godotengine.org/releases/4.4, /4.5, /4.6, /4.7.

## 3. Environment, post-processing, camera, physical units

- **Tonemap** (`Environment.tonemap_mode`): LINEAR=0 (the default), REINHARDT=1, FILMIC=2, ACES=3, AGX=4. AgX arrived in 4.4 (PR #87260). 4.6 exposed `tonemap_agx_white` (default 16.29) and `tonemap_agx_contrast` (default 1.25), PR #106940. AgX is the slowest tonemapper. On Mobile with HDR 2D off, `white` is ignored and 2.0 is used. Sources: docs: classes/class_environment.html (4.7); docs: tutorials/3d/environment_and_post_processing.html (4.7).
- **Glow**: since 4.6 glow is blended before tonemapping and Screen is the default blend mode (PR #110671). The exception is Softlight, which still applies to the tonemapped image.
  - CONFLICT DETECTED: the class reference (4.7) gives `glow_blend_mode` default = 1 (SCREEN), which matches the 4.6 release notes, while the environment_and_post_processing tutorial (4.7 docs) still calls Softlight the default. The tutorial is stale; trust the class reference.
  - Compatibility hides Levels, Normalized, Strength, Blend Mode, Mix and Map.
- **Fog**: `fog_mode` is EXPONENTIAL=0 or DEPTH=1. Depth fog arrived in 4.3 (releases/4.3).
- **Volumetric fog** is Forward+ only. It has a finite range (`volumetric_fog_length` defaults to 64), and banding and ghosting come from temporal reprojection. Keep Length as low as possible and FogVolume density textures at 64³ or smaller. Lights that live briefly should set `light_volumetric_fog_energy=0`. Mobile and Compatibility fall back to fog quads. Source: docs: tutorials/3d/volumetric_fog.html (4.7).
- **Adjustments** (applied after tonemapping): brightness, contrast, saturation, plus color correction from a 1D gradient or a 3D LUT. A LUT must be imported as Texture3D with the correct slice count (17, 33, 51 or 65).
- **CameraAttributes**: Practical or Physical. A Camera3D's attributes override the WorldEnvironment's. Auto exposure is Forward+ only.
- **Physical light units**: enable `rendering/lights_and_shadows/use_physical_light_units` (default false) and restart. Directional lights use lux (sun about 100,000), omni and spot lights use lumens (bulb 600–1,200), sky uses nits. Without CameraAttributes, the editor view blows out when a DirectionalLight3D is visible. Physical light units affect 3D only. Source: docs: tutorials/3d/physical_light_and_camera_units.html (4.7).

```ini
; project.godot, a desktop realistic baseline (Forward+)
[rendering]
anti_aliasing/quality/use_debanding=true
anti_aliasing/quality/msaa_3d=2
```

```gdscript
env.tonemap_mode = Environment.TONE_MAPPER_AGX   # 4.4+
env.tonemap_agx_contrast = 1.25                  # 4.6+
env.glow_enabled = true                          # Screen blend is default since 4.6
```

## 4. HDR output (4.7)

- Supported on Windows (D3D12), macOS, iOS and visionOS (Metal or Vulkan), and Linux under Wayland only.
- Forward+ and Mobile only. Not available on Compatibility, the web or X11. Android is "planned for a future release".
- Enable it with `display/window/hdr/request_hdr_output` (default false); no editor restart is needed.
- Projects created before 4.5 must set `rendering/rendering_device/driver.windows="d3d12"`.
- PRs #94496, #102987 and #106814.
- Sources: godotengine.org/article/hdr-output-arrives-in-godot-4-7/ and godotengine.org/releases/4.7/ (June 2026).
- CONFLICT DETECTED: ziva.sh/blogs/godot-4-7 (secondary, based on the beta notes) says Android HDR shipped in 4.6 and iOS is "not yet". The official article lists iOS as supported and Android as pending. Trust the official article.

## 5. Anti-aliasing and scaling

| Option                   | Renderers                   | Cost           | Since            | Setting                                                   |
| ------------------------ | --------------------------- | -------------- | ---------------- | --------------------------------------------------------- |
| MSAA 2/4/8x              | all (Compatibility 3D only) | medium         | 4.0              | `rendering/anti_aliasing/quality/msaa_3d`, `msaa_2d`      |
| TAA                      | Forward+                    | medium         | 4.0              | `.../quality/use_taa`                                     |
| FXAA                     | Forward+, Mobile            | very low       | 4.0              | `.../quality/screen_space_aa=1`                           |
| SMAA 1x                  | Forward+, Mobile            | low            | 4.5 (PR #102330) | `screen_space_aa=2`, `smaa_edge_detection_threshold=0.05` |
| FSR 1.0 / FSR 2.2        | FSR2 is Forward+ only       | high (FSR2)    | FSR2 4.2         | `rendering/scaling_3d/mode` 1 / 2, `fsr_sharpness=0.2`    |
| MetalFX spatial/temporal | Metal driver (macOS/iOS)    | n/a            | 4.4              | `scaling_3d/mode` 3 / 4                                   |
| Nearest 3D scaling       | n/a (no 2D effect)          | about bilinear | 4.7 (PR #79731)  | `scaling_3d/mode` 5                                       |
| SSAA                     | all                         | very high      | n/a              | `scaling_3d/scale>1.0`, bilinear                          |

Sources: docs: tutorials/3d/3d_antialiasing.html (4.7); docs: classes/class_viewport.html (4.7). FSR3 is not exposed: the 4.7 Scaling3DMode enum stops at NEAREST. UNVERIFIED: no official statement on FSR3 plans was found.

## 6. 2D rendering

- **Lights**:
  - PointLight2D and DirectionalLight2D; directional shadows are always infinitely long.
  - LightOccluder2D casts shadows. PCF13 is expensive, so use it on only a few lights.
  - CanvasModulate sets ambient darkness.
  - Normal/specular maps go through CanvasTexture.
  - Light is computed at viewport resolution, so Nearest filtering does not pixelate lights.
  - Shadow atlas: `rendering/2d/shadow_atlas/size=2048`.
  - Source: docs: tutorials/2d/2d_lights_and_shadows.html (4.7).
  - UNVERIFIED: the per-CanvasItem 2D light limit in 4.7 is not stated on the docs pages read.
- **HDR 2D**: `rendering/viewport/hdr_2d` (4.2+) gives an RGBA16 linear buffer, needed for 2D glow above 1.0. `use_debanding` has no effect in Compatibility.
- **Batching**: 2D batching reached the RD renderers in 4.4 (PR #92797).
- **Pixel art** (docs: tutorials/rendering/multiple_resolutions.html, 4.7):
  - Base size between 256×224 and 640×480; 640×360 is recommended.
  - `display/window/stretch/mode="viewport"`, `aspect="keep"` (or `expand`), `scale_mode="integer"` (4.2+; the default is `fractional`).
  - `rendering/textures/canvas_textures/default_texture_filter=0` (Nearest; the default is 1, Linear).
  - Snapping: `rendering/2d/snap/snap_2d_transforms_to_pixel` and `snap_2d_vertices_to_pixel` (both default false). Transform snapping can make Camera2D smoothing jitter.
  - Import pixel art with `compress/mode=0` (Lossless) and keep Detect 3D from turning it into VRAM Compressed.
- **4.7 additions**: `GradientTexture2D.FILL_CONIC` (PR #115394), TextureRect tiling part of an AtlasTexture (PR #113808), `DrawableTexture2D` (PR #105701).

## 7. Particles and VFX organisation

- **GPU vs CPU**: GPUParticles scale to hundreds of thousands of particles. The CPUParticles3D 4.7 class reference has no turbulence, collision, sub-emitter, trail or attractor properties (checked against the property list). `CPUParticles3D.convert_from_particles()` converts one way. Source: docs: classes/class_cpuparticles3d.html (4.7).
- **Turbulence** uses 3D noise and has a high GPU cost. Keep it to a few systems on screen and avoid it on mobile and web (docs: tutorials/3d/particles/turbulence.html).
- **Collision** comes from Box, Sphere, SDF (indoor) or HeightField (outdoor) colliders. Not available in Compatibility (renderers page).
- **Sub-emitters** have Constant, At End and At Collision modes. The child's `amount` caps them, Explosiveness is ignored, and instanced scenes need Editable Children (docs: tutorials/3d/particles/subemitters.html).
- **Trails** need `trail_enabled`, a RibbonTrailMesh or TubeTrailMesh draw pass, and a material with Use Particle Trails. Forward+ and Mobile only (docs: .../particles/trails.html).
- **Recent additions**: 3D particle scale and rotation (4.7, PR #112447), emission-shape gizmo (4.4, PR #100113), premultiplied alpha for 3D materials (4.3).
- **Organisation** (convention, not from docs): one scene per effect under `vfx/<name>.tscn`, with shared `ParticleProcessMaterial` `.tres` files. Set `visibility_aabb` explicitly; give one-shot effects `one_shot=true` and free them on `finished`; provide a CPU fallback scene for Compatibility targets.

## 8. Texture import

- **Compress modes** (`compress/mode`): 0 Lossless (2D default, pixel art), 1 Lossy (smaller files, same VRAM), 2 VRAM Compressed (3D default, 4–6× less memory, artifacts in 2D), 3 VRAM Uncompressed, 4 Basis Universal (smallest files, lower quality, no float).
- **Per-platform VRAM formats**: desktop uses S3TC (DXT1/5), or BPTC (BC7/BC6H) with High Quality on. Mobile and web use ETC2, or ASTC with High Quality on. High Quality is always off in Compatibility. Project flags: `rendering/textures/vram_compression/import_etc2_astc` and `import_s3tc_bptc` (both default false). UNVERIFIED: the export dialog offers to enable ETC2/ASTC when a mobile preset needs it; this was not confirmed in the 4.7 docs.
- **Normal maps**: `compress/normal_map` defaults to Detect (Enable means RGTC with the blue channel lost). `process/normal_map_invert_y` converts DirectX-style maps.
- **Roughness**: `roughness/mode` plus `roughness/src_normal` gives an import-time specular-aliasing limiter.
- **Mipmaps**: `mipmaps/generate` adds about 33% memory. Use it for 3D, and in 2D only if the camera zooms out. `mipmaps/limit` is not implemented.
- **Detect 3D**: a texture first used in 3D is reimported as VRAM Compressed with mipmaps. `detect_3d/compress_to` controls the target mode.
- **Size**: mobile and web are usually limited to 4096², and textures over 8192² may fail on old desktop GPUs. Mobile needs power-of-two textures for repeat. `process/size_limit` downscales on import.
- **HDR (.hdr/.exr)**: `compress/hdr_compression` defaults to Opaque Only. Leave `process/hdr_as_srgb` off unless the file is broken.
- **Alpha**: `process/fix_alpha_border` should stay on. `process/premult_alpha` requires a premultiplied-alpha material.
- **Betsy GPU compressor**: arrived in 4.4 (PR #91535) and runs about 2× faster in 4.6 (PR #110060).
- Sources: docs: tutorials/assets_pipeline/importing_images.html (4.7); docs: tutorials/3d/3d_rendering_limitations.html (4.7).

## 9. 3D import pipeline

- **Formats**: glTF 2.0 is preferred. `.glb` embeds textures; `.gltf` diffs better in version control. `.blend` needs Blender 3.0+ (3.5+ recommended), an official build, and the Blender path in Editor Settings; it is not available in the web or Android editors. FBX defaults to ufbx since 4.3, while FBX files added in 4.2 or earlier stay on FBX2glTF until switched. OBJ has no skinning, animation, UV2 or PBR. Source: docs: .../importing_3d_scenes/available_formats.html (4.7).
- **Import script** (in the import dock's Path option):

```gdscript
@tool
extends EditorScenePostImport
func _post_import(scene: Node) -> Object:
    return scene  # must return the scene
```

- **Options**: Ensure Tangents, Generate LODs (`LODs > Normal Merge Angle`), Create Shadow Meshes (welds vertices; cannot go below source LOD), and Light Baking set to Static Lightmaps (generates UV2 and exposes texel size). Source: docs: .../import_configuration.html (4.7).
- **Materials**: Advanced Import Settings, then Actions > Extract Materials, writes `.tres` files. Use External plus a path replaces the embedded material. Meshes can be saved to `.res` with Save to File (docs: .../advanced_import_settings.html, 4.7).
- **Collision suffixes**: `-col`, `-convcol`, `-colonly`, `-convcolonly`, `-occ`, `-occonly`, `-navmesh`, `-rigid`, `-vehicle`, `-wheel`, `-noimp`, `-vcol`, `-alpha`, `-loop`/`-cycle`. Prefer primitive shapes. Advanced Import Settings can instead set body type Static/Dynamic/Area and shape type Trimesh or Decompose Convex (docs: .../node_type_customization.html, 4.7).
- **Inheritance vs editable children**:
  - Inherited scenes are documented: base nodes can't be removed but nodes can be added, and subresources must be saved externally.
  - Editable children: UNVERIFIED in official docs. Forum reports (not relied on) say overrides and signal connections are dropped on reimport.
  - Recommendation: wrap the imported scene in your own scene and apply changes through an import script or extracted resources.
- **Mesh LOD**: auto-generated for glTF, .blend, DAE and FBX. Global threshold `mesh_lod_threshold` (1 px), per-instance `lod_bias`. The LOD level is chosen per node AABB, so a MultiMesh shares one LOD (docs: tutorials/3d/mesh_lod.html). LOD generation keeps multi-part meshes intact better since 4.6 (PR #110028).

## 10. VRAM budgeting and auditing

- Runtime: `Performance.get_monitor(Performance.RENDER_TEXTURE_MEM_USED)`, `RENDER_BUFFER_MEM_USED` and `RENDER_VIDEO_MEM_USED` (the total includes miscellaneous allocations), plus `RENDER_TOTAL_DRAW_CALLS_IN_FRAME` and `RENDER_TOTAL_PRIMITIVES_IN_FRAME` (docs: classes/class_performance.html, 4.7).
- Editor: the Debugger's Video RAM tab lists each resource with type, format and size, and shows a total (docs: tutorials/scripting/debug/debugger_panel.html).
- Offline estimate per texture (standard GPU block sizes, not from Godot docs):
  - Size in bytes = w × h × bpp / 8 × (1.33 if mipmapped).
  - bpp: RGBA8 = 32, DXT1/ETC2 RGB = 4, DXT5/BC7/ETC2 RGBA/ASTC 4×4 = 8, RGTC (normal map) = 8.

## Version-specific features

| Feature                                                                                                                                                                                                                                  | Version | Source                                          |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------- | ----------------------------------------------- |
| FSR 2.2, integer stretch scale, HDR 2D                                                                                                                                                                                                   | 4.2     | 3d_antialiasing, multiple_resolutions, env docs |
| ufbx FBX importer, Compositor effects, depth fog, LightmapGI/MSAA/glow in Compatibility, 2D physics interpolation                                                                                                                        | 4.3     | releases/4.3                                    |
| AgX (#87260), lightmap bicubic + shadowmask (#89919, #85653), ubershaders (#90400), Metal + MetalFX (#88199), Betsy (#91535), 2D batching in RD (#92797), renderer fallback (#97142)                                                     | 4.4     | releases/4.4                                    |
| SMAA 1x (#102330), stencil (#80710), shader baker (#102552), bent normals (#89988), specular occlusion (#106145), Mobile F16 (#107119)                                                                                                   | 4.5     | releases/4.5                                    |
| AgX white/contrast (#106940), glow before tonemap with Screen default (#110671), octahedral probes (#107902), SSR rework (#111210), material debanding (#109084), D3D12 default (#113213), Jolt default (#105737), SSAO in Compatibility | 4.6     | releases/4.6, env docs                          |
| HDR output (#94496), AreaLight3D (#108219), clearcoat fix (#111464), nearest 3D scaling (#79731), particle scale/rotation (#112447), DrawableTexture2D (#105701), Vulkan subsampled images (#116220)                                     | 4.7     | releases/4.7                                    |

## Checkable rules an agent should follow

1. `rendering_method.web` is `gl_compatibility`, and no web preset assumes Forward+ features.
1. Projects with Mobile or Compatibility as the effective renderer have no Environment with `sdfgi_enabled`, `ssil_enabled`, `ssr_enabled` or `volumetric_fog_enabled` set to true, and no VoxelGI node.
1. Mobile targets have no Environment with `ssao_enabled=true` (it is ignored on Mobile).
1. `use_taa=true` or `scaling_3d/mode=2` (FSR2) only with Forward+.
1. `scaling_3d/mode` 3 or 4 (MetalFX) only in `.macos` or `.ios` overrides.
1. `display/window/hdr/request_hdr_output=true` only with Forward+ or Mobile; on Windows the driver is d3d12.
1. If any export preset targets Android, iOS or Web, `import_etc2_astc=true`.
1. Textures under a pixel-art folder use `compress/mode=0` and `mipmaps/generate=false`, and `detect_3d/compress_to` does not reintroduce VRAM compression.
1. Pixel-art projects set `default_texture_filter=0`, `stretch/mode="viewport"` and `stretch/scale_mode="integer"`.
1. Textures used in 3D have `mipmaps/generate=true` and `compress/mode=2` (or Basis).
1. Mobile and web textures are at most 4096 px per side, and repeat-wrapped textures there are power of two.
1. Normal maps have `compress/normal_map` set to 0 (Detect) or 1, and DirectX-sourced maps set `process/normal_map_invert_y=true`.
1. `process/hdr_as_srgb=false` unless a comment justifies it.
1. Every MeshInstance3D under a LightmapGI with `gi_mode=Static` comes from an import with Static Lightmaps baking or has UV2.
1. LightmapGI data is an external `.lmbake`, not embedded, and a scene has at most 8 LightmapGI nodes.
1. The number of Omni/Spot lights that can affect one mesh stays at or below 8 on Mobile and Compatibility.
1. With `use_physical_light_units=true`, every WorldEnvironment or Camera3D has CameraAttributes.
1. Volumetric fog `volumetric_fog_length` is at most what the scene needs (a flag above 64 needs justification).
1. GPUParticles with turbulence are 4 or fewer per scene and none in mobile or web builds.
1. Scenes for Compatibility contain no GPUParticles collision nodes, trails (`trail_enabled`) or Decal nodes.
1. Imported model scenes are referenced via inherited or wrapper scenes, and no `.tscn` edits the `.glb` itself. Import scripts return the scene.
1. 3D AA uses `screen_space_aa=2` (SMAA, 4.5+) or MSAA, not both FXAA and TAA by habit; Compatibility uses MSAA only.
1. Desktop 3D projects with gradients set `use_debanding=true` (Forward+ and Mobile).
1. Glow configs do not assume the Softlight default (Screen since 4.6); `glow_blend_mode` is explicit.

## What a tool could check automatically

- **project.godot audit**:
  - Parse `[rendering]` and `[display]`.
  - Compute the effective renderer per platform from `rendering_method`, `.mobile`, `.web` and `export_presets.cfg`.
  - Flag feature mismatches (rules 1–7, 9, 17, 23).
- **`.import` audit**: parse every `*.import` (an INI-like `[params]` section) and check `compress/mode`, `mipmaps/generate`, `detect_3d/compress_to`, `compress/normal_map`, `process/size_limit` and `process/hdr_as_srgb` against folder-based policy (pixel art, UI, 3D).
- **Texture size and VRAM budget**:
  - Read PNG/JPG/WebP headers (stdlib `struct`) for w×h.
  - Estimate VRAM with the bpp table above per compress mode and platform.
  - Sum per scene by following `ext_resource` paths in `.tscn`/`.tres`, and compare against a budget in a JSON config.
  - Flag textures over 4096 for mobile and web, and non-power-of-two repeat textures.
- **Scene audit (`.tscn` text)**:
  - Count `OmniLight3D`/`SpotLight3D`/`DirectionalLight3D` (more than 8 directional lights is always an error), `LightmapGI` (8 max), `VoxelGI`, `ReflectionProbe` (`update_mode=1` means Always), `GPUParticles3D` with `turbulence_enabled`, `trail_enabled`, `Decal`, `FogVolume`.
  - Flag WorldEnvironment without CameraAttributes under physical units.
  - Flag an embedded `LightmapGIData` sub_resource.
- **Environment resource audit**: `tonemap_mode`, `glow_blend_mode` present, `sdfgi/ssil/ssr/volumetric_fog` flags against the renderer.
- **Import pipeline**: list `.fbx` imports still on FBX2glTF (importer field in `.import`) and models without LOD or shadow meshes. Check `.blend` imports when web or Android editor builds matter.
- **Live, optional** (`live_godot`): run a scene headless or windowed, print `Performance` RENDER\_\* monitors as an explicit summary line, and judge from the log, not the exit code.

## Pitfalls

- Stale docs: the post-processing tutorial still calls Softlight the glow default, but it has been Screen since 4.6 (class reference, release notes).
- Detect 3D silently converts a 2D or pixel-art texture to VRAM Compressed with mipmaps the first time it touches 3D (importing_images).
- Banding: Compatibility has the lowest precision and Mobile less than Forward+. `use_debanding` does nothing in Compatibility, so use a shader or baked noise there (3d_rendering_limitations).
- Z-fighting: the depth buffer is 24-bit on mobile. Raise Camera `near` before lowering `far`.
- Mipmap shimmer and specular aliasing: enable mipmaps for 3D and use the roughness-from-normal import limiter. The screen-space roughness limiter is on by default (`amount=0.25`, `limit=0.18`).
- sRGB mistakes: `hdr_as_srgb` darkens correct HDR files. Vertex colors need `-vcol` or the material's sRGB vertex color flag. Linear-data maps (roughness, normal) must not be treated as color; Godot handles BaseMaterial3D slots, but custom shaders must use `hint_normal` / `hint_roughness_*` (UNVERIFIED here; shaders are out of scope).
- Physical light units without CameraAttributes give a white-out editor view.
- Hiding a light does not exclude it from a lightmap bake; set bake mode Disabled.
- MultiMesh and particle LOD and culling are per node, so one node spanning the map never culls or reduces LOD.
- `.blend` import breaks on Flatpak or distro Blender builds and on the web or Android editor.
- CPUParticles conversion drops turbulence, collisions, sub-emitters and trails without warning.

## Sources

- https://docs.godotengine.org/en/stable/tutorials/rendering/renderers.html: renderer feature matrix and light limits (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/global_illumination/introduction_to_global_illumination.html: GI comparison (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/global_illumination/using_lightmap_gi.html: LightmapGI (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/environment_and_post_processing.html: tonemap, glow, fog, adjustments, CameraAttributes (4.7)
- https://docs.godotengine.org/en/stable/classes/class_environment.html: defaults and enums (4.7)
- https://docs.godotengine.org/en/stable/classes/class_viewport.html: Scaling3DMode, AA, snapping, HDR 2D (4.7)
- https://docs.godotengine.org/en/stable/classes/class_projectsettings.html: setting keys and defaults (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/3d_antialiasing.html: AA matrix (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/physical_light_and_camera_units.html: physical units (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/volumetric_fog.html: volumetric fog (4.7)
- https://docs.godotengine.org/en/stable/tutorials/2d/2d_lights_and_shadows.html: 2D lighting (4.7)
- https://docs.godotengine.org/en/stable/tutorials/rendering/multiple_resolutions.html: pixel-art stretch settings (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/particles/index.html, .../turbulence.html, .../subemitters.html, .../trails.html, and classes/class_cpuparticles3d.html: particles (4.7)
- https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_images.html: texture import (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/3d_rendering_limitations.html: size limits, banding, z-fighting, transparency (4.7)
- https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_3d_scenes/available_formats.html, import_configuration.html, advanced_import_settings.html, node_type_customization.html: 3D import (4.7)
- https://docs.godotengine.org/en/stable/tutorials/3d/mesh_lod.html: mesh LOD (4.7)
- https://docs.godotengine.org/en/stable/classes/class_performance.html and tutorials/scripting/debug/debugger_panel.html: VRAM monitoring (4.7)
- https://godotengine.org/releases/4.3/, /4.4/, /4.5/, /4.6/, /4.7/: release notes with PR numbers
- https://godotengine.org/article/hdr-output-arrives-in-godot-4-7/: HDR output (June 2026)
- https://ziva.sh/blogs/godot-4-7: secondary, cited only for the HDR platform conflict
- Forum threads on editable children (forum.godotengine.org): used only to mark the claim UNVERIFIED
