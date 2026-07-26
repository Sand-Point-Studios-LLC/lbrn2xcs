"""Generate a known-geometry SVG for reverse-engineering the .xcs format.

Every element here has exact, hand-chosen millimetre coordinates, so importing
this into XCS and saving a ``.xcs`` gives us a Rosetta Stone: whatever numbers
XCS writes for these shapes tell us how its ``x``/``y``/``scale``/``offsetX``/
``graphicX``/``skew`` fields relate to real-world position and size, and how it
snaps stroke colours onto its own layer palette.

The shapes are deliberately asymmetric — the corner marker and the L-bracket pin
down the origin and rule out mirroring, which a symmetric test pattern can't.

Usage:
    python tools/make_probe_svg.py [out_dir]        # default: samples/probe
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DOC_W_MM = 200.0
DOC_H_MM = 120.0

# name, stroke, svg element, human-readable description of the exact geometry
PROBES: list[tuple[str, str, str, str]] = [
    (
        "origin_marker",
        "#000000",
        '<rect x="0" y="0" width="5" height="5"/>',
        "5x5mm square flush in the SVG top-left corner (0,0)",
    ),
    (
        "rect_100x50",
        "#000000",
        '<rect x="10" y="10" width="100" height="50"/>',
        "100x50mm rect, top-left at (10,10), centre at (60,35)",
    ),
    (
        "circle_r20",
        "#fe0002",
        '<circle cx="150" cy="35" r="20"/>',
        "circle r=20mm centred at (150,35)",
    ),
    (
        "l_bracket",
        "#2366ff",
        '<path d="M10,110 L10,80 L40,80"/>',
        "open L: (10,110) -> (10,80) -> (40,80); vertical leg 30mm, horizontal 30mm",
    ),
    (
        "bezier",
        "#00c715",
        '<path d="M60,110 C80,70 110,110 130,80"/>',
        "one cubic bezier: start (60,110) ctrl (80,70) & (110,110) end (130,80)",
    ),
    (
        "square_20_rotated",
        "#e1c000",
        '<rect x="160" y="90" width="20" height="20" transform="rotate(30 170 100)"/>',
        "20x20mm square centred (170,100), rotated 30 deg clockwise in SVG space",
    ),
]


def build_svg() -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1"'
        f' width="{DOC_W_MM}mm" height="{DOC_H_MM}mm"'
        f' viewBox="0 0 {DOC_W_MM} {DOC_H_MM}">',
        "  <title>lbrn2xcs XCS format probe</title>",
        f"  <!-- Document is exactly {DOC_W_MM}mm x {DOC_H_MM}mm. User units are mm. -->",
    ]
    for name, stroke, element, note in PROBES:
        lines.append(f"  <!-- {name}: {note} -->")
        lines.append(
            f'  <g id="{name}" fill="none" stroke="{stroke}" stroke-width="0.1">'
            f"{element}</g>"
        )
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def build_manifest() -> dict:
    return {
        "doc_width_mm": DOC_W_MM,
        "doc_height_mm": DOC_H_MM,
        "note": (
            "SVG coordinates are Y-down from the top-left. XCS may use a different "
            "origin/handedness; comparing these values against the saved .xcs is the "
            "whole point of this file."
        ),
        "probes": [
            {"name": n, "stroke": s, "element": e, "geometry": g} for n, s, e, g in PROBES
        ],
    }


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else Path("samples/probe")
    out_dir.mkdir(parents=True, exist_ok=True)
    svg_path = out_dir / "xcs_probe.svg"
    manifest_path = out_dir / "xcs_probe.json"
    svg_path.write_text(build_svg(), encoding="utf-8")
    manifest_path.write_text(json.dumps(build_manifest(), indent=2), encoding="utf-8")
    print(f"wrote {svg_path}")
    print(f"wrote {manifest_path}")
    print()
    print("Next: import xcs_probe.svg into XCS, save it as xcs_probe.xcs in the same")
    print("folder, then run: python tools/decode_xcs.py samples/probe/xcs_probe.xcs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
