# The art bible, briefs and policy

## art/bible.json

```json
{
  "master_style": "flat shapes, two-tone shading, thick dark outline",
  "families": {
    "unit": {"mode": "flat", "min_subject_px": 120, "grounds": ["#d8cfb4", "#3a4a3a"]},
    "card": {"mode": "painterly", "min_subject_px": 240}
  },
  "roots": [
    {"id": "scout-root", "family": "unit", "file": "art/roots/scout.png",
     "status": "approved", "approved_at": "2026-11-15"},
    {"id": "painterly-root", "family": "card", "file": "art/roots/old.png", "status": "superseded"}
  ],
  "palette": {"ally": "#3070c0", "enemy": "#c03030", "loot": "#e0b030"},
  "banned": ["text or letters", "a frame or border", "photoreal faces"]
}
```

| Field                            | Meaning                                                                                   |
| -------------------------------- | ----------------------------------------------------------------------------------------- |
| `master_style`                   | One sentence every judge sheet quotes.                                                    |
| `families.<name>.mode`           | flat, painterly, photoreal, pixel, or the project's own word.                             |
| `families.<name>.min_subject_px` | The size a player meets the subject at; the readability judge reads 120 and 240 px.       |
| `families.<name>.grounds`        | Hex colours a sprite of the family sits on; `artkit precheck` measures against the worst. |
| `roots[]`                        | `id`, `family`, `file`, `status` (proposed, approved, superseded), `approved_at`.         |
| `palette`                        | Role to `#rrggbb`.                                                                        |
| `banned`                         | What no asset shows.                                                                      |

## art/briefs/<id>.json

The file name is the id: lower case, digits and hyphens.

```json
{
  "id": "scout-portrait",
  "family": "unit",
  "title": "Scout portrait",
  "hook": "a scout mid-stride, scanning the ridge",
  "readability": "the scout's silhouette and rifle read at 120 px",
  "contrast": "warm body against the cool ground",
  "roots": ["scout-root"],
  "refs": ["habitat-ridge"],
  "forbidden": ["a second figure"],
  "dependents": ["scout-card"],
  "canon_topics": ["units"],
  "asset": "scout-portrait-a1b2"
}
```

- `roots` must all be approved. `refs` may name roots or other briefs; a brief named there is upstream of this one.
- `dependents` names briefs built on this one, such as a card that frames a portrait.
- `asset` is written by `artkit register` on the first registration; never set it by hand.

## art/policy.json

Read by `artkit audit`; the first rule whose glob matches a file applies, and `*` crosses folders.

```json
{
  "target": "desktop",
  "vram_budget_mb": 512,
  "rules": [
    {"glob": "art/models/*", "mipmaps": true, "compress_modes": [2], "max_triangles": 20000,
     "max_materials": 2},
    {"glob": "art/pixel/*", "mipmaps": false, "compress_modes": [0]},
    {"glob": "art/cards/*", "max_texture_mb": 16}
  ]
}
```

- `target` is desktop, mobile or web; mobile and web limit the longest side to 4096 px (research 27, UNTESTED).
- Budgets are the project's numbers. No polygon or VRAM budget ships with the kit, since none has a tested source.
