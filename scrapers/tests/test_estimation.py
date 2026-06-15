"""Reconcile-guard logic for measured fuel mixes (estimation._mix_trusted)."""

from gridscrapers.estimation import RECONCILE_BAND, _mix_trusted

LO, HI = RECONCILE_BAND
DEMAND = 10000.0


def test_full_mix_within_band_is_trusted():
    # Karnataka-style full mix, generation ~= demand
    assert _mix_trusted("karnataka_sldc", 9500.0, DEMAND)
    assert _mix_trusted("karnataka_sldc", LO * DEMAND, DEMAND)   # at the floor
    assert _mix_trusted("karnataka_sldc", HI * DEMAND, DEMAND)   # at the ceiling


def test_full_mix_far_below_demand_is_distrusted():
    # parser dropped most rows -> generation collapses well under the floor
    assert not _mix_trusted("karnataka_sldc", 0.3 * DEMAND, DEMAND)


def test_full_mix_absurdly_high_is_distrusted():
    # doubled unit / unit error -> generation blows past the ceiling
    assert not _mix_trusted("karnataka_sldc", 3.0 * DEMAND, DEMAND)


def test_own_generation_source_is_exempt():
    # Delhi reports only its own gas+waste fleet, a small slice of demand;
    # must NOT be rejected for being far below demand
    assert _mix_trusted("delhi_sldc", 500.0, DEMAND)


def test_empty_mix_is_never_trusted():
    assert not _mix_trusted("karnataka_sldc", 0.0, DEMAND)
    assert not _mix_trusted("delhi_sldc", 0.0, DEMAND)


def test_no_demand_does_not_reject_a_real_mix():
    # with no demand to check against, a non-empty mix is allowed through
    assert _mix_trusted("karnataka_sldc", 5000.0, 0.0)
