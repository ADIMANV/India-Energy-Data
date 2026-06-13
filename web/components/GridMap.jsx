"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import { NAME_TO_ZONE, ageMinutes, ageLabel, fmtMW, STALE_AFTER_MIN } from "../lib/zones";

// muted monochromatic slate→teal base; states must read on the matte field
const NO_DATA_COLOR = "#262626";
const DEMAND_STOPS = [
  [0, "#2a3431"],
  [2000, "#33514a"],
  [8000, "#437468"],
  [18000, "#69b394"],
  [30000, "#c4e6d2"],
];
// carbon intensity, gCO2/kWh: muted teal (clean) → muted rust (coal)
const CARBON_STOPS = [
  [0, "#1f5c52"],
  [250, "#4f7a4a"],
  [500, "#8a8a3c"],
  [750, "#b07a3a"],
  [1000, "#8a4a2c"],
];

function fillColorExpr(mode) {
  const [stops, key] = mode === "carbon" ? [CARBON_STOPS, "carbon"] : [DEMAND_STOPS, "demand"];
  return [
    "case",
    ["boolean", ["feature-state", `${key}Missing`], true],
    NO_DATA_COLOR,
    ["interpolate", ["linear"], ["to-number", ["feature-state", key], -1],
      ...stops.flat()],
  ];
}

export default function GridMap({ zonesData, onSelect, selectedZone, colorMode }) {
  const containerRef = useRef(null);
  const mapRef = useRef(null);
  const featureIdsRef = useRef({}); // zone -> feature id
  const [ready, setReady] = useState(false);
  const [tooltip, setTooltip] = useState(null);

  useEffect(() => {
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: { version: 8, sources: {}, layers: [
        { id: "bg", type: "background", paint: { "background-color": "#0a0a0a" } },
      ]},
      center: [80.5, 22.5],
      zoom: 3.6,
      attributionControl: false,
      dragRotate: false,
      preserveDrawingBuffer: true,  // so headless screenshots capture the WebGL canvas
    });
    map.addControl(new maplibregl.AttributionControl({
      customAttribution: "Boundaries: datameet/maps (CC-BY 2.5 IN) · Data: Vidyut Pravah, MERIT",
      compact: true,
    }), "bottom-right");
    mapRef.current = map;

    // the map lives in a flex child that often has no measured size at init,
    // so maplibre falls back to 400×300 and renders blank. Observe the
    // container and resize once it has real dimensions.
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(containerRef.current);

    map.on("load", async () => {
      map.resize();
      const geo = await (await fetch("/india_states.geojson")).json();
      geo.features.forEach((f, i) => {
        f.id = i;
        const zone = NAME_TO_ZONE[f.properties.ST_NM] || null;
        f.properties.zone = zone;
        if (zone) featureIdsRef.current[zone] = i;
      });
      map.addSource("states", { type: "geojson", data: geo });
      map.addLayer({
        id: "states-fill",
        type: "fill",
        source: "states",
        paint: { "fill-color": fillColorExpr(), "fill-opacity": 0.9 },
      });
      map.addLayer({
        id: "states-line",
        type: "line",
        source: "states",
        paint: { "line-color": "#0a0a0a", "line-width": 0.5 },
      });
      map.addLayer({
        id: "states-selected",
        type: "line",
        source: "states",
        paint: { "line-color": "#ffd60a", "line-width": 2.5 },
        filter: ["==", ["get", "zone"], "___none___"],
      });
      map.fitBounds([[68, 6.5], [97.5, 36]], { padding: 20 });

      map.on("click", "states-fill", (e) => {
        const zone = e.features[0]?.properties?.zone;
        if (zone) onSelect(zone);
      });
      map.on("mousemove", "states-fill", (e) => {
        const f = e.features[0];
        if (!f) return;
        map.getCanvas().style.cursor = f.properties.zone ? "pointer" : "";
        setTooltip({
          x: e.point.x,
          y: e.point.y,
          name: f.properties.ST_NM,
          zone: f.properties.zone,
        });
      });
      map.on("mouseleave", "states-fill", () => {
        map.getCanvas().style.cursor = "";
        setTooltip(null);
      });
      setReady(true);
    });

    return () => { ro.disconnect(); map.remove(); };
  }, [onSelect]);

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
        }
      );
    }
  }, [ready, zonesData]);

  // swap choropleth scale when the color mode toggles
  useEffect(() => {
    if (!ready) return;
    mapRef.current.setPaintProperty("states-fill", "fill-color", fillColorExpr(colorMode));
  }, [ready, colorMode]);

  useEffect(() => {
    if (!ready) return;
    mapRef.current.setFilter("states-selected", [
      "==", ["get", "zone"], selectedZone || "___none___",
    ]);
  }, [ready, selectedZone]);

  const tipZone = tooltip?.zone
    ? zonesData?.zones.find((z) => z.zone === tooltip.zone)
    : null;

  return (
    <div className="map-wrap" ref={containerRef}>
      {tooltip && (
        <div className="tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
          <div><b>{tooltip.name}</b></div>
          {tipZone ? (
            <>
              <div>{fmtMW(tipZone.demand_met_mw)} demand met</div>
              {tipZone.carbon_intensity && (
                <div>
                  {Math.round(tipZone.carbon_intensity.value)} gCO₂/kWh
                  {tipZone.carbon_intensity.estimated ? " (est.)" : ""}
                </div>
              )}
              <div className={`t-age ${ageMinutes(tipZone.ts) > STALE_AFTER_MIN ? "stale" : ""}`}>
                updated {ageLabel(tipZone.ts)}
              </div>
            </>
          ) : (
            <div className="t-age">no live data</div>
          )}
        </div>
      )}
      <div className="legend">
        {colorMode === "carbon" ? (
          <>
            <div>Carbon intensity (mostly estimated)</div>
            <div className="bar carbon" />
            <div className="ends"><span>0</span><span>1000+ gCO₂/kWh</span></div>
          </>
        ) : (
          <>
            <div>Current demand met</div>
            <div className="bar demand" />
            <div className="ends"><span>0</span><span>30+ GW</span></div>
          </>
        )}
        <div className="ends" style={{ marginTop: 4 }}>
          <span style={{ color: NO_DATA_COLOR }}>■</span>
          <span>no data / stale &gt;{STALE_AFTER_MIN} min</span>
        </div>
      </div>
    </div>
  );
}
