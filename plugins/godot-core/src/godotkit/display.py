"""Picks the display a native (rendering) Godot run uses, or says plainly that there is none."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass

# Large enough that no requested window size is clamped by the virtual screen.
XVFB_SCREEN = "-screen 0 3840x2160x24"


class NoDisplay(RuntimeError):
    """No desktop display and no xvfb-run: a native run cannot start, so it must not pass."""


@dataclass(frozen=True)
class NativeDisplay:
    name: str
    args: tuple[str, ...]
    wrapper: tuple[str, ...] = ()


def find_display(
    env: Mapping[str, str], which: Callable[[str], str | None] = shutil.which
) -> NativeDisplay:
    # Godot's default driver choice picked Wayland and died on AloneGodot (research 05), so name it.
    sound = ("--audio-driver", "Dummy")
    if env.get("DISPLAY"):
        return NativeDisplay(f"x11 {env['DISPLAY']}", ("--display-driver", "x11", *sound))
    if env.get("WAYLAND_DISPLAY"):
        # UNTESTED: no Wayland-only session was available on 4.7.2.
        name = f"wayland {env['WAYLAND_DISPLAY']}"
        return NativeDisplay(name, ("--display-driver", "wayland", *sound))
    xvfb = which("xvfb-run")
    if xvfb is not None:
        wrapper = (xvfb, "-a", "-s", XVFB_SCREEN)
        return NativeDisplay("xvfb-run", ("--display-driver", "x11", *sound), wrapper)
    raise NoDisplay("no DISPLAY or WAYLAND_DISPLAY and no xvfb-run on PATH")
