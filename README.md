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

`.xcs` is undocumented but is plain UTF-8 JSON (not zipped). The format was
established by round-tripping a known-geometry probe through XCS itself — import
an SVG whose every coordinate we chose, save, and read back what XCS wrote —
then cross-checking against six unrelated real projects.

Each drawable is a `display`. `PATH` displays carry `dPath`: ordinary SVG path
data, Y-down, in millimetres, stored **verbatim** — XCS keeps an imported path's
data byte-for-byte and positions it with:

```
canvas_x = graphicX + scale.x * local_x
canvas_y = graphicY + scale.y * local_y
```

`x`/`y` are the local bbox minimum corner through that transform (using the
curve's true extrema, not its control points) and `width`/`height` are the local
bbox size times `scale`.

One trap worth recording: vertically mirrored art carries `skew.x = π`, and then
the Y term is *negated*. Every file in the initial sample set happened to be
mirrored, which made the minus sign look intrinsic — it isn't. A straightforward
import has `skew = 0`. The probe is what caught this.

**Layers pass straight through.** XCS does not snap imported art onto a fixed
palette: it creates one layer per distinct stroke colour, named with the uppercase
hex. So LightBurn's palette colours are written as XCS layer colours directly and
the layer structure survives exactly.

Machine settings are written with XCS's own defaults for a fresh import
(`VECTOR_ENGRAVING`, `materialType: customize`) rather than translated from
LightBurn. xTool's material model is not a unit conversion away from LightBurn's
power/speed, and a silently wrong power setting is worse than an obvious default
you set in XCS.

### Verification status

Confirmed: XCS's own output decodes exactly as described, and a `.xcs` written by
this tool decodes back to geometry identical to its SVG. Every field and top-level
key emitted is one XCS writes itself — the test suite asserts that against the
probe file, and skips if you haven't produced one.

Not yet confirmed: that XCS *opens* a file written here. Try one, and if anything
looks off, the harness is the way in:

```bash
python tools/make_probe_svg.py          # known-geometry SVG, exact mm coordinates
#   -> import samples/probe/xcs_probe.svg into XCS, save as samples/probe/xcs_probe.xcs
python tools/decode_xcs.py samples/probe/xcs_probe.xcs --svg out/probe-decoded.svg
```

`decode_xcs.py` reports on any `.xcs` — versions, layer table, per-display
transforms, machine parameters — and re-renders the displays to SVG, so a wrong
coordinate reading is visible rather than theoretical.

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
