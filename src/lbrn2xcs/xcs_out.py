"""Native ``.xcs`` writer — Tier B.

``.xcs`` is undocumented but is plain UTF-8 JSON (not zipped). The contract below
was established by round-tripping a known-geometry probe through XCS itself
(``tools/make_probe_svg.py`` → import → save → ``tools/decode_xcs.py``) and
cross-checked against six unrelated real projects.

**Geometry.** Each drawable is a ``display``. ``PATH`` displays carry ``dPath``:
ordinary SVG path data, Y-down, in millimetres, kept *verbatim* — XCS stores an
imported path's data byte-for-byte and positions it with::

    canvas_x = graphicX + scale.x * local_x
    canvas_y = graphicY + scale.y * local_y

``x``/``y`` are the local bbox minimum corner through that same transform (using
the curve's true extrema, not its control points) and ``width``/``height`` are the
local bbox size times ``scale``.

A caution worth recording: files that have been vertically mirrored carry
``skew.x = π`` and then the Y term is *negated*. Measuring only such files makes
the minus look intrinsic — it isn't. A straightforward import has ``skew = 0``,
which is what this writer emits.

**Layers.** ``layerData`` maps a colour to ``{name, order, visible}`` and displays
point at one via ``layerTag``/``layerColor``. XCS does not force imported art onto
a fixed palette: it creates a layer per distinct stroke colour, named with the
uppercase hex. So LightBurn's palette colours are passed straight through and
LightBurn's layer structure survives exactly.

**Machine settings.** ``device`` holds per-display processing config keyed by
display id. Written here with XCS's own defaults for a freshly imported drawing
(``VECTOR_ENGRAVING``, ``materialType: customize``) rather than translated from
LightBurn's power/speed — xTool's material model is not a unit conversion away
from LightBurn's, and a silently wrong power setting is worse than an obvious
default the user sets in XCS.
"""

from __future__ import annotations

import json
import time
import uuid
from copy import deepcopy
from pathlib import Path

from .model import Project
from .settings_map import D1_PRO_40W, P3_80W, Machine, XcsSettings, convert
from .svg_path import contour_to_path_data, contours_bbox, parse_path_data

# Version strings as written by XCS 1.5.8 / canvas 2.15.93.
XCS_FILE_VERSION = "1.5.8"
XCS_CANVAS_VERSION = "2.15.93"
XCS_MIN_REQUIRED_VERSION = "2.6.0"

# Target machine. XCS records this on save; "P3" is the xTool P3.
DEFAULT_DEVICE_ID = "P3"
DEFAULT_DEVICE_POWER = [80, 5, 0]

# Constants XCS writes on every display regardless of content.
STROKE_WIDTH = 0.2834645669291339
LINE_COLOR = 16421416
FILL_COLOR = "#f9932b"

# XCS's default processing parameters for a newly imported drawing, copied
# verbatim from a probe file it saved itself.
DEFAULT_PROCESS_DATA = {
    "VECTOR_CUTTING": {
        "materialType": "customize",
        "planType": "official",
        "parameter": {
            "customize": {
                "power": 1,
                "speed": 16,
                "repeat": 1,
                "cuttingDrop": False,
                "sinkingMethod": "one",
                "firstCuttingDropValue": 1,
                "cuttingDropValue": 1,
                "descentIntervalDescent": 1,
                "descentPerStep": 1,
                "enableBreakPoint": False,
                "breakPointSize": 0.5,
                "breakPointCount": 2,
                "breakPointMode": "count",
                "breakPointDistance": 100,
                "breakPointPower": 0,
                "enableKerf": False,
                "kerfDistance": 0,
                "laser": "LASER",
                "processHead": "LASER",
                "enableOverCut": False,
                "overCutDistance": 0.5,
                "airPump": 100,
                "powerCutoff": "FOLLOW_ACTUALLY_POWER",
                "powerCutoffValue": 9.5,
            }
        },
    },
    "VECTOR_ENGRAVING": {
        "materialType": "customize",
        "planType": "official",
        "parameter": {
            "customize": {
                "power": 1,
                "speed": 20,
                "repeat": 1,
                "enableKerf": False,
                "kerfDistance": 0,
                "laser": "LASER",
                "processHead": "LASER",
                "airPump": 25,
            }
        },
    },
    "FILL_VECTOR_ENGRAVING": {
        "materialType": "customize",
        "planType": "official",
        "parameter": {
            "customize": {
                "power": 1,
                "speed": 80,
                "repeat": 1,
                "density": 100,
                "laser": "LASER",
                "bitmapScanMode": "zMode",
                "processHead": "LASER",
                "airPump": 25,
                "enableKerf": False,
                "kerfDistance": 0,
            }
        },
    },
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _uuid() -> str:
    return str(uuid.uuid4())


def _z_order(base: int, index: int) -> float:
    """Mirror XCS's ordering: integer base plus a fraction per display.

    XCS uses one decimal place for a handful of displays and four for a thousand,
    i.e. enough digits that the fractional parts stay ordered and below 1.
    """
    step = 10.0 ** -len(str(max(base, 1)))
    return base + (index + 1) * step


def _display(
    *,
    d_path: str,
    layer_color: str,
    local_bbox: tuple[float, float, float, float],
    graphic_x: float,
    graphic_y: float,
    z_order: float,
    group_tag: str,
    closed: bool,
    compound: bool,
) -> dict:
    min_x, min_y, max_x, max_y = local_bbox
    return {
        "id": _uuid(),
        "name": None,
        "type": "PATH",
        "x": graphic_x + min_x,
        "y": graphic_y + min_y,
        "angle": 0,
        "scale": {"x": 1, "y": 1},
        "skew": {"x": 0, "y": 0},
        "pivot": {"x": 0, "y": 0},
        "localSkew": {"x": 0, "y": 0},
        "offsetX": graphic_x,
        "offsetY": graphic_y,
        "lockRatio": True,
        "isClosePath": closed,
        "zOrder": z_order,
        "groupTag": group_tag,
        "layerTag": layer_color,
        "layerColor": layer_color,
        "visible": True,
        "originColor": layer_color,
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
            "color": int(layer_color[1:], 16),
            "alpha": 1,
            "width": STROKE_WIDTH,
            "cap": "butt",
            "join": "miter",
            "miterLimit": 4,
            "alignment": 0.5,
        },
        "width": max_x - min_x,
        "height": max_y - min_y,
        "isFill": False,
        "lineColor": LINE_COLOR,
        "fillColor": FILL_COLOR,
        "points": [],
        "dPath": d_path,
        "fillRule": "nonzero",
        "graphicX": graphic_x,
        "graphicY": graphic_y,
        "isCompoundPath": compound,
    }


def _process_entry(display_id: str, settings: XcsSettings | None) -> list:
    """One [displayId, config] pair for the device block.

    With no *settings* this is XCS's own fresh-import default. With settings, the
    parameters for the chosen operation are filled in and the others left at
    their defaults — which is how XCS itself stores a file: all three blocks
    present, `processingType` selecting the live one.
    """
    data = deepcopy(DEFAULT_PROCESS_DATA)
    operation = "VECTOR_ENGRAVING"
    ignored = False

    if settings is not None:
        operation = settings.operation
        ignored = settings.ignored
        params = data[operation]["parameter"]["customize"]
        params["power"] = settings.power
        params["speed"] = settings.speed
        params["repeat"] = settings.repeat
        if settings.density is not None and "density" in params:
            params["density"] = settings.density
        if settings.kerf:
            params["enableKerf"] = True
            params["kerfDistance"] = settings.kerf

    return [
        display_id,
        {
            "isFill": False,
            "type": "PATH",
            "processingType": operation,
            "data": data,
            "processIgnore": ignored,
            "isWhiteModel": True,
        },
    ]


def project_to_xcs_dict(
    project: Project,
    *,
    title: str = "",
    origin: tuple[float, float] = (0.0, 0.0),
    device_id: str = DEFAULT_DEVICE_ID,
    source_machine: Machine | None = D1_PRO_40W,
    target_machine: Machine = P3_80W,
    power_scale: float = 1.0,
) -> dict:
    """Build the ``.xcs`` document for *project* as a plain dict.

    *origin* is where the drawing's top-left corner lands on the XCS canvas, in
    millimetres. Pass ``source_machine=None`` to skip settings translation and
    fall back to XCS's own fresh-import defaults.
    """
    min_x, min_y, max_x, max_y = project.bbox()
    graphic_x, graphic_y = origin

    # dPath is Y-down millimetres, matching the SVG emitter, so an imported SVG
    # and a written .xcs describe the same geometry the same way.
    def to_local(p: tuple[float, float]) -> tuple[float, float]:
        return (p[0] - min_x, max_y - p[1])

    by_layer = project.shapes_by_layer()
    layer_data: dict[str, dict] = {}
    displays: list[dict] = []
    group_tag = f"g-{_uuid()}"

    total = sum(len(shapes) for shapes in by_layer.values())
    settings_by_display: dict[str, XcsSettings] = {}

    for slot, index in enumerate(sorted(by_layer)):
        layer = project.layers.get(index)
        # LightBurn's own palette colour becomes the XCS layer colour; XCS names
        # layers by uppercase hex and does not remap to a fixed palette.
        color = (layer.color if layer else "#000000").lower()
        layer_data.setdefault(
            color, {"name": color.upper(), "order": slot + 1, "visible": True}
        )
        settings = (
            convert(layer, source=source_machine, target=target_machine, scale=power_scale)
            if layer is not None and source_machine is not None
            else None
        )

        for shape in by_layer[index]:
            if not shape.contours:
                continue
            local = [c.mapped(to_local) for c in shape.contours]
            d_path = "".join(contour_to_path_data(c) for c in local)
            if not d_path:
                continue
            displays.append(
                _display(
                    d_path=d_path,
                    layer_color=color,
                    # Measured off the serialised path: dPath is written at finite
                    # precision, and x/y/width/height must agree with the string
                    # XCS will parse, not with slightly more precise source values.
                    local_bbox=contours_bbox(parse_path_data(d_path)),
                    graphic_x=graphic_x,
                    graphic_y=graphic_y,
                    z_order=_z_order(total, len(displays)),
                    group_tag=group_tag,
                    closed=all(c.closed for c in local),
                    compound=len(local) > 1,
                )
            )
            if settings is not None:
                settings_by_display[displays[-1]["id"]] = settings

    canvas_id = _uuid()
    created = _now_ms()
    group_data = (
        {
            group_tag: {
                "groupName": "",
                "groupTag": group_tag,
                "visible": True,
                "enableTransform": True,
                "zOrder": displays[-1]["zOrder"],
            }
        }
        if displays
        else {}
    )

    return {
        "canvasId": canvas_id,
        "canvas": [
            {
                "id": canvas_id,
                "title": title or "{panel}1",
                "layerData": layer_data,
                "groupData": group_data,
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
        "extId": device_id,
        "extName": device_id,
        "device": {
            "id": device_id,
            "power": list(DEFAULT_DEVICE_POWER),
            "data": {
                "dataType": "Map",
                "value": [
                    [
                        canvas_id,
                        {
                            "mode": "LIFTING_PLATFORM_PROCESS",
                            "data": {
                                "LIFTING_PLATFORM_PROCESS": {
                                    "material": 0,
                                    "focalLength": None,
                                    "perimeter": None,
                                    "diameter": None,
                                    "distence": None,
                                    "isProcessByLayer": False,
                                    "pathPlanning": "auto",
                                    "fillPlanning": "separate",
                                    "scanDirection": "topToBottom",
                                    "enableOddEvenKerf": True,
                                    "xcsUsed": [],
                                }
                            },
                            "displays": {
                                "dataType": "Map",
                                "value": [
                                    _process_entry(d["id"], settings_by_display.get(d["id"]))
                                    for d in displays
                                ],
                            },
                        },
                    ]
                ],
            },
            "materialList": [],
            "materialTypeList": [],
            "customProjectData": {},
        },
        "version": XCS_FILE_VERSION,
        "created": created,
        "modify": created,
        "ua": "lbrn2xcs",
        "meta": [{"version": XCS_FILE_VERSION, "date": created, "ua": "lbrn2xcs"}],
        "cover": "",
        "minRequiredVersion": XCS_MIN_REQUIRED_VERSION,
        "appMinRequiredVersion": "",
        "webMinRequiredVersion": "",
        "projectTraceID": _uuid(),
    }


def write_xcs(
    project: Project,
    path: Path,
    *,
    title: str = "",
    origin: tuple[float, float] = (0.0, 0.0),
    device_id: str = DEFAULT_DEVICE_ID,
    source_machine: Machine | None = D1_PRO_40W,
    target_machine: Machine = P3_80W,
    power_scale: float = 1.0,
) -> None:
    """Write *project* to *path* as a ``.xcs`` file."""
    doc = project_to_xcs_dict(
        project,
        title=title,
        origin=origin,
        device_id=device_id,
        source_machine=source_machine,
        target_machine=target_machine,
        power_scale=power_scale,
    )
    Path(path).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
