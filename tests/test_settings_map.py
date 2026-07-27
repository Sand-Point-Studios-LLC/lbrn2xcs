"""LightBurn -> xTool P3 settings translation tests."""

from __future__ import annotations

import math

import pytest

from lbrn2xcs.model import Layer
from lbrn2xcs.settings_map import (
    CUT,
    CUT_ANCHOR,
    D1_PRO_40W,
    FILL_ENGRAVE,
    LINE_ENGRAVE,
    P3_80W,
    SURFACE_ANCHOR,
    classify,
    convert,
    energy_ratio,
)


def layer(**kw) -> Layer:
    base = dict(index=0, name="", kind="Cut", max_power=100.0, speed=10.0, num_passes=1)
    base.update(kw)
    return Layer(**base)


def energy(watts: float, power: float, speed: float) -> float:
    return watts * (power / 100.0) / speed


# --------------------------------------------------------------------------
# Classification — what operation XCS should run
# --------------------------------------------------------------------------


def test_raster_layer_types_become_fill():
    assert classify(layer(kind="Scan")) == FILL_ENGRAVE
    assert classify(layer(kind="Image")) == FILL_ENGRAVE


def test_layer_name_decides_when_it_states_intent():
    assert classify(layer(name="1 - Cut - Shore / Lakes", speed=7.5)) == CUT
    assert classify(layer(name="Contour 1 - cut", speed=7.5)) == CUT
    assert classify(layer(name="Bottom - Engrave", speed=7.5)) == LINE_ENGRAVE
    assert classify(layer(name="Score border", speed=7.5)) == LINE_ENGRAVE


def test_engrave_wins_over_cut_when_a_name_contains_both():
    """"1 - Engrave - Roads" is an engrave, even though "cut" may appear nearby."""
    assert classify(layer(name="Engrave cutout area", speed=7.5)) == LINE_ENGRAVE


def test_speed_decides_when_the_name_says_nothing():
    assert classify(layer(name="C00", speed=8.33, max_power=100)) == CUT
    assert classify(layer(name="C00", speed=133.33, max_power=80)) == LINE_ENGRAVE


def test_slow_but_weak_is_not_treated_as_a_cut():
    assert classify(layer(name="C00", speed=8.0, max_power=20)) == LINE_ENGRAVE


# --------------------------------------------------------------------------
# Energy ratio — how hard the beam is working
# --------------------------------------------------------------------------


def test_energy_ratio_reproduces_both_anchors():
    assert energy_ratio(SURFACE_ANCHOR[0]) == pytest.approx(SURFACE_ANCHOR[1], rel=1e-6)
    assert energy_ratio(CUT_ANCHOR[0]) == pytest.approx(CUT_ANCHOR[1], rel=1e-6)


def test_energy_ratio_is_clamped_outside_the_measured_range():
    assert energy_ratio(0.001) == pytest.approx(SURFACE_ANCHOR[1])
    assert energy_ratio(500.0) == pytest.approx(CUT_ANCHOR[1])


def test_energy_ratio_falls_monotonically_with_depth():
    """The deeper the beam works, the bigger CO2's advantage over the diode."""
    samples = [energy_ratio(e) for e in (0.16, 0.5, 1.0, 2.0, 4.8)]
    assert all(a > b for a, b in zip(samples, samples[1:]))


# --------------------------------------------------------------------------
# Conversion
# --------------------------------------------------------------------------


def test_cut_anchor_lands_on_the_published_p3_setting():
    """8.33 mm/s @ 100% on the D1 Pro is the library's most common cut.

    The P3's published figure for the same material is 50 mm/s @ 80%, i.e.
    1.28 J/mm. The conversion should land on that energy.
    """
    result = convert(layer(name="Cut", speed=8.33, max_power=100.0))
    delivered = energy(P3_80W.watts, result.power, result.speed)
    assert delivered == pytest.approx(1.28, rel=0.05)
    assert result.operation == CUT


def test_conversion_preserves_the_intended_energy_exactly():
    lb = layer(name="Cut", speed=8.33, max_power=100.0)
    result = convert(lb)
    source_energy = energy(D1_PRO_40W.watts, 100.0, 8.33)
    expected = source_energy * energy_ratio(source_energy)
    assert energy(P3_80W.watts, result.power, result.speed) == pytest.approx(expected, rel=0.01)


def test_deep_engrave_stays_an_engrave_but_converts_in_the_cut_regime():
    """The hazard case: named engrave, run at cutting energy.

    It must remain VECTOR_ENGRAVING in XCS, but be scaled with the deep-regime
    factor — converting it as light surface marking would burn through the piece.
    """
    deep = convert(layer(name="1 - Engrave - Roads", speed=7.5, max_power=100.0))
    light = convert(layer(name="Shading", speed=200.0, max_power=80.0))
    assert deep.operation == LINE_ENGRAVE
    assert light.operation == LINE_ENGRAVE

    source_deep = energy(D1_PRO_40W.watts, 100.0, 7.5)
    assert energy(P3_80W.watts, deep.power, deep.speed) == pytest.approx(
        source_deep * energy_ratio(source_deep), rel=0.01
    )
    # And the two must not receive the same factor.
    assert energy_ratio(source_deep) < energy_ratio(energy(D1_PRO_40W.watts, 80.0, 200.0))


def test_speed_goes_up_and_power_comes_down_for_a_cut():
    result = convert(layer(name="Cut", speed=8.33, max_power=100.0))
    assert result.speed > 8.33
    assert result.power < 100.0


def test_power_scale_runs_lighter():
    full = convert(layer(name="Cut", speed=8.33, max_power=100.0))
    light = convert(layer(name="Cut", speed=8.33, max_power=100.0), scale=0.8)
    assert energy(P3_80W.watts, light.power, light.speed) == pytest.approx(
        0.8 * energy(P3_80W.watts, full.power, full.speed), rel=0.01
    )


def test_passes_are_preserved():
    assert convert(layer(name="Cut", speed=5.0, num_passes=3)).repeat == 3


def test_result_is_always_within_machine_limits():
    for speed in (0.5, 5.0, 200.0, 2666.7):
        for power in (5.0, 50.0, 100.0):
            r = convert(layer(name="x", speed=speed, max_power=power))
            assert 1.0 <= r.power <= 100.0
            assert 1.0 <= r.speed <= P3_80W.max_speed


def test_very_fast_layer_is_clamped_and_says_so():
    result = convert(layer(name="Shading", kind="Scan", speed=2666.7, max_power=80.0))
    assert result.speed == P3_80W.max_speed
    assert "clamp" in result.note


def test_zero_power_placeholder_is_flagged_not_divided_by_zero():
    """Real files contain 0% marker layers such as "Precut"."""
    result = convert(layer(name="Precut", speed=333.33, max_power=0.0))
    assert result.ignored is True
    assert result.note
    assert result.power >= 1.0


def test_missing_speed_is_flagged():
    result = convert(layer(name="Tool", speed=0.0))
    assert result.ignored is True


def test_disabled_layers_are_marked_ignored():
    assert convert(layer(name="Cut", speed=8.0, output=False)).ignored is True
    assert convert(layer(name="Cut", speed=8.0, hidden=True)).ignored is True
    assert convert(layer(name="Cut", speed=8.0)).ignored is False


def test_fill_interval_becomes_density():
    """XCS's default density of 100 matches LightBurn's common 0.1 mm interval."""
    assert convert(layer(kind="Scan", speed=200.0, interval=0.1)).density == pytest.approx(100.0)
    assert convert(layer(kind="Scan", speed=200.0, interval=0.05)).density == pytest.approx(200.0)
    assert convert(layer(kind="Scan", speed=200.0)).density is None


def test_kerf_is_carried_through():
    assert convert(layer(name="Cut", speed=8.0, kerf=0.15)).kerf == pytest.approx(0.15)


def test_a_weaker_source_machine_needs_less_scaling_up():
    """The same LightBurn numbers from a 10W Falcon mean far less delivered energy."""
    from lbrn2xcs.settings_map import FALCON_10W

    lb = layer(name="Cut", speed=8.33, max_power=100.0)
    d1 = convert(lb, source=D1_PRO_40W)
    falcon = convert(lb, source=FALCON_10W)
    assert energy(P3_80W.watts, falcon.power, falcon.speed) < energy(
        P3_80W.watts, d1.power, d1.speed
    )


def test_conversion_is_monotonic_in_source_energy():
    """A slower LightBurn layer must never convert to a faster P3 layer."""
    speeds = [2.0, 4.0, 8.0, 16.0]
    out = [convert(layer(name="Cut", speed=s, max_power=100.0)) for s in speeds]
    delivered = [energy(P3_80W.watts, r.power, r.speed) for r in out]
    assert all(a > b for a, b in zip(delivered, delivered[1:]))
    assert not any(math.isnan(d) for d in delivered)
