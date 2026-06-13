# Zone data provenance

Per-zone provenance of the **live carbon-intensity / fuel-mix** signal, and
the freshness ladder that decides which basis wins. Updated as SLDC plugins
land (Prompt C).

## Freshness ladder (highest wins)

1. **measured** (`estimated=false`) — an SLDC publishes live in-state
   generation by fuel. Outranks every estimate. Sources in
   `gridscrapers.sources.MEASURED_MIX_SOURCES`.
2. **psp_actual_t1** — RLDC daily PSP report, T-1 actual energy shares.
3. **cea_blend_t1** — CEA dgr2 conventional + gen-re RE, T-1.
4. **merit_schedule_t2** — MERIT scheduled dispatch, T-2.

A zone flips from estimated→measured automatically the first tick its SLDC
plugin writes generation; the API `estimated` flag and the map/panel badge
follow. When a zone becomes measured, stale estimated generation in the live
window is purged so the donut shows only the measured mix.

> **Caveat — measured = in-state generation CI, not consumption CI.** The
> measured mix is what the state *generates*, not what it *consumes*; imports
> carry the seller's mix. For states that generate most of their own supply
> (Karnataka, Punjab) the two are close. For heavy net-importers (Delhi) they
> diverge sharply — see Delhi below. A consumption-weighted blend is a
> documented future refinement.

## SLDC sources

| Zone | Source | Endpoint | Exposes | Status |
|---|---|---|---|---|
| IN-PB | `punjab_sldc` | sldcapi.pstcl.org JSON | full in-state fuel mix | ✅ measured |
| IN-KA | `karnataka_sldc` | kptclsldc.in StateGen + StateNCEP (HTML) | coal/hydro/gas stations + wind/solar/biomass/cogen | ✅ measured (representative) |
| IN-DL | `delhi_sldc` | delhisldc.org Redirect.aspx?Loc=0804 (HTML) | own-gen by GENCO (gas CCGTs + waste-to-energy) | ✅ measured (own-gen only — see note) |
| IN-MH | `maha_vision` | mahasldc.in /assets/public/scada/mvrreport3.jpg | SCADA dashboard JPEG → vision parser | ⏳ in progress |
| IN-GJ | — | sldcguj.com realtimedemand.php | (HTML/PHP) | ⏸ skipped: connect timeout from this host; revisit from VPS |
| IN-HP | — | hpsldc.com admin-ajax | (mostly hydro) | ⏸ deferred: page loads but ajax endpoint not yet mapped; timebox spent on KA/DL/MH first |

### IN-KA (Karnataka) — representative measured mix
StateGen station totals classified: RTPS/BTPS/YTPS/JINDAL/UPCL → coal,
YCCP → gas, all other stations → state hydro. StateNCEP TOTAL_IPPS row →
biomass (bio-mass + cogen), wind, solar; Pavagada Solar Park added to solar.
NCEP mini-hydro (~0.7%) dropped to avoid a cross-page key collision with
state hydro. Total in-state generation ≈ matches demand closely.

### IN-DL (Delhi) — own-generation only, import-dominated
Delhi's own fleet is ~0.5 GW of gas CCGTs (CCGT-Bawana, Pragati, GT) plus
four municipal waste-to-energy plants (→ `other`); ~90% of Delhi's ~4.5 GW
demand is central imports. The measured mix and CI (~480 g, gas-weighted)
therefore describe **Delhi's own generation, not its supply** — its
consumption CI is much higher (coal imports). Flagged measured for
consistency with the in-state-generation convention, but this is the clearest
case where a consumption blend would change the headline number.

### IN-MH (Maharashtra) — vision parser
SCADA dashboard served as a JPEG (`mvrreport3.jpg`). Parsed by the generic
`vision` plugin (Claude API, strict JSON schema, ±10% reconciliation or
quarantine). Reusable for future SCADA-screenshot states (UP, Bihar, …).
