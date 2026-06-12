# Methodology: estimated fuel mix & carbon intensity

Honest labeling is the contract: every API value and map color derived from an
estimate carries `estimated: true`. Measured values (e.g. Punjab SLDC live
SCADA) carry `estimated: false`. Estimated values additionally carry
`estimation_basis`:

- **`psp_actual_t1`** — daily fuel shares from RLDC PSP reports (measured
  T-1 energy). Preferred wherever available (NR + SR states currently).
- **`merit_schedule_t2`** — daily fuel shares from MERIT scheduled dispatch
  (T-2). Fallback for states without a parsed PSP report.

The preference rule lives in one place (`current_fuel_shares` DB view): PSP
gets a 2-day recency bonus over MERIT; if PSP ingestion stalls, the freshest
basis wins again.

## PSP-based shares (`psp_actual_t1`)

From each day's RLDC PSP report (see `gridscrapers/psp.py`):
`consumption mix = own generation by fuel (2A, actual MU) + actual drawal ×
central-station mix (3B day energy by fuel)`. The central pool covers only
part of total state drawal — the uncovered remainder (inter-regional / power
exchange energy of unknown origin) is assigned to `other` (700 gCO2/kWh,
near-coal, deliberately conservative). `match_rate` records the fraction of
consumption MU with a known fuel.

## Live state fuel mix (estimated)

1. **Daily fuel shares.** MERIT publishes plant-wise scheduled dispatch per
   state (`GetPowerStationData`, ~T-2 days). Each station row is assigned a
   fuel:
   - MERIT's own `TypeOfGeneration` for Hydro, Nuclear, Gas; `TOTAL SOLAR` →
     solar; `TOTAL NON SOLAR` / Renewable → `res_nonsolar` (wind + biomass +
     small-hydro blend — MERIT does not split it).
   - "Thermal" is ambiguous (coal/lignite/gas/oil) → fuzzy name match against
     the plant registry (`india_plants`, from WRI GPPD). Below the match
     threshold the row falls back to **coal** (the Indian thermal default)
     and lands in `plant_match_review` for manual mapping.
   Shares = scheduled MWh by fuel / total scheduled MWh, stored per
   `(zone, as_of)` in `state_fuel_shares` with the MWh-weighted match rate.

2. **Live estimate.** `estimated_mix(zone, t) = latest_shares(zone) ×
   demand_met(zone, t)`. Stored as `generation` datapoints,
   `source='estimate'`, `estimated=true`.

### Known limitations (v1)

- Shares are T-2 daily averages applied to live demand: intra-day solar/wind
  swings are smoothed away. (Fix direction: solar irradiance shaping.)
- Scheduled ≠ actual dispatch; deviations are typically small but real.
- Power-exchange and bilateral purchases carry the *seller's* unknown mix;
  v1 normalizes over scheduled dispatch only.
- MERIT plant-wise data exists for only ~12 of 31 states (2026-06). States
  without it get **no estimated mix** — demand only, never a guess.
- Unmatched thermal → coal biases CI slightly *up* in gas-heavy states until
  reviewed (match rates logged per state).

## Carbon intensity

`CI(zone, t) = Σ_fuel share_fuel × EF_fuel`, in gCO2eq/kWh, stored as
`carbon_intensity` datapoints. National CI = demand-weighted mean over states
with a CI value.

Emission factors are versioned in
[`scrapers/gridscrapers/emission_factors.json`](../scrapers/gridscrapers/emission_factors.json)
(`version` field is bumped on any change; datapoints record `parser_version`):

| fuel | gCO2eq/kWh | basis |
|---|---|---|
| coal | 950 | CEA CO2 Baseline Database v19, fleet-weighted (incl. lignite) |
| gas | 450 | CEA baseline, Indian CCGT average |
| oil | 800 | IPCC direct combustion |
| hydro | 24 | IPCC AR5 lifecycle median |
| nuclear | 12 | IPCC AR5 lifecycle median |
| solar | 48 | IPCC AR5 lifecycle median (utility PV) |
| wind | 11 | IPCC AR5 lifecycle median (onshore) |
| biomass | 230 | IPCC AR5 lifecycle median |
| res_nonsolar | 100 | blend midpoint (MERIT aggregate, unsplittable) |
| other | 700 | conservative, near-coal |

Sources: CEA "CO2 Baseline Database for the Indian Power Sector" (User Guide
v19); IPCC AR5 WGIII Annex III Table A.III.2. Mixed basis is deliberate:
combustion factors for the fossil fleet we can attribute, lifecycle medians
elsewhere — same convention Electricity Maps uses for its India zones.

## Punjab (measured, not estimated)

Punjab SLDC SCADA (`sldcapi.pstcl.org`) gives live MW by fuel directly:
coal (state thermal + IPPs), hydro, solar, biomass. Its CI is computed from
the measured mix and stored with `estimated=false`. Where measured data
exists it always wins over the estimate.

## Source independence (what cross-checks can and cannot catch)

Vidyut Pravah and MERIT both read the **same NLDC backend** — many states'
demand values are byte-identical between them at the same time block. The
VP↔MERIT cross-check on /status therefore detects **our parser bugs and
staleness**, not source errors: if NLDC publishes a wrong number, both
"sources" agree on it.

Genuinely independent validation comes from sources with separate data
chains, exercised by the daily backtests (`gridscrapers/backtest.py`,
surfaced on /status):

| chain | source | used as |
|---|---|---|
| State SCADA | SLDC APIs (Punjab live) | measured live mix, `estimated: false` |
| Regional dispatch | RLDC daily PSP reports (NR, SR) | T-1 actual fuel shares + consumption backtest |
| Central statistics | CEA/NPP daily generation report (dgr2) | station/state energy backtest vs PSP |

Backtest deltas carry known scope biases (CEA groups stations by plant
location and omits RE; PSP 2A counts control-area dispatch — Uttarakhand
reads ~+70% in CEA because its private hydro exports inter-state). Alerts
fire on a >5pp shift of the 7-day median against the trailing baseline —
a *change* in the relationship — never on the standing bias itself.

## Plant registry refresh

```sh
.venv/bin/python -m gridscrapers.plants load          # downloads GPPD CSV
.venv/bin/python -m gridscrapers.fuelmix compute      # recompute shares
```

GPPD is a 2021 snapshot (newest plants missing — they surface in
`plant_match_review`). powerplantmatching's precompiled dataset contained no
India rows as of v0.8.1 (2026-06-11); revisit if that changes. Review queue:
`SELECT * FROM plant_match_review WHERE NOT resolved ORDER BY schedule_mwh DESC;`
