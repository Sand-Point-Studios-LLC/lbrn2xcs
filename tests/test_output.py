"""SVG and DXF emitter tests."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from lbrn2xcs.dxf_out import flatten_contour, write_dxf
from lbrn2xcs.lbrn import parse_lbrn
from lbrn2xcs.model import Contour, Segment
from lbrn2xcs.svg_out import contour_to_path_data, project_to_svg

SVG_NS = "{http://www.w3.org/2000/svg}"

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.7.03">'


def make_project(tmp_path: Path, body: str):
    path = tmp_path / "t.lbrn2"
    path.write_text(f"{HEADER}{body}</LightBurnProject>", encoding="utf-8")
    return parse_lbrn(path)


TWO_LAYER_BODY = """
  <CutSetting type="Cut"><index Value="0"/><name Value="Outline"/></CutSetting>
  <CutSetting type="Cut"><index Value="2"/><name Value="Detail"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="100" H="50" Cr="0"><XForm>1 0 0 1 50 25</XForm></Shape>
  <Shape Type="Rect" CutIndex="2" W="10" H="10" Cr="0"><XForm>1 0 0 1 10 10</XForm></Shape>
"""


# --------------------------------------------------------------------------
# SVG
# --------------------------------------------------------------------------


def test_svg_document_is_sized_in_mm_to_the_tight_bbox(tmp_path):
    project = make_project(tmp_path, TWO_LAYER_BODY)
    root = ET.fromstring(project_to_svg(project))
    assert root.get("width") == "100mm"
    assert root.get("height") == "50mm"
    assert root.get("viewBox") == "0 0 100 50"


def test_svg_groups_shapes_by_layer_with_palette_stroke(tmp_path):
    project = make_project(tmp_path, TWO_LAYER_BODY)
    root = ET.fromstring(project_to_svg(project))
    groups = root.findall(f"{SVG_NS}g")
    assert [g.get("id") for g in groups] == ["C00", "C02"]
    assert groups[0].get("stroke") == "#000000"
    assert groups[1].get("stroke") == "#FF0000"
    assert groups[0].get("fill") == "none"
    assert all(len(g.findall(f"{SVG_NS}path")) == 1 for g in groups)


def test_svg_flips_y_so_lightburn_top_stays_on_top(tmp_path):
    """LightBurn is Y-up, SVG is Y-down. A shape high in LightBurn must land
    near y=0 in the SVG, not at the bottom."""
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 5 95</XForm></Shape>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 5 5</XForm></Shape>
"""
    project = make_project(tmp_path, body)
    root = ET.fromstring(project_to_svg(project))
    paths = root.findall(f"{SVG_NS}g/{SVG_NS}path")
    ys = [
        [float(n) for n in re.findall(r"[-\d.]+,([-\d.]+)", p.get("d") or "")] for p in paths
    ]
    # First shape is the LightBurn-high one; it must own the smallest SVG y.
    assert min(ys[0]) == 0.0
    assert max(ys[1]) == 100.0


def test_contour_path_data_emits_curves_and_close():
    contour = Contour(
        start=(0.0, 0.0),
        segments=[
            Segment("C", (10.0, 0.0), c1=(3.0, 3.0), c2=(7.0, 3.0)),
            Segment("L", (0.0, 0.0)),
        ],
        closed=True,
    )
    d = contour_to_path_data(contour, flip_y=10.0)
    assert d == "M0,10C3,7 7,7 10,10L0,10Z"


def test_svg_escapes_layer_names(tmp_path):
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="A &amp; B &lt;x&gt;"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 0 0</XForm></Shape>
"""
    project = make_project(tmp_path, body)
    svg = project_to_svg(project)
    assert "A &amp; B &lt;x&gt;" in svg
    ET.fromstring(svg)  # must still parse


def test_empty_project_still_produces_valid_svg(tmp_path):
    project = make_project(
        tmp_path, '<CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>'
    )
    root = ET.fromstring(project_to_svg(project))
    assert root.findall(f"{SVG_NS}g") == []


# --------------------------------------------------------------------------
# Bezier flattening
# --------------------------------------------------------------------------


def test_flatten_keeps_straight_lines_unsubdivided():
    contour = Contour(start=(0.0, 0.0), segments=[Segment("L", (10.0, 0.0))])
    assert flatten_contour(contour) == [(0.0, 0.0), (10.0, 0.0)]


def test_flatten_degenerate_bezier_needs_no_subdivision():
    """Control points on the chord means the curve *is* the chord."""
    contour = Contour(
        start=(0.0, 0.0),
        segments=[Segment("C", (9.0, 0.0), c1=(3.0, 0.0), c2=(6.0, 0.0))],
    )
    assert flatten_contour(contour) == [(0.0, 0.0), (9.0, 0.0)]


def test_flatten_curve_stays_within_tolerance():
    """A quarter-circle bezier, flattened, must sit on the true arc."""
    r, k = 50.0, 50.0 * (4.0 / 3.0 * (math.sqrt(2.0) - 1.0))
    contour = Contour(
        start=(r, 0.0),
        segments=[Segment("C", (0.0, r), c1=(r, k), c2=(k, r))],
    )
    pts = flatten_contour(contour, tolerance=0.01)
    assert len(pts) > 8
    # Every flattened point should be ~r from the centre (bezier approximates a
    # circle to ~0.03% of the radius, which dominates the flattening error).
    for x, y in pts:
        assert abs(math.hypot(x, y) - r) < 0.05


def test_flatten_drops_duplicate_closing_point():
    contour = Contour(
        start=(0.0, 0.0),
        segments=[
            Segment("L", (10.0, 0.0)),
            Segment("L", (0.0, 0.0)),
        ],
        closed=True,
    )
    assert flatten_contour(contour) == [(0.0, 0.0), (10.0, 0.0)]


# --------------------------------------------------------------------------
# DXF
# --------------------------------------------------------------------------


def test_dxf_has_one_layer_per_cut_index_with_true_color(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    project = make_project(tmp_path, TWO_LAYER_BODY)
    target = tmp_path / "o.dxf"
    write_dxf(project, target)

    doc = ezdxf.readfile(target)
    names = {layer.dxf.name for layer in doc.layers} - {"0", "Defpoints"}
    assert names == {"C00 Outline", "C02 Detail"}
    assert tuple(doc.layers.get("C02 Detail").rgb) == (255, 0, 0)
    assert doc.layers.get("C00 Outline").color == 7  # black -> ACI 7 by convention

    polylines = list(doc.modelspace().query("LWPOLYLINE"))
    assert len(polylines) == 2
    assert all(p.closed for p in polylines)


def test_dxf_geometry_is_y_up_and_origin_shifted(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    project = make_project(tmp_path, TWO_LAYER_BODY)
    target = tmp_path / "o.dxf"
    write_dxf(project, target)

    doc = ezdxf.readfile(target)
    pts = [pt for p in doc.modelspace().query("LWPOLYLINE") for pt in p.get_points("xy")]
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    assert (min(xs), max(xs)) == (0.0, 100.0)
    assert (min(ys), max(ys)) == (0.0, 50.0)
    # The small C02 rect sits low in LightBurn, so it must stay low in DXF.
    small = [p for p in doc.modelspace().query("LWPOLYLINE") if p.dxf.layer == "C02 Detail"][0]
    assert max(y for _, y in small.get_points("xy")) < 25.0


def test_dxf_layer_name_strips_illegal_characters(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="Cut / Score: fast"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 0 0</XForm></Shape>
"""
    project = make_project(tmp_path, body)
    target = tmp_path / "o.dxf"
    write_dxf(project, target)
    names = {layer.dxf.name for layer in ezdxf.readfile(target).layers}
    assert "C00 Cut  Score fast" in names
