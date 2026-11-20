"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { NAME_TO_ZONE, ZONE_TO_NAME, ageMinutes, ageLabel, fmtMW, STALE_AFTER_MIN } from "../lib/zones";
import { GROUPS, INSTALLED, fuelGroup, fuelLabel } from "../lib/fuels";

const INK = "#0e0d0b";
const LAND = "#1b1a17";
const NO_DATA = "#22201d";
const BORDER = "rgba(236, 230, 218, 0.2)";
const SELECTED = "#ece6da";
const MUTED_PLANT = "#4a463f";

// Single-hue ramps stepped by OKLCH lightness, dark = low. Carbon takes the
// fossil magenta, so on the carbon map more magenta means more fossil.
const DEMAND_STOPS = [[0, "#312d27"], [2000, "#585148"], [8000, "#82796b"], [18000, "#b2a695"], [30000, "#e8dccb"]];
const CARBON_STOPS = [[0, "#42232c"], [250, "#7a354d"], [500, "#b7476f"], [750, "#e46f96"], [1000, "#ffafc7"]];

const INDIA = [[68, 6.5], [97.5, 36]];
const PLANT_GROUPS = ["fossil", "firm", "renewable"];

// MapLibre draws 512-px tiles: at zoom z one pixel spans 360/(512·2^z) degrees
// of longitude, and 40,075 km/(512·2^z)·cos(lat) metres on the ground.
const DEG_PER_PX_Z0 = 360 / 512;
const M_PER_PX_Z0 = 40075016.686 / 512;
const COLUMN_RADIUS_PX = 1.8;

function fillColorExpr(mode) {
  const [stops, key] = mode === "carbon" ? [CARBON_STOPS, "carbon"] : [DEMAND_STOPS, "demand"];
  return [
    "case",
    ["boolean", ["feature-state", `${key}Missing`], true],
    NO_DATA,
    ["interpolate", ["linear"], ["to-number", ["feature-state", key], -1], ...stops.flat()],
  ];
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
        properties: { i, fuel: p.fuel, h0: p.h0 },
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
const HEIGHT = heightExpr(["get", "h0"]);
const GROUP_COLOR = [
  "match", ["get", "fuel"],
  ["coal", "gas", "oil"], GROUPS.fossil.color,
  ["hydro", "nuclear"], GROUPS.firm.color,
  ["solar", "wind", "biomass", "res_nonsolar"], GROUPS.renewable.color,
  GROUPS.unattributed.color,
];

function plantPaint(activeFuels) {
  if (!activeFuels) return { color: GROUP_COLOR, height: HEIGHT };
  const on = ["in", ["get", "fuel"], ["literal", activeFuels]];
  // filtered-out plants stay as flat grey footprints, so the selection is read
  // against the whole fleet rather than an empty country
  return {
    color: ["case", on, GROUP_COLOR, MUTED_PLANT],
    height: heightExpr(["case", on, ["get", "h0"], 0]),
  };
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

function activeFuelsOf(facet, stats) {
  if (!facet || !stats) return null;
  if (facet.kind === "fuel") return [facet.key];
  return stats.byGroup[facet.key].fuels.map((f) => f.fuel);
}

export default function GridMap({ zonesData, onSelect, selectedZone, colorMode }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const featureIdsRef = useRef({}); // zone -> feature id
  const plantsRef = useRef([]);
  const modeRef = useRef(colorMode);
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState(null);
  const [facet, setFacet] = useState(null); // {kind: "group"|"fuel", key}
  const plants = usePlants();
  const stats = useMemo(() => plantStats(plants), [plants]);
  modeRef.current = colorMode;

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
    const attribution = new maplibregl.AttributionControl({
      customAttribution:
        "Boundaries: datameet (CC BY 2.5 IN) · Plants: WRI Global Power Plant Database (CC BY 4.0) · " +
        "Live: Vidyut Pravah, MERIT, state load despatch centres",
      compact: true,
    });
    map.addControl(attribution, "bottom-right");
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
      // start it folded so it never runs underneath the legend (the ⓘ opens it)
      containerRef.current
        ?.querySelector(".maplibregl-ctrl-attrib")
        ?.classList.remove("maplibregl-compact-show");
      map.setLight({ anchor: "viewport", color: "#ffffff", intensity: 0.32, position: [1.3, 205, 35] });

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
      map.addLayer({ id: "states-fill", type: "fill", source: "states", paint: { "fill-color": LAND } });
      map.addLayer({
        id: "states-line",
        type: "line",
        source: "states",
        paint: { "line-color": BORDER, "line-width": 0.6 },
      });
      map.addLayer({
        id: "states-selected",
        type: "line",
        source: "states",
        paint: { "line-color": SELECTED, "line-width": 1.6 },
        filter: ["==", ["get", "zone"], "___none___"],
      });
      map.addSource("plants", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addLayer({
        id: "plants",
        type: "fill-extrusion",
        source: "plants",
        paint: {
          "fill-extrusion-color": GROUP_COLOR,
          "fill-extrusion-height": HEIGHT,
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
      map.on("click", (e) => {
        const zone = pickPlant(e.point)?.zone || pickState(e.point)?.properties.zone;
        if (zone) onSelect(zone);
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
      const demandStale = !z || ageMinutes(z.ts) > STALE_AFTER_MIN;
      const ci = z?.carbon_intensity;
      const ciStale = !ci || ageMinutes(ci.ts) > STALE_AFTER_MIN;
      map.setFeatureState(
        { source: "states", id: fid },
        {
          demand: z ? z.demand_met_mw : -1,
          demandMissing: demandStale,
          carbon: ci ? ci.value : -1,
          carbonMissing: ciStale,
        },
      );
    }
  }, [ready, zonesData]);

  // plants mode draws the fleet on plain land; the other two are choropleths
  useEffect(() => {
    if (!ready) return;
    const map = mapRef.current;
    const plantsMode = colorMode === "plants";
    map.setLayoutProperty("plants", "visibility", plantsMode ? "visible" : "none");
    map.setPaintProperty("states-fill", "fill-color", plantsMode ? LAND : fillColorExpr(colorMode));
    setTooltip(null);
  }, [ready, colorMode]);

  useEffect(() => {
    if (!ready) return;
    const { color, height } = plantPaint(activeFuelsOf(facet, stats));
    mapRef.current.setPaintProperty("plants", "fill-extrusion-color", color);
    mapRef.current.setPaintProperty("plants", "fill-extrusion-height", height);
  }, [ready, facet, stats]);

  useEffect(() => {
    if (!ready) return;
    mapRef.current.setFilter("states-selected", ["==", ["get", "zone"], selectedZone || "___none___"]);
  }, [ready, selectedZone]);

  return (
    <>
      <div className="map-wrap" ref={containerRef}>
        {tooltip && <Tooltip tip={tooltip} zonesData={zonesData} />}
      </div>
      {colorMode === "plants" ? (
        <PlantLegend stats={stats} facet={facet} setFacet={setFacet} />
      ) : (
        <RampLegend mode={colorMode} />
      )}
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
  return (
    <div className="tooltip" style={style}>
      <div className="t-name">{tip.name}</div>
      {z ? (
        <>
          <div className="t-line"><span className="num">{fmtMW(z.demand_met_mw)}</span> demand met</div>
          {z.carbon_intensity && (
            <div className="t-line">
              <span className="num">{Math.round(z.carbon_intensity.value)}</span> gCO₂/kWh
              {z.carbon_intensity.estimated ? <span className="t-sub"> · estimated</span> : ""}
            </div>
          )}
          <div className={`t-sub ${ageMinutes(z.ts) > STALE_AFTER_MIN ? "stale" : ""}`}>
            updated {ageLabel(z.ts)}
          </div>
        </>
      ) : (
        <div className="t-sub">no live data</div>
      )}
    </div>
  );
}

function PlantLegend({ stats, facet, setFacet }) {
  if (!stats) return <aside className="legend"><p className="lg-note">Loading plants…</p></aside>;
  const active = activeFuelsOf(facet, stats);
  const toggle = (next) =>
    setFacet(facet && facet.kind === next.kind && facet.key === next.key ? null : next);
  const tallestState = ZONE_TO_NAME[stats.tallest.zone];
  const registryRenewables = stats.byGroup.renewable.mw;
  return (
    <aside className="legend">
      <h2 className="lg-title">Installed capacity, by fuel</h2>
      {PLANT_GROUPS.map((g) => {
        const grp = stats.byGroup[g];
        const groupOn = !active || grp.fuels.some((f) => active.includes(f.fuel));
        return (
          <div className={`lg-group${groupOn ? "" : " off"}`} key={g}>
            <button
              className={`lg-row${facet?.kind === "group" && facet.key === g ? " on" : ""}`}
              onClick={() => toggle({ kind: "group", key: g })}
              aria-pressed={facet?.kind === "group" && facet.key === g}
            >
              <i className="lg-swatch" style={{ background: GROUPS[g].color }} />
              <span className="lg-label">{GROUPS[g].label}</span>
              <span className="num">{fmtGW(grp.mw)}</span>
            </button>
            <div className="lg-fuels">
              {grp.fuels.map((f) => {
                const on = facet?.kind === "fuel" && facet.key === f.fuel;
                return (
                  <button
                    key={f.fuel}
                    className={`lg-fuel${on ? " on" : ""}${active && !active.includes(f.fuel) ? " off" : ""}`}
                    onClick={() => toggle({ kind: "fuel", key: f.fuel })}
                    aria-pressed={on}
                  >
                    {fuelLabel(f.fuel)} <span className="num">{fmtGW(f.mw)}</span>
                  </button>
                );
              })}
            </div>
          </div>
        );
      })}
      {facet && (
        <button className="lg-reset" onClick={() => setFacet(null)}>Show every plant</button>
      )}
      <p className="lg-note">
        Column height is installed capacity. The tallest, in {tallestState}, is{" "}
        {fmtCap(stats.tallest.capacity_mw)}.
      </p>
      <p className="lg-note">
        These {stats.count.toLocaleString("en-IN")} plants, {fmtGW(stats.total)}, are the last open
        plant registry (WRI, 2021). India has {fmtGW(INSTALLED.mw)} installed ({INSTALLED.source},{" "}
        {INSTALLED.asOf}). Almost all of the difference is renewables: the registry has{" "}
        {fmtGW(registryRenewables)} of solar, wind and biomass; India has {fmtGW(INSTALLED.renewablesMw)}.{" "}
        <a href="/data-gaps">Why</a>
      </p>
    </aside>
  );
}

function RampLegend({ mode }) {
  const carbon = mode === "carbon";
  const stops = carbon ? CARBON_STOPS : DEMAND_STOPS;
  return (
    <aside className="legend">
      <h2 className="lg-title">{carbon ? "Carbon intensity of generation" : "Demand met, right now"}</h2>
      <div className="lg-ramp" style={{ background: `linear-gradient(to right, ${stops.map((s) => s[1]).join(", ")})` }} />
      <div className="lg-ends num">
        <span>0</span>
        <span>{carbon ? "1,000+ gCO₂/kWh" : "30+ GW"}</span>
      </div>
      <div className="lg-nodata">
        <i className="lg-swatch flat" style={{ background: NO_DATA }} /> no data, or older than {STALE_AFTER_MIN} min
      </div>
      {carbon && (
        <p className="lg-note">
          Mostly estimated: only a few states publish live generation by fuel.{" "}
          <a href="/methodology">How it&rsquo;s calculated</a>
        </p>
      )}
    </aside>
  );
}
