"use client";

import { useCallback, useEffect, useState } from "react";
import GridMap from "../components/GridMap";
import SidePanel from "../components/SidePanel";
import { fetchZones, fetchLive } from "../lib/api";
import { ageLabel, fmtMW } from "../lib/zones";

const REFRESH_MS = 5 * 60 * 1000;

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

  return (
    <div className="app">
      <header className="header">
        <h1>⚡ India Electricity Data</h1>
        <div className="header-stats">
          <div className="stat">
            <span className="label">National demand met</span>
            <span className="value">{fmtMW(natDemand?.value)}</span>
          </div>
          <div className="stat">
            <span className="label">States reporting</span>
            <span className="value">{stateCount}</span>
          </div>
        </div>
        <div className="header-controls">
          <div className="toggle" role="group" aria-label="map color mode">
            <button className={colorMode === "demand" ? "on" : ""} onClick={() => setColorMode("demand")}>
              Demand
            </button>
            <button className={colorMode === "carbon" ? "on" : ""} onClick={() => setColorMode("carbon")}>
              Carbon
            </button>
          </div>
          {selectedZone !== "IN" && (
            <button className="allindia" onClick={() => setSelectedZone("IN")}>All India</button>
          )}
          <div className="freshness">
            {apiError
              ? `API unreachable: ${apiError}`
              : natDemand ? `updated ${ageLabel(natDemand.ts)} · refresh 5 min` : "loading…"}
          </div>
        </div>
      </header>
      <main className="main">
        <GridMap zonesData={zonesData} onSelect={setSelectedZone} selectedZone={selectedZone} colorMode={colorMode} />
        <SidePanel zone={selectedZone} onSelect={setSelectedZone} refreshKey={refreshKey} />
      </main>
      <footer className="footer">
        <span>Open electricity data for India · estimates labelled, never faked</span>
        <nav>
          <a href="/methodology">Methodology</a>
          <a href="/status">Data quality</a>
        </nav>
      </footer>
    </div>
  );
}
