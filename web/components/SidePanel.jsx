"use client";

import { useEffect, useState } from "react";
import { fetchLive, fetchPanelHistory } from "../lib/api";
import { ZONE_TO_NAME, ageLabel, ageMinutes, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { BASIS_LABELS } from "../lib/fuels";
import { CIChart, FuelBars, SupplyChart, yesterdayDelta } from "./charts";

// Whether a number was measured or estimated is the credibility marker, so it
// is said in words next to the number, and one click explains how.
function BasisNote({ estimated, basis }) {
  const label = estimated ? BASIS_LABELS[basis] || "estimated" : BASIS_LABELS.measured;
  return (
    <a className={`basis${estimated ? "" : " measured"}`} href="/methodology#freshness-ladder"
       title="How this is computed">{label}</a>
  );
}

// "▲ 3.2% vs same time yesterday" — same clock-time delta, restrained styling
function Delta({ d }) {
  if (!d) return null;
  const up = d.delta >= 0;
  return (
    <span className="delta">
      <span className="num">{up ? "▲" : "▼"} {Math.abs(d.pct).toFixed(1)}%</span>
      <span className="delta-basis">vs same time yesterday</span>
    </span>
  );
}

function Figure({ label, value, unit, delta, note }) {
  return (
    <div className="figure">
      <div className="figure-label">{label}</div>
      <div className="figure-value">
        <span className="fig">{value}</span>
        {unit && <span className="figure-unit">{unit}</span>}
      </div>
      {delta && <Delta d={delta} />}
      {note && <div className="figure-note">{note}</div>}
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
    return <aside className="panel"><h2>{title}</h2><p className="hint">No recent data. ({error})</p></aside>;
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

  const mix = live.metrics
    .filter((m) => m.metric === "generation" && m.fuel && m.fuel !== "own_generation")
    .filter((m) => ageMinutes(m.ts) <= STALE_AFTER_MIN)
    .sort((a, b) => b.value - a.value);
  const mixEstimated = mix.some((m) => m.estimated);
  const mixBasis = mix.find((m) => m.estimation_basis)?.estimation_basis;
  // The national mix is a sum of whichever states reported by fuel in the last
  // half hour. If that covers a sliver of demand — only the few live-SCADA
  // states — it is not India's mix, and drawing it as one would mislead.
  const mixMW = mix.reduce((s, m) => s + m.value, 0);
  const partialNational = isNational && demand && mixMW < 0.5 * demand.value;
  const points = history?.points || [];
  const hasSupply = points.some((p) => p.metric === "generation");
  const demandDelta = yesterdayDelta(points, "demand_met");
  const ciDelta = yesterdayDelta(points, "carbon_intensity");

  return (
    <aside className="panel">
      {!isNational && (
        <button className="breadcrumb" onClick={() => onSelect("IN")}>← All India</button>
      )}
      <h2>{title}</h2>
      <div className={`age ${stale ? "stale" : ""}`}>
        Updated {demand ? ageLabel(demand.ts) : "—"}{stale ? " · stale" : ""}
      </div>

      <div className="figures">
        <Figure label="Demand met" value={fmtMW(demand?.value)} delta={demandDelta} />
        {ci && (
          <Figure
            label="Carbon intensity"
            value={Math.round(ci.value)} unit="gCO₂/kWh" delta={ciDelta}
            note={<BasisNote estimated={ci.estimated} basis={ci.estimation_basis} />}
          />
        )}
      </div>

      {/* generation mix — the differentiated thing, leads the data */}
      {mix.length > 0 && partialNational && (
        <section className="block">
          <h3>Generation mix</h3>
          <p className="hint">
            Only {fmtMW(mixMW)} of the {fmtMW(demand.value)} India is using right now has been
            reported by fuel, too little to call a national mix. Pick a state to see its own.
          </p>
        </section>
      )}
      {mix.length > 0 && !partialNational && (
        <section className="block">
          <h3>Generation mix</h3>
          <div className="block-note"><BasisNote estimated={mixEstimated} basis={mixBasis} /></div>
          <FuelBars mix={mix} />
        </section>
      )}

      {hasSupply && (
        <section className="block">
          <h3>Supply</h3>
          <SupplyChart points={points} />
        </section>
      )}

      {points.some((p) => p.metric === "carbon_intensity") && (
        <section className="block">
          <h3>Carbon intensity</h3>
          <CIChart points={points} />
        </section>
      )}

      {(price || purchase) && (
        <section className="block">
          <h3>Power exchange</h3>
          {price && (
            <div className="row"><span className="k">Price</span>
              <span className="num">₹{price.value.toFixed(2)}/kWh</span></div>
          )}
          {purchase && (
            <div className="row"><span className="k">Purchased</span>
              <span className="num">{fmtMW(purchase.value)}</span></div>
          )}
        </section>
      )}
    </aside>
  );
}
