"""Native ``.xcs`` writer — Tier B.

``.xcs`` is undocumented, but it is plain UTF-8 JSON (not zipped), and the parts
that carry geometry were worked out by measuring 5,995 displays across real files
saved by XCS itself. What follows is the observed contract, not a guess:

**Geometry.** Each drawable is a ``display`` of type ``PATH`` whose ``dPath`` is
ordinary SVG path data in a *local* coordinate space. The mapping from local
units to canvas millimetres is::

    canvas_x = graphicX + scale.x * local_x
    canvas_y = graphicY - scale.y * local_y      # note the minus

Both formulas reproduce the stored ``x``/``y`` on 100% of displays in every
sample (``x`` and ``y`` hold the local bbox's minimum corner run through the same
transform), and ``width``/``height`` are the local bbox size times ``scale``.
The negated Y is the ``skew.x = π`` that every display carries.

This writer exploits the negation rather than fighting it: LightBurn is already
Y-up, so ``dPath`` is emitted in LightBurn's own orientation and ``graphicY`` is
set to the drawing height, which makes ``canvas_y`` come out Y-down and correct
with no flipping of the geometry itself.

**Layers.** ``layerData`` maps an XCS palette colour to a name and z-order, and
each display points at one via ``layerTag``/``layerColor``. XCS snaps imported
stroke colours onto that fixed palette, keeping the pre-import colour in
``originColor`` — so LightBurn's palette colour goes there and the LightBurn
layer index picks the XCS palette slot.

**Machine settings.** The ``device`` block holds per-display power/speed keyed by
display id. It is left empty here, exactly as the older XCS-written samples do,
so XCS applies its own material defaults on open — mapping LightBurn's
power/speed onto xTool's material model is a separate problem, and getting it
wrong silently would be worse than not doing it.

Treat this as experimental until a round-trip is confirmed against your XCS build:
``tools/make_probe_svg.py`` and ``tools/decode_xcs.py`` exist for exactly that.
"""

from __future__ import annotations

import json
import math
import time
import uuid
from pathlib import Path

from .model import Project
from .palette import xcs_layer
from .svg_path import contour_to_path_data, contours_bbox, parse_path_data

# Schema/app version strings copied from files saved by XCS 2.15.93 (the
# "1.5.8" here is the project-file schema version, not the application version).
XCS_FILE_VERSION = "1.5.8"
XCS_CANVAS_VERSION = "2.15.93"
XCS_MIN_REQUIRED_VERSION = "2.6.0"

# Every display in every sample carries this: a vertical mirror expressed as skew.
Y_MIRROR_SKEW = math.pi


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uuid() -> str:
    return str(uuid.uuid4())


def _display(
    *,
    d_path: str,
    layer_color: str,
    origin_color: str,
    local_bbox: tuple[float, float, float, float],
    graphic_x: float,
    graphic_y: float,
    z_order: float,
    closed: bool,
    compound: bool,
) -> dict:
    min_x, min_y, max_x, max_y = local_bbox
    return {
        "id": _uuid(),
        "name": None,
        "type": "PATH",
        # x/y are the local bbox minimum corner mapped through the transform.
        "x": graphic_x + min_x,
        "y": graphic_y - min_y,
        "angle": 0,
        "scale": {"x": 1, "y": 1},
        "skew": {"x": Y_MIRROR_SKEW, "y": 0},
        "pivot": {"x": 0, "y": 0},
        "localSkew": {"x": Y_MIRROR_SKEW, "y": 0},
        "offsetX": graphic_x,
        "offsetY": graphic_y,
        "lockRatio": True,
        "isClosePath": closed,
        "zOrder": z_order,
        "groupTag": _uuid(),
        "layerTag": layer_color,
        "layerColor": layer_color,
        "visible": True,
        "originColor": origin_color,
        "enableTransform": True,
        "visibleState": True,
        "lockState": False,
        "resourceOrigin": "",
        "customData": {},
        "rootComponentId": "",
        "minCanvasVersion": "0.0.0",
        "fill": {"paintType": "color", "visible": False, "color": 0, "alpha": 1},
        "stroke": {
            "paintType": "color",
            "visible": True,
            "color": 0,
            "alpha": 1,
            "width": 0.1,
            "cap": "butt",
            "join": "miter",
            "miterLimit": 4,
            "alignment": 0.5,
        },
        "width": max_x - min_x,
        "height": max_y - min_y,
        "isFill": False,
        "fillRule": "nonzero",
        "points": [],
        "dPath": d_path,
        "graphicX": graphic_x,
        "graphicY": graphic_y,
        "isCompoundPath": compound,
    }


def project_to_xcs_dict(project: Project, *, title: str = "") -> dict:
    """Build the ``.xcs`` document for *project* as a plain dict."""
    min_x, min_y, max_x, max_y = project.bbox()
    height = max_y - min_y

    # dPath is emitted in LightBurn's Y-up space shifted to start at (0, 0);
    # graphicY = height then makes canvas_y = height - local_y, i.e. Y-down.
    graphic_x = 0.0
    graphic_y = height

    def to_local(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] - min_x, p[1] - min_y)

    by_layer = project.shapes_by_layer()
    layer_data: dict[str, dict] = {}
    displays: list[dict] = []

    total = sum(len(v) for v in by_layer.values())
    counter = 0

    for slot, index in enumerate(sorted(by_layer)):
        layer = project.layers.get(index)
        xcs_color, xcs_name = xcs_layer(slot)
        layer_data[xcs_color] = {
            "name": xcs_name,
            "order": slot + 1,
            "visible": True,
        }
        origin_color = (layer.color if layer else "#000000").lower()

        for shape in by_layer[index]:
            contours = shape.contours
            if not contours:
                continue
            local = [c.mapped(to_local) for c in contours]
            d_path = "".join(contour_to_path_data(c) for c in local)
            if not d_path:
                continue
            counter += 1
            displays.append(
                _display(
                    d_path=d_path,
                    layer_color=xcs_color,
                    origin_color=origin_color,
                    # Measured back off the serialised path, not the source
                    # geometry: dPath is written at finite precision, and x/y/
                    # width/height must agree with the string XCS will actually
                    # parse, not with numbers a hair more precise.
                    local_bbox=contours_bbox(parse_path_data(d_path)),
                    graphic_x=graphic_x,
                    graphic_y=graphic_y,
                    z_order=float(total) + counter / max(total, 1) / 1000.0,
                    closed=all(c.closed for c in local),
                    compound=len(local) > 1,
                )
            )

    canvas_id = _uuid()
    created = _now_ms()
    return {
        "canvasId": canvas_id,
        "canvas": [
            {
                "id": canvas_id,
                "title": title or "{panel}1",
                "layerData": layer_data,
                "groupData": {},
                "displays": displays,
                "extendInfo": {
                    "version": XCS_CANVAS_VERSION,
                    "minCanvasVersion": "0.0.0",
                    "displayProcessConfigMap": {},
                    "rulerPluginData": {"rulerGuide": []},
                    "type": "2d",
                    "gridOptions": {"color": "normal", "isShow": True},
                },
            }
        ],
        "extId": "",
        "extName": "",
        # Left deliberately empty: XCS then applies its own material defaults
        # rather than inheriting settings translated from LightBurn by guesswork.
        "device": {
            "id": "",
            "power": 0,
            "data": {"dataType": "Map", "value": []},
            "materialList": [],
            "materialTypeList": [],
        },
        "version": XCS_FILE_VERSION,
        "created": created,
        "modify": created,
        "ua": "lbrn2xcs",
        "meta": [{"version": XCS_FILE_VERSION, "date": created, "ua": "lbrn2xcs"}],
        "minRequiredVersion": XCS_MIN_REQUIRED_VERSION,
        "appMinRequiredVersion": "",
        "webMinRequiredVersion": "",
        "projectTraceID": _uuid(),
    }


def write_xcs(project: Project, path: Path, *, title: str = "") -> None:
    """Write *project* to *path* as a ``.xcs`` file."""
    doc = project_to_xcs_dict(project, title=title)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
