// The basemap: a quiet grey relief map, so the data sits in a real landscape
// instead of floating on a void. Vector tiles and fonts from OpenFreeMap
// (OpenMapTiles schema, OSM data) and elevation from the AWS Terrain Tiles
// open dataset — both free and keyless.
//
// No boundary layers, on purpose. OpenStreetMap draws international and
// disputed boundaries "as on the ground", which doesn't match India's official
// map; the only boundaries on this map are the datameet state polygons drawn
// by GridMap on top. Country and state labels are left out for the same reason
// (they'd sit against lines we don't draw); city and river names stay.

export const LAND = "#dfe1de";
export const WATER = "#f3f4f2";
const LABEL = "#4d5658";
const HALO = "rgba(243, 244, 242, 0.85)";

const name = ["coalesce", ["get", "name:en"], ["get", "name_en"], ["get", "name"]];

export function baseStyle() {
  return {
    version: 8,
    glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
    sources: {
      omt: { type: "vector", url: "https://tiles.openfreemap.org/planet" },
      dem: {
        type: "raster-dem",
        tiles: ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
        tileSize: 256,
        encoding: "terrarium",
        maxzoom: 11,
        attribution: "Terrain: AWS Terrain Tiles (Mapzen)",
      },
    },
    layers: [
      { id: "land", type: "background", paint: { "background-color": LAND } },
      {
        id: "relief",
        type: "hillshade",
        source: "dem",
        paint: {
          "hillshade-exaggeration": 0.7,
          "hillshade-shadow-color": "#5b6567",
          "hillshade-highlight-color": "#ffffff",
          "hillshade-accent-color": "#7c8587",
          "hillshade-illumination-direction": 315,
        },
      },
      { id: "water", type: "fill", source: "omt", "source-layer": "water", paint: { "fill-color": WATER } },
      {
        id: "rivers",
        type: "line",
        source: "omt",
        "source-layer": "waterway",
        minzoom: 3.5,
        filter: ["==", ["get", "class"], "river"],
        paint: {
          "line-color": WATER,
          "line-width": ["interpolate", ["linear"], ["zoom"], 3.5, 0.5, 8, 1.6],
        },
      },
      {
        id: "highways",
        type: "line",
        source: "omt",
        "source-layer": "transportation",
        minzoom: 4.5,
        filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk"]]],
        paint: {
          "line-color": "#cdb77c",
          "line-opacity": 0.55,
          "line-width": ["interpolate", ["linear"], ["zoom"], 4.5, 0.3, 9, 1.3],
        },
      },
      // GridMap inserts its own layers here, under the labels (BEFORE_LABELS)
      {
        id: "cities-major",
        type: "symbol",
        source: "omt",
        "source-layer": "place",
        filter: ["all", ["==", ["get", "class"], "city"], ["<=", ["get", "rank"], 2]],
        layout: {
          "text-field": name,
          "text-font": ["Noto Sans Regular"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 3.5, 10, 8, 13],
          "symbol-sort-key": ["get", "rank"],
          "text-padding": 6,
        },
        paint: { "text-color": LABEL, "text-halo-color": HALO, "text-halo-width": 1.3 },
      },
      {
        id: "cities-minor",
        type: "symbol",
        source: "omt",
        "source-layer": "place",
        minzoom: 5.5,
        filter: ["all", ["in", ["get", "class"], ["literal", ["city", "town"]]], [">", ["get", "rank"], 2]],
        layout: {
          "text-field": name,
          "text-font": ["Noto Sans Regular"],
          "text-size": 11,
          "symbol-sort-key": ["get", "rank"],
          "text-padding": 4,
        },
        paint: { "text-color": LABEL, "text-halo-color": HALO, "text-halo-width": 1.2 },
      },
    ],
  };
}

export const BEFORE_LABELS = "cities-major";

export const ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> · ' +
  '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> · ' +
  "Terrain: AWS Terrain Tiles";
