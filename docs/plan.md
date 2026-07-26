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

### Known gaps

| Gap | Count | Note |
|---|---|---|
| `Bitmap` | 159 shapes / 97 files | Raster. The base64 PNG is in the `Data` attribute, so SVG `<image>` embedding is feasible — the clear next feature, since 5 files are *nothing but* a photo engrave. |
| `QrCode` | 66 shapes / 10 files | Only `Content` + `ErrorCorrection` are stored; regenerating needs a QR encoder. |
| Single-vertex `Path` | 5 shapes | Degenerate stray points. Nothing to draw; reported, not emitted. |

## Tier B — native `.xcs` — **writer built, round-trip unverified**

`.xcs` turned out to be plain UTF-8 JSON, not zipped, and inspectable. Two format
generations appear in the samples (a 2024 one and the current one), and the
geometry contract is identical in both.

### The coordinate contract

Each drawable is a `display` of type `PATH`. `dPath` is ordinary SVG path data in
a local space; the mapping to canvas millimetres is:

```
canvas_x = graphicX + scale.x * local_x
canvas_y = graphicY - scale.y * local_y      # note the minus
```

`x`/`y` hold the local bbox's minimum corner run through that same transform, and
`width`/`height` are the local bbox size times `scale`. Confirmed on **5,995 of
5,995 displays** — the residual median is ~1e-6 mm, i.e. float noise. The negated
Y is what the `skew.x = π` on every display encodes.

The writer exploits the negation instead of fighting it: LightBurn is already
Y-up, so `dPath` is emitted in LightBurn's own orientation with `graphicY` set to
the drawing height, which makes `canvas_y` come out Y-down and correct without
transforming the geometry.

Other invariants that hold across every sample and are reproduced on output:
`offsetX == graphicX`, `offsetY == graphicY`, `localSkew == skew`, `angle == 0`,
`isFill == false`, `fillRule == "nonzero"`, `lockRatio == true`, `points == []`.

### Layers

`layerData` maps an XCS palette colour → `{name, order, visible}`; displays point
at one via `layerTag`/`layerColor`. XCS snaps imported stroke colours onto its own
8-colour palette and preserves the pre-import colour in `originColor`.

Useful confirmation: in a LightBurn-derived `.xcs`, the `originColor` values are
exactly LightBurn palette entries (`#0000ff`, `#00e0e0`, `#d0d000`, `#b45a00`,
`#004754` = C01/C06/C04/C26/C27). That independently validates the palette table
in `palette.py` *and* the whole LightBurn-colour → SVG-stroke → XCS-layer path.

### Machine settings — deliberately not translated

The `device` block holds per-display power/speed/`processingType`
(`VECTOR_CUTTING` / `VECTOR_ENGRAVING` / `FILL_VECTOR_ENGRAVING`) keyed by display
id, plus a material id and lift-platform config. The writer leaves it empty, as
XCS's own older files do, so XCS applies material defaults on open. Mapping
LightBurn's mm/s + %power onto xTool's material model is a separate problem and a
silently wrong power setting is worse than no setting.

### What's left to verify

1. **Does a written `.xcs` open in the current XCS build?** Everything else is
   downstream of this. `tools/make_probe_svg.py` emits a known-geometry SVG
   (exact mm, asymmetric so mirroring can't hide); import it into XCS, save, then
   `tools/decode_xcs.py` reports what XCS wrote and can re-render it to SVG.
2. Whether `extId`/`device.id` must name a machine (`P3`) or may stay empty.
3. Whether the `cover` thumbnail matters, or XCS regenerates it.
4. Whether `groupData` needs populating to keep shapes grouped on open.
