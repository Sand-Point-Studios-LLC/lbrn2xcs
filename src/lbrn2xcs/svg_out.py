"""SVG emitter.

Writes one ``<g>`` per LightBurn layer, stroked in that layer's palette colour,
so LightBurn's layer structure survives the trip into XCS (which keys its own
layers off stroke colour on import).

Coordinates are baked, not left to a wrapper transform: LightBurn is Y-up and
SVG is Y-down, so every point is flipped about the drawing's bounding box and
shifted to start at (0, 0). The result is a tight document whose user units are
millimetres, with an explicit ``mm`` width/height so importers pick up real-world
scale instead of guessing at 96 dpi.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from .model import Contour, Project

# Hairline stroke: thin enough not to imply a cut width, thick enough to see.
STROKE_WIDTH_MM = 0.1
PAD_MM = 0.0


def _num(v: float) -> str:
    """Compact fixed-precision number — 4dp is well under laser resolution."""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def contour_to_path_data(contour: Contour, flip_y: float, off_x: float = 0.0) -> str:
    """Serialise one contour as SVG path data, flipping Y about *flip_y*."""

    def pt(p: tuple[float, float]) -> str:
        return f"{_num(p[0] - off_x)},{_num(flip_y - p[1])}"

    parts = [f"M{pt(contour.start)}"]
    for seg in contour.segments:
        if seg.kind == "C" and seg.c1 and seg.c2:
            parts.append(f"C{pt(seg.c1)} {pt(seg.c2)} {pt(seg.end)}")
        else:
            parts.append(f"L{pt(seg.end)}")
    if contour.closed:
        parts.append("Z")
    return "".join(parts)


def project_to_svg(project: Project, *, title: str = "") -> str:
    """Render a parsed project as an SVG document string."""
    min_x, min_y, max_x, max_y = project.bbox()
    width = max(max_x - min_x, 0.0) + 2 * PAD_MM
    height = max(max_y - min_y, 0.0) + 2 * PAD_MM
    # Flip about the bbox: y_out = max_y - y  (plus padding, minus min_x on X).
    flip_y = max_y + PAD_MM
    off_x = min_x - PAD_MM

    by_layer = project.shapes_by_layer()

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" version="1.1"'
        f' width="{_num(width)}mm" height="{_num(height)}mm"'
        f' viewBox="0 0 {_num(width)} {_num(height)}">',
    ]
    if title:
        lines.append(f"  <title>{escape(title)}</title>")

    for index in sorted(by_layer):
        layer = project.layers.get(index)
        color = layer.color if layer else "#000000"
        name = layer.display_name if layer else f"C{index:02d}"
        lines.append(
            f'  <g id="C{index:02d}" inkscape:label="{escape(name)}"'
            f' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"'
            f' fill="none" stroke="{color}" stroke-width="{_num(STROKE_WIDTH_MM)}">'
        )
        for shape in by_layer[index]:
            for contour in shape.contours:
                d = contour_to_path_data(contour, flip_y, off_x)
                if d:
                    lines.append(f'    <path d="{d}"/>')
        lines.append("  </g>")

    lines.append("</svg>")
    return "\n".join(lines) + "\n"
