// GeoJSON ST_NM (datameet/maps spellings, sic) -> zone id used by the API.
// UTs without grid data (Andaman, Lakshadweep, ...) are deliberately absent.
export const NAME_TO_ZONE = {
  "Andhra Pradesh": "IN-AP",
  "Arunanchal Pradesh": "IN-AR",
  "Assam": "IN-AS",
  "Bihar": "IN-BR",
  "Chandigarh": "IN-CH",
  "Chhattisgarh": "IN-CG",
  "NCT of Delhi": "IN-DL",
  "Goa": "IN-GA",
  "Gujarat": "IN-GJ",
  "Haryana": "IN-HR",
  "Himachal Pradesh": "IN-HP",
  "Jammu & Kashmir": "IN-JK",
  "Jharkhand": "IN-JH",
  "Karnataka": "IN-KA",
  "Kerala": "IN-KL",
  "Madhya Pradesh": "IN-MP",
  "Maharashtra": "IN-MH",
  "Manipur": "IN-MN",
  "Meghalaya": "IN-ML",
  "Mizoram": "IN-MZ",
  "Nagaland": "IN-NL",
  "Odisha": "IN-OD",
  "Puducherry": "IN-PY",
  "Punjab": "IN-PB",
  "Rajasthan": "IN-RJ",
  "Sikkim": "IN-SK",
  "Tamil Nadu": "IN-TN",
  "Telangana": "IN-TS",
  "Tripura": "IN-TR",
  "Uttar Pradesh": "IN-UP",
  "Uttarakhand": "IN-UK",
  "West Bengal": "IN-WB",
};

export const ZONE_TO_NAME = Object.fromEntries(
  Object.entries(NAME_TO_ZONE).map(([name, zone]) => [zone, name])
);

export function ageMinutes(isoTs) {
  return (Date.now() - new Date(isoTs).getTime()) / 60000;
}

export function ageLabel(isoTs) {
  if (!isoTs) return "no data";
  const m = Math.round(ageMinutes(isoTs));
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.floor(m / 60);
  return `${h} h ${m % 60} min ago`;
}

export const STALE_AFTER_MIN = 60;

export function fmtMW(v) {
  if (v == null) return "—";
  if (v >= 1000) return `${(v / 1000).toFixed(1)} GW`;
  return `${Math.round(v).toLocaleString("en-IN")} MW`;
}
