"use client";

import {
  Area, AreaChart, CartesianGrid, Line, LineChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from "recharts";

export const FUEL_COLORS = {
  coal: "#6e6e6e", gas: "#e0a030", oil: "#a0522d", hydro: "#4f9cd6",
  nuclear: "#b06fc9", solar: "#f5d33c", wind: "#7fd4c1", biomass: "#8a9a4a",
  res_nonsolar: "#6fbf73", other: "#888", own_generation: "#2e7d6e", import: "#5470c6",
};
export const FUEL_LABELS = { res_nonsolar: "other RE", own_generation: "own gen" };

const BUCKET_MS = 15 * 60 * 1000;
const HOUR_MS = 3600 * 1000;

const bucket = (iso) => Math.round(new Date(iso).getTime() / BUCKET_MS) * BUCKET_MS;

export function fmtIST(ms, withDay = false) {
  const opts = { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Kolkata" };
  if (withDay) opts.weekday = "short";
  return new Intl.DateTimeFormat("en-IN", opts).format(new Date(ms));
}

function hourTicks(t0, t1, everyH = 3) {
  // ticks on round IST hours (IST = UTC+5:30, so hour marks sit at :30 UTC)
  const step = everyH * HOUR_MS;
  const off = 5.5 * HOUR_MS;
  const ticks = [];
  for (let t = Math.ceil((t0 + off) / step) * step - off; t <= t1; t += step) ticks.push(t);
  return ticks;
}

const axisStyle = { fontSize: 10, fill: "#8a93ab" };
const gridStroke = "#26304f";

function ChartTip({ active, payload, label, unit, digits = 1 }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tip">
      <div className="t-age">{fmtIST(label, true)} IST</div>
      {payload.filter((p) => p.value != null && p.value !== 0).map((p) => (
        <div key={p.dataKey}>
          <span className="dot" style={{ background: p.stroke || p.fill }} />
          {FUEL_LABELS[p.dataKey] || p.dataKey}: <b>{Number(p.value).toFixed(digits)} {unit}</b>
          {p.payload[`${p.dataKey}_src`] ? <span className="src"> {p.payload[`${p.dataKey}_src`]}</span> : null}
        </div>
      ))}
    </div>
  );
}

/** Demand, GW: today solid + yesterday dashed overlay. */
export function DemandChart({ points }) {
  const now = Date.now();
  const t0 = now - 24 * HOUR_MS;
  const rows = new Map();
  for (const p of points) {
    if (p.metric !== "demand_met" || p.fuel) continue;
    const t = bucket(p.ts);
    const gw = p.value / 1000;
    if (t >= t0) {
      const r = rows.get(t) || { t };
      r.today = gw;
      r.today_src = p.source;
      rows.set(t, r);
    } else {
      const ts = t + 24 * HOUR_MS; // overlay yesterday on today's axis
      const r = rows.get(ts) || { t: ts };
      r.yesterday = gw;
      rows.set(ts, r);
    }
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  if (!data.length) return <p className="age">no demand history</p>;
  return (
    <>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={data} margin={{ top: 4, right: 6, left: -14, bottom: 0 }}>
          <CartesianGrid stroke={gridStroke} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[t0, now]} ticks={hourTicks(t0, now)}
                 tickFormatter={(t) => fmtIST(t)} tick={axisStyle} />
          <YAxis domain={[0, "auto"]} tick={axisStyle} width={44}
                 label={{ value: "GW", angle: -90, position: "insideLeft", fill: "#8a93ab", fontSize: 10 }} />
          <Tooltip content={<ChartTip unit="GW" />} />
          <Line dataKey="yesterday" stroke="#8a93ab" strokeDasharray="4 4" dot={false}
                strokeWidth={1} isAnimationActive={false} connectNulls />
          <Line dataKey="today" stroke="#ffb454" dot={false} strokeWidth={2}
                isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-caption">demand met, last 24 h (IST) · dashed = yesterday</div>
    </>
  );
}

/** Generation, stacked GW by fuel; falls back to own-gen vs import. */
export function GenerationChart({ points }) {
  const now = Date.now();
  const t0 = now - 24 * HOUR_MS;
  const fuels = new Set();
  let anyEstimated = false;
  const rows = new Map();
  const fuelPoints = points.filter(
    (p) => p.metric === "generation" && p.fuel && p.fuel !== "own_generation"
      && bucket(p.ts) >= t0
  );
  let mode = "fuel";
  let series = fuelPoints;
  if (!fuelPoints.length) {
    mode = "ownimport";
    series = points.filter(
      (p) => bucket(p.ts) >= t0 &&
        ((p.metric === "generation" && p.fuel === "own_generation") || p.metric === "net_import")
    ).map((p) => ({ ...p, fuel: p.metric === "net_import" ? "import" : "own_generation" }));
  }
  for (const p of series) {
    const t = bucket(p.ts);
    const r = rows.get(t) || { t };
    r[p.fuel] = (p.value > 0 ? p.value : 0) / 1000;
    r[`${p.fuel}_src`] = p.source;
    if (p.estimated) anyEstimated = true;
    fuels.add(p.fuel);
    rows.set(t, r);
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  if (!data.length) return <p className="age">no generation history</p>;
  const order = ["coal", "other", "gas", "oil", "nuclear", "hydro", "wind", "solar",
                 "biomass", "res_nonsolar", "own_generation", "import"].filter((f) => fuels.has(f));
  return (
    <>
      <ResponsiveContainer width="100%" height={170}>
        <AreaChart data={data} margin={{ top: 4, right: 6, left: -14, bottom: 0 }}>
          <CartesianGrid stroke={gridStroke} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[t0, now]} ticks={hourTicks(t0, now)}
                 tickFormatter={(t) => fmtIST(t)} tick={axisStyle} />
          <YAxis domain={[0, "auto"]} tick={axisStyle} width={44}
                 label={{ value: "GW", angle: -90, position: "insideLeft", fill: "#8a93ab", fontSize: 10 }} />
          <Tooltip content={<ChartTip unit="GW" digits={2} />} />
          {order.map((f) => (
            <Area key={f} dataKey={f} stackId="g" stroke={FUEL_COLORS[f]}
                  fill={FUEL_COLORS[f]} fillOpacity={anyEstimated ? 0.45 : 0.75}
                  strokeWidth={1} isAnimationActive={false} connectNulls />
          ))}
        </AreaChart>
      </ResponsiveContainer>
      <div className="chart-caption">
        {mode === "fuel" ? "generation by fuel" : "own generation vs import"}, last 24 h (IST)
        {anyEstimated ? " · estimated (lighter fill)" : " · measured"}
      </div>
    </>
  );
}

/** Carbon intensity line, gCO2/kWh. */
export function CIChart({ points }) {
  const now = Date.now();
  const t0 = now - 24 * HOUR_MS;
  const rows = new Map();
  let anyEstimated = false;
  for (const p of points) {
    if (p.metric !== "carbon_intensity") continue;
    const t = bucket(p.ts);
    if (t < t0) continue;
    rows.set(t, { t, ci: p.value, ci_src: p.source });
    if (p.estimated) anyEstimated = true;
  }
  const data = [...rows.values()].sort((a, b) => a.t - b.t);
  if (!data.length) return null;
  return (
    <>
      <ResponsiveContainer width="100%" height={130}>
        <LineChart data={data} margin={{ top: 4, right: 6, left: -14, bottom: 0 }}>
          <CartesianGrid stroke={gridStroke} vertical={false} />
          <XAxis dataKey="t" type="number" domain={[t0, now]} ticks={hourTicks(t0, now)}
                 tickFormatter={(t) => fmtIST(t)} tick={axisStyle} />
          <YAxis domain={[0, "auto"]} tick={axisStyle} width={44}
                 label={{ value: "g/kWh", angle: -90, position: "insideLeft", fill: "#8a93ab", fontSize: 10 }} />
          <Tooltip content={<ChartTip unit="gCO₂/kWh" digits={0} />} />
          <Line dataKey="ci" stroke="#8fbf4d" dot={false} strokeWidth={2}
                strokeDasharray={anyEstimated ? "6 3" : "0"} isAnimationActive={false} connectNulls />
        </LineChart>
      </ResponsiveContainer>
      <div className="chart-caption">
        carbon intensity gCO₂/kWh, last 24 h (IST){anyEstimated ? " · estimated (dashed)" : ""}
      </div>
    </>
  );
}
