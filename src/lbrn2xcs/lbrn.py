"""Parsing of LightBurn .lbrn/.lbrn2 project files (stub).

To implement (see docs/plan.md): parse the XML into layers (from <CutSetting>)
and shapes (from <Shape Type="Path|Rect|Ellipse|Line|Text">), applying any
per-shape <XForm> transform, and flattening Path PrimList beziers to polylines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Shape:
    cut_index: int
    kind: str  # "path" | "rect" | "ellipse" | "line" | "text" | ...
    points: list[tuple[float, float]] = field(default_factory=list)
    closed: bool = False


@dataclass
class Layer:
    index: int
    name: str
    color: str  # hex, e.g. "#FF0000"


@dataclass
class LbrnProject:
    layers: dict[int, Layer]
    shapes: list[Shape]


def parse_lbrn(path: Path) -> LbrnProject:  # noqa: ARG001 — stub
    """Parse a .lbrn/.lbrn2 file into a LbrnProject. Not implemented yet."""
    raise NotImplementedError("LightBurn parsing not implemented yet — see docs/plan.md")
