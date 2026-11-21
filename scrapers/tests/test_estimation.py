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


# --- intra-day shaping ----------------------------------------------------------

def test_conventional_fleet_keeps_its_must_run_floor_at_noon():
    # Gujarat's CEA blend on 18 Nov 2026: 42% coal by energy, but with Khavda's
    # inter-state parks counted, enough solar to swamp demand at midday
    from datetime import datetime, timezone

    from gridscrapers.estimation import MUST_RUN_FRAC, shaped_mix

    shares = {"coal": 0.42, "solar": 0.32, "wind": 0.18, "nuclear": 0.05, "hydro": 0.02}
    noon = datetime(2026, 11, 18, 6, 30, tzinfo=timezone.utc)  # 12:00 IST
    mix = shaped_mix("IN-GJ", shares, demand_mw=23000, d_avg_mw=21000, ts_utc=noon)
    assert abs(sum(mix.values()) - 23000) < 1
    conv = mix["coal"] + mix["nuclear"] + mix["hydro"]
    assert conv >= MUST_RUN_FRAC * 0.49 * 21000 - 1          # floor holds
    assert mix["coal"] / 23000 > 0.2                         # not the 4% it used to read
    assert mix["solar"] > mix["coal"]                        # solar still leads at noon


def test_floor_changes_nothing_when_renewables_leave_room():
    from datetime import datetime, timezone

    from gridscrapers.estimation import shaped_mix

    shares = {"coal": 0.8, "solar": 0.1, "nuclear": 0.1}
    night = datetime(2026, 11, 18, 18, 30, tzinfo=timezone.utc)  # midnight IST
    mix = shaped_mix("IN-MH", shares, demand_mw=25000, d_avg_mw=24000, ts_utc=night)
    assert mix.get("solar", 0) == 0
    assert abs(mix["coal"] - 25000 * 0.8 / 0.9) < 1
