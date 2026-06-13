"use client";

import { useEffect, useState } from "react";
import { ageLabel } from "../../lib/zones";
import AccuracyTable from "../../components/AccuracyTable";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export default function StatusPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    const load = () =>
      fetch(`${API}/v1/status`, { cache: "no-store" })
        .then((r) => r.json())
        .then(setData)
        .catch((e) => setError(String(e)));
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, []);

  if (error) return <main className="status-page"><p>API unreachable: {error}</p></main>;
  if (!data) return <main className="status-page"><p>Loading…</p></main>;

  const worstDelta = Math.max(0, ...data.cross_checks.map((c) => Math.abs(c.delta_pct)));

  return (
    <main className="status-page">
      <h1>Data quality <a href="/">← map</a></h1>
      <p className="sub">
        Per-source health, cross-source agreement, and response-structure
        tracking. Auto-refreshes every minute. Raw responses are archived
        before parsing; estimates are always flagged.
      </p>

      <h2>Sources</h2>
      <table>
        <thead><tr>
          <th>source</th><th>last success</th><th>datapoints 24h</th>
          <th>uptime 24h</th><th>largest gap 24h</th>
        </tr></thead>
        <tbody>
          {data.sources.map((s) => (
            <tr key={s.source} className={s.uptime_24h_pct < 80 ? "bad" : ""}>
              <td>{s.source}</td>
              <td>{ageLabel(s.last_success)}</td>
              <td>{s.points_24h.toLocaleString()}</td>
              <td>{s.uptime_24h_pct}%</td>
              <td>{s.largest_gap_24h || "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h2>Cross-source demand agreement (Vidyut Pravah vs MERIT)</h2>
      <p className="sub">worst current delta: {worstDelta.toFixed(1)}% (alert threshold 10%)</p>
      <table>
        <thead><tr><th>zone</th><th>vidyut pravah</th><th>merit</th><th>delta</th><th>checked</th></tr></thead>
        <tbody>
          {data.cross_checks
            .sort((a, b) => Math.abs(b.delta_pct) - Math.abs(a.delta_pct))
            .map((c) => (
              <tr key={c.zone} className={Math.abs(c.delta_pct) > 10 ? "bad" : ""}>
                <td>{c.zone}</td>
                <td>{Math.round(c.vidyut_pravah_mw).toLocaleString()} MW</td>
                <td>{Math.round(c.merit_mw).toLocaleString()} MW</td>
                <td>{c.delta_pct > 0 ? "+" : ""}{c.delta_pct.toFixed(1)}%</td>
                <td>{ageLabel(c.checked_at)}</td>
              </tr>
            ))}
        </tbody>
      </table>

      <h2>Carbon-intensity accuracy <a href="/methodology#accuracy">methodology →</a></h2>
      <AccuracyTable ci={data.ci_accuracy} />

      <h2>Cross-source backtests (daily, trailing 7 days)</h2>
      <p className="sub">
        known scope biases are expected (CEA groups plants by location, RLDC PSP
        by control area) — alerts fire only when the relationship shifts &gt;5pp.
      </p>
      <table>
        <thead><tr><th>check</th><th>median delta 7d</th><th>mean |delta| 7d</th><th>zone-days</th><th>latest day</th></tr></thead>
        <tbody>
          {(data.backtests || []).map((b) => (
            <tr key={b.check}>
              <td>{b.check}</td>
              <td>{b.median_delta_pct_7d > 0 ? "+" : ""}{b.median_delta_pct_7d}%</td>
              <td>{b.mean_abs_delta_pct_7d}%</td>
              <td>{b.zone_days_7d}</td>
              <td>{b.latest}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {data.match_audit && (
        <p className="sub">
          MERIT registry match rate (weekly audit): {(data.match_audit.mwh_match_rate * 100).toFixed(1)}%
          · review queue {data.match_audit.review_open} open / {data.match_audit.review_total}
          · audited {ageLabel(data.match_audit.audited_at)}
        </p>
      )}

      <h2>Response structures (drift detection)</h2>
      <table>
        <thead><tr><th>source</th><th>endpoint family</th><th>known structures</th><th>newest first seen</th></tr></thead>
        <tbody>
          {data.schema_structures.map((s) => (
            <tr key={`${s.source}-${s.kind}`} className={s.distinct_structures > 1 ? "bad" : ""}>
              <td>{s.source}</td>
              <td>{s.kind}</td>
              <td>{s.distinct_structures}</td>
              <td>{ageLabel(s.newest_seen)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sub">
        more than one known structure for a family = the source changed shape
        at some point; the scraper tick fails loudly when a new one appears.
      </p>
    </main>
  );
}
