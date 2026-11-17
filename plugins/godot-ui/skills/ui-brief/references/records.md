# UI records

All three are JSON written by hand or by the agent and checked by `uikit lint`.

## ui/briefs/<surface>.json

| Field           | Meaning                                                                                 |
| --------------- | --------------------------------------------------------------------------------------- |
| `title`         | What the surface is, in a few words.                                                    |
| `input_devices` | Any of mouse, keyboard, gamepad, touch; keyboard or gamepad makes focus order required. |
| `sizes`         | Capture sizes as `WxH`; `uikit capture` shoots each, `uikit check` reads each.          |
| `states`        | The states the surface shows, such as idle, paused, locked.                             |
| `min_font_px`   | Smallest text allowed; every font token must reach it.                                  |
| `min_target_px` | Shortest side of anything clicked, tapped or focused, in window pixels.                 |
| `contrast`      | `text` and `nontext` ratios that `uikit tokens contrast` holds the pairs to.            |
| `strings_ns`    | The l10n namespace; screen keys must exist in it.                                       |
| `hard_rules`    | `id`, `text`, `check` (`judge` puts the rule on the conformance sheet).                 |
| `approved`      | null, or `{"by": "owner", "at": "YYYY-MM-DD"}` on the owner's yes.                      |

## ui/tokens.json

```json
{
  "color": {"ink": "#1a1a1a", "paper": "#f4efe4", "danger": "#c03030", "glass": "#131415eb"},
  "space": {"s": 4, "m": 8},
  "font": {"body": {"size_px": 16, "file": "res://fonts/body.ttf"}, "title": {"size_px": 28}},
  "stylebox": {
    "panel": {"bg": "paper", "border": "ink", "border_px": 2, "radius_px": 6, "margin_px": 8},
    "glass": {"bg": "glass", "margin_px": {"left": 12, "top": 8, "right": 12, "bottom": 8}}
  },
  "types": {"Button": {"color": {"normal": "ink", "hover": "danger"}, "stylebox": {"normal": "panel"}}},
  "variations": {
    "DangerButton": {"base": "Button", "color": "danger", "stylebox": "panel"},
    "Card": {"base": "PanelContainer", "stylebox": {"panel": "glass"}},
    "Stack": {"base": "VBoxContainer", "constants": {"separation": "m"}}
  },
  "contrast_pairs": [
    {"fg": "ink", "bg": "paper", "kind": "text"},
    {"fg": "paper", "bg": "glass", "ground": "ink", "kind": "text"}
  ]
}
```

- Colours are `#rrggbb` or `#rrggbbaa`. A pair whose `bg` is see-through names an opaque `ground`; `uikit tokens contrast` blends fg over bg over ground in sRGB before the WCAG ratio.
- `font.body.size_px` becomes the Theme's `default_font_size`, and its `file` the `default_font`. A `file` is a `res://` font file (FontFile) or a `.tres` FontVariation or SystemFont; a variation using a role with a `file` gets `fonts/font`.
- `variations` are named type variations with a `base` class; `types` style a built-in class itself, so every plain Button or Label takes the look. Both take the same fields; a name is one or the other.
- `color` as one name sets the font colour of normal, hover, pressed, hover-pressed and focus; as a map it sets only the states it names, from `normal`, `hover`, `pressed`, `hover_pressed`, `focus` and `disabled`. With one colour, hover shows no change.
- `stylebox` as one name fills normal, hover and pressed; as a map it fills the slots it names, such as `disabled`, `focus`, or `panel` for a PanelContainer. Without a `focus` slot the outline stays Godot's.
- `constants` sets theme constants (`separation`, `margin_left`, `h_separation`) to a whole number or a `space` token. `color_items` sets other named colours that scripts read with `get_theme_color`.
- `border_px` and `margin_px` take one whole px or one per side; 0 is allowed, as a hand-made Theme writes margins of 0.
- `min_font_px` is in window pixels: `uikit check` scales each font token by window/canvas at every size, so a 22 px token on a 1920x1080 base fails 18 at 1280x720 (14.7 px).
- Godot 4.7.2 loaded the written Theme and applied a variation's colour, border and radius to a Button (2026-11-15); it read back the default font, a FontVariation, a disabled colour, a focus box, alpha, per-side margins, constants and a named colour item (2026-11-17).

## ui/screens/<surface>/<screen>.json

```json
{
  "states": ["idle", "paused"],
  "strings": ["hud.pause"],
  "components": [
    {"name": "pause", "class": "Button", "variation": "DangerButton", "string": "hud.pause"},
    {"name": "score", "class": "Label"}
  ],
  "focus_order": ["pause"],
  "initial_focus": "pause",
  "scene": "res://ui/hud.tscn"
}
```

- `scene` is added once the scene exists; lint checks the file. `capture` is written by `uikit capture`; never set it by hand.
