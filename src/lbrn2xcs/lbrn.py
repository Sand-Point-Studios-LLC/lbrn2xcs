"""Parser for LightBurn ``.lbrn`` / ``.lbrn2`` project files.

LightBurn files are XML. The parts that matter:

* ``<CutSetting type="Cut">`` blocks — one per layer, keyed by ``<index Value>``.
  ``CutSetting_Img`` is the image-layer variant.
* ``<Shape Type="...">`` elements with an optional ``<XForm>`` (a 2x3 affine
  matrix, SVG ``matrix()`` order) and type-specific geometry.
* ``<Shape Type="Group">`` nests more shapes under ``<Children>``; transforms
  compose down the tree.

``Path`` geometry is the interesting one. ``<VertList>`` is a run-together
sequence of ``V<x> <y>`` vertices, each optionally carrying bezier handles as
``c0x``/``c0y`` and ``c1x``/``c1y``, in absolute local coordinates. ``c0`` is the
*outgoing* handle (pointing at the next vertex) and ``c1`` the *incoming* one
(pointing back at the previous vertex) — verified by checking that a vertex's
``c0`` lands near the following vertex. A handle only counts when *both* of its
components are present; LightBurn writes a bare ``c0x1`` as a "no handle here"
placeholder.

``<PrimList>`` then wires the vertices together: ``L<i> <j>`` for a line,
``B<i> <j>`` for a cubic bezier from *i* to *j* whose control points are *i*'s
outgoing handle and *j*'s incoming handle. The shorthand ``LineClosed`` means
"join every vertex in order with lines and close the loop".

Repeated geometry is stored once: a shape carries ``VertID``/``PrimID``, and only
the *first* shape using a given id writes out the actual ``<VertList>``/
``<PrimList>``. Later shapes reference the id with no geometry of their own and
differ only by ``<XForm>``. In this corpus that's 201k vertex lists serving 1.4M
paths, so resolving those references is not optional.

``Text`` shapes are converted through their ``<BackupPath>`` — LightBurn keeps a
vectorised copy of the rendered glyphs there, which sidesteps font handling
entirely.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from .model import IDENTITY, Contour, Layer, Matrix, Project, Segment, Shape, apply, mat_mul
from .palette import lightburn_color, lightburn_layer_name

# Circular arc → cubic bezier magic constant.
KAPPA = 4.0 / 3.0 * (math.sqrt(2.0) - 1.0)

_VERT_RE = re.compile(
    r"V\s*(-?[\d.eE+]+)\s+(-?[\d.eE+]+)"  # vertex x y
    r"((?:c[01][xy]-?[\d.eE+]+)*)"  # trailing handle tokens
)
_HANDLE_RE = re.compile(r"c([01])([xy])(-?[\d.eE+]+)")
_PRIM_RE = re.compile(r"([LB])\s*(\d+)\s+(\d+)")

# Raster / generated shape types we cannot turn into vectors here. QrCode would
# need a QR encoder to regenerate its modules; Bitmap is pixels, not geometry.
UNSUPPORTED = frozenset({"Bitmap", "Image", "Photo", "QrCode"})


@dataclass
class _Vertex:
    p: tuple[float, float]
    c0: tuple[float, float] | None = None  # outgoing handle (toward next vertex)
    c1: tuple[float, float] | None = None  # incoming handle (toward previous vertex)


@dataclass
class _GeometryCache:
    """Resolves ``VertID``/``PrimID`` back-references within one document."""

    verts: dict[str, list[_Vertex]]
    prims: dict[str, str]

    @classmethod
    def from_document(cls, root: ET.Element) -> _GeometryCache:
        """Pre-scan every definition so reference order cannot matter.

        Resolving lazily during the walk assumes a ``VertID`` is always defined
        before it is used, which does not quite hold — a handful of real files
        reference an id whose ``<VertList>`` appears later, or inside a group
        visited afterwards. Collecting definitions up front (keeping the first
        for any repeated id, so document order still wins ties) makes the walk
        order-independent.
        """
        cache = cls(verts={}, prims={})
        for elem in root.iter():
            if elem.tag not in ("Shape", "BackupPath"):
                continue
            vert_id = elem.get("VertID")
            if vert_id is not None and vert_id not in cache.verts:
                node = elem.find("VertList")
                if node is not None and (node.text or "").strip():
                    cache.verts[vert_id] = parse_vertlist(node.text or "")
            prim_id = elem.get("PrimID")
            if prim_id is not None and prim_id not in cache.prims:
                node = elem.find("PrimList")
                if node is not None and (node.text or "").strip():
                    cache.prims[prim_id] = node.text or ""
        return cache

    def resolve_verts(self, elem: ET.Element) -> list[_Vertex]:
        node = elem.find("VertList")
        key = elem.get("VertID")
        if node is not None and (node.text or "").strip():
            verts = parse_vertlist(node.text or "")
            if key is not None:
                self.verts[key] = verts
            return verts
        return self.verts.get(key or "", [])

    def resolve_prims(self, elem: ET.Element) -> str:
        node = elem.find("PrimList")
        key = elem.get("PrimID")
        if node is not None and (node.text or "").strip():
            text = node.text or ""
            if key is not None:
                self.prims[key] = text
            return text
        return self.prims.get(key or "", "")


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _child_value(elem: ET.Element, tag: str) -> str | None:
    """LightBurn stores scalars as ``<tag Value="..."/>`` children."""
    child = elem.find(tag)
    return child.get("Value") if child is not None else None


def _bool_value(elem: ET.Element, tag: str, default: bool) -> bool:
    raw = _child_value(elem, tag)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "")


def parse_xform(elem: ET.Element) -> Matrix:
    node = elem.find("XForm")
    if node is None or not (node.text or "").strip():
        return IDENTITY
    parts = node.text.split()
    if len(parts) < 6:
        return IDENTITY
    a, b, c, d, e, f = (_float(p) for p in parts[:6])
    return (a, b, c, d, e, f)


def parse_vertlist(text: str) -> list[_Vertex]:
    verts: list[_Vertex] = []
    for match in _VERT_RE.finditer(text):
        x, y = _float(match.group(1)), _float(match.group(2))
        handles: dict[str, float] = {}
        for which, axis, raw in _HANDLE_RE.findall(match.group(3) or ""):
            handles[which + axis] = _float(raw)
        vert = _Vertex((x, y))
        # A handle is real only when both components are written out.
        if "0x" in handles and "0y" in handles:
            vert.c0 = (handles["0x"], handles["0y"])
        if "1x" in handles and "1y" in handles:
            vert.c1 = (handles["1x"], handles["1y"])
        verts.append(vert)
    return verts


def _contours_from_prims(verts: list[_Vertex], prim_text: str) -> list[Contour]:
    """Wire vertices into contours per ``<PrimList>``."""
    if not verts:
        return []

    prims = _PRIM_RE.findall(prim_text or "")
    if not prims:
        # "LineClosed" / "LineOpen" shorthand (or an unrecognised list): join
        # every vertex in order.
        closed = "closed" in (prim_text or "").lower()
        contour = Contour(start=verts[0].p, closed=closed)
        for v in verts[1:]:
            contour.segments.append(Segment("L", v.p))
        return [contour] if contour.segments else []

    contours: list[Contour] = []
    current: Contour | None = None
    prev_end: int | None = None

    for kind, i_raw, j_raw in prims:
        i, j = int(i_raw), int(j_raw)
        if i >= len(verts) or j >= len(verts):
            continue
        vi, vj = verts[i], verts[j]

        if current is None or prev_end != i:
            # Discontinuity: a Path shape can hold several sub-contours.
            if current is not None and current.segments:
                contours.append(current)
            current = Contour(start=vi.p)

        if kind == "B":
            leaving = vi.c0 or vi.p
            arriving = vj.c1 or vj.p
            current.segments.append(Segment("C", vj.p, c1=leaving, c2=arriving))
        else:
            current.segments.append(Segment("L", vj.p))

        # Closing back onto the contour's first vertex ends it.
        if abs(vj.p[0] - current.start[0]) < 1e-9 and abs(vj.p[1] - current.start[1]) < 1e-9:
            current.closed = True
            contours.append(current)
            current = None
            prev_end = None
            continue
        prev_end = j

    if current is not None and current.segments:
        contours.append(current)
    return contours


def _ellipse_contour(rx: float, ry: float) -> Contour:
    """Origin-centred ellipse as four cubic beziers."""
    kx, ky = rx * KAPPA, ry * KAPPA
    contour = Contour(start=(rx, 0.0), closed=True)
    contour.segments += [
        Segment("C", (0.0, ry), c1=(rx, ky), c2=(kx, ry)),
        Segment("C", (-rx, 0.0), c1=(-kx, ry), c2=(-rx, ky)),
        Segment("C", (0.0, -ry), c1=(-rx, -ky), c2=(-kx, -ry)),
        Segment("C", (rx, 0.0), c1=(kx, -ry), c2=(rx, -ky)),
    ]
    return contour


def _rect_contour(w: float, h: float, r: float) -> Contour:
    """Origin-centred rectangle, optionally with rounded corners."""
    hw, hh = w / 2.0, h / 2.0
    r = max(0.0, min(r, hw, hh))
    if r <= 1e-9:
        contour = Contour(start=(-hw, -hh), closed=True)
        contour.segments += [
            Segment("L", (hw, -hh)),
            Segment("L", (hw, hh)),
            Segment("L", (-hw, hh)),
            Segment("L", (-hw, -hh)),
        ]
        return contour

    k = r * KAPPA
    contour = Contour(start=(-hw + r, -hh), closed=True)
    contour.segments += [
        Segment("L", (hw - r, -hh)),
        Segment("C", (hw, -hh + r), c1=(hw - r + k, -hh), c2=(hw, -hh + r - k)),
        Segment("L", (hw, hh - r)),
        Segment("C", (hw - r, hh), c1=(hw, hh - r + k), c2=(hw - r + k, hh)),
        Segment("L", (-hw + r, hh)),
        Segment("C", (-hw, hh - r), c1=(-hw + r - k, hh), c2=(-hw, hh - r + k)),
        Segment("L", (-hw, -hh + r)),
        Segment("C", (-hw + r, -hh), c1=(-hw, -hh + r - k), c2=(-hw + r - k, -hh)),
    ]
    return contour


def _polygon_contour(radius: float, sides: int) -> Contour:
    sides = max(3, sides)
    pts = [
        (radius * math.cos(2 * math.pi * i / sides), radius * math.sin(2 * math.pi * i / sides))
        for i in range(sides)
    ]
    contour = Contour(start=pts[0], closed=True)
    for p in pts[1:]:
        contour.segments.append(Segment("L", p))
    contour.segments.append(Segment("L", pts[0]))
    return contour


def _transform_contours(contours: list[Contour], m: Matrix) -> list[Contour]:
    if m == IDENTITY:
        return contours
    out: list[Contour] = []
    for c in contours:
        moved = Contour(start=apply(m, c.start), closed=c.closed)
        for s in c.segments:
            moved.segments.append(
                Segment(
                    s.kind,
                    apply(m, s.end),
                    c1=apply(m, s.c1) if s.c1 else None,
                    c2=apply(m, s.c2) if s.c2 else None,
                )
            )
        out.append(moved)
    return out


def _local_contours(elem: ET.Element, kind: str, cache: _GeometryCache) -> list[Contour]:
    """Geometry in the shape's own coordinate space, before its XForm."""
    if kind in ("Path", "BackupPath"):
        return _contours_from_prims(cache.resolve_verts(elem), cache.resolve_prims(elem))

    if kind == "Ellipse":
        return [_ellipse_contour(_float(elem.get("Rx")), _float(elem.get("Ry")))]

    if kind == "Rect":
        return [
            _rect_contour(_float(elem.get("W")), _float(elem.get("H")), _float(elem.get("Cr")))
        ]

    if kind == "Polygon":
        return [_polygon_contour(_float(elem.get("R")), int(_float(elem.get("N"), 3)))]

    if kind == "Line":
        # Rare; a two-point path stored as X0/Y0/X1/Y1.
        start = (_float(elem.get("X0")), _float(elem.get("Y0")))
        end = (_float(elem.get("X1")), _float(elem.get("Y1")))
        return [Contour(start=start, segments=[Segment("L", end)])]

    return []


def _walk(
    elem: ET.Element,
    parent_matrix: Matrix,
    parent_cut_index: int,
    project: Project,
    cache: _GeometryCache,
) -> None:
    kind = elem.get("Type") or ""
    matrix = mat_mul(parent_matrix, parse_xform(elem))
    cut_index = int(_float(elem.get("CutIndex"), parent_cut_index))

    if kind in ("Group", "Component"):
        children = elem.find("Children")
        if children is not None:
            for child in children.findall("Shape"):
                _walk(child, matrix, cut_index, project, cache)
        return

    if kind == "Text":
        # Prefer LightBurn's own vectorised glyph outlines over re-rendering the
        # font. <BackupPath> is a fully baked, self-contained shape: it carries
        # its own Type, CutIndex and XForm, and that XForm places the glyphs in
        # *absolute project coordinates* — the Text shape's own transform and any
        # enclosing group's are already folded into it.
        #
        # So it starts from the identity, not from the accumulated matrix.
        # Applying the Text's XForm as well double-counts a transform that is
        # typically [0 1; 1 0] — a reflection about the diagonal — which mirrors
        # every label and flings it off the canvas. Checked against the
        # <Thumbnail> LightBurn embeds in the file, which is what the design is
        # actually supposed to look like.
        backup = elem.find("BackupPath")
        if backup is not None:
            _walk(backup, IDENTITY, cut_index, project, cache)
        else:
            project.skipped["Text (no BackupPath)"] = (
                project.skipped.get("Text (no BackupPath)", 0) + 1
            )
        return

    if kind in UNSUPPORTED:
        project.skipped[kind] = project.skipped.get(kind, 0) + 1
        return

    contours = _local_contours(elem, kind, cache)
    if not contours:
        if kind:
            project.skipped[kind] = project.skipped.get(kind, 0) + 1
        return

    project.shapes.append(Shape(cut_index, kind, _transform_contours(contours, matrix)))


def _parse_layers(root: ET.Element) -> dict[int, Layer]:
    layers: dict[int, Layer] = {}
    for node in root:
        if not node.tag.startswith("CutSetting"):
            continue
        index = int(_float(_child_value(node, "index"), -1))
        if index < 0:
            continue
        kind = node.get("type") or ("Image" if node.tag.endswith("_Img") else "Cut")
        name = _child_value(node, "name") or ""
        layers[index] = Layer(
            index=index,
            name=name or lightburn_layer_name(index),
            kind=kind,
            color=lightburn_color(index),
            max_power=(
                _float(_child_value(node, "maxPower"))
                if _child_value(node, "maxPower") is not None
                else None
            ),
            speed=(
                _float(_child_value(node, "speed"))
                if _child_value(node, "speed") is not None
                else None
            ),
            num_passes=int(_float(_child_value(node, "numPasses"), 1)),
            output=_bool_value(node, "doOutput", True),
            hidden=_bool_value(node, "hide", False),
            priority=int(_float(_child_value(node, "priority"), 0)),
        )
    return layers


def parse_lbrn(path: Path) -> Project:
    """Parse a ``.lbrn``/``.lbrn2`` file into a :class:`Project`."""
    # LightBurn occasionally writes stray bytes; be forgiving about encoding.
    raw = Path(path).read_bytes()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        root = ET.fromstring(raw.decode("utf-8", "replace").encode("utf-8"))

    project = Project(source=str(path), app_version=root.get("AppVersion") or "")
    project.layers = _parse_layers(root)

    cache = _GeometryCache.from_document(root)
    for node in root.findall("Shape"):
        _walk(node, IDENTITY, 0, project, cache)

    # Any CutIndex used by geometry but missing a CutSetting still needs a layer.
    for shape in project.shapes:
        if shape.cut_index not in project.layers:
            project.layers[shape.cut_index] = Layer(
                index=shape.cut_index,
                name=lightburn_layer_name(shape.cut_index),
                color=lightburn_color(shape.cut_index),
            )
    return project
