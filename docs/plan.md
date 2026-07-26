# lbrn2xcs — implementation plan

## Tier A — `.lbrn`/`.lbrn2` → SVG/DXF (build first)

LightBurn files are XML. Goal: parse each project's shapes + layers and emit a
clean SVG (and optionally DXF) that XCS can import, with layers preserved.

1. **Parse `.lbrn`/`.lbrn2`** with `xml.etree.ElementTree`.
   - Root `<LightBurnProject>`; `<CutSetting>` blocks define layers (index →
     name/color/params); `<Shape Type="...">` elements hold geometry.
   - Shape types to handle: `Path` (has `<VertList>` / `<PrimList>` — bezier +
     line primitives), `Rect`, `Ellipse`, `Line`, `Text` (defer text first pass).
   - Each shape has `CutIndex` → which layer/color it belongs to.
   - Shapes may carry a transform (`XForm`) — apply it to vertices.
2. **Map layer → color** using LightBurn's standard palette (mirror StrataBurn's
   `design/lightburn.py` `LIGHTBURN_LAYERS`).
3. **Emit SVG** (`svgwrite`): one `<g>` per layer, stroke = layer color. Mind the
   Y-axis convention (LightBurn origin vs SVG top-left).
4. **Emit DXF** (`ezdxf`): LWPOLYLINE per shape on a per-color layer (reuse
   StrataBurn's `design/dxf_builder.py` approach).
5. **CLI**: batch a folder (recursive), write `<name>.svg` / `.dxf` per input.

Bezier handling: LightBurn `Path` PrimList uses `L` (line) and `B` (bezier)
primitives referencing VertList points + control handles. Flatten beziers to
polylines at a tolerance for DXF; keep as SVG paths for SVG.

## Tier B — native `.xcs` (experimental, needs a sample)

`.xcs` is undocumented and version-specific. Recent XCS `.xcs` appears to be a
JSON document (sometimes zipped). Approach:

1. **Get a sample**: save a simple project from the *current* XCS version (a few
   shapes across 2–3 layers). Put it in `samples/` (gitignored).
2. **Inspect**: unzip if needed; pretty-print the JSON; identify where canvas
   size, elements (path data / points), layer/processing params, and units live.
3. **Round-trip test**: write a minimal `.xcs` with one known shape; confirm XCS
   opens it correctly. Only then map `.lbrn` shapes → `.xcs` elements.
4. **Be honest about fragility**: gate behind `--format xcs` with a clear
   "experimental; tested against XCS version X" note. Prefer Tier A otherwise.

## Open questions

- Which XCS version is the target? (schema differs across versions.)
- Units + coordinate origin mapping between LightBurn and XCS.
- How XCS represents cut/engrave/score operations vs LightBurn CutSettings.
