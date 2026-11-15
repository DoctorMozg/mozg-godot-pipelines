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
  "color": {"ink": "#1a1a1a", "paper": "#f4efe4", "danger": "#c03030"},
  "space": {"s": 4, "m": 8},
  "font": {"body": {"size_px": 16}, "title": {"size_px": 28}},
  "stylebox": {"panel": {"bg": "paper", "border": "ink", "border_px": 2, "radius_px": 6, "margin_px": 8}},
  "variations": {"DangerButton": {"base": "Button", "color": "danger", "stylebox": "panel"}},
  "contrast_pairs": [{"fg": "ink", "bg": "paper", "kind": "text"}]
}
```

- `font.body.size_px` becomes the Theme's `default_font_size`.
- A variation sets the font colour of every state (normal, hover, pressed, focus) from `color`, `font_size` from `font`, and the normal, hover and pressed StyleBoxes from `stylebox`; the focus outline stays Godot's. With one colour per state, hover shows no change until tokens name hover colours.
- `min_font_px` is in window pixels: `uikit check` scales each font token by window/canvas at every size, so a 22 px token on a 1920x1080 base fails 18 at 1280x720 (14.7 px).
- Godot 4.7.2 loaded the written Theme and applied a variation's colour, border and radius to a Button (2026-11-15).

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
