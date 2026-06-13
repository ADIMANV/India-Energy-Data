const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function get(path) {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

export const fetchZones = () => get("/v1/zones");
export const fetchLive = (zone) => get(`/v1/zone/${zone}/live`);
export const fetchHistory = (zone, metric = "demand_met", hours = 24) =>
  get(`/v1/zone/${zone}/history?metric=${metric}&hours=${hours}`);

// one fetch per zone covering every panel chart
export const PANEL_METRICS = "demand_met,generation,carbon_intensity,net_import";
export const fetchPanelHistory = (zone) => fetchHistory(zone, PANEL_METRICS, 48);
