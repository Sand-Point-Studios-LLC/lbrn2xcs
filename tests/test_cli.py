"""CLI tests."""

from __future__ import annotations

from pathlib import Path

from lbrn2xcs.cli import _find_inputs, _output_path, main

MINIMAL = """<?xml version="1.0" encoding="UTF-8"?>
<LightBurnProject AppVersion="1.7.03">
  <CutSetting type="Cut"><index Value="0"/><name Value="Outline"/></CutSetting>
  <Shape Type="Rect" CutIndex="0" W="40" H="20" Cr="0"><XForm>1 0 0 1 20 10</XForm></Shape>
</LightBurnProject>
"""

BROKEN = "<?xml version='1.0'?><LightBurnProject><Shape Type='Rect' W='oops'"


def make(path: Path, content: str = MINIMAL) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Input discovery
# --------------------------------------------------------------------------


def test_find_inputs_filters_lightburn(tmp_path: Path):
    make(tmp_path / "a.lbrn")
    make(tmp_path / "b.lbrn2")
    (tmp_path / "c.txt").write_text("x")
    found = _find_inputs(tmp_path, recursive=False)
    assert {p.name for p in found} == {"a.lbrn", "b.lbrn2"}


def test_find_inputs_is_case_insensitive(tmp_path: Path):
    make(tmp_path / "A.LBRN2")
    assert [p.name for p in _find_inputs(tmp_path, recursive=False)] == ["A.LBRN2"]


def test_find_inputs_only_recurses_when_asked(tmp_path: Path):
    make(tmp_path / "top.lbrn2")
    make(tmp_path / "nested" / "deep.lbrn2")
    assert len(_find_inputs(tmp_path, recursive=False)) == 1
    assert len(_find_inputs(tmp_path, recursive=True)) == 2


def test_find_inputs_accepts_a_single_file(tmp_path: Path):
    target = make(tmp_path / "one.lbrn2")
    assert _find_inputs(target, recursive=False) == [target]


# --------------------------------------------------------------------------
# Output paths
# --------------------------------------------------------------------------


def test_output_path_defaults_alongside_input(tmp_path: Path):
    source = tmp_path / "sub" / "x.lbrn2"
    assert _output_path(source, tmp_path, None, ".svg") == tmp_path / "sub" / "x.svg"


def test_output_path_mirrors_folder_structure(tmp_path: Path):
    source = tmp_path / "a" / "b" / "x.lbrn2"
    out = tmp_path / "out"
    assert _output_path(source, tmp_path, out, ".svg") == out / "a" / "b" / "x.svg"


def test_output_path_for_single_file_input_is_flat(tmp_path: Path):
    source = tmp_path / "x.lbrn2"
    out = tmp_path / "out"
    assert _output_path(source, source, out, ".dxf") == out / "x.dxf"


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_main_converts_a_folder_to_svg(tmp_path: Path, capsys):
    make(tmp_path / "in" / "proj.lbrn2")
    out = tmp_path / "out"
    assert main([str(tmp_path / "in"), "--out", str(out)]) == 0
    svg = (out / "proj.svg").read_text(encoding="utf-8")
    assert 'width="40mm"' in svg
    assert "Done: 1/1 converted." in capsys.readouterr().out


def test_main_both_formats_writes_svg_and_dxf(tmp_path: Path):
    make(tmp_path / "in" / "proj.lbrn2")
    out = tmp_path / "out"
    assert main([str(tmp_path / "in"), "--out", str(out), "--format", "both"]) == 0
    assert (out / "proj.svg").exists()
    assert (out / "proj.dxf").exists()


def test_main_recursive_mirrors_structure(tmp_path: Path):
    make(tmp_path / "in" / "deep" / "proj.lbrn2")
    out = tmp_path / "out"
    assert main([str(tmp_path / "in"), "--out", str(out), "--recursive"]) == 0
    assert (out / "deep" / "proj.svg").exists()


def test_main_no_files_returns_1(tmp_path: Path):
    assert main([str(tmp_path)]) == 1


def test_main_reports_shapes_and_layers(tmp_path: Path, capsys):
    make(tmp_path / "proj.lbrn2")
    main([str(tmp_path / "proj.lbrn2"), "--out", str(tmp_path / "out")])
    out = capsys.readouterr().out
    assert "1 shapes" in out
    assert "40.0x20.0mm" in out
    assert "layers [C00]" in out


def test_main_keeps_going_after_a_bad_file_and_exits_1(tmp_path: Path, capsys):
    """One unparseable project must not abandon the rest of a 400-file batch."""
    make(tmp_path / "in" / "good.lbrn2")
    make(tmp_path / "in" / "bad.lbrn2", BROKEN)
    out = tmp_path / "out"
    assert main([str(tmp_path / "in"), "--out", str(out), "--quiet"]) == 1
    assert (out / "good.svg").exists()
    captured = capsys.readouterr()
    assert "bad.lbrn2" in captured.err
    assert "Done: 1/2 converted." in captured.out


def test_main_flags_files_that_produced_no_geometry(tmp_path: Path, capsys):
    empty = """<?xml version="1.0"?><LightBurnProject AppVersion="1.7.03">
      <CutSetting type="Cut"><index Value="0"/><name Value="L"/></CutSetting>
      </LightBurnProject>"""
    make(tmp_path / "in" / "empty.lbrn2", empty)
    assert main([str(tmp_path / "in"), "--out", str(tmp_path / "out"), "--quiet"]) == 0
    assert "1 file(s) produced no geometry" in capsys.readouterr().out
