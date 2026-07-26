# lbrn2xcs

Personal batch tool to convert LightBurn projects (`.lbrn` / `.lbrn2`) toward
xTool Creative Space (XCS). Personal use only.

## Why

`.lbrn`/`.lbrn2` (LightBurn XML) and `.xcs` (xTool, closed/undocumented) are both
proprietary. The reliable bridge is neutral **SVG/DXF**, which both LightBurn and
XCS import. This tool batches a LightBurn library into importable SVG/DXF, and
(experimentally) explores writing native `.xcs`.

## Plan

- **Tier A** — batch `.lbrn`/`.lbrn2` → SVG (+ DXF), preserving layers by color.
  Build first; reliable.
- **Tier B** — native `.xcs` output. Needs a real `.xcs` sample to reverse-
  engineer the (undocumented, version-specific) schema. See `docs/plan.md`.

## Usage (planned)

```bash
lbrn2xcs INPUT [--out OUT_DIR] [--format svg|dxf|xcs] [--recursive]
```

## Status

Scaffold only — implementation happens in a dedicated session. Drop sample
files in `samples/` (gitignored) to work on Tier B.
