# Build details

## Scene rules and where they come from

Research 22 (docs 4.7, read 2026-11-13) lists them; none was measured on 4.7.2 unless marked.

| Rule                                                                      | Checked by                        |
| ------------------------------------------------------------------------- | --------------------------------- |
| `display/window/stretch/mode` is canvas_items or viewport                 | `uikit scan` (stretch)            |
| `gui/theme/custom` names an existing theme                                | `uikit scan` (theme)              |
| No Container child sets position, rotation or scale                       | `uikit scan` (container)          |
| No Button has `focus_mode = 0`                                            | `uikit scan` (focus)              |
| A full-screen Control, ColorRect, TextureRect or Panel ignores the mouse  | `uikit scan` (mouse_filter)       |
| Every `theme_type_variation` is a token variation                         | `uikit scan` (variation)          |
| No `Color(` literal in a screen's scripts                                 | `uikit scan` (colour)             |
| First focus grabbed in `_ready` when keyboard or gamepad is in the brief  | readability judge (U5)            |
| An autowrapping Label has a maximum width (4.7 docs; 4.6 docs do not say) | not checked: the sources conflict |

- `uikit scan` reads only the scenes that screen records name, and the scripts those scenes attach.
- Default `mouse_filter` on Godot 4.7.2 (2026-11-15): Label 2 (ignore); Control, ColorRect and Panel 0 (stop); TextureRect 1 (pass).

## Shots

```bash
godotkit shot --project <project> --scene <scene> --sizes 1280x720,1920x1080 --out <folder>
uikit check --shots <folder> --brief <surface>
```

- `godotkit shot` writes `<W>x<H>.json` (window rects of visible Controls) and, natively, `<W>x<H>.png` per size, in one Godot process.
- `uikit check` reads the JSON: font tokens drawn under `min_font_px` once stretch scales them, off screen (beyond 0.5 px of the window), interactive targets under `min_target_px`, overlapping interactive controls that are not parent and child, a control present at one size only, a size with no file.
- Interactive means a Button family class, LineEdit, TextEdit, SpinBox, a slider, ItemList, Tree or TabBar.

## Judges

1. `uikit judge <surface>/<screen> --shots <folder> --kind readability` writes the sheet under `.mozg/ui/judging/`, with the brief's numbers and the `uikit check` findings.
1. Dispatch `ui-readability-judge` with the sheet path alone; then the same for `conformance` and `ui-conformance-judge`.
1. `assetkit note <asset> --project <project> --body '<judge>: <verdict>; <failed ids with evidence>'`.
1. A fail goes back to step 4 of the skill with the evidence as the change. Delete `.mozg/ui/judging/<screen>/` after the owner decides.
