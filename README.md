# lbrn2xcs

Batch-convert LightBurn projects (`.lbrn` / `.lbrn2`) toward xTool Creative Space
(XCS) — via SVG/DXF, or as native `.xcs` project files.

Personal tool. Both file formats are proprietary; nothing here is redistributed
and none of it is for sale. See `CLAUDE.md` for the background (StrataBurn's
XDEC-161).

## Install

```bash
python -m pip install -e ".[dev]"
```

Python 3.13+. `ezdxf` is the only third-party dependency and it is imported
lazily, so SVG and `.xcs` output work without it.

## Use

```bash
# One file or a whole tree
lbrn2xcs "path/to/project.lbrn2"
lbrn2xcs "path/to/library" --recursive --out converted/

# Formats: svg (default), dxf, xcs, both (svg+dxf), all
lbrn2xcs library --recursive --out converted/ --format both
```

Output mirrors the input folder structure under `--out`. One bad file never
aborts the batch — failures are listed at the end and the exit status is non-zero.

Per-file reporting shows shape count, drawing size and which layers were used, and
flags anything that could not be converted:

```
  Gluing Box.lbrn2 -> Gluing Box.svg, Gluing Box.dxf
      10 shapes  280.0x280.0mm  layers [C00,C01,C02]
```

## What converts

Verified against a 414-file library: **1,403,289 shapes, zero failures.**

| LightBurn | Status |
|---|---|
| `Path` (lines + cubic beziers) | ✅ |
| `Rect` (incl. corner radius), `Ellipse`, `Polygon`, `Line` | ✅ |
| `Group` / nested transforms | ✅ |
| `Text` | ✅ via LightBurn's vectorised `<BackupPath>` — no font handling needed |
| `VertID`/`PrimID` shared geometry | ✅ 201k vertex lists serve 1.4M paths |
| Layers (`CutSetting`) → colour + name | ✅ |
| `Bitmap` (photo engraves) | ❌ raster — 159 shapes across 97 files |
| `QrCode` | ❌ would need a QR encoder — 66 shapes across 10 files |

Anything unconvertible is counted and reported per file, never silently dropped.

Layer identity is preserved by colour, using LightBurn's real 30-entry palette
(C00–C29), because that is what both XCS and LightBurn key layers off on import.

## Output formats

**SVG** — one `<g>` per LightBurn layer, stroked in the layer colour, sized in
real `mm`. Y is flipped (LightBurn is Y-up, SVG is Y-down) and geometry is shifted
to a (0,0) origin. Beziers stay beziers.

**DXF** — R2010, millimetres, one layer per LightBurn layer with both true-colour
and a nearest-ACI index set. Beziers are flattened to polylines at `--tolerance`
(default 0.05 mm).

**XCS** (`--format xcs`) — native `.xcs`, **experimental**. See below.

## Native .xcs

`.xcs` is undocumented, but it is plain UTF-8 JSON (not zipped) and its geometry
model was measured, not guessed. Each drawable is a `display` of type `PATH` whose
`dPath` is ordinary SVG path data in a local space, mapped to canvas millimetres by:

```
canvas_x = graphicX + scale.x * local_x
canvas_y = graphicY - scale.y * local_y      # note the minus
```

Those two formulas reproduce the stored `x`/`y` on **100% of 5,995 displays**
across every real sample, spanning two different XCS format generations, and
`width`/`height` are the local bbox size times `scale`. The negated Y is the
`skew.x = π` that every display carries.

A cross-check fell out of the same analysis: the `originColor` values XCS keeps for
imported art are exactly LightBurn palette entries, which independently confirms
both the palette table and the colour→layer path.

Machine settings (`device`) are deliberately left empty, exactly as XCS's own
older files do, so XCS applies its material defaults on open. Translating
LightBurn power/speed onto xTool's material model is a separate problem, and
getting it silently wrong would be worse than not doing it.

**Still to confirm:** that a written `.xcs` opens cleanly in a current XCS build.
The round-trip harness is ready:

```bash
python tools/make_probe_svg.py          # known-geometry SVG, exact mm coordinates
#   -> import samples/probe/xcs_probe.svg into XCS, save as xcs_probe.xcs
python tools/decode_xcs.py samples/probe/xcs_probe.xcs --svg out/probe-decoded.svg
```

`decode_xcs.py` reports on any `.xcs` — versions, layer table, per-display
transforms, machine parameters — and can re-render the displays to SVG, so a wrong
coordinate reading is visible rather than theoretical.

Until that round-trip passes, prefer SVG: it is the low-risk path and XCS imports
it directly.

## Development

```bash
python -m pytest -q
python -m ruff check .
```

`samples/` is gitignored — drop real `.lbrn2`/`.xcs` files there for local work.

Layout:

| Path | Role |
|---|---|
| `src/lbrn2xcs/model.py` | geometry model (contours, affine transforms, tight bboxes) |
| `src/lbrn2xcs/lbrn.py` | LightBurn XML parser |
| `src/lbrn2xcs/palette.py` | LightBurn C00–C29 and XCS layer palettes |
| `src/lbrn2xcs/svg_path.py` | SVG path data read/write (also decodes XCS `dPath`) |
| `src/lbrn2xcs/svg_out.py` | SVG emitter |
| `src/lbrn2xcs/dxf_out.py` | DXF emitter |
| `src/lbrn2xcs/xcs_out.py` | native `.xcs` writer |
| `tools/` | format reverse-engineering harness |
