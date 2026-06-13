# Methodology: estimated fuel mix & carbon intensity

The headline number is **carbon intensity**, in gCO₂eq/kWh:

> **CI(zone, t) = live demand met × fuel shares × emission factors**, summed
> over fuels and normalized — i.e. `Σ_fuel share_fuel × EF_fuel`.

The fuel shares come either from a **measured** SLDC feed or from one of three
**estimated** bases; the emission factors are a versioned CEA/IPCC table (see
below). Honest labeling is the contract: every API value and map color derived
from an estimate carries `estimated: true`; measured values carry
`estimated: false`. Estimated values additionally carry an `estimation_basis`.

## Freshness ladder

Per state, per day, the freshest and most authoritative fuel-share basis wins
(`current_fuel_shares` DB view). Highest to lowest:

- **measured** (`estimated: false`) — an SLDC publishes live in-state
  generation by fuel (Punjab, Karnataka, Delhi own-gen, Maharashtra vision).
  Outranks every estimate. See *Measured fuel mix* below.
- **`psp_actual_t1`** — daily fuel shares from RLDC PSP reports (measured
  T-1 energy). Preferred wherever available (NR + SR + WR states).
- **`cea_blend_t1`** — for states without a parsed PSP report: conventional
  split (coal/gas/oil/hydro/nuclear) from CEA dgr2 + state-wise daily RE
  (wind/solar/other) from CEA's renewable report (gen-re.cea.gov.in), both
  T-1 actuals. **Caveats:** this describes the *in-state generation* mix —
  drawal is unmodeled (unlike the PSP blend), `match_rate` is NULL to mark
  that; and the RE report counts ISTS-connected parks under their host state
  (Rajasthan solar reads ~4× its control-area number). Acceptable for the
  ER/NER states it currently covers, where RE and imports are small.
- **`merit_schedule_t2`** — daily fuel shares from MERIT scheduled dispatch
  (T-2). Last-resort fallback.

The estimated tiers carry a recency bonus so a fresh lower tier doesn't shadow
yesterday's better one: psp (+2 days) > cea_blend (+1 day) > merit. If a higher
basis stalls, the freshest available wins again — per state, per day (e.g.
Goa's PSP row goes missing some days and falls back to cea_blend automatically).

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

2. **Live estimate with intra-day solar shaping.** Daily shares alone would
   smear solar across the night, so per 15-min block
   (`estimation.shaped_mix`, curve in `solar.py`):
   - solar MW = daily-average solar MW × clear-sky weight (state centroid
     lat/lon, IST; weight is energy-preserving — daily mean 1, 0 at night);
   - wind + other RE run flat at their daily-average MW (capped together
     with solar at 95% of instantaneous demand);
   - conventional fuels absorb the residual `demand − RE` in proportion to
     their daily energy split.
   Geometry only — no clouds; monsoon haze makes real solar flatter than
   the curve, which the conventional residual absorbs. Stored as
   `generation` datapoints, `source='estimate'`, `estimated=true`.
   Verified 2026-06-12: Rajasthan CI went from a flat 543 g profile to
   695 g (night) → ~305 g (11:00–12:00 IST trough) with the same daily
   energy — the expected solar duck curve.

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

## Measured fuel mix (SLDC live)

Where a State Load Despatch Centre publishes live generation by fuel, that
mix is used directly and its CI is stored with `estimated=false` — it always
outranks the estimate:

- **Punjab** (`sldcapi.pstcl.org`, JSON) — coal (state thermal + IPPs), hydro,
  solar, biomass.
- **Karnataka** (`kptclsldc.in`, HTML) — full mix: coal/hydro/gas stations
  plus wind/solar/biomass from the NCEP page.
- **Delhi** (`delhisldc.org`, HTML) — own generation only (gas CCGTs +
  waste-to-energy); see the caveat below.
- **Maharashtra** (`mahasldc.in` SCADA JPEG) — thermal/hydro/gas/solar read
  from the dashboard image by a vision parser, with a ±10% fuel-sum-vs-demand
  reconciliation gate (a value that fails is quarantined, never written).

**Caveat — measured CI is *generation* CI, not *consumption* CI.** The
measured mix is what the state *generates*, not what it *consumes*; imports
carry the seller's mix, which an SLDC's own-generation feed doesn't see. For
states that generate most of their own supply (Karnataka, Punjab) the two are
close. For heavy net-importers (Delhi, ~90% imported, mostly coal) the
measured ~480 g understates true consumption CI sharply. A consumption-weighted
blend is a documented future refinement.

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

## Data sources & latency

Every number traces to a public source. Latency is how far behind real time
the source runs.

| Source | What we take | Latency |
|---|---|---|
| [Vidyut Pravah](https://vidyutpravah.in) (Ministry of Power) | state demand met, exchange price/purchase, shortage | **live** (~5-min blocks) |
| [MERIT](https://meritindia.in) (Ministry of Power) | state demand, own-generation vs import, plant-wise daily dispatch | **live** demand; dispatch **T-2** |
| [Punjab SLDC](https://sldcapi.pstcl.org) | live generation by fuel | **live** (SCADA) |
| [Karnataka SLDC](https://kptclsldc.in) | live station + RE generation by fuel | **live** (SCADA) |
| [Delhi SLDC](http://www.delhisldc.org) | live own-generation by GENCO | **live** (SCADA) |
| [Maharashtra SLDC](https://mahasldc.in) | SCADA dashboard image → vision parse | **live** (SCADA) |
| RLDC daily PSP reports — [NRLDC](https://nrldc.in), [SRLDC](https://srldc.in), [WRLDC](https://www.wrldc.in) | actual state energy by fuel, peak demand | **T-1** |
| [CEA / NPP daily generation (dgr2)](https://npp.gov.in) | state×sector×fuel conventional energy | **T-1** |
| [CEA renewable generation report](https://gen-re.cea.gov.in) | state-wise daily wind/solar/other-RE | **T-1** |
| [WRI Global Power Plant Database](https://datasets.wri.org/dataset/globalpowerplantdatabase) | plant fuel/capacity registry for matching | static (2021 snapshot) |

Note Vidyut Pravah and MERIT share the NLDC backend (see *Source independence*
above) — they cross-check our parsers, not the underlying source. Independent
validation comes from the separate SLDC, RLDC PSP, and CEA chains.

## Plant registry refresh

```sh
.venv/bin/python -m gridscrapers.plants load          # downloads GPPD CSV
.venv/bin/python -m gridscrapers.fuelmix compute      # recompute shares
```

GPPD is a 2021 snapshot (newest plants missing — they surface in
`plant_match_review`). powerplantmatching's precompiled dataset contained no
India rows as of v0.8.1 (2026-06-11); revisit if that changes. Review queue:
`SELECT * FROM plant_match_review WHERE NOT resolved ORDER BY schedule_mwh DESC;`

## Accuracy

We backtest the estimated carbon intensity against CI recomputed from *actual*
fuel energy, per state per day (`gridscrapers/ci_backtest.py`, table
`ci_backtest`). The actual CI uses the **same emission factors** as the live
pipeline, so any gap is fuel-SHARE error, not a factor dispute.

- **`ci_actual`** = actual fuel-energy split — from the RLDC PSP 2A report or
  the CEA dgr2 + renewable report — times the live emission factors.
- **`ci_estimated`** = the demand-weighted daily mean of our archived live CI
  for that state-day (demand-weighted so it matches the energy-weighted actual
  and isolates share error from time-of-day weighting).
- **Independence.** A check is only meaningful if the estimate and the actual
  come from *different* data chains. A `psp_actual_t1` state checked against the
  PSP report is circular (≈0 by construction) — those are marked
  `independent=false` and excluded from headlines. The meaningful cells are the
  measured states (full-pipeline, SLDC vs PSP/CEA) and estimated states checked
  against a different actual than their basis.
- **Worst case (`merit_method`).** For every state with actuals we also
  reconstruct what the pure MERIT-T-2 schedule estimate would have produced and
  compare to actual — always independent. This bounds trust for the merit-only
  and grey (unestimated) states.

Headlines use the **median** absolute percentage error over cells whose actual
CI clears 100 gCO₂/kWh: percentage error is unstable for near-zero-carbon hydro
states (a 30 g miss on a 25 g actual is 120% but trivial), so those are
reported in absolute grams and kept out of the percentage headline. States
cross-checked against CEA inherit CEA's conventional-scope bias (it
under-weights renewables), a standing negative bias visible in the table below.

Live results (auto-updated; backfilled across all archived history):
