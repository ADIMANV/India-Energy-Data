# Data source recon — Phase 0

Probed 2026-06-11. Sample responses in this directory. All curl fetches used a
desktop browser User-Agent; gov sites are touchy about default UAs.

## Status summary

| Source | Status | What it gives us | Sample |
|---|---|---|---|
| Vidyut Pravah | ✅ working | Per-state demand met, exchange purchase/price, shortage | `vidyutpravah_home.html`, `vidyutpravah_state_maharashtra.html` |
| MERIT | ✅ working (alive!) | Per-state demand + ISGS/import split, daily portfolio energy, plant-wise dispatch | `meritindia_*.html`, `merit_*.json` |
| Grid-India (grid-india.in) | ⚠️ corporate SPA only | Links to 5 RLDCs; no live data in app bundle | `grid-india_in.html` |
| WRLDC | ⚠️ endpoint live, returns empty | State-wise real-time data, inter-regional flows (JSON) | `wrldc_statewise_sample.json` |
| ERLDC | ❌ `app.erldc.in` DNS dead | (was: PSP report API) | — |
| NPP | 🔍 not probed deeply | Daily plant-wise generation (SPA, needs devtools pass) | `npp_gov_in.html` |
| CEA | 🔍 not probed deeply | Daily regional fuel-wise reports (PDF/Excel) | `cea_nic_in.html` |

## Vidyut Pravah (vidyutpravah.in)

**Gotchas:**
- Use the **apex domain** `vidyutpravah.in`. `www.vidyutpravah.in` serves a
  different (broken) site: cert SAN mismatch + "Page Not Found" at root.
- TLS cert is invalid even on apex → scraper must use `verify=False`.
- Occasional connection resets; retry with backoff.

**Endpoints:**
- `GET https://vidyutpravah.in/` — homepage. National current/prev demand met
  (`#CurrentDemandMET`, `#PrevDemandMET`), some state prices on hover map,
  and links to all 31 state pages (`/state-data/<slug>`).
- `GET https://vidyutpravah.in/state-data/<slug>` — per-state, server-rendered,
  ~12 KB. Updates per 15-min time block ("PRICE ... FOR TIME BLOCK 12:30 - 12:45
  DATED 11 JUN 2026" — parse timestamp from this header). Values in spans by class:
  - `.value_DemandMET_en` — current demand met (MW); `.value_PrevDemandMET_en` — yesterday
  - `.value_PowerPurchase_en` / `.value_PrevPowerPurchase_en` — exchange purchase (MW)
  - `.value_ExchangePrice_en` / `.value_PrevExchangePrice_en` — ₹/unit
  - `.value_PeakDemand_en` — yesterday peak shortage MW (%); `.value_TotalEnergy_en` — energy shortage MU (%)

**State slugs (31):** andhra-pradesh, arunachal-pradesh, assam, bihar, chandigarh,
chhattisgarh, delhi, goa, gujarat, haryana, himachal-pradesh, jammu-kashmir,
jharkhand, karnataka, kerala, madhya-pradesh, maharashtra, manipur, meghalaya,
mizoram, nagaland, puducherry, punjab, rajasthan, sikkim, tamil-nadu, telangana,
tripura, uttar-pradesh, uttarakhand, west-bengal

## MERIT (meritindia.in) — alive and gold

ASP.NET MVC app, JSON AJAX endpoints, no auth, no cookies needed.

- `GET /state-data/<slug>` — server-rendered daily summary (data is ~T-2 days):
  portfolio energy + avg MW (State Generation / Central ISGS / Other ISGS /
  Bilateral / Power Exchange), marginal prices, and a **plant-wise dispatch
  table** with plant type (Thermal/Hydro/...), ownership, capacity, schedule MWh.
- `POST /StateWiseDetails/BindCurrentStateStatus` body `{"StateCode":"MHA"}` →
  `[{"Demand":"27,044","ISGS":"16,813","ImportData":"10,231"}]` — **live**, MW,
  page polls it on an interval. Cross-checked vs Vidyut Pravah MH demand (27,055) ✓
- **"ISGS" field = state's own in-state generation, NOT central allocation.**
  Verified 2026-06-11 ("Goa test"): Goa & Chandigarh (≈100% central-supplied)
  return `ISGS: null`; `Demand = ISGS + ImportData` holds to the MW across all
  states tested; Punjab ISGS matched Punjab SLDC measured in-state generation
  to 0.7% in the same minute. Mapped to `generation/own_generation`.
- `POST /StateWiseDetails/GetStateWiseDetailsForPiChart` body
  `{"StateCode":"MHA","date":"09 Jun 2026"}` → daily energy MWh by portfolio type.
  Returns `-3` if params missing/no data for date.
- `POST /StateWiseDetails/GetPowerStationData` body `{StateCode, date}` → plant-wise (untested with date).
- State codes are 3-letter (MHA, ...); hidden input `#StateCode` on each state
  page maps slug → code. Also `POST /StateWiseDetails/BindStateListToRedirect`.

Caveat: MERIT has historically flapped. Treat as enrichment over Vidyut Pravah,
alert on staleness, never sole source.

## Grid-India / NLDC / RLDCs

`grid-india.in` is a Vite/React corporate site — no live data in its JS bundle.
Live grid data lives on the five RLDC sites: `wrldc.in`, `nrldc.in`, `srldc.in`,
`erldc.in`, `nerldc.in`.

- **WRLDC**: `POST https://www.wrldc.in/OnlinestateTest1.aspx/GetRealTimeData_state_Wise`
  (ASP.NET `{"d": "<json-string>"}` envelope) with `{"date":"YYYY-MM-DD"}` —
  returns HTTP 200 but `{"d":"[]"}` for every date tried (today/yesterday, all
  formats, with session cookies). electricitymaps routes this through their own
  proxy (`in-proxy-jfnx5klx2a-el.a.run.app?host=https://www.wrldc.in`) — data may
  be geo-fenced to Indian IPs, or the method needs extra headers. **TODO: probe
  from browser devtools / Indian IP.** Same pattern for
  `InterRegionalLinks_Data.aspx/Get_InterRegionalLinks_Region_Wise` (flows).
- **ERLDC**: `app.erldc.in` no longer resolves. emaps used
  `/api/pspreportpsp/Get/pspreport_psp_*/GetByTwoDate`. TODO: try `erldc.in` directly.
- **NRLDC/SRLDC/NERLDC**: 2026-06-11 follow-up — nrldc.in and srldc.in require
  **legacy TLS renegotiation** (OpenSSL 3 rejects with
  `UNSAFE_LEGACY_RENEGOTIATION_DISABLED`; fix: `ssl.OP_LEGACY_SERVER_CONNECT` +
  `SECLEVEL=1`, see `scripts/probe_rldc.py`). With that, their homepages load
  fine from outside India; the WRLDC-style `.aspx` API paths 404/405 on them —
  each RLDC needs its own endpoint recon. `nerldc.in` and `app.erldc.in` don't
  resolve in public DNS (possibly split-horizon — check from the VPS).

## RLDC daily PSP reports (PDF) — measured T-1 state fuel energy

The daily "Power Supply Position" reports are the highest-quality fuel-mix
source: actual (not scheduled) MU by fuel per state, T-1. Parsed by
`gridscrapers/psp.py` into `daily_state_energy` + `station_daily` with ±2%
total validation and quarantine. Samples: `NRLDC_daily100626.pdf`,
`SRLDC_psp_100626.pdf`.

| RLDC | Discovery | Archive depth | Status |
|---|---|---|---|
| NRLDC | `GET /get-documents-list/111` (DataTables JSON, needs `X-Requested-With: XMLHttpRequest`) → `download-file?any=...` links | Apr 2024 (747 docs, 2026-06) | ✅ parsing |
| SRLDC | direct URL `srldc.in/var/ftp/reports/psp/{YYYY}/{MonYY}/{DD-MM-YYYY}-psp.pdf` | ≥ mid-2022 | ✅ parsing |
| WRLDC | IIS dir tree `reporting.wrldc.in:8081/PSP/{YYYY}/{MonthName}/WRLDC_PSP_Report_{DD-MM-YYYY}.pdf` | 2018 | ✅ parsing 2A+3A. Bilingual headers (mangled CID glyphs, numbers fine); wind-before-solar column order (verified via CG row); Goa's row missing some days (~40%) — falls back to cea_blend. **3B central section unparsed**: mixes a second RE/state-area listing + ISGS/IPP aggregates; shares blend without central pool (uncovered drawal → `other`) |
| ERLDC | React SPA route `/reports/dailyreport/misreports/dailypspreport`; backing API `erldc.in/api//fetchStandardPageMetaData` returns 500 for every guessed payload | ? | ⏸ skipped — needs the exact request body from a browser devtools capture |
| NERLDC | `www.nerldc.in` resolves (apex does not). WP `admin-ajax.php` action `template_power_supply_position_reports` (`optionyear`) serves **monthly** PSP PDFs only; `template_daily_reports` returns empty | monthly only | ⏸ skipped — no daily PSP found; CEA dgr2 + RE report cover NER states daily (basis `cea_blend_t1`) |

Layout notes: section numbering is shared (2A state fuel MU, 2B/2C peak
demand, 3A state stations, 3B central stations) but column orders differ —
NR: thermal/hydro/gas/solar/wind/others ×13 cols; SR: thermal/hydro/gas/
**wind/solar**/others ×12 cols, and 3B net-MU column position differs (see
`RegionCfg`). Full backfill (VPS): `python -m gridscrapers.psp ingest
--region NR --backfill 750` and `--region SR --backfill 1400`.

## NPP (npp.gov.in) & CEA (cea.nic.in)

Both alive. NPP is an SPA (redirects to `/landing-home`) — daily plant-wise
generation reports need a devtools pass to find the XHR/report endpoints.
CEA serves daily fuel-wise reports as PDF/Excel. Both are Phase 3 inputs
(fuel-mix calibration), not needed for first datapoints.

## electricitymaps-contrib reference

India parsers copied to `docs/reference/emaps-parsers/` (MIT-licensed; commit from
2026-06-11 clone). Useful per-state endpoints they use (verify before building on):

| State | Source | Note |
|---|---|---|
| Delhi | `delhisldc.org/Redirect.aspx?Loc=0804` | HTML |
| Maharashtra | `mahasldc.in/wp-content/reports/sldc/mvrreport3.jpg` | JPG → needs vision parsing |
| Punjab | `sldcapi.pstcl.org/wsDataService.asmx/dynamicData`, `pbGenData2` | clean JSON API |
| Karnataka | `kptclsldc.in/StateGen.aspx`, `StateNCEP.aspx` | HTML |
| Gujarat | `sldcguj.com/RealTimeData/PrintPage.php?page=realtimedemand.php` | archived parser |
| HP | `hpsldc.com/wp-admin/admin-ajax.php` | WP AJAX |
| UP | `upsldc.org/real-time-data` | archived parser |
| Uttarakhand | `uksldc.in/real-time-data` | |
| Chhattisgarh | `117.239.199.203/csptcl/GEN.aspx` | bare-IP ASP page |
| AP | `core.ap.gov.in/CMDashBoard/UserInterface/Power/PowerReport.aspx` | archived |

They proxy several sources through their own GCP relay — expect some SLDCs to
require Indian IPs or header tricks.
