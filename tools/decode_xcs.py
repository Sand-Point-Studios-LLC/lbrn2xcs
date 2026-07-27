"""Decode a .xcs file into a readable report — the Tier B reverse-engineering tool.

Point this at a ``.xcs`` saved by XCS (ideally one produced by importing
``samples/probe/xcs_probe.svg``, whose real-world geometry we know exactly) and
it prints the structure without drowning you in the multi-megabyte path data:

* file/app version, target machine, canvas metadata
* the layer table and which colours XCS assigned
* per-display transform fields, with the effective placement worked out
* per-display processing parameters from the ``device`` block
* an SVG rendering of the displays, so you can *see* whether your
  interpretation of the coordinates is right

Usage:
    python tools/decode_xcs.py FILE.xcs [--limit N] [--svg OUT.svg] [--full]
"""

from __future__ import annotations

import argparse
import collections
import json
import math
from pathlib import Path
from typing import Any

TRANSFORM_KEYS = (
    "x",
    "y",
    "width",
    "height",
    "angle",
    "offsetX",
    "offsetY",
    "graphicX",
    "graphicY",
    "zOrder",
)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        if abs(v) < 1e-9:
            return "0"
        return f"{v:.6g}"
    return str(v)


def describe_header(doc: dict) -> None:
    print("=" * 78)
    print("HEADER")
    print("=" * 78)
    for key in (
        "version",
        "extId",
        "extName",
        "minRequiredVersion",
        "appMinRequiredVersion",
        "webMinRequiredVersion",
        "created",
        "modify",
        "ua",
    ):
        if key in doc:
            val = doc[key]
            if key in ("created", "modify") and isinstance(val, int):
                # milliseconds since epoch
                secs = val / 1000.0
                val = f"{val}  (epoch ms)"
                del secs
            print(f"  {key:24} {val}")
    print(f"  top-level keys           {list(doc.keys())}")
    dev = doc.get("device") or {}
    if dev:
        print(f"  device.id                {dev.get('id')}")
        print(f"  device.power             {dev.get('power')}")
        print(f"  device keys              {list(dev.keys())}")


def describe_canvas(canvas: dict, index: int) -> list[dict]:
    print()
    print("=" * 78)
    print(f"CANVAS[{index}]  id={canvas.get('id')}  title={canvas.get('title')!r}")
    print("=" * 78)
    layer_data = canvas.get("layerData") or {}
    print(f"  layers ({len(layer_data)}):")
    for color, meta in layer_data.items():
        print(f"    {color:10} order={meta.get('order'):<4} name={meta.get('name')!r} "
              f"visible={meta.get('visible')}")
    group_data = canvas.get("groupData") or {}
    print(f"  groupData: {len(group_data)} group(s)")
    for gid, meta in list(group_data.items())[:5]:
        print(f"    {gid}: {json.dumps(meta)[:160]}")
    ext = canvas.get("extendInfo")
    print(f"  extendInfo: {json.dumps(ext)[:300] if ext else None}")

    displays = canvas.get("displays") or []
    print(f"  displays: {len(displays)}")
    print(f"    types: {collections.Counter(d.get('type') for d in displays).most_common()}")
    print(f"    per-layer: {collections.Counter(d.get('layerTag') for d in displays).most_common()}")
    return displays


def describe_displays(displays: list[dict], limit: int, full: bool) -> None:
    print()
    print("=" * 78)
    print(f"DISPLAYS (showing {min(limit, len(displays))} of {len(displays)})")
    print("=" * 78)
    for d in displays[:limit]:
        print(f"\n  --- {d.get('type')}  id={d.get('id')}  name={d.get('name')!r} "
              f"layer={d.get('layerTag')} origColor={d.get('originColor')}")
        vals = {k: d.get(k) for k in TRANSFORM_KEYS if k in d}
        print("      " + "  ".join(f"{k}={_fmt(v)}" for k, v in vals.items()))
        for key in ("scale", "skew", "localSkew", "pivot"):
            if key in d:
                s = d[key]
                print(f"      {key}: x={_fmt(s.get('x'))} y={_fmt(s.get('y'))}"
                      + (f"   [x={_fmt(math.degrees(s['x']))}deg y={_fmt(math.degrees(s['y']))}deg]"
                         if key in ("skew", "localSkew") and isinstance(s.get("x"), (int, float))
                         else ""))
        for key in ("isClosePath", "isFill", "isCompoundPath", "fillRule", "lockRatio",
                    "radius", "maxRadius", "groupTag", "resourceOrigin", "minCanvasVersion"):
            if key in d:
                print(f"      {key}: {_fmt(d[key])}")
        for key in ("stroke", "fill"):
            if key in d:
                print(f"      {key}: {json.dumps(d[key])}")
        if "points" in d and d["points"]:
            pts = d["points"]
            print(f"      points: {len(pts)} -> {json.dumps(pts[:4])}")
        dpath = d.get("dPath")
        if dpath is not None:
            print(f"      dPath ({len(dpath)} chars):")
            print(f"        {dpath if full else dpath[:400]}")
        # Anything we did not explicitly print
        known = set(TRANSFORM_KEYS) | {
            "scale", "skew", "localSkew", "pivot", "isClosePath", "isFill", "isCompoundPath",
            "fillRule", "lockRatio", "radius", "maxRadius", "groupTag", "resourceOrigin",
            "minCanvasVersion", "stroke", "fill", "points", "dPath", "type", "id", "name",
            "layerTag", "originColor",
        }
        extra = {k: v for k, v in d.items() if k not in known}
        if extra:
            print(f"      other: {json.dumps(extra)[:400]}")


def describe_device_processing(doc: dict, limit: int) -> None:
    dev = doc.get("device") or {}
    entries = ((dev.get("data") or {}).get("value")) or []
    if not entries:
        print()
        print("(no device processing block — this .xcs has no machine settings attached)")
        return
    print()
    print("=" * 78)
    print("DEVICE PROCESSING")
    print("=" * 78)
    for canvas_id, cfg in entries:
        print(f"\n  canvas {canvas_id}  mode={cfg.get('mode')}")
        for mode, mode_cfg in (cfg.get("data") or {}).items():
            printable = {k: v for k, v in mode_cfg.items() if not isinstance(v, (dict, list))}
            print(f"    mode {mode}: {json.dumps(printable)[:500]}")
        per_display = ((cfg.get("displays") or {}).get("value")) or []
        print(f"    per-display entries: {len(per_display)}")
        counts = collections.Counter(e[1].get("processingType") for e in per_display)
        print(f"    processingType: {counts.most_common()}")
        for display_id, entry in per_display[:limit]:
            print(f"\n      display {display_id}")
            print(f"        processingType={entry.get('processingType')} "
                  f"isFill={entry.get('isFill')} type={entry.get('type')} "
                  f"processIgnore={entry.get('processIgnore')}")
            for ptype, pdata in (entry.get("data") or {}).items():
                params = (pdata.get("parameter") or {}).get("customize")
                if params is None:
                    params = pdata.get("parameter")
                print(f"        {ptype}: materialType={pdata.get('materialType')} "
                      f"planType={pdata.get('planType')}")
                print(f"          {json.dumps(params)[:400]}")


def render_svg(displays: list[dict], out_path: Path) -> None:
    """Re-render the displays as SVG using the confirmed transform.

        canvas_x = graphicX + scale.x * local_x
        canvas_y = graphicY + scale.y * local_y

    with the Y term negated when the display carries skew.x = π (a vertical
    mirror). If this render matches what XCS shows on its canvas, the reading is
    right; where it doesn't, the difference is the clue.
    """
    body: list[str] = []
    bounds: list[tuple[float, float]] = []
    for d in displays:
        dpath = d.get("dPath")
        if not dpath:
            continue
        sx = (d.get("scale") or {}).get("x", 1) or 1
        sy = (d.get("scale") or {}).get("y", 1) or 1
        gx, gy = d.get("graphicX", 0), d.get("graphicY", 0)
        angle = d.get("angle", 0) or 0
        color = d.get("layerColor") or "#000000"
        mirrored = abs((d.get("skew") or {}).get("x", 0) - math.pi) < 1e-6

        parts = [f"translate({gx},{gy})"]
        if angle:
            parts.append(f"rotate({angle})")
        parts.append(f"scale({sx},{-sy if mirrored else sy})")
        body.append(
            f'<g transform="{" ".join(parts)}" fill="none" stroke="{color}" '
            f'stroke-width="{0.2 / max(abs(sx), 1e-6):.6g}"><path d="{dpath}"/></g>'
        )
        bounds.append((d.get("x", 0), d.get("y", 0)))
        bounds.append((d.get("x", 0) + d.get("width", 0), d.get("y", 0) + d.get("height", 0)))

    if bounds:
        xs = [p[0] for p in bounds]
        ys = [p[1] for p in bounds]
        pad = 10.0
        vx, vy = min(xs) - pad, min(ys) - pad
        vw, vh = (max(xs) - min(xs)) + 2 * pad, (max(ys) - min(ys)) + 2 * pad
    else:
        vx, vy, vw, vh = 0.0, 0.0, 100.0, 100.0

    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{vw}mm" height="{vh}mm" '
        f'viewBox="{vx} {vy} {vw} {vh}">\n'
        f'<rect x="{vx}" y="{vy}" width="{vw}" height="{vh}" fill="white"/>\n'
        + "\n".join(body)
        + "\n</svg>\n"
    )
    out_path.write_text(svg, encoding="utf-8")
    print(f"\nwrote {out_path}  ({len(body)} displays rendered)")


def main() -> int:
    ap = argparse.ArgumentParser(description="Decode and report on a .xcs file")
    ap.add_argument("path", type=Path)
    ap.add_argument("--limit", type=int, default=8, help="how many displays to detail")
    ap.add_argument("--svg", type=Path, default=None, help="also re-render displays to SVG")
    ap.add_argument("--full", action="store_true", help="print full dPath strings")
    args = ap.parse_args()

    doc = json.loads(args.path.read_text(encoding="utf-8"))
    describe_header(doc)
    all_displays: list[dict] = []
    for i, canvas in enumerate(doc.get("canvas") or []):
        all_displays += describe_canvas(canvas, i)
    describe_displays(all_displays, args.limit, args.full)
    describe_device_processing(doc, min(args.limit, 3))
    if args.svg:
        render_svg(all_displays, args.svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
