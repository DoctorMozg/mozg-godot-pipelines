# Game UI/UX (Godot 4.7)

Source: web research of 2026-11-13 against docs.godotengine.org/en/4.7, the 4.4–4.7 release notes and dev snapshots, XAG 101, Game Accessibility Guidelines and Steam Deck docs. Probes and GDScript examples are UNTESTED on 4.7.2.

Research date: 2026-11-13. Docs pages were read from `docs.godotengine.org/en/4.7/` unless noted otherwise. This report complements `docs/research/06-ui-ux.md`, which covers AloneGodot evidence, and `16-web-i18n.md`.

## Executive summary

Godot 4.7 changes UI work in a few ways that matter:

- **Animating children of containers:** `offset_transform_*` (4.7) moves, rotates or scales a child of a Container without the container resetting it. Before 4.7 you had to fight the container or wrap the child.
- **Maximum size:** `custom_maximum_size` arrived in 4.7, and the docs now say an autowrapping Label needs a *maximum* width.
- **Focus:** since 4.6, focus from a mouse click is hidden by default (`grab_focus(hide_focus)`, `gui/common/show_focus_state_on_pointer_event`).
- **Screen readers:** support (AccessKit) arrived in 4.5 and is still experimental. 4.7 adds landmark regions.

There is no built-in support for safe-area layout, subtitles, colour-blind modes or a remapping UI. Projects build those themselves, so an agent can check them only by convention.

## 1. Layout: anchors, offsets, containers, size flags

- **Anchors and offsets:** anchors run 0.0–1.0 of the parent, and offsets are pixel distances from the anchor. Giving an axis two different anchor values makes the control resize with its parent. https://docs.godotengine.org/en/4.7/tutorials/ui/size_and_anchors.html
- **Containers own their children:** inside a Container, "all children Control nodes give up their own positioning ability". Manual edits are "either ignored or invalidated the next time their parent is resized". https://docs.godotengine.org/en/4.7/tutorials/ui/gui_containers.html
- **Size flags:**
  - `SIZE_FILL` = 1 (default), `SIZE_EXPAND` = 2, `SIZE_EXPAND_FILL` = 3, `SIZE_SHRINK_CENTER` = 4, `SIZE_SHRINK_END` = 8.
  - `size_flags_stretch_ratio` shares the free space among expanding children.
  - Source: Control class reference, 4.7.
- **Container types:** FoldableContainer (4.5), AspectRatioContainer, FlowContainer, and SubViewportContainer (one SubViewport child).
- **Custom container:** handle `NOTIFICATION_SORT_CHILDREN`, then call `fit_child_in_rect`. Call `queue_sort()` when a setting changes. (gui_containers page, 4.7)
- **Maximum size (4.7):**
  - `custom_maximum_size` defaults to `Vector2(-1,-1)`, meaning no maximum. Added in GH-116640: https://godotengine.org/article/dev-snapshot-godot-4-7-dev-4/
  - `get_combined_minimum_size()` ignores the maximum, so the docs recommend `get_bound_minimum_size()` instead.
- **When to use which:**
  - Containers for any list, form, menu or HUD strip that must survive resizing or translation.
  - Anchors on a root-level Control for corner HUD pieces and full-screen overlays.
  - Manual `position` only for free-floating things: tooltips that follow the cursor, damage numbers, drag ghosts. This is an inference from the container docs.

```gdscript
# HUD root: full rect, never eats clicks meant for the world
anchors_preset = PRESET_FULL_RECT   # .tscn: layout_mode = 3, anchors_preset = 15
mouse_filter = MOUSE_FILTER_IGNORE
```

## 2. Themes, type variations, StyleBoxes, tokens

- **Lookup order:**
  1. A local override.
  1. The `theme` of each ancestor Control, matched by variation, then class, then parent classes.
  1. The project theme (`gui/theme/custom`).
  1. The default theme.
- **Local overrides** affect only that control, not its children.
- **Focus StyleBoxes** draw as an overlay, so they should be outlines or translucent.
- **Type variations:**
  - Set with `theme_type_variation` (for example `HeaderLabel` based on `Label`).
  - The Inspector lists only variations from the default or project theme.
- Source: https://docs.godotengine.org/en/4.7/tutorials/ui/gui_skinning.html
- **Tokens:** generate one `Theme.tres` from the token file, with colours, font sizes, constants (separation, margins) and StyleBoxFlat (`bg_color`, `corner_radius_*`, `content_margin_*`). Scripts then read only `theme_type_variation`, not literal colours. This is a recommended pattern, not an engine feature.
- **`LabelSettings`:** shared Label styling that takes priority over the theme. Stacked outline and shadow layers arrived in 4.5 (https://godotengine.org/releases/4.5/).

```gdscript
var t := Theme.new()
t.set_type_variation("DangerButton", "Button")
t.set_color("font_color", "DangerButton", Color("#ff5a5a"))
t.set_font_size("font_size", "DangerButton", 22)
```

## 3. Resolution, aspect ratio, scaling

- **Project settings (4.7 defaults):**

  - `display/window/stretch/mode="disabled"`
  - `aspect="keep"`
  - `scale=1.0`
  - `scale_mode="fractional"`
  - `display/window/dpi/allow_hidpi=true`
  - Source: https://docs.godotengine.org/en/4.7/classes/class_projectsettings.html

- **Recommended settings by game type:**

  | Game type          | Base size | `stretch/mode` | `stretch/aspect`   | Other                            |
  | ------------------ | --------- | -------------- | ------------------ | -------------------------------- |
  | Desktop, non-pixel | 1920×1080 | `canvas_items` | `expand`           | —                                |
  | Mobile, landscape  | 1280×720  | `canvas_items` | `expand`           | —                                |
  | Pixel art          | 640×360   | `viewport`     | `keep` or `expand` | `scale_mode=integer` (since 4.2) |

  `expand` covers ultrawide. With a 4K base, use `default_theme_scale` 2.0–3.0 and mipmaps or DPITexture. Source: https://docs.godotengine.org/en/4.7/tutorials/rendering/multiple_resolutions.html

- **Player-facing UI scale:** set `get_tree().root.content_scale_factor`; the docs recommend Stretch Scale for accessibility. `gui/theme/default_theme_scale` is read only once at startup (same page).

- **Steam Deck:**

  - Support 1280×800 (preferred) or 1280×720.
  - The smallest glyph must be at least 9 px tall at 1280×800; 12 px is recommended.
  - Glyphs must match the active input device.
  - Text entry needs the Steamworks on-screen keyboard API or controller-only entry.
  - Source: https://partner.steamgames.com/doc/steamdeck/compat (undated page, fetched 2026-11).
  - A 1920×1080 base with `expand` gives extra vertical space on 16:10, so anchor the HUD to its edges.

- **Safe areas:** `DisplayServer.get_display_safe_area() -> Rect2i` and `get_display_cutouts()` exist (DisplayServer reference, 4.7). The 4.7 multiple-resolutions page does not mention safe areas.

  - UNVERIFIED: which platforms return a meaningful value (assumed Android and iOS).

```gdscript
func _apply_safe_area() -> void:
    var safe := DisplayServer.get_display_safe_area()   # screen pixels
    var win := get_window()
    var s := Vector2(win.content_scale_size) / Vector2(win.size)  # screen→canvas
    $SafeMargin.add_theme_constant_override("margin_left", int(safe.position.x * s.x))
```

UNVERIFIED: this conversion assumes `canvas_items`, a fullscreen window and the `expand` aspect.

## 4. Fonts and text

- **Font types:**
  - Dynamic fonts: TTF, OTF, WOFF, WOFF2.
  - Bitmap fonts: `.fnt` or an image font.
  - With no font set, Godot uses Open Sans SemiBold.
  - Source: https://docs.godotengine.org/en/4.7/tutorials/ui/gui_using_fonts.html
- **MSDF:**
  - Crisp at any size and no rasterisation stutter at large sizes.
  - Higher base cost, weak at small sizes (no hinting), no LCD subpixel.
  - Set MSDF pixel range to at least 2× the outline size.
  - `gui/theme/default_font_multichannel_signed_distance_field` affects only the built-in font.
  - Use MSDF for world-space text, zoomed text and big titles.
- **Rendering settings:** grayscale antialiasing for games. For pixel fonts, turn subpixel positioning off and use a Nearest filter with integer scaling.
- **Fallbacks:**
  - Set in Advanced Import → Fallbacks (CJK, Cyrillic, emoji).
  - Emoji fonts: CBDT/CBLC and SVG work; COLR/CPAL does not.
  - `SystemFont` is useful but metrics vary, so leave slack in layouts.
- **Pre-render configurations** remove first-display glyph stutter, at the cost of file size.
- **Label:**
  - `autowrap_mode` (default 0, off), `text_overrun_behavior`, `ellipsis_char`, `max_lines_visible`, `clip_text`.
  - 4.7 note: "Labels with autowrapping enabled must have a custom maximum width configured to work correctly." The 4.6 page has no such note. https://docs.godotengine.org/en/4.7/classes/class_label.html
- **RichTextLabel:**
  - Defaults: `bbcode_enabled=false`, `autowrap_mode=3`, `fit_content=false`, `threaded=false`.
  - Use `append_text()`, not `text +=`, which "can cause slowdowns".
  - With `threaded`, line and height queries are partial until `finished` fires.
  - 4.7: `[img height=1em]` sizes images relative to the font.
  - Source: https://docs.godotengine.org/en/4.7/classes/class_richtextlabel.html
- **Right-to-left and complex scripts:**
  - RTL mirrors anchors, margins, alignment and child order. Override per control with `layout_direction`.
  - Exports need "Include Text Server Data" (about 4 MB of ICU data) for languages written without spaces.
  - Test with `godot --language ar` or `internationalization/locale/test`.
  - Source: https://docs.godotengine.org/en/4.7/tutorials/i18n/internationalizing_games.html

## 5. Focus and gamepad/keyboard navigation

- **`focus_mode` values:** `FOCUS_NONE`=0, `FOCUS_CLICK`=1, `FOCUS_ALL`=2, `FOCUS_ACCESSIBILITY`=3 (focusable only when a screen reader is active; 4.5+). Labels default to None and Buttons to All. Source: Control class reference, 4.7.
- **Navigation rules from the docs:**
  - `focus_neighbor_*` sets d-pad and arrow navigation; `focus_next`/`focus_previous` set Tab order.
  - Without neighbours the engine guesses, which "can be unpredictable".
  - A hidden node loses focus.
  - `ui_*` actions "should not be used for any gameplay code".
  - Initial focus is mandatory: `$Start.grab_focus.call_deferred()`.
  - Source: https://docs.godotengine.org/en/4.7/tutorials/ui/gui_navigation.html
- **Mixed mouse and gamepad (4.6+):**
  - Focus given by a mouse click is not drawn. PRs #110250 and #110895 are cited from mirror commits; the upstream GitHub pages were not opened.
  - Setting `gui/common/show_focus_state_on_pointer_event` (default 1 = "control supports keyboard input"; 0 = never, 2 = always).
  - API: `grab_focus(hide_focus := false)`; `has_focus(ignore_hidden_focus := false)`.
  - On the first gamepad or key event after mouse use, call `grab_focus()` on the last hovered or focused control so the focus ring appears.
- **Locking a whole panel (4.5+):** `focus_behavior_recursive` / `mouse_behavior_recursive` = `*_DISABLED` turns off a subtree, for example an inventory detail panel that stays inactive until an item is chosen. https://godotengine.org/releases/4.5/
- **4.7 input changes:** a project setting ignores joypads while the window is unfocused (default off), and `InputEvent.DEVICE_ID_KEYBOARD` / `DEVICE_ID_MOUSE` exist. https://godotengine.org/releases/4.7/

## 6. Accessibility

- **Screen readers (AccessKit, 4.5+, experimental):**
  - Covers Control nodes plus bindings for any Node. https://godotengine.org/releases/4.5/
  - Control properties: `accessibility_name`, `accessibility_description`, `accessibility_live`, `accessibility_labeled_by_nodes`, `accessibility_described_by_nodes`, `accessibility_controls_nodes`, `accessibility_flow_to_nodes`.
  - `accessibility/general/accessibility_support` defaults to 0 = "Auto": updates are processed only when an assistive app is running. `updates_per_second` defaults to 60.
  - UNVERIFIED: the meaning of values 1 and 2 (assumed "always" and "disabled", taken from the editor-setting equivalent).
  - 4.7 adds landmark navigation. A mirror commit and a forum post put an `accessibility_region` property on Container. UNVERIFIED: the exact class and property name against official docs.
  - Rémi Verschelde: "I don't think we can claim yet that Godot is accessible" (reported by heise, Sept 2025: https://heise.de/-10651078).
- **Text size, Xbox Accessibility Guideline 101** (page updated 2026-06): https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/101
  - Minimum default sizes: 26 px at 1080p on console, 18 px at 1080p on PC.
  - Scaling to 200% without loss of content.
  - Lines of 80 characters or fewer, line spacing of at least 1.5×.
  - Glyphs scale with the text.
- **Game Accessibility Guidelines (basic level):** https://gameaccessibilityguidelines.com/full-list/
  - All UI reachable with the gameplay input method.
  - Remappable controls.
  - Readable default font size.
  - High contrast.
  - "No essential information … by a fixed colour alone".
  - Clear subtitles for important speech.
  - Avoid flicker.
- **Built into Godot vs not:**
  - Remapping UI: not built in. Use `InputMap.action_erase_events` / `action_add_event` and persist to `user://` through `ConfigFile`.
  - Subtitles: no built-in node; drive a Label or RichTextLabel from AnimationPlayer or audio cue data.
  - Colour-blind palettes: no built-in mode. Ship alternative Theme variants and pair colour with icon or shape.

## 7. Diegetic UI and SubViewports

- **SubViewport behaviour:**
  - A SubViewport gets input only from its parent SubViewportContainer.
  - "Disable Input" turns input off.
  - `render_target_update_mode`: Never, Once, Always, When Parent Visible.
  - `transparent_bg` for overlays.
  - Source: https://docs.godotengine.org/en/4.7/tutorials/rendering/viewports.html
- **GUI on a 3D mesh:** use a SubViewport plus a ViewportTexture on the mesh material. Raycast to UV, then call `subviewport.push_input(event)` with the converted position. Reference: the official demo `viewport/gui_in_3d` in https://github.com/godotengine/godot-demo-projects. UNVERIFIED: the demo's current 4.7 state was not opened.
- **Simple world text:** use `Label3D`, with MSDF for crisp zoom.
- **When not to use 3D UI:** prefer a Control overlay unless the UI must be physically in the world. Mesh UI loses text scaling and focus navigation for free, as AloneGodot's plan found (see 06-ui-ux.md).

## 8. HUD, menus and animation

- **Pause menu:**
  - Root `process_mode = PROCESS_MODE_ALWAYS` on a CanvasLayer, with `get_tree().paused = true`.
  - Its tweens need `set_pause_mode(Tween.TWEEN_PAUSE_PROCESS)`.
  - Grab focus on open and restore the previous focus on close.
  - `ui_cancel` closes the menu.
- **Confirmation dialogs:** `ConfirmationDialog`, or a custom modal with a STOP-filter full-rect backdrop. Default focus goes to the non-destructive button.
- **Settings screen:**
  - Apply and persist through `ConfigFile` in `user://settings.cfg`.
  - The resolution and UI-scale options map to `content_scale_factor` and the window mode.
- **Tweens** (https://docs.godotengine.org/en/4.7/classes/class_tween.html):
  - Not reusable ("undefined behavior"); create one per animation.
  - Looping tweens should use `bind_node()`. `create_tween()` on a node binds it to that node.
  - `kill()` the old tween before starting a new one on the same property.
  - `tween_await(signal)` is new in 4.7.
- **Pitfall (fixed in 4.7):** a container resets a child's position, scale and rotation on re-sort. Options:
  - 4.7+: animate `offset_transform_position`, `offset_transform_scale` or `offset_transform_rotation`, with `offset_transform_enabled=true`. Visual only by default (`offset_transform_visual_only=true`), so hit areas do not move. PR #87081; https://godotengine.org/releases/4.7/
  - Before 4.7: animate `modulate`, or wrap the child in a plain Control and animate the inner node.
  - `pivot_offset_ratio = Vector2(0.5, 0.5)` (4.6+) keeps scale centred while the control resizes.

```gdscript
func pulse(b: Control) -> void:
    b.offset_transform_enabled = true
    var tw := b.create_tween()
    tw.tween_property(b, "offset_transform_scale", Vector2(1.1, 1.1), 0.08)
    tw.tween_property(b, "offset_transform_scale", Vector2.ONE, 0.12)
```

## 9. Performance of large UIs

- **2D batching:** Forward+ and Mobile gained it in 4.4 (GH-92797); Compatibility has had it since 4.0. Effect is "particularly noticeable in scenes with a lot of text". https://godotengine.org/releases/4.4/
- **Long lists:** prefer `ItemList`, `Tree` or a recycled pool of row scenes inside a ScrollContainer over thousands of Buttons. This is engineering opinion; there is no official number.
- **Hide what is not visible:** `visible=false` on off-screen panels, not `modulate.a=0`, which still draws and still takes input.
- **`clip_contents`:** clips children's drawing and input (Control reference). UNVERIFIED: whether it splits 2D batches in 4.x RD renderers.
- **Text updates:** do not rebuild a RichTextLabel every frame; use `append_text`, or `threaded` for long logs.
- **Measuring:** the Visual Profiler, plus `Performance.get_monitor(Performance.OBJECT_NODE_COUNT)` and `RENDER_TOTAL_DRAW_CALLS_IN_FRAME`.

## 10. Separating UI from game state

- **Official guidance:** a signal "should be used only to 'respond' to behavior, not start it"; methods start behaviour. Scenes should have no outside dependencies; use dependency injection. A common ancestor mediates between siblings. https://docs.godotengine.org/en/4.7/tutorials/best_practices/scene_organization.html
- **MVVM-like pattern:**
  - The model is a typed `Resource` or a plain object that emits `changed` or specific signals.
  - The view (Control scene) gets the model injected through a `bind(model)` method, reads it, and never mutates it directly.
  - User actions go out as view signals, or as calls on a controller or presenter.
  - Text comes from `tr()` keys; numbers are formatted in the view.
- **Payoff:** the view can be tested by feeding a fake model, and the game logic can be tested headless with no UI.

## 11. Testing UI headless

```gdscript
extends SceneTree
func _initialize() -> void:
    var ui: Control = load("res://ui/pause_menu.tscn").instantiate()
    root.add_child(ui)
    await process_frame; await process_frame          # container sort is deferred
    var ok := ui.get_viewport().gui_get_focus_owner() == ui.get_node("%Resume")
    var ev := InputEventAction.new(); ev.action = "ui_down"; ev.pressed = true
    root.push_input(ev)
    await process_frame
    ok = ok and root.gui_get_focus_owner() == ui.get_node("%Settings")
    ok = ok and root.get_visible_rect().encloses(ui.get_node("%Resume").get_global_rect())
    print("UI_SUMMARY ok=%s" % ok); quit(0 if ok else 1)
```

- **Signals:** connect a lambda counter, then emit through `button.pressed.emit()` or a real `InputEventMouseButton` sent via `push_input` at `get_global_rect().get_center()`.
- UNVERIFIED: that `--headless` computes font metrics and Container layout exactly as native rendering does. 06-ui-ux.md found that the Dummy renderer differs for MultiMesh. Assert the root viewport size first, and run layout matrices natively or under Xvfb.

## Version-specific features

| Feature                                                                                                                        | Version | Source                                                                 |
| ------------------------------------------------------------------------------------------------------------------------------ | ------- | ---------------------------------------------------------------------- |
| `display/window/stretch/scale_mode` (integer)                                                                                  | 4.2     | multiple_resolutions (4.7 docs)                                        |
| 2D batching on Forward+/Mobile                                                                                                 | 4.4     | releases/4.4, GH-92797                                                 |
| AccessKit screen reader, `accessibility_*`, `FOCUS_ACCESSIBILITY` (experimental)                                               | 4.5     | releases/4.5; 4.6 class docs                                           |
| FoldableContainer                                                                                                              | 4.5     | releases/4.5                                                           |
| `focus_behavior_recursive` / `mouse_behavior_recursive`                                                                        | 4.5     | releases/4.5                                                           |
| Label stacked outline and shadow effects                                                                                       | 4.5     | releases/4.5                                                           |
| DPITexture (runtime SVG re-rasterisation, experimental)                                                                        | 4.5     | godotengine.org 4.5 beta 6 article                                     |
| Editor live translation preview                                                                                                | 4.5     | releases/4.5                                                           |
| `pivot_offset_ratio`                                                                                                           | 4.6     | releases/4.6                                                           |
| Mouse focus hidden; `grab_focus(hide_focus)`, `has_focus(ignore_hidden_focus)`, `gui/common/show_focus_state_on_pointer_event` | 4.6     | releases/4.6; 4.6 class docs; PR #110250/#110895 (from mirror commits) |
| CSV translations `?context` / `?plural` columns                                                                                | 4.6     | releases/4.6                                                           |
| `offset_transform_*`                                                                                                           | 4.7     | releases/4.7; PR #87081                                                |
| `custom_maximum_size`, `get_bound_minimum_size()`; autowrap needs a maximum width                                              | 4.7     | 4.7 dev 4 article, GH-116640; 4.7 Label docs                           |
| Accessibility landmark regions                                                                                                 | 4.7     | releases/4.7 (property name UNVERIFIED)                                |
| RichTextLabel `[img height=1em]`; TextureRect AtlasTexture tiling; PopupMenu search                                            | 4.7     | releases/4.7                                                           |
| `Tween.tween_await()`; `VirtualJoystick`; `DEVICE_ID_KEYBOARD/MOUSE`; ignore joypad when unfocused                             | 4.7     | releases/4.7                                                           |

UNVERIFIED: the version that introduced `LAYOUT_DIRECTION_APPLICATION_LOCALE` / `SYSTEM_LOCALE`. They are present in 4.7, and the old `LAYOUT_DIRECTION_LOCALE` is deprecated.

## Checkable rules an agent should follow

1. `project.godot` sets `display/window/stretch/mode` to `canvas_items` or `viewport`. It is not left at the default `disabled` for a game.
1. Non-pixel games use `stretch/aspect="expand"`. Pixel-art games set `scale_mode="integer"`.
1. `gui/theme/custom` points to an existing `.tres` theme.
1. No `.gd` file outside the theme or token builder contains `Color(` literals or `add_theme_*_override` with literal values for player-facing UI.
1. No child of a Container node in a `.tscn` sets `position`, `rotation` or `scale`. Animations target `offset_transform_*` or `modulate`.
1. Every Label with `autowrap_mode != 0` has a width source on 4.7: its own `custom_maximum_size.x > 0`, or an ancestor's.
1. Every interactive scene sets initial focus (a `grab_focus` call, deferred or in `_ready`) on a visible control.
1. Every `Button`/`BaseButton` in a menu scene keeps `focus_mode` 2 (the default) unless it has `FOCUS_NONE` plus a keyboard alternative.
1. Full-rect HUD roots and decorative `TextureRect`/`ColorRect`/`Label` nodes set `mouse_filter = 2` (IGNORE).
1. Gameplay scripts do not read `ui_accept`, `ui_cancel` or `ui_*` actions; they use their own actions.
1. Every `InputMap` action used in gameplay has both a keyboard and a joypad event.
1. A remapping screen exists if the game has more than a handful of actions, and it saves to `user://`.
1. Font sizes in Theme, LabelSettings and overrides are at least 18 px at a 1080p base (XAG 101, PC), or at least 26 px for console or TV.
1. A UI-scale setting writes `content_scale_factor`. Nothing tries to change `default_theme_scale` at runtime.
1. `RichTextLabel` text is never built with `text +=` while BBCode is on.
1. Every `create_tween()` used on a pause menu sets `TWEEN_PAUSE_PROCESS`, and no Tween is stored and replayed.
1. Pause-menu roots have `process_mode` = ALWAYS (3).
1. Player-facing strings go through `tr()` keys, and `.tscn` `text=` values are keys.
1. Icon-only buttons set `accessibility_name` (4.5+) and a tooltip.
1. A state that colour conveys also has an icon, shape or text difference: the theme variation differs in more than `font_color`.
1. Long lists of more than about 100 rows use ItemList, Tree or a pooled view, not one Button per row.
1. Exports that ship CJK or Thai text have "Include Text Server Data" on, and fonts have fallbacks for every shipped locale.
1. SubViewport-based 3D UI forwards input with `push_input`, and its SubViewport has an explicit `render_target_update_mode`.

## What a tool could check automatically

**Static checks on `project.godot`** (an INI-like file; Python `configparser` needs care):

- The stretch mode, aspect, scale mode, `allow_hidpi` and `gui/theme/custom` exist and are sensible.
- `accessibility/general/accessibility_support` is not 2.
- `internationalization/locale/test` is empty before commit.

**`.tscn` scan** (parse `[node ... parent=...]` blocks into a tree):

- A Container child carries a `position=`, `rotation=` or `scale=` key.
- An autowrapping Label has no maximum width (4.7).
- A full-rect Control (`anchors_preset = 15`) with no input role has a `mouse_filter` other than 2.
- A Button has `focus_mode = 0`.
- A TextureButton has no `accessibility_name`.
- Literal `text = "..."` values are not translation keys.
- A `theme_type_variation` value is missing from the project theme.

**`.tres` theme scan:**

- Collect `font_size` and `default_font_size` values below a threshold.
- Check that each `Button` type has a `focus` StyleBox, and that it is not `StyleBoxEmpty`.
- Compute WCAG contrast of `font_color` against StyleBoxFlat `bg_color` pairs per type, against 4.5:1.

**`.gd` grep:**

- `Color(` literals in UI scripts.
- `\.text\s*\+=` on RichTextLabel.
- `Input.is_action_.*"ui_` outside UI scripts.
- `create_tween()` without `set_pause_mode` in files under `pause`.
- `grab_focus()` absent in scenes that contain Buttons.

**`InputMap` audit:** each `[input]` action has an `InputEventKey` and an `InputEventJoypadButton` or `InputEventJoypadMotion`.

**Runtime probe** (headless, then native or Xvfb), across a resolution matrix of 1280×720, 1280×800, 1920×1080, 2560×1080, 3440×1440 and 3840×2160, plus a pseudolocale (`internationalization/pseudolocalization/use_pseudolocalization`). Dump every visible Control as JSON: class, path, `global_rect`, focus mode, `mouse_filter`, effective font size, line count and clipped flag. Then assert:

- No rect falls outside the viewport.
- No interactive rect is below 32×32 px.
- No overlapping interactive siblings.
- The focus walk with `ui_down`/`ui_focus_next` visits every focusable control and returns to the start.
- The focus owner after open is not null.
- Print one summary line for the log-based verdict.

**Accessibility probe:** with support forced on, list focusable Controls that have empty `accessibility_name` and no visible text. UNVERIFIED: whether the AccessKit tree can be queried from GDScript.

## Pitfalls

- **Container resets:** positions and scales set on Container children are wiped on the next re-sort. Tweens on `position` look fine until a resize, then snap back.
- **Layout timing:** reading `size` or `global_rect` in `_ready` before the deferred sort gives stale values. Await one or two `process_frame`.
- **Autowrap without width:** on 4.7, an autowrapping Label or `fit_content` RichTextLabel without a maximum width (own or inherited) lays out wrongly.
- **Theme scale:** `default_theme_scale` cannot change at runtime. A UI-scale slider must use `content_scale_factor`.
- **Focus on 4.6+:**
  - `grab_focus()` after a mouse click does not show a ring by default.
  - Code that reads `has_focus(true)` treats hidden focus as no focus.
  - A forum report says `grab_focus()` seemed ineffective on LineEdit under some values of the setting. UNVERIFIED, single forum source.
- **`modulate.a = 0`** still blocks clicks. Use `visible = false` or `mouse_filter = IGNORE`.
- **Paused tree:** menus without `PROCESS_MODE_ALWAYS` freeze, and tweens stop unless set to `TWEEN_PAUSE_PROCESS`.
- **Reusing Tweens** is undefined behaviour. Looping tweens without `bind_node` keep running after the node is freed.
- **MSDF at small sizes** looks soft. Use regular rasterised fonts for body text under about 16 px.
- **Font coverage:** a missing fallback renders tofu. SystemFont metrics differ per OS. Emoji COLR fonts are unsupported.
- **ICU data** is not exported by default, so line breaking breaks for languages without spaces.
- **Screen readers** are experimental (4.5–4.7). A decorative Control can be announced; one forum report concerns a TextureRect cursor. Test with Narrator, VoiceOver or Orca.
- **Headless runs** may not reflect native rendering, so judge layout screenshots natively.
- **Pixel UI:** fractional scaling blurs it. Use `scale_mode=integer` and Nearest filtering.

## Risks and gaps

- 4.7 tutorial pages lag behind the class reference; the custom GUI controls page is marked "not yet updated for 4.7".
- PR numbers #110250, #110895 and #87081 come from mirror commits; the upstream GitHub pages were not opened.
- The 4.3 and 4.4 release pages were truncated in fetches, so smaller UI items from those versions may be missing from the table.

CONFLICT DETECTED: the 4.6 Label docs have no width requirement for autowrap; the 4.7 Label docs require a custom maximum width. This is a behaviour or documentation change at the 4.7 boundary.

UNVERIFIED claims, collected:

- Safe-area platform coverage.
- The values of `accessibility_support`.
- The class and name of `accessibility_region`.
- Whether `clip_contents` breaks batching.
- Headless layout parity with native.
- The 4.7 state of the `gui_in_3d` demo.
- When `LAYOUT_DIRECTION_*_LOCALE` was introduced.

## Sources

- https://godotengine.org/releases/4.5/ : AccessKit, FoldableContainer, recursive focus and mouse behaviour, Label effects
- https://godotengine.org/releases/4.6/ : `pivot_offset_ratio`, mouse/keyboard focus split, CSV `?context`/`?plural`
- https://godotengine.org/releases/4.7/ : offset transforms, landmarks, RichTextLabel img sizing, `tween_await`, VirtualJoystick, device IDs
- https://godotengine.org/releases/4.4/ : 2D batching
- https://godotengine.org/article/dev-snapshot-godot-4-7-dev-4/ : `custom_maximum_size` (GH-116640)
- https://godotengine.org/article/dev-snapshot-godot-4-5-beta-6/ : DPITexture rename, experimental status
- https://docs.godotengine.org/en/4.7/classes/class_control.html and https://docs.godotengine.org/en/4.6/classes/class_control.html : properties, enums, focus API
- https://docs.godotengine.org/en/4.7/classes/class_label.html and https://docs.godotengine.org/en/4.6/classes/class_label.html : autowrap note
- https://docs.godotengine.org/en/4.7/classes/class_richtextlabel.html, https://docs.godotengine.org/en/4.7/classes/class_tween.html, https://docs.godotengine.org/en/4.7/classes/class_projectsettings.html, https://docs.godotengine.org/en/4.7/classes/class_displayserver.html
- https://docs.godotengine.org/en/4.7/tutorials/ui/size_and_anchors.html, https://docs.godotengine.org/en/4.7/tutorials/ui/gui_containers.html, https://docs.godotengine.org/en/4.7/tutorials/ui/gui_skinning.html, https://docs.godotengine.org/en/4.7/tutorials/ui/gui_using_fonts.html, https://docs.godotengine.org/en/4.7/tutorials/ui/gui_navigation.html
- https://docs.godotengine.org/en/4.7/tutorials/rendering/multiple_resolutions.html, https://docs.godotengine.org/en/4.7/tutorials/rendering/viewports.html, https://docs.godotengine.org/en/4.7/tutorials/i18n/internationalizing_games.html, https://docs.godotengine.org/en/4.7/tutorials/best_practices/scene_organization.html
- https://learn.microsoft.com/en-us/gaming/accessibility/xbox-accessibility-guidelines/101 : text size and spacing (updated 2026-06)
- https://gameaccessibilityguidelines.com/full-list/ : basic, intermediate and advanced guidelines
- https://partner.steamgames.com/doc/steamdeck/compat : Deck resolution, 9/12 px text, glyphs, on-screen keyboard
- https://heise.de/-10651078 : 4.5 accessibility status quote (secondary, dated Sept 2025)
- Mirrors, lower confidence: remotebranch.eu and git.objectionable.solutions commits for PRs #110250, #110895, #87081 and the accessibility region commit
- https://github.com/godotengine/godot-demo-projects : `viewport/gui_in_3d` (not opened)
