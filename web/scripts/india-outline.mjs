// Builds public/india_outline.json from public/india_states.min.geojson: the
// country's outline, as rings (coast, land border and islands).
//
//   node web/scripts/india-outline.mjs
//
// The map needs to say where India ends — that's the area you can click, and
// with land drawn on both sides of the border, Ladakh fades into Tibet and the
// north-east into its neighbours. The states file shares border vertices
// exactly (scripts/simplify-states.mjs), so the outline is every edge that
// belongs to exactly one state: an edge two states share is an internal
// border. Those edges are chained back into rings.
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const pub = join(dirname(dirname(fileURLToPath(import.meta.url))), "public");
const geo = JSON.parse(readFileSync(join(pub, "india_states.min.geojson"), "utf8"));

const key = ([x, y]) => `${x},${y}`;
const edgeKey = (a, b) => (key(a) < key(b) ? `${key(a)}|${key(b)}` : `${key(b)}|${key(a)}`);

const edges = new Map(); // edgeKey -> {a, b, n}
for (const f of geo.features) {
  const polys = f.geometry.type === "MultiPolygon" ? f.geometry.coordinates : [f.geometry.coordinates];
  for (const poly of polys) {
    for (const ring of poly) {
      for (let i = 0; i + 1 < ring.length; i++) {
        const k = edgeKey(ring[i], ring[i + 1]);
        const e = edges.get(k);
        if (e) e.n += 1;
        else edges.set(k, { a: ring[i], b: ring[i + 1], n: 1 });
      }
    }
  }
}

const outer = [...edges.values()].filter((e) => e.n === 1);
const at = new Map(); // point -> outline edges touching it
for (const e of outer) {
  for (const p of [e.a, e.b]) {
    const k = key(p);
    if (!at.has(k)) at.set(k, []);
    at.get(k).push(e);
  }
}

const used = new Set();
const rings = [];
for (const start of outer) {
  if (used.has(start)) continue;
  used.add(start);
  const ring = [start.a, start.b];
  let cur = start.b;
  for (;;) {
    const next = (at.get(key(cur)) || []).find((e) => !used.has(e));
    if (!next) break;
    used.add(next);
    cur = key(next.a) === key(cur) ? next.b : next.a;
    ring.push(cur);
    if (key(cur) === key(ring[0])) break;
  }
  if (ring.length >= 4 && key(ring[0]) === key(ring[ring.length - 1])) rings.push(ring);
}

const area = (r) => {
  let s = 0;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) s += (r[j][0] - r[i][0]) * (r[j][1] + r[i][1]);
  return s / 2; // > 0 clockwise in lon/lat
};
const inside = ([x, y], r) => {
  let c = false;
  for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const [xi, yi] = r[i], [xj, yj] = r[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) c = !c;
  }
  return c;
};

// A ring inside another ring is a gap between states, not coast or border.
rings.sort((a, b) => Math.abs(area(b)) - Math.abs(area(a)));
const coast = rings.filter((r, i) => !rings.slice(0, i).some((big) => inside(r[1], big)));

// Just the rings: the map builds its mask (the world with these cut out) from
// them, so the geometry ships once.
const out = { type: "Feature", properties: {}, geometry: { type: "MultiLineString", coordinates: coast } };
writeFileSync(join(pub, "india_outline.json"), JSON.stringify(out));
const pts = coast.reduce((s, r) => s + r.length, 0);
console.log(`${coast.length} rings (${rings.length - coast.length} internal gaps dropped), ${pts} points;`,
  `mainland ${coast[0].length} points`);
