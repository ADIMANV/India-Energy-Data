"""CI-backtest unit tests: actual-CI math, independence, % stability."""

from gridscrapers import ci_backtest
from gridscrapers.estimation import EF, _ci_from_shares


def test_psp_fuel_map_in_ef_vocab():
    assert set(ci_backtest.PSP_FUELS.values()) <= set(EF)


def test_actual_ci_from_psp_energy_is_coal_heavy():
    # Punjab-like 2A energy (MU): mostly coal + some hydro/solar
    energy = {"coal": 95.3, "hydro": 16.6, "gas": 0.0, "solar": 5.0,
              "wind": 0.0, "res_nonsolar": 2.5}
    ci = _ci_from_shares(energy)
    assert 700 < ci < 900  # coal-dominated, well above hydro floor


def test_independence_family_rules():
    fam = ci_backtest.BASIS_FAMILY
    # measured/merit checked against psp or cea = independent
    assert fam["measured"] == "sldc" and fam["measured"] != "psp"
    assert fam["merit_schedule_t2"] == "merit" and fam["merit_method"] == "merit"
    # psp-vs-psp would be the degenerate (same family) case
    assert fam["psp_actual_t1"] == "psp"
    assert fam["cea_blend_t1"] == "cea"


def test_pct_floor_excludes_low_carbon_states():
    # the headline floor keeps a near-zero-carbon hydro state out of the %
    assert ci_backtest.PCT_STABLE_FLOOR_G >= 50
