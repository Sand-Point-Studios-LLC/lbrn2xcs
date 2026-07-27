# lbrn2xcs — implementation notes

Status as of the first build session. The format details below are *measured*
against a real 414-file LightBurn library and 6 real `.xcs` files, not inferred
from documentation (there isn't any for `.xcs`).

## Tier A — `.lbrn`/`.lbrn2` → SVG/DXF — **done**

Converts the whole library: 1,403,289 shapes across 414 files, zero failures.

### The LightBurn format, as actually encountered

* Root `<LightBurnProject AppVersion=… MirrorX MirrorY>`. Sixteen distinct
  `AppVersion`s appear in this library (1.0.06 → 2.0.05); the geometry encoding is
  stable across all of them.
* `<CutSetting type="Cut|Scan|Image|Tool">` blocks define layers, keyed by
  `<index Value>`. Scalars are `<tag Value="…"/>` children, not attributes.
* Shapes: `Path`, `Group`, `Text`, `Rect`, `Ellipse`, `Bitmap`, `QrCode`.
  (`Polygon` and `Line` are handled too but don't appear in this corpus.)
* `<XForm>a b c d e f</XForm>` is an affine matrix in SVG `matrix()` order and
  composes down through `Group`/`<Children>`.

**`Path` geometry.** `<VertList>` is a run-together sequence of `V<x> <y>`
vertices, each optionally carrying bezier handles `c0x`/`c0y` and `c1x`/`c1y` in
absolute local coordinates.

* `c0` is the **outgoing** handle (toward the next vertex), `c1` the **incoming**
  one. Verified by checking that a vertex's `c0` lands near the following vertex;
  swapping them produces visible spurs at every vertex, which is how the bug was
  caught in the first place.
* A handle counts only when *both* components are present. LightBurn writes a bare
  `c0x1` as a "no handle here" placeholder — the `1` is not a coordinate.

`<PrimList>` wires vertices together: `L<i> <j>` line, `B<i> <j>` cubic using
*i*'s outgoing and *j*'s incoming handle. `LineClosed` is shorthand for "join all
vertices in order and close".

**Shared geometry.** Shapes carry `VertID`/`PrimID`, and only the first user of an
id writes the actual list; later shapes reference the id and differ only by
`<XForm>`. In this corpus 201k vertex lists serve 1.4M paths, so resolving these
is mandatory, not an optimisation. Definitions are collected in a pre-pass so
reference order cannot matter.

**Text.** `Text` shapes carry `<BackupPath>` — LightBurn's own vectorised copy of
the rendered glyphs. Converting through it sidesteps fonts entirely. 2,126 Text
shapes in this corpus; exactly one lacks a backup path.

Crucially, a backup path is **fully baked**: it has its own `Type`, `CutIndex` and
`XForm`, and that `XForm` places the glyphs in *absolute project coordinates*. The
Text shape's transform and any enclosing group's are already folded in, so it must
be walked from the identity, not from the accumulated matrix. Applying the Text's
own transform as well double-counts it — and text transforms are routinely
`[0 1; 1 0]`, a reflection about the diagonal, so every label ends up mirrored and
flung outside the canvas. Two useful checks on this:

* LightBurn embeds a `<Thumbnail>` (base64 PNG) in every file. Decoding it shows
  exactly what the design should look like — cheap, decisive ground truth for any
  placement question, and worth reaching for before reasoning about matrices.
* Across all 161 text-bearing files in the corpus, text now sits *entirely* inside
  the drawing's bounding box: maximum overhang 0.0000 of the drawing size.

### Known gaps

| Gap | Count | Note |
|---|---|---|
| `Bitmap` | 159 shapes / 97 files | Raster. The base64 PNG is in the `Data` attribute, so SVG `<image>` embedding is feasible — the clear next feature, since 5 files are *nothing but* a photo engrave. |
| `QrCode` | 66 shapes / 10 files | Only `Content` + `ErrorCorrection` are stored; regenerating needs a QR encoder. |
| Single-vertex `Path` | 5 shapes | Degenerate stray points. Nothing to draw; reported, not emitted. |

## Tier B — native `.xcs` — **writer built, matches XCS's own output**

`.xcs` is plain UTF-8 JSON, not zipped. The contract was settled by round-tripping
a known-geometry probe through XCS (`tools/make_probe_svg.py` → import → save →
`tools/decode_xcs.py`) and cross-checking six unrelated real projects.

### The coordinate contract

`PATH` displays carry `dPath`: ordinary SVG path data, Y-down, in millimetres,
kept **verbatim** — the probe's `M60,110 C80,70 110,110 130,80` came back
byte-for-byte. Placement is:

```
canvas_x = graphicX + scale.x * local_x
canvas_y = graphicY + scale.y * local_y
```

`x`/`y` are the local bbox minimum corner through that same transform, using the
curve's *true extrema* rather than its control points (the probe's bezier reports
`height: 30` for a curve whose control points span 40, which is how we know).
`width`/`height` are the local bbox size times `scale`.

**The mirror trap.** Vertically mirrored art carries `skew.x = π`, and then the Y
term is negated. All six of the initially available samples were mirrored, so the
minus sign fit 5,995 of 5,995 displays and looked intrinsic. It isn't — a plain
import has `skew = 0` and a plus. Measuring a large corpus was not enough here;
only a probe with known input distinguished "always true" from "true of every file
I happened to have". Worth remembering for the next format.

Also reproduced on output because XCS writes them on every display:
`offsetX == graphicX`, `offsetY == graphicY`, `localSkew == skew`, `angle == 0`,
`isFill == false`, `fillRule == "nonzero"`, `lockRatio == true`, `points == []`,
plus the constants `lineColor: 16421416` and `fillColor: "#f9932b"`.

### Layers

XCS does **not** snap imported art onto a fixed palette. It creates one layer per
distinct stroke colour, keyed by lowercase hex in `layerData` and named with the
uppercase hex; `originColor` equals the layer colour. The probe's five stroke
colours produced exactly five layers. So LightBurn palette colours are written
through unchanged and layer structure survives exactly — no remapping, and no
8-colour ceiling.

(An earlier reading of the older sample files suggested a fixed 8-colour palette
with `{Red}`-style i18n names. Those names appear in 2024-era files; current XCS
names layers by hex.)

### Native shape types

XCS has `RECT`, `CIRCLE` and `TEXT` display types alongside `PATH` — the probe's
rect became a `RECT` with native `angle: 30` for the rotated one, and its circle a
`CIRCLE` with `scale: 0.01`. `PATH` is used for everything written here: it round-
trips exactly, keeps beziers, and avoids a second geometry encoding to get wrong.

### Machine settings

`device.data` maps canvas id → `{mode, data, displays}`, where `displays` is a
list of `[displayId, config]` pairs holding `processingType`
(`VECTOR_CUTTING` / `VECTOR_ENGRAVING` / `FILL_VECTOR_ENGRAVING`) and full
parameter blocks per type. Written here with XCS's own fresh-import defaults
(`VECTOR_ENGRAVING`, `materialType: customize`, power 1 / speed 20) rather than
translated from LightBurn: xTool's material model is not a unit conversion away
from LightBurn's mm/s + %power, and a silently wrong power setting is worse than
an obvious default.

### What's verified, and what isn't

Verified: XCS's own output decodes exactly as described above; a `.xcs` written
here decodes back to geometry identical to its SVG; and every field and top-level
key emitted is one XCS writes itself (asserted in `tests/test_xcs_out.py` against
the probe, skipped when no probe is present).

Not verified: that XCS opens a file written here. If it doesn't, likely suspects
in order — `cover` (written empty; XCS writes a base64 PNG thumbnail),
`groupData` wiring, and whether `material: 0` is acceptable when no material has
been chosen.
