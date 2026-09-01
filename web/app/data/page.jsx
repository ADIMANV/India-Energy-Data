// The download page. The whole point of the project is that India's grid data
// is published but not comparable, so the one artefact that has to be obvious
// is a single file with one shape for every state.
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const metadata = {
  title: "Download data — India Electricity Data",
  description:
    "Live grid data for all 32 Indian states in one CSV or JSON, with identical columns for every state.",
};

const COLUMNS = [
  ["zone", "text", "ISO 3166-2:IN code. IN is the national row."],
  ["zone_name", "text", "State or union territory name."],
  ["ts_utc", "ISO 8601", "Timestamp of the underlying measurement, UTC. Sources publish on 15-minute time blocks."],
  ["data_age_min", "number", "Minutes between ts_utc and the moment the file was generated."],
  ["demand_met_mw", "MW", "Demand met."],
  ["carbon_intensity_gco2_kwh", "gCO2eq/kWh", "Generation-based carbon intensity. See the caveat below."],
  ["ci_estimated", "true / false", "false only where a state publishes live per-fuel SCADA. true means modelled."],
  ["ci_basis", "text", "Which rung of the freshness ladder produced the mix: measured, psp_actual_t1, cea_blend_t1 or merit_schedule_t2."],
  ["gen_coal_mw … gen_other_mw", "MW", "Generation by fuel: coal, gas, oil, nuclear, hydro, wind, solar, biomass, res_nonsolar, other. Blank where that state's sources don't publish a breakdown."],
  ["gen_total_mw", "MW", "Sum of the fuel columns. Not equal to demand — the difference is imports and unattributed energy."],
  ["net_import_mw", "MW", "Net import. Positive means the state is drawing more than it generates."],
  ["exchange_price_rs_kwh", "₹/kWh", "Power exchange price where published."],
];

export default function DataPage() {
  return (
    <main className="doc-page">
      <div className="doc-nav">
        <a href="/">← map</a>
        <a href="/methodology">methodology →</a>
      </div>

      <h1>Download data</h1>
      <p>
        Every state, one file, the same columns for all of them. Values are the
        current 15-minute time block, refreshed every 15 minutes. Free, no key,
        no rate limit.
      </p>

      <div className="dl-row">
        <a className="dl-btn" href={`${API}/v1/export/live.csv`}>
          Download CSV
        </a>
        <a className="dl-btn secondary" href={`${API}/v1/export/live.json`}>
          Download JSON
        </a>
      </div>

      <h2>From the command line</h2>
      <pre>
        <code>curl -O {API}/v1/export/live.csv</code>
      </pre>

      <h2>Installed capacity by sector</h2>
      <p>
        A separate, slower-moving dataset: installed capacity per state, split
        by ownership sector (state, private, central) and fuel, from CEA&rsquo;s
        monthly report. This is <strong>capacity, not generation</strong> —
        solar and wind run at far lower capacity factors than coal, so a
        private capacity share is not a private generation share.
      </p>
      <div className="dl-row">
        <a className="dl-btn secondary" href={`${API}/v1/export/capacity.csv`}>
          Download capacity CSV
        </a>
      </div>

      <h2>Columns</h2>
      <p>
        Blank means that state&rsquo;s sources do not publish the field — not
        that the value is zero. The column set never varies by state.
      </p>
      <div className="table-scroll">
        <table className="dict">
          <thead>
            <tr><th>Column</th><th>Unit</th><th>Meaning</th></tr>
          </thead>
          <tbody>
            {COLUMNS.map(([name, unit, desc]) => (
              <tr key={name}>
                <td><code>{name}</code></td>
                <td className="unit">{unit}</td>
                <td>{desc}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h2>Two things to read before using this</h2>
      <p>
        <strong>Check <code>ci_estimated</code> before quoting a carbon number.</strong>{" "}
        Only a handful of states publish live per-fuel generation; for everyone
        else the mix is modelled from day-old reports and labelled accordingly.
        The <a href="/methodology">methodology</a> explains how, and{" "}
        <a href="/data-gaps">data gaps</a> explains what that costs.
      </p>
      <p>
        <strong>Carbon intensity here is generation-based, not consumption-based.</strong>{" "}
        It describes what a state generates, not what it consumes. For
        import-heavy states the two differ a great deal — Kerala imports roughly
        90% of its electricity, so its number reflects a small domestic fleet
        rather than the power its consumers actually draw.
      </p>

      <h2>Other endpoints</h2>
      <div className="table-scroll">
        <table className="dict">
          <thead><tr><th>Endpoint</th><th>Returns</th></tr></thead>
          <tbody>
            <tr><td><code>/v1/zones</code></td><td>All zones, latest demand and carbon intensity</td></tr>
            <tr><td><code>/v1/zone/{"{id}"}/live</code></td><td>Every current metric for one zone</td></tr>
            <tr><td><code>/v1/zone/{"{id}"}/history?metric=&amp;hours=</code></td><td>Timeseries, up to 168 hours</td></tr>
            <tr><td><code>/v1/zone/{"{id}"}/export.csv?metric=&amp;hours=</code></td><td>Historical CSV for one zone and metric</td></tr>
            <tr><td><code>/v1/status</code></td><td>Per-source uptime, cross-checks, schema drift, backtests</td></tr>
          </tbody>
        </table>
      </div>

      <h2>Licence and attribution</h2>
      <p>
        Code is MIT. The underlying data is public and remains subject to its
        publishers&rsquo; terms — Ministry of Power (Vidyut Pravah, MERIT), the
        regional load despatch centres, CEA, and the state load despatch centres.
        If you use this, please credit them alongside this project.
      </p>
    </main>
  );
}
