"use client";

import { useCallback, useEffect, useState } from "react";
import GridMap from "../components/GridMap";
import SidePanel from "../components/SidePanel";
import StateSearch from "../components/StateSearch";
import { fetchZones, fetchLive } from "../lib/api";
import { STALE_AFTER_MIN, ageLabel, ageMinutes, fmtMW } from "../lib/zones";

const REFRESH_MS = 5 * 60 * 1000;

const MODES = [
  { key: "demand", label: "Demand" },
  { key: "plants", label: "Plants" },
  { key: "carbon", label: "Carbon" },
];

export default function Home() {
  const [zonesData, setZonesData] = useState(null);
  const [national, setNational] = useState(null);
  const [selectedZone, setSelectedZone] = useState("IN");
  const [refreshKey, setRefreshKey] = useState(0);
  const [apiError, setApiError] = useState(null);
  const [colorMode, setColorMode] = useState("demand");

  const refresh = useCallback(() => {
    fetchZones()
      .then((d) => { setZonesData(d); setApiError(null); })
      .catch((e) => setApiError(String(e)));
    fetchLive("IN").then(setNational).catch(() => setNational(null));
    setRefreshKey((k) => k + 1);
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, REFRESH_MS);
    return () => clearInterval(t);
  }, [refresh]);

  const natDemand = national?.metrics.find((m) => m.metric === "demand_met");
  const stateCount = zonesData ? zonesData.zones.filter((z) => z.zone !== "IN").length : 0;
  const live = natDemand && !apiError && ageMinutes(natDemand.ts) <= STALE_AFTER_MIN;

  return (
    <div className="app">
      <GridMap
        zonesData={zonesData}
        onSelect={setSelectedZone}
        selectedZone={selectedZone}
        colorMode={colorMode}
      />

      <header className="topbar">
        <a className="wordmark" href="/">
          <svg viewBox="6 6 20 20" aria-hidden="true">
            <rect x="7" y="7" width="5" height="18" rx="1" fill="#d55181" />
            <rect x="13.5" y="13" width="5" height="12" rx="1" fill="#3987e5" />
            <rect x="20" y="17" width="5" height="8" rx="1" fill="#c98500" />
          </svg>
          India Electricity Data
        </a>
        <StateSearch selectedZone={selectedZone} onSelect={setSelectedZone} />
        <nav className="seg" aria-label="Map layer">
          {MODES.map((m) => (
            <button key={m.key} className={colorMode === m.key ? "on" : ""}
                    aria-pressed={colorMode === m.key} onClick={() => setColorMode(m.key)}>
              {m.label}
            </button>
          ))}
        </nav>
        <div className="live" aria-live="polite">
          <i className={`dot${live ? "" : " off"}`} />
          {apiError ? "Live data unavailable"
            : natDemand ? <><b className="num">{fmtMW(natDemand.value)}</b> India · {stateCount} states · {ageLabel(natDemand.ts)}</>
              : "Loading…"}
        </div>
        <nav className="links">
          <a href="/data">Data</a>
          <a href="/methodology">Methodology</a>
          <a href="/data-gaps">Data gaps</a>
          <a href="/status">Status</a>
          <a href="https://github.com/ADIMANV/India-Energy-Data">GitHub</a>
        </nav>
      </header>

      <SidePanel zone={selectedZone} onSelect={setSelectedZone} refreshKey={refreshKey} zonesData={zonesData} />
    </div>
  );
}
