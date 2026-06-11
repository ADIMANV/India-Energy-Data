# Methodology: estimated fuel mix & carbon intensity

Honest labeling is the contract: every API value and map color derived from an
estimate carries `estimated: true`. Measured values (e.g. Punjab SLDC live
SCADA) carry `estimated: false`.

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

## Plant registry refresh

```sh
.venv/bin/python -m gridscrapers.plants load          # downloads GPPD CSV
.venv/bin/python -m gridscrapers.fuelmix compute      # recompute shares
```

GPPD is a 2021 snapshot (newest plants missing — they surface in
`plant_match_review`). powerplantmatching's precompiled dataset contained no
India rows as of v0.8.1 (2026-06-11); revisit if that changes. Review queue:
`SELECT * FROM plant_match_review WHERE NOT resolved ORDER BY schedule_mwh DESC;`
