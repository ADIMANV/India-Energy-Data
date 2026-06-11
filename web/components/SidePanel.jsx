"use client";

import { useEffect, useState } from "react";
import { fetchLive, fetchHistory } from "../lib/api";
import { ZONE_TO_NAME, ageLabel, ageMinutes, fmtMW, STALE_AFTER_MIN } from "../lib/zones";

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
  const stale = demand && ageMinutes(demand.ts) > STALE_AFTER_MIN;
  const splitTotal = (ownGen?.value || 0) + (imp?.value || 0);

  return (
    <aside className="panel">
      <h2>{ZONE_TO_NAME[zone] || zone}</h2>
      <div className={`age ${stale ? "stale" : ""}`}>
        updated {demand ? ageLabel(demand.ts) : "—"}{stale ? " (STALE)" : ""}
      </div>

      <div className="big">{fmtMW(demand?.value)}</div>
      <div className="row"><span className="k">Demand met</span>
        <span>{fmtMW(demand?.value)}<span className="src">{demand?.source}</span></span></div>

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
