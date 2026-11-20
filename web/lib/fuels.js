// What each fuel is called and how it is drawn — shared by the map, the legend
// and the side panel, so a fuel looks the same everywhere on the site.
//
// Colour is by GROUP, not by fuel. On a map any two plants can end up side by
// side, and no set of more than three hues stays tellable-apart for every pair
// — for colour-blind readers, and past four not even with full colour vision
// (checked with the dataviz validator, all pairs, OKLab ΔE). These three pass
// on the map's land colour: worst pair ΔE 13.2 colour-blind, 19.3 normal. The
// individual fuel is carried by labels, tooltips and the legend filter.
export const GROUPS = {
  fossil: { label: "Fossil", color: "#d55181" },
  firm: { label: "Hydro & nuclear", color: "#3987e5" },
  renewable: { label: "Solar, wind & biomass", color: "#c98500" },
  // energy we can't attribute to a fuel (exchange purchases, own-generation
  // totals). Neutral on purpose: calling it fossil would be a guess.
  unattributed: { label: "Unattributed", color: "#6f6a61" },
};
export const GROUP_ORDER = ["fossil", "firm", "renewable", "unattributed"];

export const FUEL_GROUP = {
  coal: "fossil", gas: "fossil", oil: "fossil",
  hydro: "firm", nuclear: "firm",
  solar: "renewable", wind: "renewable", biomass: "renewable", res_nonsolar: "renewable",
  other: "unattributed", own_generation: "unattributed",
};

const FUEL_LABELS = {
  res_nonsolar: "other renewables", own_generation: "own generation",
  other: "unattributed", import: "imported",
};
export const fuelLabel = (fuel) => FUEL_LABELS[fuel] || fuel;
export const fuelGroup = (fuel) => FUEL_GROUP[fuel] || "unattributed";
export const fuelColor = (fuel) => GROUPS[fuelGroup(fuel)].color;

// fossil first (descending carbon), then low-carbon — stable stack order
export const FUEL_ORDER = [
  "coal", "oil", "gas", "other", "nuclear", "hydro", "biomass", "res_nonsolar", "wind", "solar",
];

// What India actually has installed, for scale against the 2021 registry the
// map draws. All-India utility capacity, CEA installed capacity report;
// renewablesMw is CEA's RES column (solar, wind, biomass, small hydro).
export const INSTALLED = { mw: 551995, renewablesMw: 239661, asOf: "July 2026", source: "CEA" };

// Plain-English names for the freshness-ladder rungs the API reports.
export const BASIS_LABELS = {
  measured: "measured · live state SCADA",
  psp_actual_t1: "estimated · from yesterday's plant actuals",
  cea_blend_t1: "estimated · from yesterday's CEA report",
  merit_schedule_t2: "estimated · from the dispatch schedule",
};
