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
  const [selectedZone, setSelectedZone] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [apiError, setApiError] = useState(null);

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
        <h1>⚡ India Live Grid</h1>
        <div className="stat">
          <span className="label">National demand met</span>
          <span className="value">{fmtMW(natDemand?.value)}</span>
        </div>
        <div className="stat">
          <span className="label">States reporting</span>
          <span className="value">{stateCount}</span>
        </div>
        <div className="freshness">
          {apiError
            ? `API unreachable: ${apiError}`
            : natDemand ? `national data ${ageLabel(natDemand.ts)} · auto-refresh 5 min` : "loading…"}
        </div>
      </header>
      <main className="main">
        <GridMap zonesData={zonesData} onSelect={setSelectedZone} selectedZone={selectedZone} />
        <SidePanel zone={selectedZone} refreshKey={refreshKey} />
      </main>
    </div>
  );
}
