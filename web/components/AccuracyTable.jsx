"use client";

import { ZONE_TO_NAME } from "../lib/zones";

// Renders the CI-accuracy backtest: worst-case headline + per-state table.
// `ci` is the /v1/status ci_accuracy object. Shared by /status and /methodology.
export default function AccuracyTable({ ci }) {
  if (!ci) return null;
  const { overall, merit_method, per_state } = ci;

  return (
    <>
      {(overall || merit_method) && (
        <div className="accuracy-headline">
          {overall && (
            <p>
              For the <b>{overall.zones} states</b> we can check against independent
              measured/actual fuel energy, estimated carbon intensity is within a
              <b> median of {overall.median_abs_pct}%</b> (mean absolute error
              {" "}{overall.mean_abs_g} gCO₂/kWh, {overall.n} state-days).
            </p>
          )}
          {merit_method && (
            <p>
              <b>Worst case</b> — when only the MERIT T-2 schedule is available
              (no measured or PSP data), CI is within a median of{" "}
              <b>{merit_method.median_abs_pct}%</b> of actual ({merit_method.zones}
              {" "}states, {merit_method.n} state-days). This bounds trust for the
              merit-only and grey states.
            </p>
          )}
        </div>
      )}
      <table>
        <thead><tr>
          <th>state</th><th>basis</th><th>median |error|</th>
          <th>mean |error|</th><th>signed bias</th><th>actual CI</th><th>n days</th><th>independent</th>
        </tr></thead>
        <tbody>
          {(per_state || []).map((r) => (
            <tr key={r.zone} className={r.ci_actual < 100 ? "muted-row" : ""}>
              <td>{ZONE_TO_NAME[r.zone] || r.zone}</td>
              <td>{r.basis}</td>
              <td>{r.ci_actual < 100 ? "—" : `${r.median_abs_pct}%`}</td>
              <td>{r.mean_abs_g} g</td>
              <td>{r.signed_bias_pct > 0 ? "+" : ""}{r.signed_bias_pct}%</td>
              <td>{r.ci_actual} g</td>
              <td>{r.n_days}</td>
              <td>yes</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="sub">
        Actual CI = actual fuel-energy split (RLDC PSP 2A or CEA dgr2+RE) × the
        same emission factors used live, so the error isolates fuel-share error.
        States cross-checked against CEA carry CEA's conventional-scope bias
        (it under-weights renewables), which adds a standing negative bias.
        Near-zero-carbon hydro states (actual &lt; 100 g) are shown in grey and
        omitted from the % headline — a small absolute miss is a huge percentage.
        Circular cells (estimate and actual from the same chain) are excluded.
      </p>
    </>
  );
}
