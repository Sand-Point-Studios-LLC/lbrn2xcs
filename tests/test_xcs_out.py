"""Native .xcs writer tests.

The invariants asserted here are the ones measured across 5,995 displays in real
XCS-written files (see the module docstring in ``xcs_out``). They are what makes
the output loadable, so they are checked on the writer's own output rather than
trusted.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from lbrn2xcs.lbrn import parse_lbrn
from lbrn2xcs.svg_path import contours_bbox, parse_path_data
from lbrn2xcs.xcs_out import project_to_xcs_dict, write_xcs

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.7.03">'

BODY = """
  <CutSetting type="Cut"><index Value="0"/><name Value="Outline"/></CutSetting>
  <CutSetting type="Cut"><index Value="2"/><name Value="Detail"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="100" H="50" Cr="0"><XForm>1 0 0 1 50 25</XForm></Shape>
  <Shape Type="Ellipse" CutIndex="2" Rx="10" Ry="10"><XForm>1 0 0 1 20 20</XForm></Shape>
"""


def make_project(tmp_path: Path, body: str = BODY):
    path = tmp_path / "t.lbrn2"
    path.write_text(f"{HEADER}{body}</LightBurnProject>", encoding="utf-8")
    return parse_lbrn(path)


def displays(doc: dict) -> list[dict]:
    return doc["canvas"][0]["displays"]


# --------------------------------------------------------------------------
# Structure
# --------------------------------------------------------------------------


def test_document_has_the_expected_top_level_shape(tmp_path):
    doc = project_to_xcs_dict(make_project(tmp_path), title="Demo")
    assert doc["version"] == "1.5.8"
    assert doc["canvasId"] == doc["canvas"][0]["id"]
    assert doc["canvas"][0]["title"] == "Demo"
    assert doc["meta"][0]["version"] == "1.5.8"
    # device left empty on purpose so XCS applies its own material defaults
    assert doc["device"]["data"]["value"] == []


def test_file_is_plain_json_not_zipped(tmp_path):
    project = make_project(tmp_path)
    target = tmp_path / "o.xcs"
    write_xcs(project, target)
    raw = target.read_bytes()
    assert raw[:1] == b"{"
    assert json.loads(raw.decode("utf-8"))["canvas"]


def test_one_display_per_shape_with_paths_and_layers(tmp_path):
    doc = project_to_xcs_dict(make_project(tmp_path))
    ds = displays(doc)
    assert len(ds) == 2
    assert all(d["type"] == "PATH" and d["dPath"] for d in ds)
    layer_data = doc["canvas"][0]["layerData"]
    assert list(layer_data) == ["#000000", "#fe0002"]
    assert [meta["order"] for meta in layer_data.values()] == [1, 2]
    assert {d["layerTag"] for d in ds} == {"#000000", "#fe0002"}
    assert all(d["layerTag"] == d["layerColor"] for d in ds)


def test_origin_color_carries_the_lightburn_palette_color(tmp_path):
    """XCS stores the pre-import stroke colour here; ours should be LightBurn's."""
    doc = project_to_xcs_dict(make_project(tmp_path))
    by_layer = {d["layerTag"]: d["originColor"] for d in displays(doc)}
    assert by_layer["#000000"] == "#000000"  # LightBurn C00
    assert by_layer["#fe0002"] == "#ff0000"  # LightBurn C02


# --------------------------------------------------------------------------
# The measured coordinate contract
# --------------------------------------------------------------------------


def test_every_display_satisfies_the_measured_transform(tmp_path):
    """x/y/width/height must be exactly consistent with the dPath as written."""
    doc = project_to_xcs_dict(make_project(tmp_path))
    for d in displays(doc):
        min_x, min_y, max_x, max_y = contours_bbox(parse_path_data(d["dPath"]))
        sx, sy = d["scale"]["x"], d["scale"]["y"]
        assert d["x"] == d["graphicX"] + sx * min_x
        assert d["y"] == d["graphicY"] - sy * min_y
        assert math.isclose(d["width"], (max_x - min_x) * sx, abs_tol=1e-9)
        assert math.isclose(d["height"], (max_y - min_y) * sy, abs_tol=1e-9)
        assert d["offsetX"] == d["graphicX"]
        assert d["offsetY"] == d["graphicY"]


def test_displays_carry_the_vertical_mirror_skew(tmp_path):
    doc = project_to_xcs_dict(make_project(tmp_path))
    for d in displays(doc):
        assert d["skew"] == {"x": math.pi, "y": 0}
        assert d["localSkew"] == d["skew"]
        assert d["angle"] == 0


def test_canvas_extents_match_the_lightburn_drawing_size(tmp_path):
    """Applying the transform to every path must reproduce the source bbox."""
    project = make_project(tmp_path)
    src_min_x, src_min_y, src_max_x, src_max_y = project.bbox()
    doc = project_to_xcs_dict(project)

    xs: list[float] = []
    ys: list[float] = []
    for d in displays(doc):
        min_x, min_y, max_x, max_y = contours_bbox(parse_path_data(d["dPath"]))
        sx, sy = d["scale"]["x"], d["scale"]["y"]
        xs += [d["graphicX"] + sx * min_x, d["graphicX"] + sx * max_x]
        ys += [d["graphicY"] - sy * max_y, d["graphicY"] - sy * min_y]

    assert math.isclose(max(xs) - min(xs), src_max_x - src_min_x, abs_tol=1e-3)
    assert math.isclose(max(ys) - min(ys), src_max_y - src_min_y, abs_tol=1e-3)
    # Drawing sits inside the positive quadrant starting at the origin.
    assert math.isclose(min(xs), 0.0, abs_tol=1e-3)
    assert math.isclose(min(ys), 0.0, abs_tol=1e-3)


def test_y_is_flipped_relative_to_lightburn(tmp_path):
    """A shape high in LightBurn must end up low in XCS canvas Y."""
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 5 95</XForm></Shape>
  <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0"><XForm>1 0 0 1 5 5</XForm></Shape>
"""
    doc = project_to_xcs_dict(make_project(tmp_path, body))
    high, low = displays(doc)

    def canvas_y_range(d):
        _, min_y, _, max_y = contours_bbox(parse_path_data(d["dPath"]))
        return (d["graphicY"] - d["scale"]["y"] * max_y,
                d["graphicY"] - d["scale"]["y"] * min_y)

    assert canvas_y_range(high)[0] < canvas_y_range(low)[0]
    assert math.isclose(canvas_y_range(high)[0], 0.0, abs_tol=1e-3)


# --------------------------------------------------------------------------
# Path content
# --------------------------------------------------------------------------


def test_closed_shapes_are_marked_and_curves_survive(tmp_path):
    doc = project_to_xcs_dict(make_project(tmp_path))
    rect, ellipse = displays(doc)
    assert rect["isClosePath"] is True
    assert ellipse["isClosePath"] is True
    assert rect["dPath"].endswith("Z")
    assert "C" in ellipse["dPath"]  # ellipse kept as beziers, not polygonised
    assert rect["isCompoundPath"] is False


def test_multi_contour_shape_is_flagged_compound(tmp_path):
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>
  <Shape Type="Path" CutIndex="0">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x1c1x1V10 0c0x1c1x1V50 50c0x1c1x1V60 50c0x1c1x1</VertList>
    <PrimList>L0 1L2 3</PrimList>
  </Shape>
"""
    (display,) = displays(project_to_xcs_dict(make_project(tmp_path, body)))
    assert display["isCompoundPath"] is True
    assert display["dPath"].count("M") == 2


def test_open_path_is_not_marked_closed(tmp_path):
    body = """
  <CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>
  <Shape Type="Path" CutIndex="0">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x1c1x1V10 0c0x1c1x1</VertList>
    <PrimList>L0 1</PrimList>
  </Shape>
"""
    (display,) = displays(project_to_xcs_dict(make_project(tmp_path, body)))
    assert display["isClosePath"] is False
    assert "Z" not in display["dPath"]


def test_layer_slots_wrap_around_the_xcs_palette(tmp_path):
    """XCS has 8 layer colours; a 9th LightBurn layer must reuse one, not crash."""
    body = "".join(
        f'<CutSetting type="Cut"><index Value="{i}"/><name Value="L{i}"/></CutSetting>'
        for i in range(9)
    ) + "".join(
        f'<Shape Type="Rect" CutIndex="{i}" W="5" H="5" Cr="0">'
        f"<XForm>1 0 0 1 {i * 10} 0</XForm></Shape>"
        for i in range(9)
    )
    doc = project_to_xcs_dict(make_project(tmp_path, body))
    assert len(displays(doc)) == 9
    assert len(doc["canvas"][0]["layerData"]) == 8  # 9th wraps onto the first


def test_empty_project_produces_a_valid_empty_canvas(tmp_path):
    body = '<CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>'
    doc = project_to_xcs_dict(make_project(tmp_path, body))
    assert displays(doc) == []
    assert doc["canvas"][0]["layerData"] == {}


def test_ids_are_unique_per_display(tmp_path):
    doc = project_to_xcs_dict(make_project(tmp_path))
    ids = [d["id"] for d in displays(doc)]
    assert len(set(ids)) == len(ids)
    assert doc["canvasId"] not in ids
