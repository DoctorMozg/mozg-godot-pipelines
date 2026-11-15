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
- The license of a model's output depends on the endpoint. Read the model page before a commercial project uses it, and put the license id on the asset with `--license`.
- Hunyuan 3D is allowed with a warning (owner, 2026-11-15). Tencent's Hunyuan3D 2.0 and 2.1 community licenses exclude the European Union, the United Kingdom and South Korea from their territory (LICENSE files on Hugging Face, read 2026-11-15). fal's page for `fal-ai/hunyuan-3d/v3.1/pro/image-to-3d` tags it "Commercial use" and names no territory (read 2026-11-15); whether the exclusion reaches v3.1 on fal is UNTESTED. Before a call, name both to the owner, and record the license the owner picks with `--license`.

## Recording a judge's verdict

```bash
assetkit note <asset> --project <project> --body '<judge>: <verdict>; <failed ids with evidence>'
```

A fail goes back to step 2 of the skill with the evidence turned into one sentence of the prompt. Two failed redraws of the same brief stop the batch for that brief and go to the owner.

## After the owner's decision

- Approved: `assetkit promote <asset> --to res://<path>` copies the version into the project and imports it; then `artkit audit` once more.
- Sent back: the owner's note is the change for the next redraw.
- Delete `.mozg/art/judging/<brief>/` once the owner has decided.
