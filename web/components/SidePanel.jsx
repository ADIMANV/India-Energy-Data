"use client";

import { useEffect, useState } from "react";
import { fetchLive, fetchHistory } from "../lib/api";
import { ZONE_TO_NAME, ageLabel, ageMinutes, fmtMW, STALE_AFTER_MIN } from "../lib/zones";

const FUEL_COLORS = {
  coal: "#6e6e6e", gas: "#e0a030", oil: "#a0522d", hydro: "#4f9cd6",
  nuclear: "#b06fc9", solar: "#f5d33c", wind: "#7fd4c1", biomass: "#8a9a4a",
  res_nonsolar: "#6fbf73", other: "#888",
};
const FUEL_LABELS = { res_nonsolar: "other RE" };

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

function Sparkline({ points }) {
  if (!points?.length) return <div className="age">no history yet</div>;
  const w = 300, h = 70, pad = 4;
  const ts = points.map((p) => new Date(p.ts).getTime());
  const vs = points.map((p) => p.value);
  const [t0, t1] = [Math.min(...ts), Math.max(...ts)];
  const [v0, v1] = [Math.min(...vs), Math.max(...vs)];
  const x = (t) => pad + ((t - t0) / Math.max(t1 - t0, 1)) * (w - 2 * pad);
  const y = (v) => h - pad - ((v - v0) / Math.max(v1 - v0, 1)) * (h - 2 * pad);
  const d = points.map((p, i) => `${i ? "L" : "M"}${x(ts[i]).toFixed(1)},${y(vs[i]).toFixed(1)}`).join(" ");
  return (
    <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
      <path d={d} fill="none" stroke="#ffb454" strokeWidth="2" />
    </svg>
  );
}

export default function SidePanel({ zone, refreshKey }) {
  const [live, setLive] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!zone) return;
    setError(null);
    Promise.all([fetchLive(zone), fetchHistory(zone, "demand_met", 24)])
      .then(([l, h]) => { setLive(l); setHistory(h); })
      .catch((e) => { setLive(null); setHistory(null); setError(String(e)); });
  }, [zone, refreshKey]);

  if (!zone) {
    return (
      <aside className="panel">
        <p className="hint">
          Click a state to see live demand, generation vs import split,
          exchange price, and the last 24 hours.
        </p>
      </aside>
    );
  }
  if (error) {
    return (
      <aside className="panel">
        <h2>{ZONE_TO_NAME[zone] || zone}</h2>
        <p className="hint">No recent data for this state. ({error})</p>
      </aside>
    );
  }
  if (!live) return <aside className="panel"><p className="hint">Loading…</p></aside>;

  const byMetric = {};
  for (const m of live.metrics) byMetric[m.fuel ? `${m.metric}:${m.fuel}` : m.metric] = m;

  const demand = byMetric["demand_met"];
  const ownGen = byMetric["generation:own_generation"];
  const imp = byMetric["net_import"];
  const price = byMetric["exchange_price"];
  const purchase = byMetric["exchange_purchase"];
  const ci = byMetric["carbon_intensity"];
  const stale = demand && ageMinutes(demand.ts) > STALE_AFTER_MIN;
  const splitTotal = (ownGen?.value || 0) + (imp?.value || 0);

  // per-fuel generation rows (exclude MERIT's own_generation aggregate)
  const mix = live.metrics
    .filter((m) => m.metric === "generation" && m.fuel && m.fuel !== "own_generation")
    .filter((m) => ageMinutes(m.ts) <= STALE_AFTER_MIN)
    .sort((a, b) => b.value - a.value);
  const mixEstimated = mix.some((m) => m.estimated);

  return (
    <aside className="panel">
      <h2>{ZONE_TO_NAME[zone] || zone}</h2>
      <div className={`age ${stale ? "stale" : ""}`}>
        updated {demand ? ageLabel(demand.ts) : "—"}{stale ? " (STALE)" : ""}
      </div>

      <div className="big">{fmtMW(demand?.value)}</div>
      <div className="row"><span className="k">Demand met</span>
        <span>{fmtMW(demand?.value)}<span className="src">{demand?.source}</span></span></div>
      {ci && (
        <div className="row"><span className="k">Carbon intensity</span>
          <span>
            {Math.round(ci.value)} gCO₂/kWh
            {ci.estimated ? <span className="badge">estimated</span> : <span className="badge measured">measured</span>}
          </span></div>
      )}

      {mix.length > 0 && (
        <>
          <h3>
            Generation mix
            {mixEstimated
              ? <span className="badge">estimated</span>
              : <span className="badge measured">measured</span>}
          </h3>
          <Donut mix={mix} />
        </>
      )}

      {splitTotal > 0 && (
        <>
          <h3>Own generation vs import</h3>
          <div className="splitbar">
            <div className="own" style={{ width: `${((ownGen?.value || 0) / splitTotal) * 100}%` }} />
            <div className="imp" style={{ width: `${((imp?.value || 0) / splitTotal) * 100}%` }} />
          </div>
          <div className="splitlabels">
            <span>own {fmtMW(ownGen?.value)}</span>
            <span>import {fmtMW(imp?.value)}</span>
          </div>
        </>
      )}

      <h3>Exchange</h3>
      {price && (
        <div className="row"><span className="k">Price</span>
          <span>₹{price.value.toFixed(2)}/kWh<span className="src">{ageLabel(price.ts)}</span></span></div>
      )}
      {purchase && (
        <div className="row"><span className="k">Purchased</span>
          <span>{fmtMW(purchase.value)}<span className="src">{ageLabel(purchase.ts)}</span></span></div>
      )}

      <h3>Demand, last 24 h</h3>
      <Sparkline points={history?.points} />
    </aside>
  );
}
