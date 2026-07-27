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
| Nested groups, rotated/mirrored text | ✅ backup paths are absolute; verified against LightBurn's embedded thumbnails |
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

### Power and speed translation

LightBurn and XCS use the same units (mm/s, % power), so this is not a unit
conversion — it is a machine conversion, from a 40 W blue-diode D1 Pro to an 80 W
CO2 P3. Wavelength matters more than wattage here: wood absorbs 10.6 µm far
better than 455 nm, so the P3 needs much less energy than the 2x power ratio
suggests, and the gap widens the deeper the beam works.

Both anchors are measured, not theoretical:

| | D1 Pro 40 W | P3 80 W |
|---|---|---|
| Through-cut, 3 mm plywood | 8.33 mm/s @ 100% = 4.80 J/mm | 50 mm/s @ 80% = 1.28 J/mm (0.27x) |
| Surface engrave, wood | 200 mm/s @ 80% = 0.16 J/mm | ~275 mm/s @ 45% = 0.13 J/mm (0.82x) |

The cut anchor is solid: 8.33 mm/s @ 100% is both this library's most common cut
setting (360 layers) and inside the published 8–12 mm/s @ 100% for 3 mm basswood
on a diode. The engrave anchor is softer — calibrate it.

Two questions are answered separately, which matters:

* **What operation is this?** Layer name first, speed as fallback. This picks the
  XCS `processingType`.
* **How hard is the beam working?** Delivered energy alone, interpolated between
  the anchors. This picks the conversion factor.

Keeping them apart is the whole point. A layer named `1 - Engrave - Roads` running
at 7.5 mm/s @ 100% is an engrave and stays one in XCS, but energetically it is
doing a cut's worth of work — converting it as light surface marking would burn
straight through the piece.

Also carried across: passes to `repeat`, fill line interval to `density`, kerf to
`kerfDistance`, and LightBurn's disabled/hidden layers to `processIgnore` (about
47% of layers in this library, since stacked designs enable one sheet at a time).

```bash
lbrn2xcs project.lbrn2 --format xcs                       # translate (default)
lbrn2xcs project.lbrn2 --format xcs --power-scale 0.8     # run 20% light while calibrating
lbrn2xcs project.lbrn2 --format xcs --source-machine none # leave XCS defaults alone
```

Every conversion is printed per layer so you can check it before burning:

```
  C00 0 - Cut              8.3mm/s 100% x1  ->  cut   37.7mm/s  60.4% x1
  C09 0 - Engraving      266.7mm/s  60% x1  ->  fill 417.0mm/s  38.4% x1  [density 125]
```

**Test on scrap first.** The conversion preserves the *relative* aggressiveness of
each layer, but it cannot know what material or thickness a layer was tuned for —
that is nowhere in the file. And none of it survives a change of material class:
clear acrylic cannot be cut by a diode at all but cuts well on CO2, so acrylic
layers need redoing by hand rather than scaling.

### Verification status

**XCS opens files written by this tool** — confirmed on a real conversion, with
geometry, scale and the processing panel all populated. XCS's own output decodes
exactly as described above, and a written `.xcs` decodes back to geometry
identical to its SVG. Every field and top-level key emitted is one XCS writes
itself; the test suite asserts that against the probe file and skips if you
haven't produced one.

Rough edge: the material shows as *Unknown Material* with a "Modify parameters"
prompt, because `material: 0` is written — no material is claimed, since the
source file never records one. Power and speed *are* translated (above); pick the
material once in XCS after opening.

If something looks off, the harness is the way in:

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
