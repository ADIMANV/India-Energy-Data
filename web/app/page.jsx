"use client";

import { useCallback, useEffect, useState } from "react";
import GridMap from "../components/GridMap";
import SidePanel from "../components/SidePanel";
import { fetchZones, fetchLive } from "../lib/api";
import { ageLabel, fmtMW } from "../lib/zones";

const REFRESH_MS = 5 * 60 * 1000;

const MODES = [
  { key: "plants", label: "Plants", dek: "Every power plant in the open registry, by installed capacity and fuel." },
  { key: "demand", label: "Demand", dek: "Electricity demand met in each state, right now." },
  { key: "carbon", label: "Carbon", dek: "Carbon intensity of each state's generation, right now." },
];

export default function Home() {
  const [zonesData, setZonesData] = useState(null);
  const [national, setNational] = useState(null);
  const [selectedZone, setSelectedZone] = useState("IN");
  const [refreshKey, setRefreshKey] = useState(0);
  const [apiError, setApiError] = useState(null);
  const [colorMode, setColorMode] = useState("plants");

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
  const mode = MODES.find((m) => m.key === colorMode);

  return (
    <div className="app">
      <main className="main">
        <section className="stage">
          <header className="masthead">
            <h1>India Electricity Data</h1>
            <p className="dek">{mode.dek}</p>
            <nav className="modes" aria-label="Map layer">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  className={colorMode === m.key ? "on" : ""}
                  aria-pressed={colorMode === m.key}
                  onClick={() => setColorMode(m.key)}
                >
                  {m.label}
                </button>
              ))}
            </nav>
          </header>
          <div className="readout" aria-live="polite">
            <span className="r-label">All-India demand met</span>
            <span className="r-value num">{fmtMW(natDemand?.value)}</span>
            <span className="r-age">
              {apiError
                ? "live data unavailable"
                : natDemand
                  ? `${stateCount} states · updated ${ageLabel(natDemand.ts)}`
                  : "loading…"}
            </span>
          </div>
          <GridMap
            zonesData={zonesData}
            onSelect={setSelectedZone}
            selectedZone={selectedZone}
            colorMode={colorMode}
          />
        </section>
        <SidePanel zone={selectedZone} onSelect={setSelectedZone} refreshKey={refreshKey} />
      </main>
      <footer className="footer">
        <span>Open electricity data for India · estimates labelled, never faked</span>
        <nav>
          <a href="/data">Download data</a>
          <a href="/methodology">Methodology</a>
          <a href="/data-gaps">Data gaps</a>
          <a href="/status">Data quality</a>
          <a href="https://github.com/ADIMANV/India-Energy-Data">Source</a>
        </nav>
      </footer>
    </div>
  );
}
