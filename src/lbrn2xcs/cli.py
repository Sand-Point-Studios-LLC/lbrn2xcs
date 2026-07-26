"""Command-line entry point for lbrn2xcs.

Scaffold only — the conversion is not implemented yet. See docs/plan.md.
Usage shape (planned):

    lbrn2xcs INPUT [--out OUT_DIR] [--format svg|dxf|xcs] [--recursive]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_inputs(root: Path, recursive: bool) -> list[Path]:
    if root.is_file():
        return [root]
    pattern = "**/*" if recursive else "*"
    return sorted(
        p for p in root.glob(pattern) if p.suffix.lower() in (".lbrn", ".lbrn2")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lbrn2xcs",
        description="Batch-convert LightBurn (.lbrn/.lbrn2) projects toward XCS.",
    )
    parser.add_argument("input", type=Path, help="A .lbrn/.lbrn2 file or a folder of them")
    parser.add_argument("--out", type=Path, default=None, help="Output directory (default: alongside input)")
    parser.add_argument(
        "--format",
        choices=("svg", "dxf", "xcs"),
        default="svg",
        help="Output format. 'xcs' is experimental (see docs/plan.md).",
    )
    parser.add_argument("--recursive", action="store_true", help="Recurse into subfolders")
    args = parser.parse_args(argv)

    if not args.input.exists():
        parser.error(f"input not found: {args.input}")

    inputs = _find_inputs(args.input, args.recursive)
    if not inputs:
        print("No .lbrn/.lbrn2 files found.", file=sys.stderr)
        return 1

    print(f"Found {len(inputs)} LightBurn file(s). Target format: {args.format}")
    for p in inputs:
        print(f"  - {p}")
    print(
        "\nConversion is not implemented yet — this is the project scaffold.\n"
        "See docs/plan.md for the Tier A (SVG/DXF) and Tier B (native .xcs) plan."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
