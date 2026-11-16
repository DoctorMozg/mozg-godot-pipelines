# Batch details

## The prompt from a brief

```text
<hook>. <master style>, <family mode> rendering.
<readability note>. <contrast plan>.
<forbidden and banned items, each turned into what the picture shows instead>.
Match the reference pictures for <subject identity, per root>.
```

- Positive wording: "a plain warm background" carries into the model; "no text" often draws text.
- The roots go in as reference pictures (`image_urls` on an edit endpoint), uploaded through fal-media's upload steps. A reference is never a previous candidate of the same batch.
- Keep the prompt the same for a retake unless the judges or the owner named a change; the change goes in as one sentence.

## Stills and models

| Asset | How it is made                                       | What the export needs                       |
| ----- | ---------------------------------------------------- | ------------------------------------------- |
| Still | One fal plan for the batch (`fal-plan`, `fal-run`)   | `--plan PLAN`                               |
| Model | `submit_job` on a mesh endpoint, then `falkit fetch` | `--call <tool use id>` beside `--plan PLAN` |

- fal-media prices a mesh endpoint only for a submit outside a plan, so models are never steps of the plan. `falkit ledger show` gives each call's tool use id.
- `face_count` sets the triangle count of a Hunyuan 3D model, from 40,000 up; set it at or under the folder's `max_triangles` in `art/policy.json`. A custom count and PBR maps are add-ons; `falkit estimate` gives the total ($0.675 for both on 2026-11-15).
- With PBR on, the GLB carries three 4096 px maps (colour, metal-roughness, normal), which Godot extracts beside it on import. Lossless they take 64 MiB of VRAM each; at mode 2 and 2048 px, 2.67 MiB each (`.ctex` payloads, Godot 4.7.2, 2026-11-15).
- Trellis 2 packs its two 1024 px textures (colour, metal-roughness) as WebP and lists `EXT_texture_webp` as required, with no PNG fallback (`fal-ai/trellis-2`, 2026-11-16). Godot 4.7.2 reads them; a viewer without the extension shows the model untextured and fully metallic. `artkit audit` names each required extension under `notes`. Before a model leaves Godot, re-save its images as PNG and drop the extension: an ffmpeg repack did so, and Godot and both kits read the result (2026-11-16).
- The license of a model's output depends on the endpoint. Read the model page before a commercial project uses it, and put the license id on the asset with `--license`.
- Hunyuan 3D is allowed with a warning (owner, 2026-11-15). Tencent's Hunyuan3D 2.0 and 2.1 community licenses exclude the European Union, the United Kingdom and South Korea from their territory (LICENSE files on Hugging Face, read 2026-11-15). fal's page for `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` tags it "Commercial use" and "Partner" and names no territory (read 2026-11-15 and 2026-11-16). That exclusion belongs to the open-weight 2.x releases: Hugging Face lists no v3 or v3.1 weights from Tencent (API, 2026-11-16), and v3.1 is a model version of Tencent Cloud's HY 3D API, whose Global terms (updated 2026-03-10, read 2026-11-16) exclude only sanctioned territories (§11.1(b), not the EU, UK or South Korea) and assign the output to the customer (§6.3(c)). fal's agreement with Tencent is not public, so whether it passes a territory limit through is UNTESTED; before shipping to the EU, UK or South Korea, ask fal. Before a call, name this to the owner, and record the license the owner picks with `--license`.

## Recording a judge's verdict

```bash
assetkit note <asset> --project <project> --body '<judge>: <verdict>; <failed ids with evidence>'
```

A fail goes back to step 2 of the skill with the evidence turned into one sentence of the prompt. Two failed redraws of the same brief stop the batch for that brief and go to the owner.

## After the owner's decision

- Approved: `assetkit promote <asset> --to res://<path>` copies the version into the project and imports it; then `artkit audit` once more.
- Sent back: the owner's note is the change for the next redraw.
- Delete `.mozg/art/judging/<brief>/` once the owner has decided.
