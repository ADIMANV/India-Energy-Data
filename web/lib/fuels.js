// What each fuel is called and how it is drawn — shared by the map, the legend
// and the side panel, so a fuel looks the same everywhere on the site.
//
// Colour is by GROUP, not by fuel. On a map any two plants can end up side by
// side, so every pair has to stay tellable-apart — for colour-blind readers
// too — not just neighbours in a stack. Four groups is the most that passes:
// solar and wind split, because they peak at different hours and sit in
// different districts, and hydro & nuclear stepped deeper so wind's cyan clears
// it. Checked with the dataviz validator, all pairs, OKLab ΔE, on the panel:
// worst pair 10.5 colour-blind, 15.7 normal vision, every colour ≥ 3:1. The
// individual fuel is carried by labels, tooltips and the legend filter.
export const GROUPS = {
  fossil: { label: "Fossil", color: "#d55181" },
  firm: { label: "Hydro & nuclear", color: "#2f6fd6" },
  // CEA often reports wind, biomass and small hydro as one "RES non-solar"
  // number, mostly wind, so they share wind's colour rather than a fifth hue
  wind: { label: "Wind & other renewables", color: "#0ea5c6" },
  solar: { label: "Solar", color: "#c98500" },
  // energy we can't attribute to a fuel (exchange purchases, own-generation
  // totals). Neutral on purpose: calling it fossil would be a guess.
  unattributed: { label: "Unattributed", color: "#6f6a61" },
};
// stack order, bottom up: firm generation first, solar's midday hump on top
export const GROUP_ORDER = ["fossil", "firm", "wind", "solar", "unattributed"];
export const RENEWABLE_GROUPS = ["wind", "solar"];

// The same four hues, stepped darker for the light basemap: the colours above
// sit on the dark panel and fall under 3:1 against light grey land. Validated
// as a set on the map's land colour (all pairs, worst ΔE 8.8 colour-blind,
// 15.2 normal, every colour ≥ 3:1). Wind is only ever a disc and hydro only a
// column, so shape backs up the closest pair.
export const MAP_GROUP_COLORS = {
  fossil: "#c2427a", firm: "#2456b0", wind: "#0a8fb0", solar: "#a86e00",
};

export const FUEL_GROUP = {
  coal: "fossil", gas: "fossil", oil: "fossil",
  hydro: "firm", nuclear: "firm",
  solar: "solar", wind: "wind", biomass: "wind", res_nonsolar: "wind",
  small_hydro: "wind", // MNRE counts plants under 25 MW as renewable, not as large hydro
  other: "unattributed", own_generation: "unattributed",
};

const FUEL_LABELS = {
  res_nonsolar: "other renewables", own_generation: "own generation", small_hydro: "small hydro",
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
// renewablesMw is CEA's "Wind, Solar & Other RE" (solar, wind, biomass, waste
// to energy, small hydro — everything but large hydro and nuclear).
export const INSTALLED = { mw: 563113, renewablesMw: 251149, asOf: "October 2026", source: "CEA" };

// Plain-English names for the freshness-ladder rungs the API reports.
export const BASIS_LABELS = {
  measured: "measured · live state SCADA",
  psp_actual_t1: "estimated · from yesterday's plant actuals",
  cea_blend_t1: "estimated · from yesterday's CEA report",
  merit_schedule_t2: "estimated · from the dispatch schedule",
};
