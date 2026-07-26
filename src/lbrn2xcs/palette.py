"""Colour palettes for LightBurn layers and XCS layers.

LightBurn identifies a layer by its index (``CutIndex``) and paints it with a
fixed 30-entry palette (C00–C29) plus two tool layers. XCS has its own, much
smaller named palette; when it imports an SVG it snaps stroke colours onto that
palette, so the ``.xcs`` writer maps LightBurn indices onto XCS layer colours
rather than carrying LightBurn's hexes across.
"""

from __future__ import annotations

# LightBurn C00–C29, in index order. Confirmed against the LightBurn UI palette;
# index 28 (#86FA88) also shows up as `originColor` in LightBurn-exported art
# re-opened in XCS, which is a useful cross-check.
LIGHTBURN_COLORS: tuple[str, ...] = (
    "#000000",  # C00 black
    "#0000FF",  # C01 blue
    "#FF0000",  # C02 red
    "#00E000",  # C03 green
    "#D0D000",  # C04 yellow
    "#FF8000",  # C05 orange
    "#00E0E0",  # C06 cyan
    "#FF00FF",  # C07 magenta
    "#B4B4B4",  # C08 light grey
    "#0000A0",  # C09 dark blue
    "#A00000",  # C10 dark red
    "#00A000",  # C11 dark green
    "#A0A000",  # C12 dark yellow
    "#C08000",  # C13 dark orange
    "#00A0FF",  # C14
    "#A000A0",  # C15
    "#808080",  # C16 grey
    "#7D87B9",  # C17
    "#BB7784",  # C18
    "#4A6FE3",  # C19
    "#D33F6A",  # C20
    "#8CD78C",  # C21
    "#F0B98D",  # C22
    "#F6C4E1",  # C23
    "#FA9ED4",  # C24
    "#500A78",  # C25
    "#B45A00",  # C26
    "#004754",  # C27
    "#86FA88",  # C28
    "#FFDB66",  # C29
)

TOOL_LAYER_COLOR = "#FFFFFF"  # T1/T2 tool layers (index 30/31) — no output


def lightburn_color(cut_index: int) -> str:
    """Palette colour for a LightBurn ``CutIndex``."""
    if 0 <= cut_index < len(LIGHTBURN_COLORS):
        return LIGHTBURN_COLORS[cut_index]
    return TOOL_LAYER_COLOR


def lightburn_layer_name(cut_index: int) -> str:
    """LightBurn's own label for an index: ``C00``…``C29``, ``T1``, ``T2``."""
    if 0 <= cut_index < len(LIGHTBURN_COLORS):
        return f"C{cut_index:02d}"
    return f"T{cut_index - len(LIGHTBURN_COLORS) + 1}"


# XCS's layer palette, as observed in real .xcs files. XCS names layers with
# i18n placeholders ("{Black}") which the UI renders as the localised colour
# name. Order matters: LightBurn indices are assigned round-robin over this.
XCS_LAYER_COLORS: tuple[tuple[str, str], ...] = (
    ("#000000", "{Black}"),
    ("#fe0002", "{Red}"),
    ("#00c715", "{Green}"),
    ("#2366ff", "{Blue}"),
    ("#e1c000", "{Yellow}"),
    ("#ff7f56", "{Orange}"),
    ("#a958ff", "{Purple}"),
    ("#00befe", "{Cyan}"),
)


def xcs_layer(slot: int) -> tuple[str, str]:
    """(hex, name) for the *slot*-th XCS layer, wrapping around the palette."""
    return XCS_LAYER_COLORS[slot % len(XCS_LAYER_COLORS)]
