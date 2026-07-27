"""Translate LightBurn cut settings into xTool P3 processing parameters.

Both programs speak the same units — speed in mm/s, power as a percentage — so
the conversion is not a unit problem. It is a *machine* problem: the library was
cut on a 40 W blue-diode D1 Pro, and the P3 is an 80 W CO2. Those differ in two
independent ways, and only one of them is the wattage.

**Wavelength matters more than wattage.** A diode runs at 455 nm and CO2 at
10.6 µm, and wood absorbs the infrared far better. So the P3 does the same job on
far less energy than the 2x power ratio alone suggests — and the gap is much
larger for through-cuts (where the beam has to keep working down a deepening
kerf) than for surface marking. So a single global multiplier cannot be right;
the factor has to vary with how hard the beam is working.

Both anchors come from measured settings rather than theory:

===============  ==============================  ==========================
Operation        D1 Pro 40 W (library median)    P3 80 W (published)
===============  ==============================  ==========================
Through-cut      8.33 mm/s @ 100%, 1 pass        50 mm/s @ 80%, 1 pass
3 mm plywood     -> 4.80 J/mm                    -> 1.28 J/mm  (0.27x)
Surface engrave  200 mm/s @ 80%                  ~275 mm/s @ 45%
wood             -> 0.16 J/mm                    -> 0.13 J/mm  (0.82x)
===============  ==============================  ==========================

The cut anchor is worth trusting: 8.33 mm/s @ 100% is both this library's most
common cut setting (360 layers) and squarely inside the 8–12 mm/s @ 100% that
published guidance gives for 3 mm basswood on a diode. The engrave anchor is
softer — treat it as a starting point and calibrate.

Two separate questions, deliberately decoupled:

* **What operation is this?** Decided by the layer name first, then speed. This
  picks the XCS ``processingType``, i.e. what the machine is asked to do.
* **How hard is it working?** Decided by the delivered energy alone. This picks
  the conversion factor.

Keeping them apart matters. A layer named "Engrave - Roads" running at
7.5 mm/s / 100% is an engrave and must stay one, but energetically it is doing a
cut's worth of work; converting it as light surface marking would burn through
the piece. Conversely a "Cut" layer at 133 mm/s is really a score.

None of this survives a change of material class. These numbers are for wood.
Clear acrylic cannot be cut by a diode at all but cuts well on CO2, so any layer
set up for painted or dark acrylic needs redoing by hand, not scaling.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import Layer

# --------------------------------------------------------------------------
# Machines
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Machine:
    name: str
    watts: float
    """Optical output, not wall draw."""
    max_speed: float
    """mm/s, for clamping."""
    co2: bool = False


D1_PRO_40W = Machine("xTool D1 Pro 40W", watts=40.0, max_speed=400.0)
FALCON_10W = Machine("Creality Falcon 10W", watts=10.0, max_speed=250.0)
P3_80W = Machine("xTool P3 80W", watts=80.0, max_speed=1200.0, co2=True)

SOURCE_MACHINES = {"d1pro40": D1_PRO_40W, "falcon10": FALCON_10W}

# --------------------------------------------------------------------------
# Operations
# --------------------------------------------------------------------------

CUT = "VECTOR_CUTTING"
LINE_ENGRAVE = "VECTOR_ENGRAVING"
FILL_ENGRAVE = "FILL_VECTOR_ENGRAVING"

# Below this, a LightBurn "Cut" layer is doing a real through-cut; above it, the
# same layer type is being used to score or line-engrave. The library splits
# cleanly here — 556 layers sit in 8–12 mm/s, 54 in 20–35 mm/s, and only 3 land
# in the 12–20 mm/s gap between them.
CUT_SPEED_THRESHOLD = 15.0  # mm/s (900 mm/min)
CUT_POWER_THRESHOLD = 50.0  # %

_CUT_WORDS = ("cut", "cutout", "cut-out", "thru", "through")
_SURFACE_WORDS = ("engrave", "engraving", "etch", "score", "shade", "shading", "fill", "mark")


def classify(layer: Layer) -> str:
    """Decide which XCS operation a LightBurn layer represents.

    LightBurn's ``type`` only distinguishes line work (``Cut``) from raster
    (``Scan``/``Image``) — it does not say whether line work goes *through* the
    material. The layer name is the best signal when it carries intent, and speed
    is a reliable fallback.
    """
    if layer.kind in ("Scan", "Image"):
        return FILL_ENGRAVE

    name = (layer.name or "").lower()
    # Check surface words first: "1 - Cut - Shore Lakes" vs "Contour 1 - cut"
    # both contain "cut", but an explicit engrave/score word is more specific.
    if any(word in name for word in _SURFACE_WORDS):
        return LINE_ENGRAVE
    if any(word in name for word in _CUT_WORDS):
        return CUT

    speed = layer.speed or 0.0
    power = layer.max_power if layer.max_power is not None else 100.0
    if 0 < speed <= CUT_SPEED_THRESHOLD and power >= CUT_POWER_THRESHOLD:
        return CUT
    return LINE_ENGRAVE


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------

# Two anchors, as (energy the diode delivered J/mm, energy ratio the P3 needs).
# The CO2 advantage is not constant: light surface marking depends on surface
# absorption, where both wavelengths do reasonably well, but the deeper the beam
# works the more the infrared's better coupling into wood tells. So the ratio is
# interpolated on delivered energy rather than switched on operation type.
SURFACE_ANCHOR = (0.160, 0.818)
CUT_ANCHOR = (4.800, 0.267)


def energy_ratio(source_energy: float) -> float:
    """How much of the source machine's energy per mm the P3 needs.

    Interpolated logarithmically between the two anchors and clamped to them —
    beyond the measured range there is nothing to extrapolate from.

    Deliberately keyed on *delivered energy*, not on the operation the layer is
    named for. A deep engrave run at 7.5 mm/s / 100% is doing the same physical
    work as a cut and needs the cut-regime factor, even though it is an engrave
    and must stay one in XCS. Keying this off the name instead would convert such
    layers as if they were light surface marking and burn straight through them.
    """
    lo_e, lo_k = SURFACE_ANCHOR
    hi_e, hi_k = CUT_ANCHOR
    energy = min(max(source_energy, lo_e), hi_e)
    span = math.log10(hi_e) - math.log10(lo_e)
    t = (math.log10(energy) - math.log10(lo_e)) / span
    return 10 ** (math.log10(lo_k) + t * (math.log10(hi_k) - math.log10(lo_k)))

# How much of the conversion is taken as speed rather than power. Speed is the
# better lever on a CO2: a slow pass at reduced power chars wood, where a fast
# pass at healthy power cuts clean. 1.0 = all speed, 0.0 = all power.
SPEED_BIAS = {
    CUT: 0.75,
    LINE_ENGRAVE: 0.5,
    FILL_ENGRAVE: 0.5,
}

MIN_POWER = 1.0
MAX_POWER = 100.0
MIN_SPEED = 1.0


@dataclass
class XcsSettings:
    """Converted parameters for one layer."""

    operation: str
    power: float
    speed: float
    repeat: int
    density: float | None = None
    kerf: float = 0.0
    ignored: bool = False
    note: str = ""


def _density_from_interval(interval_mm: float | None) -> float | None:
    """LightBurn line interval (mm) -> XCS fill density.

    XCS's default density of 100 corresponds to LightBurn's common 0.1 mm
    interval, i.e. density reads as lines per centimetre.
    """
    if not interval_mm or interval_mm <= 0:
        return None
    return round(10.0 / interval_mm, 2)


def convert(
    layer: Layer,
    *,
    source: Machine = D1_PRO_40W,
    target: Machine = P3_80W,
    scale: float = 1.0,
) -> XcsSettings:
    """Convert one LightBurn layer's settings for *target*.

    *scale* multiplies the delivered energy — 0.8 to run deliberately light while
    calibrating, above 1.0 to bias hotter.
    """
    operation = classify(layer)
    power = layer.max_power if layer.max_power is not None else 100.0
    speed = layer.speed or 0.0
    repeat = max(1, layer.num_passes)

    if speed <= 0 or power <= 0:
        # Placeholder layers exist in real files — a 0% "Precut" marker, or a
        # setting with no speed at all. There is no energy to scale, so pass the
        # values through and flag them rather than inventing numbers.
        return XcsSettings(
            operation=operation,
            power=max(MIN_POWER, power),
            speed=max(MIN_SPEED, speed),
            repeat=repeat,
            ignored=True,
            note="no power/speed to translate",
        )

    # Energy per mm the source machine delivered, and what the target needs to
    # match it, adjusted for how much better CO2 couples into wood.
    source_energy = source.watts * (power / 100.0) / speed
    target_energy = source_energy * energy_ratio(source_energy) * scale

    # Split the change between speed and power. The full correction expressed
    # entirely as speed would be this factor:
    full = (target.watts * (power / 100.0) / target_energy) / speed
    bias = SPEED_BIAS[operation]
    speed_factor = full**bias

    new_speed = speed * speed_factor
    note = ""

    if new_speed > target.max_speed:
        new_speed = target.max_speed
        note = f"speed clamped to {target.max_speed:g} mm/s"

    # Whatever the speed change did not absorb comes out of power, so the
    # delivered energy still lands on target_energy.
    new_power = target_energy * new_speed / target.watts * 100.0

    if new_power > MAX_POWER:
        # Cannot deliver the energy at this speed — slow back down instead of
        # silently under-powering the job.
        new_power = MAX_POWER
        wanted = target.watts * (MAX_POWER / 100.0) / target_energy
        if wanted < new_speed:
            new_speed = wanted
            note = "slowed to reach required energy at 100% power"
    new_power = max(MIN_POWER, min(MAX_POWER, new_power))
    new_speed = max(MIN_SPEED, min(target.max_speed, new_speed))

    return XcsSettings(
        operation=operation,
        power=round(new_power, 1),
        speed=round(new_speed, 1),
        repeat=repeat,
        density=_density_from_interval(layer.interval),
        kerf=layer.kerf or 0.0,
        ignored=not layer.output or layer.hidden,
        note=note,
    )
