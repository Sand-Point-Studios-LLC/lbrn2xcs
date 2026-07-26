"""DXF emitter.

One DXF layer per LightBurn layer, named ``C00 <layer name>`` and coloured with
the LightBurn palette colour as an RGB true-colour so the layer identity survives
in any CAD tool. Beziers are flattened to polylines, since plain LWPOLYLINE has
no cubic segment type and bulge-fitting an arbitrary bezier is not worth it here.

DXF is Y-up like LightBurn, so coordinates pass through unflipped — only the
translation to a (0, 0) origin is applied, matching the SVG output's framing.
"""

from __future__ import annotations

from pathlib import Path

from .model import Contour, Project

# Max distance between the true curve and the polyline that replaces it.
DEFAULT_TOLERANCE_MM = 0.05
MAX_SUBDIVISIONS = 64


def _bezier_point(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    t: float,
) -> tuple[float, float]:
    mt = 1.0 - t
    a = mt * mt * mt
    b = 3.0 * mt * mt * t
    c = 3.0 * mt * t * t
    d = t * t * t
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _bezier_steps(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    tolerance: float,
) -> int:
    """Pick a subdivision count from the control polygon's excess length.

    Cheap and conservative: the control polygon bounds the curve, so its length
    over the chord length is a fine proxy for how much bending there is.
    """

    def dist(a: tuple[float, float], b: tuple[float, float]) -> float:
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    poly = dist(p0, p1) + dist(p1, p2) + dist(p2, p3)
    chord = dist(p0, p3)
    excess = max(poly - chord, 0.0)
    if excess <= tolerance:
        return 1
    steps = int((excess / max(tolerance, 1e-9)) ** 0.5) + 2
    return min(max(steps, 2), MAX_SUBDIVISIONS)


def flatten_contour(contour: Contour, tolerance: float = DEFAULT_TOLERANCE_MM) -> list[tuple[float, float]]:
    """Contour -> plain point list, subdividing every bezier."""
    pts: list[tuple[float, float]] = [contour.start]
    for seg in contour.segments:
        if seg.kind == "C" and seg.c1 and seg.c2:
            p0 = pts[-1]
            steps = _bezier_steps(p0, seg.c1, seg.c2, seg.end, tolerance)
            for i in range(1, steps + 1):
                pts.append(_bezier_point(p0, seg.c1, seg.c2, seg.end, i / steps))
        else:
            pts.append(seg.end)
    # Drop a duplicated closing point; DXF closes the polyline via a flag.
    if contour.closed and len(pts) > 1:
        first, last = pts[0], pts[-1]
        if abs(first[0] - last[0]) < 1e-9 and abs(first[1] - last[1]) < 1e-9:
            pts.pop()
    return pts


def _nearest_aci(rgb: tuple[int, int, int]) -> int:
    """Closest AutoCAD Colour Index to *rgb*.

    True colour needs DXF R2004+, and plenty of laser software still reads only
    the ACI index, so both get set. Indices 1–255 only; 0 and 256 are BYBLOCK
    and BYLAYER.
    """
    from ezdxf import colors as ezcolors

    # ACI 7 is the conventional black-or-white entry (it renders as whichever
    # contrasts with the background), so nearest-RGB is the wrong answer there.
    if rgb in ((0, 0, 0), (255, 255, 255)):
        return 7

    best, best_dist = 7, None
    for aci in range(1, 256):
        try:
            candidate = ezcolors.aci2rgb(aci)
        except Exception:  # noqa: BLE001 — a few indices are unmapped
            continue
        dist = sum((a - b) ** 2 for a, b in zip(candidate, rgb))
        if best_dist is None or dist < best_dist:
            best, best_dist = aci, dist
    return best


def _dxf_layer_name(index: int, name: str) -> str:
    """DXF layer names disallow a handful of characters; keep it tidy."""
    clean = "".join(ch for ch in name if ch not in '<>/\\":;?*|=`,').strip()
    label = f"C{index:02d}"
    return f"{label} {clean}"[:255] if clean and clean != label else label


def write_dxf(
    project: Project,
    path: Path,
    *,
    tolerance: float = DEFAULT_TOLERANCE_MM,
) -> None:
    """Write *project* to *path* as DXF (R2000, millimetres)."""
    import ezdxf  # imported lazily so SVG-only use needs no DXF dependency

    min_x, min_y, _, _ = project.bbox()

    # R2010 rather than R2000: true-colour layers only exist from R2004 onward.
    doc = ezdxf.new("R2010", setup=False)
    doc.header["$INSUNITS"] = 4  # millimetres
    msp = doc.modelspace()

    by_layer = project.shapes_by_layer()
    for index in sorted(by_layer):
        layer = project.layers.get(index)
        color = layer.color if layer else "#000000"
        name = _dxf_layer_name(index, layer.display_name if layer else "")
        rgb = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))
        dxf_layer = doc.layers.add(name)
        dxf_layer.rgb = rgb
        dxf_layer.color = _nearest_aci(rgb)

        for shape in by_layer[index]:
            for contour in shape.contours:
                pts = [(x - min_x, y - min_y) for x, y in flatten_contour(contour, tolerance)]
                if len(pts) < 2:
                    continue
                msp.add_lwpolyline(
                    pts,
                    format="xy",
                    close=contour.closed,
                    dxfattribs={"layer": name},
                )

    doc.saveas(path)
