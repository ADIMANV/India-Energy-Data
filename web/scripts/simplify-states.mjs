// Builds public/india_states.min.geojson from the full-resolution datameet
// boundaries. The original is 15.7 MB — every visitor downloaded it to draw a
// country-scale map whose borders are a pixel wide.
//
//   node web/scripts/simplify-states.mjs
//
// Neighbouring states share their border vertices exactly, so simplifying each
// ring on its own would bend the two sides of a shared border differently and
// open slivers between states. Instead each ring is cut into arcs wherever the
// set of states touching it changes, each arc is simplified once
// (Douglas–Peucker), and both neighbours reuse the same result. No dependencies:
// the full-resolution file stays where it is, because the plant loader uses it
// for point-in-state lookups.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const pub = join(dirname(dirname(fileURLToPath(import.meta.url))), "public");
const SRC = join(pub, "india_states.geojson");
const DST = join(pub, "india_states.min.geojson");

const TOLERANCE = 0.003;   // degrees, ~330 m: under a pixel below zoom 7
const MIN_ISLAND = 2e-5;   // deg² (~0.25 km²); smaller islands vanish at country scale
const PRECISION = 1e4;     // 4 decimals, ~11 m

const key = ([x, y]) => `${x.toFixed(6)},${y.toFixed(6)}`;

function polygons(geom) {
  return geom.type === "MultiPolygon" ? geom.coordinates : [geom.coordinates];
}

function ringArea(ring) {
  let a = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    a += (ring[j][0] - ring[i][0]) * (ring[j][1] + ring[i][1]);
  }
  return Math.abs(a / 2);
}

function perpDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  if (!len2) return Math.hypot(p[0] - a[0], p[1] - a[1]);
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

// iterative Douglas–Peucker: arcs run to tens of thousands of points
function simplifyArc(pts) {
  if (pts.length <= 2) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [i, j] = stack.pop();
    let best = -1, bestD = TOLERANCE;
    for (let k = i + 1; k < j; k++) {
      const d = perpDist(pts[k], pts[i], pts[j]);
      if (d > bestD) { bestD = d; best = k; }
    }
    if (best >= 0) { keep[best] = 1; stack.push([i, best], [best, j]); }
  }
  return pts.filter((_, k) => keep[k]);
}

const geo = JSON.parse(readFileSync(SRC, "utf8"));

// which states touch each vertex
const owners = new Map();
geo.features.forEach((f, fi) => {
  for (const poly of polygons(f.geometry)) for (const ring of poly) for (const p of ring) {
    const k = key(p);
    if (!owners.has(k)) owners.set(k, new Set());
    owners.get(k).add(fi);
  }
});
const sig = (p) => [...owners.get(key(p))].sort((a, b) => a - b).join("|");

const arcCache = new Map(); // canonical arc -> simplified points, in canonical direction

function simplifyShared(arc) {
  const fwd = arc.map(key).join(";");
  const rev = arc.map(key).reverse().join(";");
  const canonical = fwd <= rev;
  const id = canonical ? fwd : rev;
  if (!arcCache.has(id)) {
    arcCache.set(id, simplifyArc(canonical ? arc : [...arc].reverse()));
  }
  const out = arcCache.get(id);
  return canonical ? out : [...out].reverse();
}

function simplifyRing(ring) {
  const pts = ring.slice(0, -1); // drop the closing duplicate
  const n = pts.length;
  const sigs = pts.map(sig);
  // a vertex is fixed where the set of states sharing the border changes
  let fixed = [];
  for (let i = 0; i < n; i++) {
    const prev = sigs[(i - 1 + n) % n], next = sigs[(i + 1) % n];
    if (sigs[i] !== prev || sigs[i] !== next || sigs[i].split("|").length > 2) fixed.push(i);
  }
  if (fixed.length < 2) {
    // a ring with one uniform border (an island, or wholly enclosed): anchor it
    // at its first vertex and the one farthest away, so it still has two arcs
    let far = 0, farD = -1;
    for (let i = 1; i < n; i++) {
      const d = Math.hypot(pts[i][0] - pts[0][0], pts[i][1] - pts[0][1]);
      if (d > farD) { farD = d; far = i; }
    }
    fixed = [0, far];
  }
  const out = [];
  for (let a = 0; a < fixed.length; a++) {
    const s = fixed[a], e = fixed[(a + 1) % fixed.length];
    const arc = [];
    for (let i = s; ; i = (i + 1) % n) { arc.push(pts[i]); if (i === e) break; }
    const simple = simplifyShared(arc);
    out.push(...simple.slice(0, -1)); // the next arc starts with this one's end
  }
  out.push(out[0]);
  return out.map(([x, y]) => [Math.round(x * PRECISION) / PRECISION, Math.round(y * PRECISION) / PRECISION]);
}

let before = 0, after = 0, droppedIslands = 0;
for (const f of geo.features) {
  const polys = polygons(f.geometry);
  const largest = Math.max(...polys.map((p) => ringArea(p[0])));
  const kept = [];
  for (const poly of polys) {
    before += poly.reduce((s, r) => s + r.length, 0);
    const outer = ringArea(poly[0]);
    if (outer < MIN_ISLAND && outer < largest) { droppedIslands++; continue; } // never a state's main body
    const rings = poly
      .filter((r, ri) => ri === 0 || ringArea(r) >= MIN_ISLAND)
      .map(simplifyRing)
      .filter((r, ri) => ri === 0 || r.length >= 4);
    if (rings[0].length < 4) continue;
    after += rings.reduce((s, r) => s + r.length, 0);
    kept.push(rings);
  }
  f.properties = { ST_NM: f.properties.ST_NM };
  f.geometry = kept.length === 1
    ? { type: "Polygon", coordinates: kept[0] }
    : { type: "MultiPolygon", coordinates: kept };
}

const text = JSON.stringify(geo);
writeFileSync(DST, text);
console.log(
  `${geo.features.length} states: ${before.toLocaleString()} → ${after.toLocaleString()} vertices, ` +
  `${droppedIslands} sub-pixel islands dropped, ${(text.length / 1e6).toFixed(2)} MB → ${DST}`,
);
