# plant_match_review — top 30 unresolved by scheduled MWh

Confirm/correct the fuel for each; add entries to `data/plant_overrides.json`.
Candidates are GPPD names (fuel, capacity MW) with fuzzy confidence.

| # | zone | MERIT station | MWh/day | candidate 1 | candidate 2 | fallback used |
|---|------|---------------|---------|-------------|-------------|---------------|
| 1 | IN-MP | KHARGONE | 60,367 | KAHALGAON (coal, 2340 MW) — 0.71 | THANE PLANT (oil, 22 MW) — 0.62 | coal |
| 2 | IN-MH | ADANI- TIRODA (UNIT- 1,4,5) | 34,251 | TIRORA TPP (coal, 3300 MW) — 0.56 | TADALI SPONGE IRON (coal, 33 MW) — 0.53 | coal |
| 3 | IN-AP | KRISHNAPATNAM (DSTPP) – I | 31,011 | THAMMINAPATNAM TPP (coal, 300 MW) — 0.55 | SOLAPUR STPP (coal, 1320 MW) — 0.52 | coal |
| 4 | IN-MH | ADANI TIRODA (UNIT- 2,3) | 25,654 | TIRORA TPP (coal, 3300 MW) — 0.56 | TADALI SPONGE IRON (coal, 33 MW) — 0.53 | coal |
| 5 | IN-MP | SSTPS_II | 25,426 | — | — | coal |
| 6 | IN-RJ | CSTPP UNIT5 | 24,262 | MEJA STPP (coal, 660 MW) — 0.57 | BARH STPP II (coal, 1320 MW) — 0.57 | coal |
| 7 | IN-RJ | SSCTPSUNIT7_8 | 23,495 | SATPURA (coal, 1330 MW) — 0.47 | PANIPAT (coal, 920 MW) — 0.47 | coal |
| 8 | IN-TN | COASTAL ENERGEN | 23,237 | KAMAL SPONGE (coal, 12 MW) — 0.52 | TADALI SPONGE IRON (coal, 33 MW) — 0.48 | coal |
| 9 | IN-MH | RATAN INDIA UNIT-01 TO 05 | 22,393 | TANDA (coal, 440 MW) — 0.53 | TALWANDI SABO (coal, 1980 MW) — 0.52 | coal |
| 10 | IN-MP | SSTPS_I | 21,848 | — | — | coal |
| 11 | IN-AP | HINDUJA | 21,120 | UCHPINDA TPP (coal, 1440 MW) — 0.67 | CHANDRAPURA (coal, 630 MW) — 0.56 | coal |
| 12 | IN-AP | THERMAL POWERTECH CORPORATION OF INDIA LIMITED -1 | 18,586 | TUTICORIN- IND BARATH (coal, 300 MW) — 0.41 | SITAPURAM POWER LIMITED (coal, 43 MW) — 0.40 | coal |
| 13 | IN-TN | MTPS STAGE 1&2 | 17,531 | MEJA STPP (coal, 660 MW) — 0.46 | PARAS (coal, 500 MW) — 0.44 | coal |
| 14 | IN-AP | VIJAYAWADA TPS (DR NARLA TATA RAO TPS (DR. NTTPS))-I,II&III | 17,258 | VASAVADATTA CEMENT (coal, 51 MW) — 0.44 | WARDHA WARORA(Sai Wardha Power) (coal, 540 MW) — 0.43 | coal |
| 15 | IN-TN | NCTPS STAGE 2 | 17,077 | DADRI (NCTPP) (coal, 1820 MW) — 0.50 | SUGEN CCCP (gas, 1148 MW) — 0.40 | coal |
| 16 | IN-GJ | WTPS_1_6 | 15,895 | PARAS (coal, 500 MW) — 0.44 | ITPCL TPP (coal, 1200 MW) — 0.44 | coal |
| 17 | IN-AP | K.PTNAM U3 | 15,332 | PAINAMPURAM (coal, 1320 MW) — 0.50 | KUTTALAM GT (gas, 101 MW) — 0.50 | coal |
| 18 | IN-RJ | RAJWEST LTPS (IPP) | 15,304 | SURAT LIG. (coal, 500 MW) — 0.48 | KORBA-WEST (coal, 1340 MW) — 0.46 | coal |
| 19 | IN-GJ | WTPS 8 | 14,798 | PARAS (coal, 500 MW) — 0.44 | ITPCL TPP (coal, 1200 MW) — 0.44 | coal |
| 20 | IN-TN | JINDAL POWER LIMITED STAGE-2 | 14,663 | SITAPURAM POWER LIMITED (coal, 43 MW) — 0.65 | BARSINGAR LIGNITE (coal, 250 MW) — 0.58 | coal |
| 21 | IN-AP | DR.NTTPS STG-V | 14,349 | DADRI (NCTPP) (coal, 1820 MW) — 0.52 | INDRA GANDHI STPP (coal, 1500 MW) — 0.48 | coal |
| 22 | IN-PB | RTPS | 14,236 | BARH STPP II (coal, 1320 MW) — 0.46 | ROPAR (coal, 840 MW) — 0.44 | coal |
| 23 | IN-GJ | ESSAR POWER GUJ | 12,815 | ESSAR GT IMP. (gas, 515 MW) — 0.67 | VIJESWARAM GT (gas, 272 MW) — 0.55 | coal |
| 24 | IN-AP | TELANGANA STPS STAGE-1 | 12,424 | PATALGANGA (gas, 66 MW) — 0.63 | MANGAON CCPP (gas, 388 MW) — 0.62 | coal |
| 25 | IN-TN | TTPS | 11,633 | PARAS (coal, 500 MW) — 0.44 | ITPCL TPP (coal, 1200 MW) — 0.44 | coal |
| 26 | IN-MP | SGTPS -4X210 | 11,328 | SATPURA (coal, 1330 MW) — 0.43 | GHTP (LEH.MOH.) (coal, 920 MW) — 0.42 | coal |
| 27 | IN-TN | NCTPS STAGE 1 | 11,250 | DADRI (NCTPP) (coal, 1820 MW) — 0.50 | SUGEN CCCP (gas, 1148 MW) — 0.40 | coal |
| 28 | IN-TN | CPP_BIOMASS_COGEN | 10,908 | RABRIYAWAS CEMENT (coal, 19 MW) — 0.47 | BINANI CEMENT PLANT (coal, 70 MW) — 0.47 | coal |
| 29 | IN-MP | SGTPS -1X500 | 10,825 | SATPURA (coal, 1330 MW) — 0.43 | GHTP (LEH.MOH.) (coal, 920 MW) — 0.42 | coal |
| 30 | IN-MH | KHAPERKHEDA UNIT - 01 TO 04 | 10,739 | KHAMBERKHERA IPP (coal, 90 MW) — 0.67 | K_KHEDA II (coal, 1340 MW) — 0.57 | coal |
