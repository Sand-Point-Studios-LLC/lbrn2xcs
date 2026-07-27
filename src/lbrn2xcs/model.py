"""Geometry model shared by every emitter.

All geometry is normalised to *contours*: a start point plus a list of line
(``L``) and cubic-bezier (``C``) segments, in absolute project millimetres.
Both SVG path data (``d=``) and XCS ``dPath`` are direct serialisations of this,
and DXF polylines fall out of flattening the beziers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

Point = tuple[float, float]

# Affine transform in SVG matrix(a, b, c, d, e, f) convention:
#   x' = a*x + c*y + e
#   y' = b*x + d*y + f
Matrix = tuple[float, float, float, float, float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def mat_mul(outer: Matrix, inner: Matrix) -> Matrix:
    """Return ``outer ∘ inner`` — apply *inner* first, then *outer*."""
    oa, ob, oc, od, oe, of = outer
    ia, ib, ic, id_, ie, if_ = inner
    return (
        oa * ia + oc * ib,
        ob * ia + od * ib,
        oa * ic + oc * id_,
        ob * ic + od * id_,
        oa * ie + oc * if_ + oe,
        ob * ie + od * if_ + of,
    )


def apply(m: Matrix, p: Point) -> Point:
    a, b, c, d, e, f = m
    x, y = p
    return (a * x + c * y + e, b * x + d * y + f)


def _cubic_at(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    mt = 1.0 - t
    a, b, c, d = mt**3, 3 * mt * mt * t, 3 * mt * t * t, t**3
    return (
        a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
        a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
    )


def _cubic_extrema(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    """Points on the cubic where either axis reaches a local extreme.

    B'(t) = 0 reduces, per axis, to the quadratic a·t² + b·t + c = 0 with
    a = p3 - 3p2 + 3p1 - p0, b = 2(p2 - 2p1 + p0), c = p1 - p0.
    """
    ts: set[float] = set()
    for axis in (0, 1):
        a = p3[axis] - 3 * p2[axis] + 3 * p1[axis] - p0[axis]
        b = 2 * (p2[axis] - 2 * p1[axis] + p0[axis])
        c = p1[axis] - p0[axis]
        if abs(a) < 1e-12:
            if abs(b) > 1e-12:
                ts.add(-c / b)
            continue
        disc = b * b - 4 * a * c
        if disc < 0:
            continue
        root = disc**0.5
        ts.add((-b + root) / (2 * a))
        ts.add((-b - root) / (2 * a))
    return [_cubic_at(p0, p1, p2, p3, t) for t in ts if 0.0 < t < 1.0]


@dataclass
class Segment:
    """A line (`kind="L"`) or cubic bezier (`kind="C"`) ending at `end`."""

    kind: str
    end: Point
    c1: Point | None = None
    c2: Point | None = None


@dataclass
class Contour:
    start: Point
    segments: list[Segment] = field(default_factory=list)
    closed: bool = False

    def points(self) -> list[Point]:
        """Every on-curve and control point."""
        pts = [self.start]
        for s in self.segments:
            if s.c1:
                pts.append(s.c1)
            if s.c2:
                pts.append(s.c2)
            pts.append(s.end)
        return pts

    def mapped(self, fn: Callable[[Point], Point]) -> Contour:
        """A copy with every point (on-curve and control) passed through *fn*."""
        return Contour(
            start=fn(self.start),
            segments=[
                Segment(
                    s.kind,
                    fn(s.end),
                    c1=fn(s.c1) if s.c1 else None,
                    c2=fn(s.c2) if s.c2 else None,
                )
                for s in self.segments
            ],
            closed=self.closed,
        )

    def extent_points(self) -> list[Point]:
        """On-curve points plus each bezier's true extrema.

        Control points sit *outside* the curve they shape, so using them for a
        bounding box inflates it — enough to leave visible slack around the art.
        Solving for the points where each cubic's derivative vanishes gives the
        exact extent instead.
        """
        pts: list[Point] = [self.start]
        cursor = self.start
        for s in self.segments:
            if s.kind == "C" and s.c1 and s.c2:
                pts.extend(_cubic_extrema(cursor, s.c1, s.c2, s.end))
            pts.append(s.end)
            cursor = s.end
        return pts


@dataclass
class Layer:
    """A LightBurn ``<CutSetting>`` — one cut/engrave layer."""

    index: int
    name: str
    kind: str = "Cut"  # Cut | Scan | Image | Offset | Tool ...
    color: str = "#000000"
    max_power: float | None = None
    speed: float | None = None
    num_passes: int = 1
    output: bool = True
    hidden: bool = False
    priority: int = 0
    interval: float | None = None
    """Raster line spacing in mm (fill layers only)."""
    kerf: float = 0.0
    """Kerf compensation in mm."""

    @property
    def display_name(self) -> str:
        return self.name or f"C{self.index:02d}"


@dataclass
class Shape:
    """One drawable LightBurn shape, flattened into world-space contours."""

    cut_index: int
    kind: str
    contours: list[Contour] = field(default_factory=list)


@dataclass
class Project:
    source: str = ""
    app_version: str = ""
    layers: dict[int, Layer] = field(default_factory=dict)
    shapes: list[Shape] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    """Shape types we could not convert, e.g. ``{"Text": 3, "Bitmap": 1}``."""

    def bbox(self) -> tuple[float, float, float, float]:
        """Tight (min_x, min_y, max_x, max_y) over all geometry; zeros if empty."""
        xs: list[float] = []
        ys: list[float] = []
        for shape in self.shapes:
            for contour in shape.contours:
                for x, y in contour.extent_points():
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return (0.0, 0.0, 0.0, 0.0)
        return (min(xs), min(ys), max(xs), max(ys))

    def used_layers(self) -> list[Layer]:
        """Layers that actually have geometry, in index order."""
        used = {s.cut_index for s in self.shapes if s.contours}
        return [self.layers[i] for i in sorted(used) if i in self.layers]

    def shapes_by_layer(self) -> dict[int, list[Shape]]:
        out: dict[int, list[Shape]] = {}
        for shape in self.shapes:
            if shape.contours:
                out.setdefault(shape.cut_index, []).append(shape)
        return out
