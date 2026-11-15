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
- `face_count` sets the triangle count of a Hunyuan 3D model; set it at or under the folder's `max_triangles` in `art/policy.json`. fal-media's price table lists the endpoint's add-ons; `falkit estimate` gives the total.
- The license of a model's output depends on the endpoint. Read the model page before a commercial project uses it, and put the license id on the asset with `--license`.

## Recording a judge's verdict

```bash
assetkit note <asset> --project <project> --body '<judge>: <verdict>; <failed ids with evidence>'
```

A fail goes back to step 2 of the skill with the evidence turned into one sentence of the prompt. Two failed redraws of the same brief stop the batch for that brief and go to the owner.

## After the owner's decision

- Approved: `assetkit promote <asset> --to res://<path>` copies the version into the project and imports it; then `artkit audit` once more.
- Sent back: the owner's note is the change for the next redraw.
- Delete `.mozg/art/judging/<brief>/` once the owner has decided.
