# lbrn2xcs — Project Context for Claude Code

## Shared Context
This project is part of Teagan Dixon's development environment.
Cross-project context lives at `~/dev-context/` — consult before provisioning
resources, choosing ports, or making architectural decisions. Key files:
`toolchain.md`, `conventions.md`, `active-projects.md`, `decisions-index.md`.
After significant decisions, append to the current month's file in `~/dev-context/decisions/`, then rerun `scripts/build-decisions-index.py`.

---

## Project Overview

**lbrn2xcs** converts LightBurn projects (`.lbrn` / `.lbrn2`) to **xTool
Creative Space (XCS)** `.xcs`, SVG or DXF. **Open source (MIT) since
2026-09-21**, published by Sand Point Studios as a free tool that points people
at StrataBurn. A browser version (Pyodide, runs client-side) lives at
`strataburn.com/converter`, built from this package.

- **Owner**: Sand Point Studios LLC
- **Repo**: Sand-Point-Studios-LLC/lbrn2xcs (**public**)
- **Directory**: `~/dev/lbrn2xcs/`
- **Status**: working; XCS confirmed to open its `.xcs` output (P3, XCS 2.x).

**Open-sourcing reversed the July rule** ("never redistribute the `.xcs`
writer"). Teagan's call on 2026-09-21. The writer was built by reading files
XCS saves (plain JSON), not by decompiling XCS, which xTool's terms forbid;
several other open-source `.xcs` tools are public. Keep it that way: **never**
add anything taken from inside the XCS application (code, assets, bundled
data), stay "unofficial / not affiliated", and comply at once with any
takedown request from xTool or LightBurn.

## Why this exists / the format landscape

Decided in StrataBurn's **XDEC-161** (`~/dev-context/decisions-index.md`): both
`.lbrn`/`.lbrn2` (LightBurn XML) and `.xcs` (xTool, **closed/undocumented**) are
proprietary. StrataBurn deliberately exports neutral **SVG/DXF** (which both
apps import) rather than native project files, to avoid the format + EULA
problems. This tool is the *personal* counterpart: get Teagan's existing
LightBurn library into XCS.

## Plan — two tiers (see `docs/plan.md`)

- **Tier A (reliable, build first):** batch `.lbrn`/`.lbrn2` → **SVG (+ DXF)**.
  LightBurn's format is XML, so parse every shape + its `CutIndex`→layer and
  emit a clean SVG/DXF per project (layers preserved by color). Import the SVGs
  into XCS. Low-risk; no reverse-engineering.
- **Tier B (native `.xcs`, harder):** write `.xcs` files directly so they open
  in XCS with layers/settings intact. Blocked on the **undocumented, version-
  specific `.xcs` schema** — recent XCS `.xcs` is JSON (sometimes zipped) and is
  inspectable, so it's plausible for a personal tool but fragile. **Needs a real
  `.xcs` sample** (saved from the current XCS version) to reverse-engineer the
  schema before committing. Drop samples in `samples/` (gitignored).

## Stack (proposed — confirm in the build session)

- **Python 3.13** CLI (matches Teagan's stack; XML parsing + `svgwrite`/`ezdxf`
  already used in StrataBurn's export code — reuse those patterns).
- Entry point: `lbrn2xcs <input-dir-or-file> [--out DIR] [--format svg|dxf|xcs]`.
- Layout: `src/lbrn2xcs/` (package), `tests/` (pytest).

## Reference material

- StrataBurn's export code is a strong reference for SVG/DXF building with
  LightBurn layer/color conventions:
  `~/dev/Laser Cut Generator/backend/src/laser_cut_gen/design/`
  (`lightburn.py` = layer→color map, `svg_builder.py`, `dxf_builder.py`).
- LightBurn `.lbrn`/`.lbrn2` is XML: `<Shape Type="Path|Rect|Ellipse|...">` with
  primitive/vertex data and `CutIndex` (layer). Parse with `xml.etree`.

## Conventions

- Follow `~/dev-context/conventions.md` unless noted here.
- Keep it simple; a good CLI + tests beats a framework.
- Public repo: no personal files in `samples/` commits, no machine-specific
  defaults (power translation is opt-in via `--source-machine`).
- Format knowledge comes only from files XCS writes, never from the app itself.
