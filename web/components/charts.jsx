"use client";

import {
  Area, AreaChart, CartesianGrid, Line, ComposedChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

// Deliberate fuel palette: earthy/muted for fossil, cool/clean for low-carbon.
// Consistent across bars and the supply chart.
export const FUEL_COLORS = {
  coal: "#6b6560",          // warm graphite
  gas: "#b5673c",           // muted ember
  oil: "#7c5230",           // lignite brown
  other: "#55504b",         // unattributed → dark warm grey (near-coal)
  nuclear: "#8f78c4",       // violet
  hydro: "#2f9c93",         // teal
  wind: "#9ad7df",          // pale cyan
  solar: "#e3ab32",         // warm gold
  biomass: "#6f8a4a",       // moss
  res_nonsolar: "#4f9e84",  // moss-teal (other RE)
  own_generation: "#6b6560",
  import: "#3a3a3a",        // imported gap — muted, hatched in the chart
};
export const FUEL_LABELS = { res_nonsolar: "other RE", own_generation: "own gen", import: "imported" };

// fossil first (descending carbon), then low-carbon — stable stack order
export const FUEL_ORDER = [
  "coal", "oil", "gas", "other", "nuclear", "hydro", "biomass", "res_nonsolar", "wind", "solar",
];

const BUCKET_MS = 15 * 60 * 1000;
const HOUR_MS = 3600 * 1000;
const ACCENT = "#ffd60a";
const INK = "#8a8a8a";
const GRID = "#1e1e1e";

const bucket = (iso) => Math.round(new Date(iso).getTime() / BUCKET_MS) * BUCKET_MS;

export function fmtIST(ms, withDay = false) {
  const opts = { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" };
  if (withDay) opts.weekday = "short";
  return new Intl.DateTimeFormat("en-IN", opts).format(new Date(ms));
}

function hourTicks(t0, t1, everyH = 3) {
  const step = everyH * HOUR_MS;
  const off = 5.5 * HOUR_MS; // round IST hours sit at :30 UTC
  const ticks = [];
  for (let t = Math.ceil((t0 + off) / step) * step - off; t <= t1; t += step) ticks.push(t);
  return ticks;
}

const axisStyle = { fontSize: 10, fill: INK, fontFamily: "var(--font-mono)" };

function ChartTip({ active, payload, label, unit, digits = 1 }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      <div className="t-age">{fmtIST(label, true)} IST</div>
      {payload.filter((p) => p.value != null && p.value !== 0).map((p) => (
        <div key={p.dataKey}>
          <span className="dot" style={{ background: p.stroke || p.fill }} />
          {FUEL_LABELS[p.dataKey] || p.dataKey}:{" "}
          <b>{Number(p.value).toFixed(digits)} {unit}</b>
        </div>
      ))}
    </div>
  );
}

/** Value now vs the same clock-time ~24h ago. Returns {delta, pct} or null. */
export function yesterdayDelta(points, metric) {
  const pts = points.filter((p) => p.metric === metric && !p.fuel)
    .sort((a, b) => new Date(a.ts) - new Date(b.ts));
  if (pts.length < 2) return null;
  const now = pts[pts.length - 1];
  const target = new Date(now.ts).getTime() - 24 * HOUR_MS;
  let best = null, bestGap = Infinity;
  for (const p of pts) {
    const gap = Math.abs(new Date(p.ts).getTime() - target);
    if (gap < bestGap) { bestGap = gap; best = p; }
  }
  if (!best || bestGap > 90 * 60 * 1000) return null; // need a point within 90 min
  const delta = now.value - best.value;
  return { delta, pct: best.value ? (delta / best.value) * 100 : 0 };
}

/** Horizontal percentage bars, ranked descending. Replaces the donut. */
export function FuelBars({ mix }) {
  const total = mix.reduce((s, m) => s + m.value, 0);
  if (total <= 0) return null;
  return (
    <div className="fuelbars">
      {mix.map((m) => {
        const pct = (m.value / total) * 100;
        return (
          <div className="fuelbar" key={m.fuel}>
            <span className="fuelbar-label">{FUEL_LABELS[m.fuel] || m.fuel}</span>
            <span className="fuelbar-track">
              <span className="fuelbar-fill"
                    style={{ width: `${pct}%`, background: FUEL_COLORS[m.fuel] || "#555" }} />
            </span>
            <span className="fuelbar-pct mono">{pct < 1 ? "<1" : pct.toFixed(0)}%</span>
          </div>
        );
      })}
    </div>
  );
}

/** Supply: stacked generation by fuel + an "imported" gap to demand, with the
 *  demand line overlaid dashed. For self-supplied states the line hugs the
 *  stack top; for importers the imported band fills the gap. */
export function SupplyChart({ points }) {
  const now = Date.now();
  const t0 = now - 24 * HOUR_MS;
  const fuels = new Set();
  let anyEstimated = false, anyImport = false;
  const rows = new Map();

  const fuelPts = points.filter(
    (p) => p.metric === "generation" && p.fuel && p.fuel !== "own_generation" && bucket(p.ts) >= t0);
  let series = fuelPts;
  if (!fuelPts.length) {
    series = points.filter(
      (p) => bucket(p.ts) >= t0 &&
        ((p.metric === "generation" && p.fuel === "own_generation") || p.metric === "net_import"))
      .map((p) => ({ ...p, fuel: p.metric === "net_import" ? "_skip_import" : "own_generation" }))
      .filter((p) => p.fuel !== "_skip_import");
  }
  for (const p of series) {
    const t = bucket(p.ts);
    const r = rows.get(t) || { t };
    r[p.fuel] = (p.value > 0 ? p.value : 0) / 1000;
    if (p.estimated) anyEstimated = true;
    fuels.add(p.fuel);
    rows.set(t, r);
  }
  // overlay demand + compute the imported gap (demand − generation, clamped ≥0)
  for (const p of points) {
    if (p.metric !== "demand_met" || p.fuel) continue;
    const t = bucket(p.ts);
    if (t < t0) continue;
    const r = rows.get(t) || { t };
    r.demand = p.value / 1000;
    rows.set(t, r);
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  for (const r of data) {
    const gen = [...fuels].reduce((s, f) => s + (r[f] || 0), 0);
    if (r.demand != null && gen > 0) {
      const gap = r.demand - gen;
      if (gap > 0.05) { r.imported = gap; anyImport = true; }
    }
  }
  if (!data.length) return <p className="muted">no supply history</p>;
  const order = FUEL_ORDER.filter((f) => fuels.has(f));
  if (fuels.has("own_generation")) order.push("own_generation");

  return (
    <>
      <ResponsiveContainer width="100%" height={184}>
        <ComposedChart data={data} margin={{ top: 6, right: 4, left: -16, bottom: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[t0, now]} ticks={hourTicks(t0, now)}
                 tickFormatter={(t) => fmtIST(t)} tick={axisStyle} stroke={GRID} />
          <YAxis domain={[0, "auto"]} tick={axisStyle} width={42} stroke={GRID} unit="" />
          <Tooltip content={<ChartTip unit="GW" digits={2} />} cursor={{ stroke: INK }} />
          {order.map((f) => (
            <Area key={f} dataKey={f} stackId="g" stroke="none"
                  fill={FUEL_COLORS[f]} fillOpacity={anyEstimated ? 0.55 : 0.85}
                  isAnimationActive={false} connectNulls />
          ))}
          {anyImport && (
            <Area dataKey="imported" stackId="g" stroke="none" fill="url(#importedHatch)"
                  isAnimationActive={false} connectNulls />
          )}
          <Line dataKey="demand" stroke={ACCENT} strokeWidth={1.5} strokeDasharray="5 3"
                dot={false} isAnimationActive={false} connectNulls />
          <defs>
            <pattern id="importedHatch" width="6" height="6" patternUnits="userSpaceOnUse"
                     patternTransform="rotate(45)">
              <rect width="6" height="6" fill="#222" />
              <line x1="0" y1="0" x2="0" y2="6" stroke="#4a4a4a" strokeWidth="1.5" />
            </pattern>
          </defs>
        </ComposedChart>
      </ResponsiveContainer>
      <div className="chart-caption">
        GW · generation mix, last 24 h IST · dashed = demand
        {anyImport ? " · hatched = imported" : ""}
        {anyEstimated ? " · estimated" : " · measured"}
      </div>
    </>
  );
}

/** Carbon intensity line, gCO₂/kWh. Dashed where estimated. */
export function CIChart({ points }) {
  const now = Date.now();
  const t0 = now - 24 * HOUR_MS;
  const rows = new Map();
  let anyEstimated = false;
  for (const p of points) {
    if (p.metric !== "carbon_intensity") continue;
    const t = bucket(p.ts);
    if (t < t0) continue;
    rows.set(t, { t, ci: p.value });
    if (p.estimated) anyEstimated = true;
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  if (!data.length) return null;
  return (
    <>
      <ResponsiveContainer width="100%" height={130}>
        <AreaChart data={data} margin={{ top: 6, right: 4, left: -16, bottom: 0 }}>
          <CartesianGrid stroke={GRID} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[t0, now]} ticks={hourTicks(t0, now)}
                 tickFormatter={(t) => fmtIST(t)} tick={axisStyle} stroke={GRID} />
          <YAxis domain={[0, "auto"]} tick={axisStyle} width={42} stroke={GRID} />
          <Tooltip content={<ChartTip unit="gCO₂/kWh" digits={0} />} cursor={{ stroke: INK }} />
          <defs>
            <linearGradient id="ciFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={ACCENT} stopOpacity={0.18} />
              <stop offset="100%" stopColor={ACCENT} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area dataKey="ci" stroke={ACCENT} strokeWidth={1.5} fill="url(#ciFill)"
                strokeDasharray={anyEstimated ? "5 3" : "0"} dot={false}
                isAnimationActive={false} connectNulls />
        </AreaChart>
      </ResponsiveContainer>
      <div className="chart-caption">
        gCO₂/kWh · carbon intensity, last 24 h IST{anyEstimated ? " · estimated (dashed)" : ""}
      </div>
    </>
  );
}
