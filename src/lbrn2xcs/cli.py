"""Command-line entry point for lbrn2xcs.

    lbrn2xcs INPUT [--out DIR] [--format svg|dxf|both] [--recursive]

INPUT is a ``.lbrn``/``.lbrn2`` file or a folder of them. Output mirrors the input
folder structure under ``--out`` when recursing, so a nested library converts in
one pass without collapsing everything into a single directory.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from .lbrn import parse_lbrn
from .model import Project
from .svg_out import project_to_svg

SUFFIXES = (".lbrn", ".lbrn2")


def _find_inputs(root: Path, recursive: bool) -> list[Path]:
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    return sorted(p for p in root.glob(pattern) if p.suffix.lower() in SUFFIXES)


def _output_path(source: Path, input_root: Path, out_dir: Path | None, suffix: str) -> Path:
    """Where *source* should be written, mirroring its path under *input_root*.

    Purely a path computation — it never touches the filesystem, so a single-file
    input (where *source* and *input_root* are the same path) lands flat in
    *out_dir* rather than trying to relativise a path against itself.
    """
    if out_dir is None:
        return source.with_suffix(suffix)
    relative = Path(source.name)
    if source != input_root:
        try:
            candidate = source.relative_to(input_root)
        except ValueError:
            candidate = Path(source.name)
        if candidate.name:
            relative = candidate
    return out_dir / relative.with_suffix(suffix)


def _summarise(project: Project) -> str:
    min_x, min_y, max_x, max_y = project.bbox()
    layers = ",".join(f"C{layer.index:02d}" for layer in project.used_layers())
    parts = [
        f"{len(project.shapes)} shapes",
        f"{max_x - min_x:.1f}x{max_y - min_y:.1f}mm",
        f"layers [{layers}]" if layers else "no layers",
    ]
    if project.skipped:
        parts.append(
            "skipped " + ", ".join(f"{k}x{v}" for k, v in sorted(project.skipped.items()))
        )
    return "  ".join(parts)


def convert_one(
    source: Path,
    input_root: Path,
    out_dir: Path | None,
    formats: tuple[str, ...],
    tolerance: float,
) -> tuple[Project, list[Path]]:
    project = parse_lbrn(source)
    written: list[Path] = []

    if "svg" in formats:
        target = _output_path(source, input_root, out_dir, ".svg")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(project_to_svg(project, title=source.stem), encoding="utf-8")
        written.append(target)

    if "dxf" in formats:
        from .dxf_out import write_dxf  # lazy: only needed when DXF is requested

        target = _output_path(source, input_root, out_dir, ".dxf")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_dxf(project, target, tolerance=tolerance)
        written.append(target)

    if "xcs" in formats:
        from .xcs_out import write_xcs

        target = _output_path(source, input_root, out_dir, ".xcs")
        target.parent.mkdir(parents=True, exist_ok=True)
        write_xcs(project, target, title=source.stem)
        written.append(target)

    return project, written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lbrn2xcs",
        description="Batch-convert LightBurn (.lbrn/.lbrn2) projects toward XCS.",
    )
    parser.add_argument("input", type=Path, help="A .lbrn/.lbrn2 file or a folder of them")
    parser.add_argument(
        "--out", type=Path, default=None, help="Output directory (default: alongside each input)"
    )
    parser.add_argument(
        "--format",
        choices=("svg", "dxf", "xcs", "both", "all"),
        default="svg",
        help=(
            "Output format(s). 'both' = svg+dxf. 'xcs' writes native XCS project "
            "files and is EXPERIMENTAL — verify one opens in your XCS build before "
            "trusting a batch (see docs/plan.md)."
        ),
    )
    parser.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="DXF bezier flattening tolerance in mm (default: 0.05)",
    )
    parser.add_argument("--quiet", action="store_true", help="Only report failures")
    args = parser.parse_args(argv)

    if not args.input.exists():
        parser.error(f"input not found: {args.input}")

    formats: tuple[str, ...] = {
        "both": ("svg", "dxf"),
        "all": ("svg", "dxf", "xcs"),
    }.get(args.format, (args.format,))

    inputs = _find_inputs(args.input, args.recursive)
    if not inputs:
        print("No .lbrn/.lbrn2 files found.", file=sys.stderr)
        return 1

    if not args.quiet:
        print(f"Converting {len(inputs)} file(s) to {'/'.join(formats)}")

    failures: list[tuple[Path, str]] = []
    empty: list[Path] = []
    for source in inputs:
        try:
            project, written = convert_one(
                source, args.input, args.out, formats, args.tolerance
            )
        except Exception as exc:  # noqa: BLE001 — one bad file must not stop a batch
            failures.append((source, f"{type(exc).__name__}: {exc}"))
            print(f"  FAIL {source.name}: {type(exc).__name__}: {exc}", file=sys.stderr)
            if not args.quiet:
                traceback.print_exc(limit=3, file=sys.stderr)
            continue

        if not project.shapes:
            empty.append(source)
        if not args.quiet:
            names = ", ".join(p.name for p in written)
            print(f"  {source.name} -> {names}")
            print(f"      {_summarise(project)}")

    ok = len(inputs) - len(failures)
    print(f"\nDone: {ok}/{len(inputs)} converted.")
    if empty:
        print(f"{len(empty)} file(s) produced no geometry:")
        for source in empty[:10]:
            print(f"  - {source}")
        if len(empty) > 10:
            print(f"  ... and {len(empty) - 10} more")
    if failures:
        print(f"{len(failures)} failure(s):", file=sys.stderr)
        for source, message in failures:
            print(f"  - {source}: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
