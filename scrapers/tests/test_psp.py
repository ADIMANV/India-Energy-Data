"""Regression tests against the archived NRLDC sample (2026-06-10 report)."""

from pathlib import Path

import pytest

from gridscrapers.psp import parse_report

SAMPLE = Path(__file__).parents[2] / "docs/sources/NRLDC_daily100626.pdf"


@pytest.fixture(scope="module")
def parsed():
    return parse_report(SAMPLE.read_bytes())


def test_validates_clean(parsed):
    assert parsed["errors"] == []
    assert str(parsed["as_of"]) == "2026-06-10"


def test_all_nr_states_present(parsed):
    zones = {r["zone"] for r in parsed["states"] if r["zone"]}
    assert zones == {"IN-PB", "IN-HR", "IN-RJ", "IN-DL", "IN-UP",
                     "IN-UK", "IN-HP", "IN-JK", "IN-CH"}


def test_punjab_2a_values(parsed):
    pb = next(r for r in parsed["states"] if r["zone"] == "IN-PB")
    assert pb["thermal_mu"] == 95.31
    assert pb["hydro_mu"] == 16.57
    assert pb["total_gen_mu"] == 119.35
    assert pb["act_drawal_mu"] == 211.72
    assert pb["consumption_mu"] == 331.07
    # 2C peak demand
    assert pb["peak_demand_met_mw"] == 15743.0
    assert pb["peak_time"] == "15:00"


def test_multiline_state_names(parsed):
    hp = next(r for r in parsed["states"] if r["zone"] == "IN-HP")
    assert hp["hydro_mu"] == 35.17
    jk = next(r for r in parsed["states"] if r["zone"] == "IN-JK")
    assert jk["shortage_mu"] == 0.96


def test_stations_no_aggregate_leakage(parsed):
    names = [s["station_raw"] for s in parsed["stations"]]
    assert not any("StateControlArea" in n or "Sub-Total" in n for n in names)
    central_mu = sum(s["day_energy_net_mu"] or 0 for s in parsed["stations"]
                     if s["zone"] == "IN-NR" and (s["day_energy_net_mu"] or 0) > 0)
    # NR central day energy must be plausible vs region consumption (1,943 MU)
    assert 300 < central_mu < 1500


def test_station_fuel_heuristics(parsed):
    by_name = {s["station_raw"]: s for s in parsed["stations"]}
    assert by_name["SINGRAULISTPS(2*500+"]["fuel"] == "coal"
    assert any(s["fuel"] == "hydro" and "BHAKRA" in s["station_raw"] for s in parsed["stations"])
