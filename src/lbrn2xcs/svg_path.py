"""SVG path data parsing and serialisation.

Needed in both directions: emitters serialise :class:`Contour` objects to path
data, and reading it back is how we verify our own output and decode the
``dPath`` strings inside ``.xcs`` files.

Supports the command set that actually shows up in LightBurn/XCS output —
M, L, H, V, C, S, Q, T, Z — in both absolute and relative form. Elliptical arcs
(``A``) are converted to cubics.
"""

from __future__ import annotations

import math
import re

from .model import Contour, Point, Segment

_TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)")

_ARG_COUNT = {
    "M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0
}


def _tokenize(data: str) -> list[str | float]:
    out: list[str | float] = []
    for match in _TOKEN.finditer(data):
        cmd, num = match.group(1), match.group(2)
        out.append(cmd if cmd else float(num))  # type: ignore[arg-type]
    return out


def _quad_to_cubic(p0: Point, q: Point, p1: Point) -> tuple[Point, Point]:
    """Exact cubic equivalent of a quadratic bezier."""
    return (
        (p0[0] + 2.0 / 3.0 * (q[0] - p0[0]), p0[1] + 2.0 / 3.0 * (q[1] - p0[1])),
        (p1[0] + 2.0 / 3.0 * (q[0] - p1[0]), p1[1] + 2.0 / 3.0 * (q[1] - p1[1])),
    )


def _arc_to_cubics(
    p0: Point, rx: float, ry: float, rotation: float, large_arc: bool, sweep: bool, p1: Point
) -> list[tuple[Point, Point, Point]]:
    """Endpoint-parameterised elliptical arc -> cubic segments (SVG F.6.5)."""
    if rx == 0 or ry == 0 or p0 == p1:
        return [] if p0 == p1 else [(p0, p1, p1)]

    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rotation)
    cos_phi, sin_phi = math.cos(phi), math.sin(phi)

    dx2, dy2 = (p0[0] - p1[0]) / 2.0, (p0[1] - p1[1]) / 2.0
    x1p = cos_phi * dx2 + sin_phi * dy2
    y1p = -sin_phi * dx2 + cos_phi * dy2

    # Scale up the radii if they cannot span the endpoints.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1:
        scale = math.sqrt(lam)
        rx, ry = rx * scale, ry * scale

    denom = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    num = max(rx * rx * ry * ry - denom, 0.0)
    coef = math.sqrt(num / denom) if denom else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp, cyp = coef * rx * y1p / ry, -coef * ry * x1p / rx

    cx = cos_phi * cxp - sin_phi * cyp + (p0[0] + p1[0]) / 2.0
    cy = sin_phi * cxp + cos_phi * cyp + (p0[1] + p1[1]) / 2.0

    def angle_of(x: float, y: float) -> float:
        return math.atan2((y - cyp) / ry, (x - cxp) / rx)

    theta1 = angle_of(x1p, y1p)
    theta2 = angle_of(-x1p, -y1p)
    delta = theta2 - theta1
    if not sweep and delta > 0:
        delta -= 2 * math.pi
    elif sweep and delta < 0:
        delta += 2 * math.pi

    steps = max(1, int(math.ceil(abs(delta) / (math.pi / 2))))
    step = delta / steps
    alpha = 4.0 / 3.0 * math.tan(step / 4.0)

    def point_at(theta: float) -> Point:
        ct, st = math.cos(theta), math.sin(theta)
        return (
            cx + rx * ct * cos_phi - ry * st * sin_phi,
            cy + rx * ct * sin_phi + ry * st * cos_phi,
        )

    def deriv_at(theta: float) -> Point:
        ct, st = math.cos(theta), math.sin(theta)
        return (
            -rx * st * cos_phi - ry * ct * sin_phi,
            -rx * st * sin_phi + ry * ct * cos_phi,
        )

    out: list[tuple[Point, Point, Point]] = []
    for i in range(steps):
        t_start = theta1 + i * step
        t_end = t_start + step
        p_start, p_end = point_at(t_start), point_at(t_end)
        d_start, d_end = deriv_at(t_start), deriv_at(t_end)
        c1 = (p_start[0] + alpha * d_start[0], p_start[1] + alpha * d_start[1])
        c2 = (p_end[0] - alpha * d_end[0], p_end[1] - alpha * d_end[1])
        out.append((c1, c2, p_end))
    return out


def parse_path_data(data: str) -> list[Contour]:
    """Parse SVG path data into contours. Unknown commands are skipped."""
    tokens = _tokenize(data)
    contours: list[Contour] = []
    current: Contour | None = None
    cursor: Point = (0.0, 0.0)
    subpath_start: Point = (0.0, 0.0)
    last_cubic_ctrl: Point | None = None
    last_quad_ctrl: Point | None = None

    i = 0
    command = ""
    while i < len(tokens):
        token = tokens[i]
        if isinstance(token, str):
            command = token
            i += 1
            if command in ("Z", "z"):
                if current is not None and current.segments:
                    current.closed = True
                    contours.append(current)
                    current = None
                cursor = subpath_start
                last_cubic_ctrl = last_quad_ctrl = None
                continue
        elif not command:
            i += 1
            continue

        upper = command.upper()
        relative = command.islower()
        need = _ARG_COUNT.get(upper, 0)
        if i + need > len(tokens):
            break
        args = tokens[i : i + need]
        if any(isinstance(a, str) for a in args):
            break
        vals: list[float] = [float(a) for a in args]  # type: ignore[arg-type]
        i += need

        def abs_pt(x: float, y: float) -> Point:
            return (cursor[0] + x, cursor[1] + y) if relative else (x, y)

        if upper == "M":
            if current is not None and current.segments:
                contours.append(current)
            cursor = abs_pt(vals[0], vals[1])
            subpath_start = cursor
            current = Contour(start=cursor)
            last_cubic_ctrl = last_quad_ctrl = None
            # A repeated coordinate pair after M means implicit L.
            command = "l" if relative else "L"
            continue

        if current is None:
            current = Contour(start=cursor)

        if upper == "L":
            cursor = abs_pt(vals[0], vals[1])
            current.segments.append(Segment("L", cursor))
            last_cubic_ctrl = last_quad_ctrl = None
        elif upper == "H":
            cursor = (cursor[0] + vals[0], cursor[1]) if relative else (vals[0], cursor[1])
            current.segments.append(Segment("L", cursor))
            last_cubic_ctrl = last_quad_ctrl = None
        elif upper == "V":
            cursor = (cursor[0], cursor[1] + vals[0]) if relative else (cursor[0], vals[0])
            current.segments.append(Segment("L", cursor))
            last_cubic_ctrl = last_quad_ctrl = None
        elif upper == "C":
            c1 = abs_pt(vals[0], vals[1])
            c2 = abs_pt(vals[2], vals[3])
            cursor = abs_pt(vals[4], vals[5])
            current.segments.append(Segment("C", cursor, c1=c1, c2=c2))
            last_cubic_ctrl, last_quad_ctrl = c2, None
        elif upper == "S":
            c1 = (
                (2 * cursor[0] - last_cubic_ctrl[0], 2 * cursor[1] - last_cubic_ctrl[1])
                if last_cubic_ctrl
                else cursor
            )
            c2 = abs_pt(vals[0], vals[1])
            cursor = abs_pt(vals[2], vals[3])
            current.segments.append(Segment("C", cursor, c1=c1, c2=c2))
            last_cubic_ctrl, last_quad_ctrl = c2, None
        elif upper == "Q":
            q = abs_pt(vals[0], vals[1])
            end = abs_pt(vals[2], vals[3])
            c1, c2 = _quad_to_cubic(cursor, q, end)
            current.segments.append(Segment("C", end, c1=c1, c2=c2))
            cursor, last_quad_ctrl, last_cubic_ctrl = end, q, c2
        elif upper == "T":
            q = (
                (2 * cursor[0] - last_quad_ctrl[0], 2 * cursor[1] - last_quad_ctrl[1])
                if last_quad_ctrl
                else cursor
            )
            end = abs_pt(vals[0], vals[1])
            c1, c2 = _quad_to_cubic(cursor, q, end)
            current.segments.append(Segment("C", end, c1=c1, c2=c2))
            cursor, last_quad_ctrl, last_cubic_ctrl = end, q, c2
        elif upper == "A":
            end = abs_pt(vals[5], vals[6])
            for c1, c2, stop in _arc_to_cubics(
                cursor, vals[0], vals[1], vals[2], bool(vals[3]), bool(vals[4]), end
            ):
                current.segments.append(Segment("C", stop, c1=c1, c2=c2))
            cursor = end
            last_cubic_ctrl = last_quad_ctrl = None

    if current is not None and current.segments:
        contours.append(current)
    return contours


def format_number(value: float, precision: int = 4) -> str:
    text = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def contour_to_path_data(
    contour: Contour,
    *,
    precision: int = 4,
    transform=None,
) -> str:
    """Serialise a contour. *transform* maps a point to output space if given."""

    def pt(p: Point) -> str:
        if transform is not None:
            p = transform(p)
        return f"{format_number(p[0], precision)},{format_number(p[1], precision)}"

    parts = [f"M{pt(contour.start)}"]
    for seg in contour.segments:
        if seg.kind == "C" and seg.c1 and seg.c2:
            parts.append(f"C{pt(seg.c1)} {pt(seg.c2)} {pt(seg.end)}")
        else:
            parts.append(f"L{pt(seg.end)}")
    if contour.closed:
        parts.append("Z")
    return "".join(parts)


def contours_bbox(contours: list[Contour]) -> tuple[float, float, float, float]:
    """Tight bbox over contours, using true bezier extrema."""
    xs: list[float] = []
    ys: list[float] = []
    for contour in contours:
        for x, y in contour.extent_points():
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))
