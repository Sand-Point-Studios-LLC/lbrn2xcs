"""Native .xcs writer tests.

The invariants asserted here are the ones measured across 5,995 displays in real
XCS-written files (see the module docstring in ``xcs_out``). They are what makes
the output loadable, so they are checked on the writer's own output rather than
trusted.
"""

from __future__ import annotations

import json
import math

import pytest
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
    assert doc["device"]["id"] == "P3"
    assert doc["extId"] == doc["extName"] == "P3"


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
    # LightBurn palette colours pass straight through: C00 black, C02 red.
    assert list(layer_data) == ["#000000", "#ff0000"]
    assert [meta["order"] for meta in layer_data.values()] == [1, 2]
    assert [meta["name"] for meta in layer_data.values()] == ["#000000", "#FF0000"]
    assert {d["layerTag"] for d in ds} == {"#000000", "#ff0000"}
    assert all(d["layerTag"] == d["layerColor"] == d["originColor"] for d in ds)


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
        assert d["y"] == d["graphicY"] + sy * min_y
        assert math.isclose(d["width"], (max_x - min_x) * sx, abs_tol=1e-9)
        assert math.isclose(d["height"], (max_y - min_y) * sy, abs_tol=1e-9)
        assert d["offsetX"] == d["graphicX"]
        assert d["offsetY"] == d["graphicY"]


def test_displays_are_unskewed(tmp_path):
    """A plain import has skew 0; only mirrored art carries skew.x = pi."""
    doc = project_to_xcs_dict(make_project(tmp_path))
    for d in displays(doc):
        assert d["skew"] == {"x": 0, "y": 0}
        assert d["localSkew"] == d["skew"]
        assert d["angle"] == 0
        assert d["scale"] == {"x": 1, "y": 1}


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
        ys += [d["graphicY"] + sy * min_y, d["graphicY"] + sy * max_y]

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
        return (d["graphicY"] + d["scale"]["y"] * min_y,
                d["graphicY"] + d["scale"]["y"] * max_y)

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


def test_every_lightburn_layer_gets_its_own_xcs_layer(tmp_path):
    """No palette to run out of: nine LightBurn layers means nine XCS layers."""
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
    assert len(doc["canvas"][0]["layerData"]) == 9


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


# --------------------------------------------------------------------------
# Conformance against a real file saved by XCS
# --------------------------------------------------------------------------

PROBE = Path(__file__).resolve().parents[1] / "samples" / "probe" / "xcs_probe.xcs"


def load_probe() -> dict:
    if not PROBE.exists():
        pytest.skip(
            "no samples/probe/xcs_probe.xcs — regenerate with tools/make_probe_svg.py, "
            "import into XCS and save"
        )
    return json.loads(PROBE.read_text(encoding="utf-8"))


def test_probe_confirms_the_transform_formula():
    """The formula must hold on XCS's own output, not just on ours."""
    doc = load_probe()
    paths = [d for d in displays(doc) if d.get("type") == "PATH"]
    assert paths, "probe should contain PATH displays"
    for d in paths:
        min_x, min_y, max_x, max_y = contours_bbox(parse_path_data(d["dPath"]))
        sx, sy = d["scale"]["x"], d["scale"]["y"]
        assert math.isclose(d["x"], d["graphicX"] + sx * min_x, abs_tol=1e-6)
        assert math.isclose(d["y"], d["graphicY"] + sy * min_y, abs_tol=1e-6)
        assert math.isclose(d["width"], (max_x - min_x) * sx, abs_tol=1e-6)
        assert math.isclose(d["height"], (max_y - min_y) * sy, abs_tol=1e-6)
        assert d["skew"] == {"x": 0, "y": 0}


def test_probe_keeps_imported_path_data_verbatim():
    """XCS stores an imported SVG's path data unchanged — so we can write it directly."""
    doc = load_probe()
    paths = {d["dPath"] for d in displays(doc) if d.get("type") == "PATH"}
    assert "M60,110 C80,70 110,110 130,80" in paths  # the probe's bezier
    assert "M10,110 L10,80 L40,80" in paths  # the probe's L-bracket


def test_probe_creates_one_layer_per_stroke_color():
    """XCS does not snap to a fixed palette, so LightBurn colours can pass through."""
    doc = load_probe()
    layer_data = doc["canvas"][0]["layerData"]
    assert set(layer_data) == {"#000000", "#fe0002", "#2366ff", "#00c715", "#e1c000"}
    for color, meta in layer_data.items():
        assert meta["name"] == color.upper()


def test_our_displays_use_only_fields_xcs_writes(tmp_path):
    """Every key we emit must appear on a real XCS PATH display."""
    probe_keys: set[str] = set()
    for d in displays(load_probe()):
        if d.get("type") == "PATH":
            probe_keys |= set(d)
    ours: set[str] = set()
    for d in displays(project_to_xcs_dict(make_project(tmp_path))):
        ours |= set(d)
    assert ours - probe_keys == set()


def test_our_document_uses_only_top_level_keys_xcs_writes(tmp_path):
    probe = load_probe()
    ours = project_to_xcs_dict(make_project(tmp_path))
    assert set(ours) - set(probe) == set()
    assert set(ours["device"]) - set(probe["device"]) == set()
    assert set(ours["canvas"][0]) - set(probe["canvas"][0]) == set()


def _first_process_entry(doc: dict) -> dict:
    return doc["device"]["data"]["value"][0][1]["displays"]["value"][0][1]


def test_our_process_defaults_match_what_xcs_writes(tmp_path):
    """With translation off, the device block is byte-identical to XCS's own."""
    probe_entry = _first_process_entry(load_probe())
    ours = project_to_xcs_dict(make_project(tmp_path), source_machine=None)
    our_entry = _first_process_entry(ours)
    assert set(our_entry) == set(probe_entry)
    assert our_entry["data"] == probe_entry["data"]


def test_translated_settings_keep_xcs_structure_and_only_change_values(tmp_path):
    """With translation on, the shape of the block is unchanged — only numbers."""
    probe_entry = _first_process_entry(load_probe())
    our_entry = _first_process_entry(project_to_xcs_dict(make_project(tmp_path)))

    assert set(our_entry) == set(probe_entry)
    assert set(our_entry["data"]) == set(probe_entry["data"])
    for op, block in our_entry["data"].items():
        ours = block["parameter"]["customize"]
        theirs = probe_entry["data"][op]["parameter"]["customize"]
        assert set(ours) == set(theirs), f"{op} gained or lost a parameter"

    # The live operation's numbers must actually have been translated.
    live = our_entry["data"][our_entry["processingType"]]["parameter"]["customize"]
    default = probe_entry["data"][our_entry["processingType"]]["parameter"]["customize"]
    assert (live["power"], live["speed"]) != (default["power"], default["speed"])
