"use client";

import { useEffect, useState } from "react";
import { fetchLive, fetchPanelHistory } from "../lib/api";
import { ZONE_TO_NAME, ageLabel, ageMinutes, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { CIChart, DemandChart, FUEL_COLORS, FUEL_LABELS, GenerationChart } from "./charts";

// The estimated/measured badge is the credibility marker — one click explains it.
function BasisBadge({ estimated, basis }) {
  const label = estimated ? `estimated${basis ? ` · ${basis}` : ""}` : "measured";
  return (
    <a className={`badge ${estimated ? "" : "measured"}`} href="/methodology#freshness-ladder"
       title="How this is computed">
      {label}
    </a>
  );
}

function Donut({ mix }) {
  const total = mix.reduce((s, m) => s + m.value, 0);
  if (total <= 0) return null;
  const r = 40, cx = 50, cy = 50, w = 18;
  let angle = -Math.PI / 2;
  const arcs = mix.map((m) => {
    const frac = m.value / total;
    const a0 = angle, a1 = (angle += frac * 2 * Math.PI);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    const p0 = [cx + r * Math.cos(a0), cy + r * Math.sin(a0)];
    const p1 = [cx + r * Math.cos(a1), cy + r * Math.sin(a1)];
    return (
      <path key={m.fuel}
        d={`M${p0[0]},${p0[1]} A${r},${r} 0 ${large} 1 ${p1[0]},${p1[1]}`}
        fill="none" stroke={FUEL_COLORS[m.fuel] || "#888"} strokeWidth={w} />
    );
  });
  return (
    <div className="mix">
      <svg viewBox="0 0 100 100" className="donut">{arcs}</svg>
      <div className="mix-legend">
        {mix.map((m) => (
          <div key={m.fuel} className="mix-row">
            <span className="dot" style={{ background: FUEL_COLORS[m.fuel] || "#888" }} />
            <span className="k">{FUEL_LABELS[m.fuel] || m.fuel}</span>
            <span>{((m.value / total) * 100).toFixed(0)}% · {fmtMW(m.value)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SidePanel({ zone, onSelect, refreshKey }) {
  const [live, setLive] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);
  const isNational = zone === "IN";

  useEffect(() => {
    let dead = false;
    setError(null);
    setLive(null);
    Promise.all([fetchLive(zone), fetchPanelHistory(zone)])
      .then(([l, h]) => { if (!dead) { setLive(l); setHistory(h); } })
      .catch((e) => { if (!dead) { setLive(null); setHistory(null); setError(String(e)); } });
    return () => { dead = true; };
  }, [zone, refreshKey]);

  const title = isNational ? "All India" : ZONE_TO_NAME[zone] || zone;
  if (error) {
    return (
      <aside className="panel">
        <h2>{title}</h2>
        <p className="hint">No recent data. ({error})</p>
      </aside>
    );
  }
  if (!live) {
    return <aside className="panel"><h2>{title}</h2><p className="hint">Loading…</p></aside>;
  }

  const byMetric = {};
  for (const m of live.metrics) {
    const key = m.fuel ? `${m.metric}:${m.fuel}` : m.metric;
    if (!(key in byMetric)) byMetric[key] = m;
  }
  const demand = byMetric["demand_met"];
  const ownGen = byMetric["generation:own_generation"];
  const imp = byMetric["net_import"];
  const price = byMetric["exchange_price"];
  const purchase = byMetric["exchange_purchase"];
  const ci = byMetric["carbon_intensity"];
  const stale = demand && ageMinutes(demand.ts) > STALE_AFTER_MIN;
  const splitTotal = (ownGen?.value || 0) + (imp?.value || 0);

  const mix = live.metrics
    .filter((m) => m.metric === "generation" && m.fuel && m.fuel !== "own_generation")
    .filter((m) => ageMinutes(m.ts) <= STALE_AFTER_MIN)
    .sort((a, b) => b.value - a.value);
  const mixEstimated = mix.some((m) => m.estimated);
  const mixBasis = mix.find((m) => m.estimation_basis)?.estimation_basis;
  const points = history?.points || [];
  const hasGenHistory = points.some((p) => p.metric === "generation" || p.metric === "net_import");

  return (
    <aside className="panel">
      {!isNational && (
        <button className="breadcrumb" onClick={() => onSelect("IN")}>← All India</button>
      )}
      <h2>{title}</h2>
      <div className={`age ${stale ? "stale" : ""}`}>
        updated {demand ? ageLabel(demand.ts) : "—"}{stale ? " (STALE)" : ""}
      </div>

      {/* a. Generation mix — the differentiated thing, leads the panel */}
      {mix.length > 0 && (
        <section className="card">
          <h3>Generation mix <BasisBadge estimated={mixEstimated} basis={mixBasis} /></h3>
          <Donut mix={mix} />
        </section>
      )}

      {/* headline figures */}
      <section className="card stats">
        <div className="big">{fmtMW(demand?.value)}</div>
        <div className="row"><span className="k">Demand met</span>
          <span>{fmtMW(demand?.value)}<span className="src">{demand?.source}</span></span></div>
        {ci && (
          <div className="row"><span className="k">Carbon intensity</span>
            <span>{Math.round(ci.value)} gCO₂/kWh
              <BasisBadge estimated={ci.estimated} basis={ci.estimation_basis} /></span></div>
        )}
        {!isNational && splitTotal > 0 && (
          <>
            <div className="splitbar">
              <div className="own" style={{ width: `${((ownGen?.value || 0) / splitTotal) * 100}%` }} />
              <div className="imp" style={{ width: `${((imp?.value || 0) / splitTotal) * 100}%` }} />
            </div>
            <div className="splitlabels">
              <span>own gen {fmtMW(ownGen?.value)}</span>
              <span>import {fmtMW(imp?.value)}</span>
            </div>
          </>
        )}
      </section>

      {/* b. demand 24h */}
      <section className="card">
        <h3>Demand, 24 h</h3>
        <DemandChart points={points} />
      </section>

      {/* c. stacked generation 24h */}
      {hasGenHistory && (
        <section className="card">
          <h3>Generation, 24 h</h3>
          <GenerationChart points={points} />
        </section>
      )}

      {/* d. carbon intensity + exchange */}
      {points.some((p) => p.metric === "carbon_intensity") && (
        <section className="card">
          <h3>Carbon intensity, 24 h</h3>
          <CIChart points={points} />
        </section>
      )}

      {(price || purchase) && (
        <section className="card">
          <h3>Power exchange</h3>
          {price && (
            <div className="row"><span className="k">Price</span>
              <span>₹{price.value.toFixed(2)}/kWh<span className="src">{ageLabel(price.ts)}</span></span></div>
          )}
          {purchase && (
            <div className="row"><span className="k">Purchased</span>
              <span>{fmtMW(purchase.value)}<span className="src">{ageLabel(purchase.ts)}</span></span></div>
          )}
        </section>
      )}
    </aside>
  );
}
