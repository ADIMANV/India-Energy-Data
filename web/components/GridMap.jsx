"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { NAME_TO_ZONE, ZONE_TO_NAME, ageMinutes, ageLabel, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { BASIS_LABELS, FUEL_GROUP, GROUPS, INSTALLED, fuelGroup, fuelLabel } from "../lib/fuels";

const INK = "#0e0d0b";
const LAND = "#1b1a17";
const BORDER = "rgba(236, 230, 218, 0.2)";
const SELECTED = "#ece6da";
const MUTED_PLANT = "#4a463f";

// Demand: one green-teal hue, dark = small, light = large — the original
// palette. Its shade is size, not greenness; greenness is the carbon map.
const DEMAND_STOPS = [[0, "#2a3431"], [2000, "#33514a"], [8000, "#437468"], [18000, "#69b394"], [30000, "#c4e6d2"]];
// Carbon: green ↔ rust around 500 g/kWh. Equal OKLCH lightness steps out from
// a dark neutral midpoint, so low-carbon and coal-heavy states both stand out
// and states near the middle recede.
const CARBON_STOPS = [
  [0, "#57bc80"], [125, "#489a68"], [250, "#3c7753"], [375, "#34533e"], [500, "#29302b"],
  [625, "#614232"], [750, "#91593c"], [875, "#be6f45"], [1000, "#e68a58"],
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
    LAND, // the hatch layer on top marks it as missing
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
  g.strokeStyle = "rgba(236, 230, 218, 0.22)";
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
const GROUP_COLOR = [
  "match", ["get", "fuel"],
  ["coal", "gas", "oil"], GROUPS.fossil.color,
  ["hydro", "nuclear"], GROUPS.firm.color,
  ["solar", "wind", "biomass", "res_nonsolar"], GROUPS.renewable.color,
  GROUPS.unattributed.color,
];

// Plants outside the current fuel filter or the selected state drop to flat
// grey footprints, so a selection is always read against the whole fleet.
// `grow` scales every column, for the rise when the plants layer opens.
function plantPaint(activeFuels, zone, grow) {
  const conds = [];
  if (activeFuels) conds.push(["in", ["get", "fuel"], ["literal", activeFuels]]);
  if (zone && zone !== "IN") conds.push(["==", ["get", "zone"], zone]);
  const h0 = grow >= 1 ? ["get", "h0"] : ["*", grow, ["get", "h0"]];
  if (!conds.length) return { color: GROUP_COLOR, height: heightExpr(h0) };
  const on = conds.length === 1 ? conds[0] : ["all", ...conds];
  return { color: ["case", on, GROUP_COLOR, MUTED_PLANT], height: heightExpr(["case", on, h0, 0]) };
}

function activeFuelsOf(facet) {
  if (!facet) return null;
  if (facet.kind === "fuel") return [facet.key];
  return Object.keys(FUEL_GROUP).filter((f) => FUEL_GROUP[f] === facet.key);
}

function graticule() {
  const line = (coordinates) => ({ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates } });
  const features = [];
  for (let lon = 65; lon <= 100; lon += 5) features.push(line([[lon, 0], [lon, 40]]));
  for (let lat = 5; lat <= 35; lat += 5) features.push(line([[58, lat], [106, lat]]));
  return { type: "FeatureCollection", features };
}

const fmtGW = (mw) => `${(mw / 1000).toFixed(mw < 10000 ? 1 : 0)} GW`;
const fmtCap = (mw) => `${Math.round(mw).toLocaleString("en-IN")} MW`;
const ordinal = (n) => `${n}${["th", "st", "nd", "rd"][(n % 100 > 10 && n % 100 < 14) || n % 10 > 3 ? 0 : n % 10]}`;
const zoneName = (zone) => (zone === "IN" ? "All India" : ZONE_TO_NAME[zone] || zone);

function usePlants() {
  const [plants, setPlants] = useState(null);
  useEffect(() => {
    let dead = false;
    fetch("/plants.json")
      .then((r) => r.json())
      .then((doc) => {
        if (dead) return;
        const rows = doc.plants.map((row) => Object.fromEntries(doc.fields.map((f, j) => [f, row[j]])));
        setPlants(rows.filter((p) => p.capacity_mw > 0));
      })
      .catch(() => !dead && setPlants([]));
    return () => { dead = true; };
  }, []);
  return plants;
}

function plantStats(plants) {
  if (!plants?.length) return null;
  const byGroup = {};
  for (const g of PLANT_GROUPS) byGroup[g] = { mw: 0, fuels: {} };
  let total = 0, tallest = plants[0];
  for (const p of plants) {
    const g = byGroup[fuelGroup(p.fuel)];
    if (!g) continue;
    g.mw += p.capacity_mw;
    g.fuels[p.fuel] = (g.fuels[p.fuel] || 0) + p.capacity_mw;
    total += p.capacity_mw;
    if (p.capacity_mw > tallest.capacity_mw) tallest = p;
  }
  for (const g of PLANT_GROUPS) {
    byGroup[g].fuels = Object.entries(byGroup[g].fuels)
      .map(([fuel, mw]) => ({ fuel, mw }))
      .sort((a, b) => b.mw - a.mw);
  }
  return { byGroup, total, count: plants.length, tallest };
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
  const plants = usePlants();
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
  };

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {},
        layers: [{ id: "bg", type: "background", paint: { "background-color": INK } }],
      },
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
        "Live: Vidyut Pravah, MERIT, state load despatch centres",
      compact: true,
    }), "bottom-right");
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "bottom-right");
    mapRef.current = map;

    // The map lives in a flex child that often has no measured size at init,
    // so maplibre falls back to 400×300 and renders blank. Observe the
    // container and resize once it has real dimensions.
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);

    const markers = [];
    map.on("load", async () => {
      map.resize();
      // compact attribution opens expanded and only folds on the first drag;
      // start it folded so it never runs underneath the key (the ⓘ opens it)
      containerRef.current
        ?.querySelector(".maplibregl-ctrl-attrib")
        ?.classList.remove("maplibregl-compact-show");
      map.setLight({ anchor: "viewport", color: "#ffffff", intensity: 0.32, position: [1.3, 205, 35] });
      map.addImage("hatch", hatchImage());

      map.addSource("graticule", { type: "geojson", data: graticule() });
      map.addLayer({
        id: "graticule",
        type: "line",
        source: "graticule",
        paint: { "line-color": "rgba(236, 230, 218, 0.07)", "line-width": 1, "line-dasharray": [1, 3] },
      });
      const label = (text, lngLat) => {
        const el = document.createElement("span");
        el.className = "grat-label";
        el.textContent = text;
        markers.push(new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(map));
      };
      for (let lat = 10; lat <= 35; lat += 5) label(`${lat}°N`, [62.5, lat]);
      for (let lon = 70; lon <= 95; lon += 5) label(`${lon}°E`, [lon, 7.2]);

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
      map.addLayer({
        id: "states-fill", type: "fill", source: "states",
        paint: { "fill-color": fillColorExpr(modeRef.current) },
      });
      map.addLayer({
        id: "states-nodata", type: "fill", source: "states",
        paint: { "fill-pattern": "hatch", "fill-opacity": 0 },
      });
      map.addLayer({
        id: "states-line", type: "line", source: "states",
        paint: { "line-color": BORDER, "line-width": 0.6 },
      });
      map.addLayer({
        id: "states-selected", type: "line", source: "states",
        paint: { "line-color": SELECTED, "line-width": 1.6 },
        filter: ["==", ["get", "zone"], "___none___"],
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
      const wide = containerRef.current.clientWidth > 760;
      const cam = map.cameraForBounds(INDIA, {
        padding: wide ? { top: 120, bottom: 40, left: 350, right: 40 } : 12,
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

      const pickPlant = (point) => {
        if (modeRef.current !== "plants") return null;
        const { x, y } = point;
        const hits = map.queryRenderedFeatures([[x - 4, y - 4], [x + 4, y + 4]], { layers: ["plants"] });
        let best = null;
        for (const h of hits) {
          const p = plantsRef.current[h.properties.i];
          if (p && (!best || p.capacity_mw > best.capacity_mw)) best = p;
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
      markers.forEach((m) => m.remove());
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
    const onZoomEnd = () => map.getSource("plants").setData(columns(plantsRef.current, map.getZoom()));
    let lastH = containerRef.current.clientHeight;
    const ro = new ResizeObserver(() => {
      const h = containerRef.current?.clientHeight;
      if (h && Math.abs(h - lastH) > 40) { lastH = h; setHeights(); }
    });
    ro.observe(containerRef.current);
    map.on("zoomend", onZoomEnd);
    return () => { map.off("zoomend", onZoomEnd); ro.disconnect(); };
  }, [ready, plants]);

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
    map.setPaintProperty("states-fill", "fill-color", plantsMode ? LAND : fillColorExpr(colorMode));
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

  const keyProps = { zonesData, selectedZone, onSelect };
  return (
    <>
      <div className="map-wrap" ref={containerRef}>
        {tooltip && <Tooltip tip={tooltip} zonesData={zonesData} />}
      </div>
      {colorMode === "plants" && <PlantKey {...keyProps} plants={plants} facet={facet} setFacet={setFacet} />}
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
        <div className="t-sub">
          {ZONE_TO_NAME[p.zone] || "outside state boundaries"}
          {p.commissioning_year ? ` · commissioned c. ${p.commissioning_year}` : ""}
        </div>
        {p.owner && <div className="t-sub">{p.owner}</div>}
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

function DemandKey({ zonesData, selectedZone, onSelect }) {
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
    </aside>
  );
}

function CarbonKey({ zonesData, selectedZone, onSelect }) {
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
    </aside>
  );
}

function PlantKey({ plants, selectedZone, onSelect, facet, setFacet }) {
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
        <p className="lg-note">No plants for this state in the open registry.</p>
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
          {stats.count.toLocaleString("en-IN")} plants · {fmtGW(stats.total)} in the registry
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
      <p className="lg-note">
        Column height is installed capacity. The largest{isState ? " here" : ""}
        {isState ? "" : `, in ${zoneName(stats.tallest.zone)},`} is {stats.tallest.name},{" "}
        {fmtCap(stats.tallest.capacity_mw)}.
      </p>
      {isState ? (
        <p className="lg-note">
          From the last open plant registry (WRI, 2021): plants built since are missing, most of
          them solar and wind. <a href="/data-gaps">Why</a>
        </p>
      ) : (
        <p className="lg-note">
          These {national.count.toLocaleString("en-IN")} plants, {fmtGW(national.total)}, are the
          last open plant registry (WRI, 2021). India has {fmtGW(INSTALLED.mw)} installed
          ({INSTALLED.source}, {INSTALLED.asOf}). Almost all of the difference is renewables: the
          registry has {fmtGW(national.byGroup.renewable.mw)} of solar, wind and biomass; India
          has {fmtGW(INSTALLED.renewablesMw)}. <a href="/data-gaps">Why</a>
        </p>
      )}
    </aside>
  );
}
