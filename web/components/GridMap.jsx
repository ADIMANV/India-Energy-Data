"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { NAME_TO_ZONE, ZONE_TO_NAME, ageMinutes, ageLabel, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { BASIS_LABELS, FUEL_GROUP, GROUPS, INSTALLED, MAP_GROUP_COLORS, fuelGroup, fuelLabel } from "../lib/fuels";
import { ATTRIBUTION, BEFORE_LABELS, baseStyle } from "../lib/basemap";

const BORDER = "rgba(58, 48, 36, 0.36)";
const SELECTED = "#18222c";
const MUTED_PLANT = "#c9bfae";
const SHEET = "#f9f5ec"; // India's paper in plants mode, lighter than the land around it

// Demand: one green-teal hue, light = small, dark = large (on a light map the
// dark end is the emphatic one). Shade is size, not greenness — that's carbon.
const DEMAND_STOPS = [[0, "#d0ece5"], [2000, "#9acdc2"], [8000, "#64ab9d"], [18000, "#2e8576"], [30000, "#005b4f"]];
// Carbon: green ↔ rust around 500 g/kWh. Equal OKLCH lightness steps out from
// a warm paper-coloured midpoint, so low-carbon and coal-heavy states both
// stand out and states near the middle recede into the sheet.
const CARBON_STOPS = [
  [0, "#1b6c36"], [125, "#418954"], [250, "#6fa87b"], [375, "#a8c7ad"], [500, "#e7e0d6"],
  [625, "#deb3a2"], [750, "#ca8469"], [875, "#af5e3e"], [1000, "#903f1c"],
];

const INDIA = [[68, 6.5], [97.5, 36]];
const PLANT_GROUPS = ["fossil", "firm", "renewable"];

// MapLibre draws 512-px tiles: at zoom z one pixel spans 360/(512·2^z) degrees
// of longitude, and 40,075 km/(512·2^z)·cos(lat) metres on the ground.
const DEG_PER_PX_Z0 = 360 / 512;
const M_PER_PX_Z0 = 40075016.686 / 512;
const COLUMN_RADIUS_PX = 1.8;
const GROW_MS = 700;

const fresh = (ts) => ts && ageMinutes(ts) <= STALE_AFTER_MIN;
const ciOf = (z) => (z?.carbon_intensity && fresh(z.carbon_intensity.ts) ? z.carbon_intensity : null);

function fillColorExpr(mode) {
  const [stops, key] = mode === "carbon" ? [CARBON_STOPS, "carbon"] : [DEMAND_STOPS, "demand"];
  return [
    "case",
    ["boolean", ["feature-state", `${key}Missing`], true],
    "rgba(255, 255, 255, 0.35)", // the hatch layer on top marks it as missing
    ["interpolate", ["linear"], ["to-number", ["feature-state", key], -1], ...stops.flat()],
  ];
}

const missingExpr = (key) => ["case", ["boolean", ["feature-state", `${key}Missing`], true], 1, 0];

// Diagonal hairlines for "no data" — texture rather than another colour, so
// missing can never be mistaken for a value on the ramp.
function hatchImage() {
  const n = 8;
  const c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d");
  g.strokeStyle = "rgba(58, 48, 36, 0.34)";
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(-1, n + 1); g.lineTo(n + 1, -1);
  g.moveTo(-1, 1); g.lineTo(1, -1);
  g.moveTo(n - 1, n + 1); g.lineTo(n + 1, n - 1);
  g.stroke();
  return g.getImageData(0, 0, n, n);
}

// Each plant is an octagonal column. The footprint is rebuilt at the end of
// every zoom so columns stay a few pixels wide at any scale; the height is a
// zoom expression over h0, so it holds its on-screen size while zooming.
function columns(plants, zoom) {
  const r = (COLUMN_RADIUS_PX * DEG_PER_PX_Z0) / 2 ** zoom;
  return {
    type: "FeatureCollection",
    features: plants.map((p, i) => {
      const k = Math.cos((p.lat * Math.PI) / 180);
      const ring = [];
      for (let a = 0; a < 8; a++) {
        const t = ((a + 0.5) / 8) * 2 * Math.PI;
        ring.push([p.lon + r * Math.cos(t), p.lat + r * k * Math.sin(t)]);
      }
      ring.push(ring[0]);
      return {
        type: "Feature",
        properties: { i, fuel: p.fuel, zone: p.zone || "", h0: p.h0 },
        geometry: { type: "Polygon", coordinates: [ring] },
      };
    }),
  };
}

// h0 · 0.5^zoom metres is a constant number of pixels at the plant's latitude.
// Base 0.5 is what makes this exact: MapLibre's exponential interpolation
// blends the two stop values, and only a base-0.5 curve between h0 at z0 and
// ~0 at z22 lands on h0 · 0.5^z (base 2 stays at ~h0 until the last zooms).
// MapLibre only accepts ["zoom"] at the top level of the expression, so any
// per-plant condition has to go inside the stops rather than around them.
const heightExpr = (h0) => ["interpolate", ["exponential", 0.5], ["zoom"], 0, h0, 22, ["/", h0, 4194304]];
// darker steps of the same three hues than the panel uses: these sit on a
// light map, the panel's on a dark card (validated separately for each)
const GROUP_COLOR = [
  "match", ["get", "fuel"],
  ["coal", "gas", "oil"], MAP_GROUP_COLORS.fossil,
  ["hydro", "nuclear"], MAP_GROUP_COLORS.firm,
  ["solar", "wind", "biomass", "res_nonsolar", "small_hydro"], MAP_GROUP_COLORS.renewable,
  GROUPS.unattributed.color,
];

// Totals — a district's (or, where districts aren't published, a whole
// state's) solar, wind, biomass and small hydro — are flat discs whose area is
// the capacity. A different mark from a plant's column on purpose: a state's
// 36 GW of solar must never read as one 36 GW plant. The radius doubles with
// each zoom level, so a disc keeps its size relative to the land under it.
const DISC_RADIUS = [
  "interpolate", ["exponential", 2], ["zoom"],
  3, ["*", 0.1, ["sqrt", ["get", "capacity_mw"]]],
  10, ["*", 12.8, ["sqrt", ["get", "capacity_mw"]]],
];

function selection(activeFuels, zone) {
  const conds = [];
  if (activeFuels) conds.push(["in", ["get", "fuel"], ["literal", activeFuels]]);
  if (zone && zone !== "IN") conds.push(["==", ["get", "zone"], zone]);
  return conds.length ? (conds.length === 1 ? conds[0] : ["all", ...conds]) : null;
}

function discPaint(activeFuels, zone) {
  const on = selection(activeFuels, zone);
  if (!on) return { color: GROUP_COLOR, opacity: 0.3, stroke: 0.85 };
  return {
    color: ["case", on, GROUP_COLOR, MUTED_PLANT],
    opacity: ["case", on, 0.3, 0.12],
    stroke: ["case", on, 0.85, 0.3],
  };
}

// Plants outside the current fuel filter or the selected state drop to flat
// grey footprints, so a selection is always read against the whole fleet.
// `grow` scales every column, for the rise when the plants layer opens.
function plantPaint(activeFuels, zone, grow) {
  const on = selection(activeFuels, zone);
  const h0 = grow >= 1 ? ["get", "h0"] : ["*", grow, ["get", "h0"]];
  if (!on) return { color: GROUP_COLOR, height: heightExpr(h0) };
  return { color: ["case", on, GROUP_COLOR, MUTED_PLANT], height: heightExpr(["case", on, h0, 0]) };
}

function activeFuelsOf(facet) {
  if (!facet) return null;
  if (facet.kind === "fuel") return [facet.key];
  return Object.keys(FUEL_GROUP).filter((f) => FUEL_GROUP[f] === facet.key);
}

// One label point per state. Labelling the polygons directly puts a name on
// every island and enclave (Andaman & Nicobar three times over), so instead
// take each state's largest piece and find its visual centre: the interior
// point farthest from any edge, by a coarse-to-fine grid search. A plain
// centroid falls outside concave states like West Bengal.
function visualCenter(ring) {
  const k = Math.cos((ring[0][1] * Math.PI) / 180); // make a degree of lon ≈ a degree of lat
  const pts = ring.map(([x, y]) => [x * k, y]);
  const inside = (x, y) => {
    let c = false;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [xi, yi] = pts[i], [xj, yj] = pts[j];
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
    }
    return c;
  };
  const edgeDist = (x, y) => {
    let best = Infinity;
    for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
      const [ax, ay] = pts[j], [bx, by] = pts[i];
      const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy || 1e-12;
      const t = Math.max(0, Math.min(1, ((x - ax) * dx + (y - ay) * dy) / len2));
      best = Math.min(best, Math.hypot(x - (ax + t * dx), y - (ay + t * dy)));
    }
    return best;
  };
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const [x, y] of pts) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
  let best = [(x0 + x1) / 2, (y0 + y1) / 2], bestD = -1;
  for (let pass = 0; pass < 3; pass++) {
    const n = 14;
    const sx = (x1 - x0) / n, sy = (y1 - y0) / n;
    for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) {
      const x = x0 + i * sx, y = y0 + j * sy;
      if (!inside(x, y)) continue;
      const d = edgeDist(x, y);
      if (d > bestD) { bestD = d; best = [x, y]; }
    }
    // zoom the search window in around the best point so far
    const w = (x1 - x0) / 4, h = (y1 - y0) / 4;
    [x0, x1, y0, y1] = [best[0] - w, best[0] + w, best[1] - h, best[1] + h];
  }
  return [best[0] / k, best[1]];
}

function labelPoints(geo) {
  const ringArea = (r) => {
    let a = 0;
    for (let i = 0, j = r.length - 1; i < r.length; j = i++) a += (r[j][0] - r[i][0]) * (r[j][1] + r[i][1]);
    return Math.abs(a / 2);
  };
  return {
    type: "FeatureCollection",
    features: geo.features.map((f) => {
      const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
      const outer = polys.map((p) => p[0]).sort((a, b) => ringArea(b) - ringArea(a))[0];
      return {
        type: "Feature",
        properties: { name: f.properties.ST_NM, zone: f.properties.zone },
        geometry: { type: "Point", coordinates: visualCenter(outer) },
      };
    }),
  };
}

const fmtGW = (mw) => (mw < 1000 ? `${Math.round(mw)} MW` : `${(mw / 1000).toFixed(mw < 10000 ? 1 : 0)} GW`);
const fmtCap = (mw) => `${Math.round(mw).toLocaleString("en-IN")} MW`;
const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) || n % 10 > 3 ? 0 : n % 10]}`;
const zoneName = (zone) => (zone === "IN" ? "All India" : ZONE_TO_NAME[zone] || zone);

// plants.json: every operational plant and total, from NITI Aayog's ICED
// (web/public, built by `python -m gridscrapers.iced export`)
function usePlants() {
  const [doc, setDoc] = useState(null);
  useEffect(() => {
    let dead = false;
    fetch("/plants.json")
      .then((r) => r.json())
      .then((d) => {
        if (dead) return;
        const rows = d.plants.map((row) => Object.fromEntries(d.fields.map((f, j) => [f, row[j]])));
        setDoc({ records: rows.filter((p) => p.capacity_mw > 0), retrieved: d.retrieved });
      })
      .catch(() => !dead && setDoc({ records: [], retrieved: null }));
    return () => { dead = true; };
  }, []);
  return doc;
}

function plantStats(plants) {
  if (!plants?.length) return null;
  const byGroup = {};
  for (const g of PLANT_GROUPS) byGroup[g] = { mw: 0, fuels: {} };
  let total = 0, tallest = null, count = 0;
  for (const p of plants) {
    const g = byGroup[fuelGroup(p.fuel)];
    if (!g) continue;
    g.mw += p.capacity_mw;
    g.fuels[p.fuel] = (g.fuels[p.fuel] || 0) + p.capacity_mw;
    total += p.capacity_mw;
    if (p.kind === "plant") {
      count += 1;
      if (!tallest || p.capacity_mw > tallest.capacity_mw) tallest = p;
    }
  }
  for (const g of PLANT_GROUPS) {
    byGroup[g].fuels = Object.entries(byGroup[g].fuels)
      .map(([fuel, mw]) => ({ fuel, mw }))
      .sort((a, b) => b.mw - a.mw);
  }
  return { byGroup, total, count, tallest };
}

export default function GridMap({ zonesData, onSelect, selectedZone, colorMode }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const featureIdsRef = useRef({}); // zone -> feature id
  const plantsRef = useRef([]);
  const modeRef = useRef(colorMode);
  const paintRef = useRef({ activeFuels: null, zone: "IN", grow: 1 });
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState(null);
  const [facet, setFacet] = useState(null); // {kind: "group"|"fuel", key}
  const [gridLines, setGridLines] = useState(0); // EHV lines drawn, for the key
  const plantDoc = usePlants();
  const records = plantDoc?.records;
  const plants = useMemo(() => records?.filter((r) => r.kind === "plant"), [records]);
  const totals = useMemo(() => records?.filter((r) => r.kind !== "plant"), [records]);
  const totalsRef = useRef([]);
  modeRef.current = colorMode;
  paintRef.current.activeFuels = activeFuelsOf(facet);
  paintRef.current.zone = selectedZone;

  const applyPlantPaint = () => {
    const map = mapRef.current;
    if (!map?.getLayer("plants")) return;
    const { activeFuels, zone, grow } = paintRef.current;
    const { color, height } = plantPaint(activeFuels, zone, grow);
    map.setPaintProperty("plants", "fill-extrusion-color", color);
    map.setPaintProperty("plants", "fill-extrusion-height", height);
    const disc = discPaint(activeFuels, zone);
    map.setPaintProperty("plant-totals", "circle-color", disc.color);
    map.setPaintProperty("plant-totals", "circle-stroke-color", disc.color);
    map.setPaintProperty("plant-totals", "circle-opacity", disc.opacity);
    map.setPaintProperty("plant-totals", "circle-stroke-opacity", disc.stroke);
  };

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: baseStyle(),
      center: [80.5, 22.5],
      zoom: 3.6,
      minZoom: 2.5,
      maxZoom: 9,
      maxPitch: 70,
      attributionControl: false,
      preserveDrawingBuffer: true, // so headless screenshots capture the WebGL canvas
    });
    map.addControl(new maplibregl.AttributionControl({
      customAttribution:
        "Boundaries: datameet (CC BY 2.5 IN) · Plants: WRI Global Power Plant Database (CC BY 4.0) · " +
        "Live: Vidyut Pravah, MERIT, state load despatch centres · Transmission: OpenStreetMap (ODbL) · " +
        ATTRIBUTION,
      compact: true,
    }), "bottom-right");
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 90, unit: "metric" }), "bottom-right");
    mapRef.current = map;

    // The map lives in a flex child that often has no measured size at init,
    // so maplibre falls back to 400×300 and renders blank. Observe the
    // container and resize once it has real dimensions.
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);

    map.on("load", async () => {
      map.resize();
      // compact attribution opens expanded and only folds on the first drag;
      // start it folded so it never runs underneath the key (the ⓘ opens it)
      containerRef.current
        ?.querySelector(".maplibregl-ctrl-attrib")
        ?.classList.remove("maplibregl-compact-show");
      map.setLight({ anchor: "viewport", color: "#ffffff", intensity: 0.28, position: [1.3, 205, 35] });
      map.addImage("hatch", hatchImage());

      // Generalised boundaries (web/scripts/simplify-states.mjs): 0.7 MB
      // instead of the 15.7 MB source, borders still shared exactly.
      const geo = await (await fetch("/india_states.min.geojson")).json();
      geo.features.forEach((f, i) => {
        f.id = i;
        const zone = NAME_TO_ZONE[f.properties.ST_NM] || null;
        f.properties.zone = zone;
        if (zone) featureIdsRef.current[zone] = i;
      });
      map.addSource("states", { type: "geojson", data: geo });
      // everything of ours goes under the city labels, so names stay legible
      const add = (layer) => map.addLayer(layer, BEFORE_LABELS);
      add({
        id: "states-fill", type: "fill", source: "states",
        paint: { "fill-color": fillColorExpr(modeRef.current), "fill-opacity": 0.86 },
      });
      add({
        id: "states-nodata", type: "fill", source: "states",
        paint: { "fill-pattern": "hatch", "fill-opacity": 0 },
      });
      // the terrain again, faintly, over the colour: the choropleth reads as
      // painted onto the landscape rather than pasted over it
      add({
        id: "relief-over", type: "hillshade", source: "dem",
        paint: {
          "hillshade-exaggeration": 0.55,
          "hillshade-shadow-color": "rgba(52, 60, 82, 0.42)",
          "hillshade-highlight-color": "rgba(255, 250, 240, 0.32)",
          "hillshade-accent-color": "rgba(52, 60, 82, 0.12)",
          "hillshade-illumination-direction": 315,
        },
      });
      add({
        id: "states-line", type: "line", source: "states",
        paint: { "line-color": BORDER, "line-width": ["interpolate", ["linear"], ["zoom"], 3, 0.5, 7, 1.1] },
      });
      add({
        id: "states-selected", type: "line", source: "states",
        paint: { "line-color": SELECTED, "line-width": 2.2 },
        filter: ["==", ["get", "zone"], "___none___"],
      });
      map.addSource("state-labels", { type: "geojson", data: labelPoints(geo) });
      add({
        id: "states-label", type: "symbol", source: "state-labels",
        minzoom: 3.6,
        layout: {
          "text-field": ["upcase", ["get", "name"]],
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 3.8, 8.5, 7, 12],
          "text-letter-spacing": 0.12,
          "text-max-width": 8,
          "text-padding": 4,
        },
        paint: {
          "text-color": "rgba(52, 44, 34, 0.66)",
          "text-halo-color": "rgba(249, 245, 236, 0.6)",
          "text-halo-width": 1,
        },
      });
      // The EHV transmission backbone (400 kV and up, from OpenStreetMap):
      // what the plants feed. Drawn in ink rather than colour — it's context,
      // and colour on this map means fuel or a reading. Mapped geometry only;
      // OSM records where lines run, not what they carry.
      fetch("/gridlines.json")
        .then((r) => (r.ok ? r.json() : null))
        .then((lines) => {
          if (!lines || !map.getStyle()) return;
          map.addSource("gridlines", { type: "geojson", data: lines });
          map.addLayer({
            id: "gridlines", type: "line", source: "gridlines",
            layout: { "line-cap": "round", "line-join": "round" },
            paint: {
              "line-color": "#2a2620",
              "line-opacity": ["case", [">=", ["get", "kv"], 700], 0.5, 0.3],
              "line-width": ["interpolate", ["linear"], ["zoom"],
                3, ["case", [">=", ["get", "kv"], 700], 0.9, 0.45],
                8, ["case", [">=", ["get", "kv"], 700], 2.2, 1.2]],
            },
          }, "states-label");
          setGridLines(lines.features.length);
        })
        .catch(() => {});
      map.addSource("plant-totals", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "plant-totals",
        type: "circle",
        source: "plant-totals",
        layout: { visibility: "none", "circle-sort-key": ["-", 0, ["get", "capacity_mw"]] },
        paint: {
          "circle-radius": DISC_RADIUS,
          "circle-color": GROUP_COLOR,
          "circle-opacity": 0.3,
          "circle-stroke-color": GROUP_COLOR,
          "circle-stroke-width": 1,
          "circle-stroke-opacity": 0.85,
          "circle-pitch-alignment": "map",
          "circle-pitch-scale": "map",
        },
      });
      map.addSource("plants", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "plants",
        type: "fill-extrusion",
        source: "plants",
        layout: { visibility: "none" },
        paint: {
          "fill-extrusion-color": GROUP_COLOR,
          "fill-extrusion-height": heightExpr(["get", "h0"]),
          "fill-extrusion-opacity": 0.95,
          "fill-extrusion-vertical-gradient": true,
        },
      });

      // Frame India, then tilt it. Overlays sit over the left and top of the
      // map on wide screens, so leave room for them there.
      const wide = containerRef.current.clientWidth > 860;
      const cam = map.cameraForBounds(INDIA, {
        padding: wide ? { top: 90, bottom: 30, left: 330, right: 410 } : 12,
      });
      // Tilting pushes the north away and shrinks it, so frame a touch closer;
      // on a tall phone screen it also leaves India sitting low under empty
      // map, so aim the camera south to lift the country up the screen.
      map.jumpTo({
        center: [cam.center.lng, cam.center.lat - (wide ? 0 : 2.6)],
        zoom: cam.zoom + (wide ? 0.25 : 0.05),
        pitch: wide ? 48 : 42,
        bearing: -9,
      });

      // a column under the cursor wins; otherwise the smallest disc, which is
      // the most specific total there (they nest: district discs inside a state's)
      const pickPlant = (point) => {
        if (modeRef.current !== "plants") return null;
        const { x, y } = point;
        const hits = map.queryRenderedFeatures([[x - 4, y - 4], [x + 4, y + 4]], { layers: ["plants"] });
        let best = null;
        for (const h of hits) {
          const p = plantsRef.current[h.properties.i];
          if (p && (!best || p.capacity_mw > best.capacity_mw)) best = p;
        }
        if (best) return best;
        for (const h of map.queryRenderedFeatures(point, { layers: ["plant-totals"] })) {
          const t = totalsRef.current[h.properties.i];
          if (t && (!best || t.capacity_mw < best.capacity_mw)) best = t;
        }
        return best;
      };
      const pickState = (point) =>
        map.queryRenderedFeatures(point, { layers: ["states-fill"] })[0] || null;

      map.on("mousemove", (e) => {
        const plant = pickPlant(e.point);
        const state = plant ? null : pickState(e.point);
        map.getCanvas().style.cursor = plant || state?.properties.zone ? "pointer" : "";
        const { x, y } = e.point;
        const w = containerRef.current.clientWidth;
        if (plant) setTooltip({ kind: "plant", x, y, w, plant });
        else if (state && modeRef.current !== "plants") {
          setTooltip({ kind: "state", x, y, w, name: state.properties.ST_NM, zone: state.properties.zone });
        } else setTooltip(null);
      });
      map.on("mouseout", () => setTooltip(null));
      // a plant selects its state; a state selects itself; open sea goes back
      // to All India
      map.on("click", (e) => {
        const plant = pickPlant(e.point);
        const state = plant ? null : pickState(e.point);
        if (plant?.zone) onSelect(plant.zone);
        else if (state?.properties.zone) onSelect(state.properties.zone);
        else if (!state) onSelect("IN");
      });
      setReady(true);
    });

    return () => {
      ro.disconnect();
      map.remove();
    };
  }, [onSelect]);

  // Column heights: the tallest plant gets ~30% of the map's height, and every
  // other column is linear in installed capacity — a 25 MW solar farm really
  // is that small next to a 4,760 MW coal station.
  useEffect(() => {
    if (!ready || !plants?.length) return;
    const map = mapRef.current;
    const maxCap = Math.max(...plants.map((p) => p.capacity_mw));
    const setHeights = () => {
      const h = containerRef.current?.clientHeight || 600;
      const pxPerMW = Math.min(260, Math.max(110, h * 0.3)) / maxCap;
      for (const p of plants) {
        const px = Math.max(p.capacity_mw * pxPerMW, 1.2);
        p.h0 = px * M_PER_PX_Z0 * Math.cos((p.lat * Math.PI) / 180);
      }
      plantsRef.current = plants;
      map.getSource("plants").setData(columns(plants, map.getZoom()));
    };
    setHeights();
    totalsRef.current = totals || [];
    map.getSource("plant-totals").setData({
      type: "FeatureCollection",
      features: (totals || []).map((t, i) => ({
        type: "Feature",
        properties: { i, fuel: t.fuel, zone: t.zone || "", capacity_mw: t.capacity_mw },
        geometry: { type: "Point", coordinates: [t.lon, t.lat] },
      })),
    });
    const onZoomEnd = () => map.getSource("plants").setData(columns(plantsRef.current, map.getZoom()));
    let lastH = containerRef.current.clientHeight;
    const ro = new ResizeObserver(() => {
      const h = containerRef.current?.clientHeight;
      if (h && Math.abs(h - lastH) > 40) { lastH = h; setHeights(); }
    });
    ro.observe(containerRef.current);
    map.on("zoomend", onZoomEnd);
    return () => { map.off("zoomend", onZoomEnd); ro.disconnect(); };
  }, [ready, plants, totals]);

  // paint demand + carbon intensity + staleness as feature-state on refresh
  useEffect(() => {
    if (!ready || !zonesData) return;
    const map = mapRef.current;
    const byZone = Object.fromEntries(zonesData.zones.map((z) => [z.zone, z]));
    for (const [zone, fid] of Object.entries(featureIdsRef.current)) {
      const z = byZone[zone];
      const ci = ciOf(z);
      map.setFeatureState(
        { source: "states", id: fid },
        {
          demand: z ? z.demand_met_mw : -1,
          demandMissing: !z || !fresh(z.ts),
          carbon: ci ? ci.value : -1,
          carbonMissing: !ci,
        },
      );
    }
  }, [ready, zonesData]);

  // Demand and Carbon are choropleths; Plants draws the fleet on plain land,
  // and the columns rise out of the ground when it opens.
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    const plantsMode = colorMode === "plants";
    map.setLayoutProperty("plants", "visibility", plantsMode ? "visible" : "none");
    map.setLayoutProperty("plant-totals", "visibility", plantsMode ? "visible" : "none");
    map.setLayoutProperty("states-label", "visibility", plantsMode ? "none" : "visible");
    // plants: India brightened against its neighbours, so the fleet stands on it
    map.setPaintProperty("states-fill", "fill-color", plantsMode ? SHEET : fillColorExpr(colorMode));
    map.setPaintProperty("states-fill", "fill-opacity", plantsMode ? 0.62 : 0.86);
    map.setPaintProperty("states-nodata", "fill-opacity", plantsMode ? 0 : missingExpr(colorMode));
    setTooltip(null);
    if (!plantsMode) return;
    let frame;
    const t0 = performance.now();
    const step = (now) => {
      const t = Math.min(1, (now - t0) / GROW_MS);
      paintRef.current.grow = 1 - (1 - t) ** 3; // ease-out
      applyPlantPaint();
      if (t < 1) frame = requestAnimationFrame(step);
    };
    frame = requestAnimationFrame(step);
    return () => { cancelAnimationFrame(frame); paintRef.current.grow = 1; };
  }, [ready, colorMode]);

  useEffect(() => {
    if (ready) applyPlantPaint();
  }, [ready, facet, selectedZone]);

  useEffect(() => {
    if (!ready) return;
    mapRef.current.setFilter("states-selected", ["==", ["get", "zone"], selectedZone || "___none___"]);
  }, [ready, selectedZone]);

  const keyProps = { zonesData, selectedZone, onSelect, gridLines };
  return (
    <>
      <div className="map-wrap" ref={containerRef}>
        {tooltip && <Tooltip tip={tooltip} zonesData={zonesData} />}
      </div>
      {colorMode === "plants" && (
        <PlantKey {...keyProps} plants={records} retrieved={plantDoc?.retrieved} facet={facet} setFacet={setFacet} />
      )}
      {colorMode === "demand" && <DemandKey {...keyProps} />}
      {colorMode === "carbon" && <CarbonKey {...keyProps} />}
    </>
  );
}

function Tooltip({ tip, zonesData }) {
  // flip to the cursor's left near the right edge so it never clips
  const style = {
    left: tip.x,
    top: tip.y,
    transform: tip.x > tip.w - 280 ? "translate(calc(-100% - 14px), -50%)" : "translate(14px, -50%)",
  };
  if (tip.kind === "plant") {
    const p = tip.plant;
    return (
      <div className="tooltip" style={style}>
        <div className="t-name">{p.name}</div>
        <div className="t-line">
          <i className="swatch" style={{ background: GROUPS[fuelGroup(p.fuel)].color }} />
          <span className="t-fuel">{fuelLabel(p.fuel)}</span>
          <span className="num">{fmtCap(p.capacity_mw)}</span>
        </div>
        {p.kind === "plant" ? (
          <>
            <div className="t-sub">
              {[p.district, ZONE_TO_NAME[p.zone]].filter(Boolean).join(", ")}
              {p.since ? ` · since ${p.since}` : ""}
              {p.units > 1 ? ` · ${p.units} units` : ""}
            </div>
            {p.owner && <div className="t-sub">{p.owner}</div>}
            {p.located !== "plant" && (
              <div className="t-sub t-approx">Location approximate: centre of its {p.located}</div>
            )}
          </>
        ) : (
          <div className="t-sub">
            {p.kind === "district"
              ? `District total${p.units > 1 ? ` of ${p.units} entries` : ""}, ${ZONE_TO_NAME[p.zone] || ""}`
              : "State total: ICED doesn't publish districts for this capacity"}
          </div>
        )}
      </div>
    );
  }
  const z = tip.zone ? zonesData?.zones.find((d) => d.zone === tip.zone) : null;
  const ci = ciOf(z);
  return (
    <div className="tooltip" style={style}>
      <div className="t-name">{tip.name}</div>
      {z ? (
        <>
          <div className="t-line"><span className="num">{fmtMW(z.demand_met_mw)}</span> demand met</div>
          {ci && (
            <div className="t-line">
              <span className="num">{Math.round(ci.value)}</span> gCO₂/kWh
              {ci.estimated ? <span className="t-sub"> · estimated</span> : ""}
            </div>
          )}
          <div className={`t-sub ${fresh(z.ts) ? "" : "stale"}`}>updated {ageLabel(z.ts)}</div>
        </>
      ) : (
        <div className="t-sub">no live data</div>
      )}
    </div>
  );
}

// ---------- the key, bottom left: All India until a state is picked ----------

function KeyHead({ title, selectedZone, onSelect }) {
  return (
    <>
      {selectedZone !== "IN" && (
        <button className="lg-back" onClick={() => onSelect("IN")}>← All India</button>
      )}
      <h2 className="lg-title">{title}</h2>
    </>
  );
}

function Ramp({ stops, ends, mid, arms }) {
  const max = stops[stops.length - 1][0];
  const gradient = stops.map(([v, c]) => `${c} ${(v / max) * 100}%`).join(", ");
  return (
    <div className="lg-rampwrap">
      <div className="lg-ramp" style={{ background: `linear-gradient(to right, ${gradient})` }} />
      <div className="lg-ends num">
        <span>{ends[0]}</span>
        {mid && <span>{mid}</span>}
        <span>{ends[1]}</span>
      </div>
      {arms && <div className="lg-ends lg-arms"><span>{arms[0]}</span><span>{arms[1]}</span></div>}
    </div>
  );
}

function NoData() {
  return (
    <div className="lg-nodata">
      <i className="lg-swatch hatch" /> no data, or older than {STALE_AFTER_MIN} min
    </div>
  );
}

function GridLineKey({ n }) {
  if (!n) return null;
  return (
    <div className="lg-nodata">
      <i className="lg-swatch line" /> transmission, 400 kV and up (OpenStreetMap)
    </div>
  );
}

function RankList({ label, rows, value, onSelect }) {
  if (!rows.length) return null;
  return (
    <>
      <div className="lg-sub">{label}</div>
      <ol className="lg-rank">
        {rows.map((z) => (
          <li key={z.zone}>
            <button onClick={() => onSelect(z.zone)}>{zoneName(z.zone)}</button>
            <span className="num">{value(z)}</span>
          </li>
        ))}
      </ol>
    </>
  );
}

function DemandKey({ zonesData, selectedZone, onSelect, gridLines }) {
  const zones = zonesData?.zones || [];
  const india = zones.find((z) => z.zone === "IN");
  const states = zones
    .filter((z) => z.zone !== "IN" && fresh(z.ts))
    .sort((a, b) => b.demand_met_mw - a.demand_met_mw);
  const ramp = <Ramp stops={DEMAND_STOPS} ends={["0", "30+ GW"]} />;

  if (selectedZone === "IN") {
    return (
      <aside className="legend">
        <KeyHead title="Demand met, right now" selectedZone="IN" onSelect={onSelect} />
        {ramp}
        <RankList label="Largest right now" rows={states.slice(0, 5)}
                  value={(z) => fmtMW(z.demand_met_mw)} onSelect={onSelect} />
        <NoData />
        <GridLineKey n={gridLines} />
      </aside>
    );
  }
  const z = zones.find((d) => d.zone === selectedZone);
  const rank = states.findIndex((d) => d.zone === selectedZone) + 1;
  return (
    <aside className="legend">
      <KeyHead title={zoneName(selectedZone)} selectedZone={selectedZone} onSelect={onSelect} />
      {z ? (
        <>
          <div className="lg-fig">{fmtMW(z.demand_met_mw)}</div>
          <p className="lg-line">
            demand met
            {india ? ` · ${((z.demand_met_mw / india.demand_met_mw) * 100).toFixed(1)}% of India` : ""}
            {rank ? ` · ${ordinal(rank)} largest of ${states.length}` : ""}
          </p>
          <p className={`lg-note${fresh(z.ts) ? "" : " stale"}`}>updated {ageLabel(z.ts)}</p>
        </>
      ) : (
        <p className="lg-note">No live demand for this state.</p>
      )}
      {ramp}
      <NoData />
      <GridLineKey n={gridLines} />
    </aside>
  );
}

function CarbonKey({ zonesData, selectedZone, onSelect, gridLines }) {
  const zones = zonesData?.zones || [];
  const india = ciOf(zones.find((z) => z.zone === "IN"));
  const states = zones
    .filter((z) => z.zone !== "IN" && ciOf(z))
    .sort((a, b) => ciOf(a).value - ciOf(b).value);
  const ramp = (
    <Ramp stops={CARBON_STOPS} ends={["0", "1,000+ g"]} mid="500" arms={["low-carbon", "coal-heavy"]} />
  );
  const g = (z) => `${Math.round(ciOf(z).value)} g`;

  if (!states.length) {
    return (
      <aside className="legend">
        <KeyHead title={selectedZone === "IN" ? "Carbon intensity of generation" : zoneName(selectedZone)}
                 selectedZone={selectedZone} onSelect={onSelect} />
        <p className="lg-line">
          Carbon intensity isn&rsquo;t available right now. <a href="/status">Data quality</a>
        </p>
        {ramp}
        <NoData />
        <GridLineKey n={gridLines} />
      </aside>
    );
  }
  if (selectedZone === "IN") {
    return (
      <aside className="legend">
        <KeyHead title="Carbon intensity of generation" selectedZone="IN" onSelect={onSelect} />
        {india && (
          <>
            <div className="lg-fig">{Math.round(india.value)}<span className="lg-unit"> gCO₂/kWh</span></div>
            <p className="lg-line">India&rsquo;s grid, right now</p>
          </>
        )}
        {ramp}
        <RankList label="Lowest right now" rows={states.slice(0, 3)} value={g} onSelect={onSelect} />
        <RankList label="Highest right now" rows={states.slice(-3).reverse()} value={g} onSelect={onSelect} />
        <p className="lg-note">
          Mostly estimated: only a few states publish live generation by fuel.{" "}
          <a href="/methodology">How it&rsquo;s calculated</a>
        </p>
      </aside>
    );
  }
  const ci = ciOf(zones.find((d) => d.zone === selectedZone));
  const vs = ci && india ? ((ci.value - india.value) / india.value) * 100 : null;
  return (
    <aside className="legend">
      <KeyHead title={zoneName(selectedZone)} selectedZone={selectedZone} onSelect={onSelect} />
      {ci ? (
        <>
          <div className="lg-fig">{Math.round(ci.value)}<span className="lg-unit"> gCO₂/kWh</span></div>
          <p className="lg-line">
            {vs == null ? "carbon intensity of generation"
              : `${Math.abs(vs).toFixed(0)}% ${vs < 0 ? "below" : "above"} India's grid`}
          </p>
          <p className="lg-note">
            {ci.estimated ? BASIS_LABELS[ci.estimation_basis] || "estimated" : BASIS_LABELS.measured}
          </p>
        </>
      ) : (
        <p className="lg-note">No carbon intensity for this state right now.</p>
      )}
      {ramp}
      <NoData />
      <GridLineKey n={gridLines} />
    </aside>
  );
}

function PlantKey({ plants, retrieved, selectedZone, onSelect, facet, setFacet, gridLines }) {
  const scoped = useMemo(
    () => (selectedZone === "IN" ? plants : plants?.filter((p) => p.zone === selectedZone)),
    [plants, selectedZone],
  );
  const stats = useMemo(() => plantStats(scoped), [scoped]);
  const national = useMemo(() => plantStats(plants), [plants]);
  const isState = selectedZone !== "IN";
  const title = isState ? zoneName(selectedZone) : "Installed capacity, by fuel";

  if (!plants) return <aside className="legend"><p className="lg-note">Loading plants…</p></aside>;
  if (!stats) {
    return (
      <aside className="legend">
        <KeyHead title={title} selectedZone={selectedZone} onSelect={onSelect} />
        <p className="lg-note">No operational plants listed for this state.</p>
      </aside>
    );
  }
  const active = activeFuelsOf(facet);
  const toggle = (next) =>
    setFacet(facet && facet.kind === next.kind && facet.key === next.key ? null : next);
  return (
    <aside className="legend">
      <KeyHead title={title} selectedZone={selectedZone} onSelect={onSelect} />
      {isState && (
        <p className="lg-line">
          {fmtGW(stats.total)} operational · {stats.count.toLocaleString("en-IN")} plants plus district totals
        </p>
      )}
      {PLANT_GROUPS.filter((g) => stats.byGroup[g].mw > 0).map((g) => {
        const grp = stats.byGroup[g];
        const groupOn = !active || grp.fuels.some((f) => active.includes(f.fuel));
        const on = facet?.kind === "group" && facet.key === g;
        return (
          <div className={`lg-group${groupOn ? "" : " off"}`} key={g}>
            <button className={`lg-row${on ? " on" : ""}`} aria-pressed={on}
                    onClick={() => toggle({ kind: "group", key: g })}>
              <i className="lg-swatch" style={{ background: GROUPS[g].color }} />
              <span className="lg-label">{GROUPS[g].label}</span>
              <span className="num">{fmtGW(grp.mw)}</span>
            </button>
            <div className="lg-fuels">
              {grp.fuels.map((f) => {
                const fon = facet?.kind === "fuel" && facet.key === f.fuel;
                return (
                  <button key={f.fuel} aria-pressed={fon}
                          className={`lg-fuel${fon ? " on" : ""}${active && !active.includes(f.fuel) ? " off" : ""}`}
                          onClick={() => toggle({ kind: "fuel", key: f.fuel })}>
                    {fuelLabel(f.fuel)} <span className="num">{fmtGW(f.mw)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {facet && <button className="lg-reset" onClick={() => setFacet(null)}>Show every fuel</button>}
      <GridLineKey n={gridLines} />
      <div className="lg-marks">
        <span><i className="mark-col" />plant, height is capacity</span>
        <span><i className="mark-disc" />district or state total</span>
      </div>
      {stats.tallest && (
        <p className="lg-note">
          The largest{isState ? " here" : `, in ${zoneName(stats.tallest.zone)},`} is{" "}
          {stats.tallest.name.split("/")[0].trim()}, {fmtCap(stats.tallest.capacity_mw)}
          {stats.tallest.owner ? `, run by ${stats.tallest.owner.replace(/\.$/, "")}` : ""}.
        </p>
      )}
      <p className="lg-note">
        {isState ? "" : `${fmtGW(national.total)} of operational capacity, against CEA's ${fmtGW(INSTALLED.mw)}. `}
        Coal, gas, nuclear and large hydro are drawn plant by plant. Solar, wind, biomass and small
        hydro are only published as totals for a district, and most solar only for a whole state.
        Source: NITI Aayog ICED{retrieved ? `, ${retrieved}` : ""}; locations from the WRI registry
        and OpenStreetMap. <a href="/data-gaps">What&rsquo;s missing</a>
      </p>
    </aside>
  );
}
