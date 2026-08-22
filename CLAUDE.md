# lbrn2xcs — Project Context for Claude Code

## Shared Context
This project is part of Teagan Dixon's development environment.
Cross-project context lives at `~/dev-context/` — consult before provisioning
resources, choosing ports, or making architectural decisions. Key files:
`toolchain.md`, `conventions.md`, `active-projects.md`, `decisions-index.md`.
After significant decisions, append to the current month's file in `~/dev-context/decisions/`, then rerun `scripts/build-decisions-index.py`.

---

## Project Overview

**lbrn2xcs** is a personal batch tool to convert LightBurn projects
(`.lbrn` / `.lbrn2`) toward **xTool Creative Space (XCS)**. Personal use only —
not a commercial product, not part of StrataBurn (the laser-cut generator).

- **Owner**: Teagan Dixon (personal)
- **Repo**: teaganwins-dev/lbrn2xcs (private)
- **Directory**: `~/dev/lbrn2xcs/` (i.e. `C:\dev\lbrn2xcs`)
- **Status**: scaffold only — implementation to be done in a dedicated session.

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
- Personal tool: keep it simple; a good CLI + tests beats a framework.
- Never redistribute reverse-engineered `.xcs` writers commercially (personal use).
