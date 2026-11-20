"use client";

import { useEffect, useState } from "react";
import { fetchLive, fetchPanelHistory } from "../lib/api";
import { ZONE_TO_NAME, ageLabel, ageMinutes, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { BASIS_LABELS } from "../lib/fuels";
import { CIChart, FuelBars, SupplyChart, yesterdayDelta } from "./charts";

const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) || n % 10 > 3 ? 0 : n % 10]}`;
const freshCI = (z) =>
  z?.carbon_intensity && ageMinutes(z.carbon_intensity.ts) <= STALE_AFTER_MIN ? z.carbon_intensity : null;

// Whether a number was measured or estimated is the credibility marker, so it
// is said in words next to the number, and one click explains how.
function BasisNote({ estimated, basis }) {
  const label = estimated ? BASIS_LABELS[basis] || "estimated" : BASIS_LABELS.measured;
  return (
    <a className={`basis${estimated ? "" : " measured"}`} href="/methodology#freshness-ladder"
       title="How this is computed">{label}</a>
  );
}

// One stat: a small label, the number, and what qualifies it.
function Tile({ label, value, unit, sub, bar }) {
  return (
    <div className="tile">
      <div className="tile-label">{label}</div>
      <div className="tile-value">
        <span className="num">{value}</span>
        {unit && <span className="tile-unit">{unit}</span>}
      </div>
      {bar != null && <div className="tile-bar"><i style={{ width: `${Math.max(3, bar * 100)}%` }} /></div>}
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

function deltaText(d) {
  if (!d) return "no reading 24 h ago";
  return `${d.delta >= 0 ? "▲" : "▼"} ${Math.abs(d.pct).toFixed(1)}% vs yesterday`;
}

export default function SidePanel({ zone, onSelect, refreshKey, zonesData }) {
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
  const head = (meta) => (
    <div className="p-head">
      <nav className="crumbs" aria-label="Breadcrumb">
        {isNational ? <span>India</span> : (
          <><button onClick={() => onSelect("IN")}>India</button><span aria-hidden="true">›</span><span>{title}</span></>
        )}
      </nav>
      <h2>{title}</h2>
      {meta}
    </div>
  );

  if (error) return <aside className="panel">{head(<p className="p-meta">No recent data. ({error})</p>)}</aside>;
  if (!live) return <aside className="panel">{head(<p className="p-meta">Loading…</p>)}</aside>;

  const byMetric = {};
  for (const m of live.metrics) {
    const key = m.fuel ? `${m.metric}:${m.fuel}` : m.metric;
    if (!(key in byMetric)) byMetric[key] = m;
  }
  const demand = byMetric["demand_met"];
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

  // context from the all-zones feed: share and rank of India's demand, and
  // how this state's carbon intensity compares with India's grid
  const zones = zonesData?.zones || [];
  const india = zones.find((z) => z.zone === "IN");
  const ranked = zones.filter((z) => z.zone !== "IN" && ageMinutes(z.ts) <= STALE_AFTER_MIN)
    .sort((a, b) => b.demand_met_mw - a.demand_met_mw);
  const rank = ranked.findIndex((z) => z.zone === zone) + 1;
  const indiaCI = freshCI(india);
  const vsIndia = !isNational && ci && indiaCI ? ((ci.value - indiaCI.value) / indiaCI.value) * 100 : null;

  return (
    <aside className="panel">
      {head(
        <p className={`p-meta${stale ? " stale" : ""}`}>
          Updated {demand ? ageLabel(demand.ts) : "—"}{stale ? " · stale" : ""}
        </p>,
      )}

      <section className="p-sec">
        <h3>Right now</h3>
        <div className="tiles">
          <Tile label="Demand met" value={fmtMW(demand?.value)} sub={deltaText(demandDelta)} />
          {isNational ? (
            <Tile label="States reporting" value={ranked.length} sub={`of ${Object.keys(ZONE_TO_NAME).length} with a grid`} />
          ) : (
            <Tile label="Share of India" value={india && demand ? `${((demand.value / india.demand_met_mw) * 100).toFixed(1)}%` : "—"}
                  bar={rank ? (ranked.length - rank + 1) / ranked.length : null}
                  sub={rank ? `${ordinal(rank)} largest of ${ranked.length}` : null} />
          )}
          {ci && (
            <Tile label="Carbon intensity" value={Math.round(ci.value)} unit="g/kWh"
                  sub={<BasisNote estimated={ci.estimated} basis={ci.estimation_basis} />} />
          )}
          {vsIndia != null && (
            <Tile label="Against India's grid" value={`${vsIndia > 0 ? "+" : "−"}${Math.abs(vsIndia).toFixed(0)}%`}
                  sub={`${vsIndia < 0 ? "lower" : "higher"} carbon than ${Math.round(indiaCI.value)} g`} />
          )}
        </div>
      </section>

      {mix.length > 0 && (
        <section className="p-sec">
          <h3>Generation mix</h3>
          {partialNational ? (
            <p className="p-note">
              Only {fmtMW(mixMW)} of the {fmtMW(demand.value)} India is using right now has been
              reported by fuel, too little to call a national mix. Pick a state to see its own.
            </p>
          ) : (
            <div className="card">
              <div className="card-note"><BasisNote estimated={mixEstimated} basis={mixBasis} /></div>
              <FuelBars mix={mix} />
            </div>
          )}
        </section>
      )}

      {hasSupply && (
        <section className="p-sec">
          <h3>Supply, last 24 hours</h3>
          <div className="card"><SupplyChart points={points} /></div>
        </section>
      )}

      {points.some((p) => p.metric === "carbon_intensity") && (
        <section className="p-sec">
          <h3>Carbon intensity, last 24 hours</h3>
          <div className="card"><CIChart points={points} /></div>
        </section>
      )}

      {(price || purchase) && (
        <section className="p-sec">
          <h3>Power exchange</h3>
          <div className="tiles">
            {price && <Tile label="Price" value={`₹${price.value.toFixed(2)}`} unit="/kWh" />}
            {purchase && <Tile label="Bought on the exchange" value={fmtMW(purchase.value)} />}
          </div>
        </section>
      )}
    </aside>
  );
}
