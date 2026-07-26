"""Parser tests.

The fixtures here are hand-written minimal LightBurn documents that reproduce
the exact encodings observed in the real corpus — the compact VertList/PrimList
form, the VertID/PrimID dedupe references, nested Group transforms, and Text
with a BackupPath.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from lbrn2xcs.lbrn import parse_lbrn, parse_vertlist
from lbrn2xcs.model import mat_mul

HEADER = '<?xml version="1.0" encoding="UTF-8"?>\n<LightBurnProject AppVersion="1.7.03">'
FOOTER = "</LightBurnProject>"

CUT_SETTING = """
  <CutSetting type="Cut">
    <index Value="0"/>
    <name Value="Outline"/>
    <maxPower Value="90"/>
    <speed Value="20"/>
  </CutSetting>
  <CutSetting type="Scan">
    <index Value="1"/>
    <name Value="Fill"/>
    <maxPower Value="30"/>
    <speed Value="200"/>
    <doOutput Value="0"/>
    <hide Value="1"/>
  </CutSetting>
"""


def write(tmp_path: Path, body: str, name: str = "t.lbrn2") -> Path:
    path = tmp_path / name
    path.write_text(f"{HEADER}{body}{FOOTER}", encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# VertList decoding
# --------------------------------------------------------------------------


def test_vertlist_bare_handle_flag_is_not_a_control_point():
    """`c0x1` with no `c0y` is LightBurn's "no handle" placeholder, not x=1."""
    verts = parse_vertlist("V10 20c0x1c1x1V30 40c0x1c1x1")
    assert [v.p for v in verts] == [(10.0, 20.0), (30.0, 40.0)]
    assert all(v.c0 is None and v.c1 is None for v in verts)


def test_vertlist_reads_full_handle_pairs():
    verts = parse_vertlist("V10 20c0x11c0y21c1x9c1y19")
    assert verts[0].p == (10.0, 20.0)
    assert verts[0].c0 == (11.0, 21.0)
    assert verts[0].c1 == (9.0, 19.0)


def test_vertlist_handles_negatives_and_exponents():
    verts = parse_vertlist("V-1.5 2e2c0x1c1x1")
    assert verts[0].p == (-1.5, 200.0)


# --------------------------------------------------------------------------
# Primitives
# --------------------------------------------------------------------------


def test_line_closed_shorthand_closes_the_contour(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x1c1x1V10 0c0x1c1x1V10 10c0x1c1x1</VertList>
    <PrimList>LineClosed</PrimList>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    (contour,) = project.shapes[0].contours
    assert contour.closed is True
    assert contour.start == (0.0, 0.0)
    assert [s.end for s in contour.segments] == [(10.0, 0.0), (10.0, 10.0)]


def test_bezier_uses_c0_of_start_and_c1_of_end(tmp_path):
    """`c0` is the outgoing handle, `c1` the incoming one.

    Getting this backwards produces visible spurs at every vertex, so pin it down.
    """
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x2c0y5c1x-2c1y-5V10 0c0x12c0y5c1x8c1y-5</VertList>
    <PrimList>B0 1</PrimList>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    (contour,) = project.shapes[0].contours
    (seg,) = contour.segments
    assert seg.kind == "C"
    assert seg.c1 == (2.0, 5.0)  # vertex 0's outgoing handle
    assert seg.c2 == (8.0, -5.0)  # vertex 1's incoming handle
    assert seg.end == (10.0, 0.0)


def test_prim_list_splits_disjoint_contours(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0">
    <VertList>V0 0c0x1c1x1V1 0c0x1c1x1V5 5c0x1c1x1V6 5c0x1c1x1</VertList>
    <PrimList>L0 1L2 3</PrimList>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    contours = project.shapes[0].contours
    assert len(contours) == 2
    assert contours[0].start == (0.0, 0.0)
    assert contours[1].start == (5.0, 5.0)


# --------------------------------------------------------------------------
# VertID / PrimID dedupe
# --------------------------------------------------------------------------


def test_vertid_reference_reuses_earlier_geometry(tmp_path):
    """Shapes 2..n carry only an XForm and point at an earlier VertID."""
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0" VertID="7" PrimID="3">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x1c1x1V10 0c0x1c1x1V10 10c0x1c1x1</VertList>
    <PrimList>LineClosed</PrimList>
  </Shape>
  <Shape Type="Path" CutIndex="0" VertID="7" PrimID="3">
    <XForm>1 0 0 1 100 200</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert len(project.shapes) == 2
    first, second = project.shapes
    assert first.contours[0].start == (0.0, 0.0)
    assert second.contours[0].start == (100.0, 200.0)
    assert second.contours[0].closed is True


def test_vertid_defined_after_first_use_still_resolves(tmp_path):
    """Definitions are collected in a pre-pass, so a forward reference works."""
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0" VertID="4" PrimID="1">
    <XForm>1 0 0 1 100 200</XForm>
  </Shape>
  <Shape Type="Path" CutIndex="0" VertID="4" PrimID="1">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V0 0c0x1c1x1V10 0c0x1c1x1V10 10c0x1c1x1</VertList>
    <PrimList>LineClosed</PrimList>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert len(project.shapes) == 2
    assert project.shapes[0].contours[0].start == (100.0, 200.0)
    assert project.skipped == {}


def test_single_vertex_path_has_nothing_to_draw(tmp_path):
    """Real files contain stray one-point 'paths'; report them, don't emit them."""
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0">
    <XForm>1 0 0 1 0 0</XForm>
    <VertList>V5 5c0x1c1x1</VertList>
    <PrimList>LineClosed</PrimList>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.shapes == []
    assert project.skipped == {"Path": 1}


def test_unknown_vertid_reference_is_reported_not_crashed(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Path" CutIndex="0" VertID="99">
    <XForm>1 0 0 1 0 0</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.shapes == []
    assert project.skipped.get("Path") == 1


# --------------------------------------------------------------------------
# Transforms
# --------------------------------------------------------------------------


def test_group_transform_composes_with_child(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Group" CutIndex="0">
    <XForm>2 0 0 2 5 5</XForm>
    <Children>
      <Shape Type="Rect" CutIndex="0" W="10" H="10" Cr="0">
        <XForm>1 0 0 1 10 0</XForm>
      </Shape>
    </Children>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    min_x, min_y, max_x, max_y = project.bbox()
    # Rect is origin-centred (-5..5), shifted +10 in x, then scaled x2 and
    # translated by (5, 5): x spans (10-5)*2+5 .. (10+5)*2+5 = 15..35.
    assert (min_x, max_x) == (15.0, 35.0)
    assert (min_y, max_y) == (-5.0, 15.0)


def test_matrix_composition_matches_svg_convention():
    scale = (2.0, 0.0, 0.0, 3.0, 0.0, 0.0)
    translate = (1.0, 0.0, 0.0, 1.0, 10.0, 20.0)
    # Apply translate first, then scale.
    assert mat_mul(scale, translate) == (2.0, 0.0, 0.0, 3.0, 20.0, 60.0)


def test_rotated_xform_is_applied(tmp_path):
    """A quarter-turn XForm must move geometry, not just scale it."""
    body = f"""{CUT_SETTING}
  <Shape Type="Rect" CutIndex="0" W="20" H="10" Cr="0">
    <XForm>0 1 -1 0 0 0</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    min_x, min_y, max_x, max_y = project.bbox()
    assert (max_x - min_x, max_y - min_y) == (10.0, 20.0)


# --------------------------------------------------------------------------
# Shape primitives
# --------------------------------------------------------------------------


def test_ellipse_extent_matches_radii(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Ellipse" CutIndex="0" Rx="30" Ry="10">
    <XForm>1 0 0 1 100 50</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    min_x, min_y, max_x, max_y = project.bbox()
    # Tight bbox: bezier extrema, not control points, so this is exact.
    assert math.isclose(max_x - min_x, 60.0, abs_tol=1e-6)
    assert math.isclose(max_y - min_y, 20.0, abs_tol=1e-6)
    assert math.isclose((min_x + max_x) / 2, 100.0, abs_tol=1e-6)
    assert math.isclose((min_y + max_y) / 2, 50.0, abs_tol=1e-6)


def test_rounded_rect_stays_within_its_bounds(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="5">
    <XForm>1 0 0 1 0 0</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    min_x, min_y, max_x, max_y = project.bbox()
    assert math.isclose(max_x - min_x, 40.0, abs_tol=1e-6)
    assert math.isclose(max_y - min_y, 20.0, abs_tol=1e-6)


# --------------------------------------------------------------------------
# Layers and unsupported shapes
# --------------------------------------------------------------------------


def test_cut_settings_become_layers_with_palette_colors(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Rect" CutIndex="1" W="10" H="10" Cr="0"><XForm>1 0 0 1 0 0</XForm></Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.layers[0].name == "Outline"
    assert project.layers[0].kind == "Cut"
    assert project.layers[0].color == "#000000"
    assert project.layers[0].max_power == 90
    assert project.layers[1].kind == "Scan"
    assert project.layers[1].color == "#0000FF"
    assert project.layers[1].output is False
    assert project.layers[1].hidden is True


def test_cut_index_without_cut_setting_still_gets_a_layer(tmp_path):
    body = """
  <Shape Type="Rect" CutIndex="5" W="10" H="10" Cr="0"><XForm>1 0 0 1 0 0</XForm></Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.layers[5].name == "C05"
    assert project.layers[5].color == "#FF8000"


def test_text_is_converted_through_its_backup_path(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Text" CutIndex="0" Str="hi" HasBackupPath="1">
    <BackupPath Type="Path" CutIndex="0">
      <XForm>1 0 0 1 3 4</XForm>
      <VertList>V0 0c0x1c1x1V10 0c0x1c1x1</VertList>
      <PrimList>L0 1</PrimList>
    </BackupPath>
    <XForm>1 0 0 1 0 0</XForm>
  </Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert len(project.shapes) == 1
    assert project.shapes[0].contours[0].start == (3.0, 4.0)
    assert project.skipped == {}


def test_text_without_backup_path_is_reported(tmp_path):
    body = f"""{CUT_SETTING}
  <Shape Type="Text" CutIndex="0" Str="hi"><XForm>1 0 0 1 0 0</XForm></Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.shapes == []
    assert project.skipped == {"Text (no BackupPath)": 1}


@pytest.mark.parametrize("kind", ["Bitmap", "QrCode"])
def test_raster_and_generated_shapes_are_reported_as_skipped(tmp_path, kind):
    body = f"""{CUT_SETTING}
  <Shape Type="{kind}" CutIndex="0" W="10" H="10"><XForm>1 0 0 1 0 0</XForm></Shape>"""
    project = parse_lbrn(write(tmp_path, body))
    assert project.shapes == []
    assert project.skipped == {kind: 1}


def test_empty_project_has_zero_bbox(tmp_path):
    project = parse_lbrn(write(tmp_path, CUT_SETTING))
    assert project.bbox() == (0.0, 0.0, 0.0, 0.0)
    assert project.used_layers() == []
