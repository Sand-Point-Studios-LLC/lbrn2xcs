"""Smoke tests for the CLI scaffold."""

from pathlib import Path

from lbrn2xcs.cli import _find_inputs, main


def test_find_inputs_filters_lightburn(tmp_path: Path):
    (tmp_path / "a.lbrn").write_text("x")
    (tmp_path / "b.lbrn2").write_text("x")
    (tmp_path / "c.txt").write_text("x")
    found = _find_inputs(tmp_path, recursive=False)
    assert {p.name for p in found} == {"a.lbrn", "b.lbrn2"}


def test_main_reports_found_files(tmp_path: Path, capsys):
    (tmp_path / "proj.lbrn").write_text("x")
    rc = main([str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Found 1 LightBurn file" in out


def test_main_no_files_returns_1(tmp_path: Path):
    assert main([str(tmp_path)]) == 1
