"""India's power plants from NITI Aayog's India Climate & Energy Dashboard (ICED).

    python -m gridscrapers.iced fetch-osm                 # refresh the OSM lookups
    python -m gridscrapers.iced export data/iced/<file>.xlsx [--gppd-csv …] [--out …]

ICED's Power Plants Database is the current national registry: one row per
generating unit, with source, status (operational / pipeline / retired /
temporarily closed), plant, state, district, commissioning date, capacity and
implementing agency. Its operational total (559 GW in Nov 2026) matches CEA's
installed capacity to within 1%, and the agency — the owner — is filled for
every conventional unit, where the 2021 WRI registry had an owner for ~4% of
capacity. The export is behind a CAPTCHA, so it's downloaded by hand into
data/iced/ (git-ignored) and this turns it into the map's web/public/plants.json.

It has no coordinates, and two kinds of row need different treatment:

* Coal, oil & gas, nuclear and large hydro are real plants. They become map
  columns, placed at the WRI registry's coordinates when the name matches
  within the state, else at an OpenStreetMap power plant's, else at the
  centre of their district — flagged `located: "district"` so the map can say
  the position is approximate.
* Solar and wind are published only as totals per district — and most solar
  (139 of 171 GW in Nov 2026) only per state, "districts not specified".
  Biomass and small hydro are per plant but carry no location finer than the
  district. All four become totals (`kind: "district"` or `"state"`), drawn as
  discs, never as plants.

District centres and OSM plant points come from OpenStreetMap (© OSM
contributors, ODbL), cached in data/osm/ so an export doesn't depend on the
Overpass API being up.
"""

import argparse
import json
import re
import sys
import time
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import httpx

from .plants import NAME_TO_ZONE, _read_gppd, india_plants, load_state_geoms, state_for

ROOT = Path(__file__).parents[2]
OSM_DIR = ROOT / "data/osm"
DEFAULT_OUT = ROOT / "web/public/plants.json"

# ICED source -> (our fuel, how it's drawn)
SOURCES = {
    "Coal": ("coal", "plant"),
    "Oil & Gas": ("gas", "plant"),
    "Nuclear": ("nuclear", "plant"),
    "Hydro": ("hydro", "plant"),
    "Solar": ("solar", "total"),
    "Wind": ("wind", "total"),
    "Bio Power": ("biomass", "total"),
    "Small-Hydro": ("small_hydro", "total"),
}
# fuels on the WRI registry / OSM side that a plant of each source may match
FAMILY = {"coal": {"coal"}, "gas": {"gas", "oil"}, "nuclear": {"nuclear"}, "hydro": {"hydro"}}
OSM_SOURCE = {"coal": "coal", "gas": "gas", "oil": "gas", "nuclear": "nuclear", "hydro": "hydro"}

# ICED state labels that aren't datameet's. Shared plants ("Rajasthan and
# Gujarat") take their first state; UTs without a zone of their own are kept
# out of zone-level totals but still drawn.
STATE_ALIASES = {
    "Jammu and Kashmir": "IN-JK", "Ladakh": "IN-JK", "Delhi": "IN-DL",
    "Arunachal Pradesh": "IN-AR",             # datameet spells it "Arunanchal"
    "Dadra and Nagar Haveli and Daman and Diu": "IN-GJ",
    "Andaman and Nicobar Islands": None, "Lakshadweep": None, "Others": None,
}

# ICED district spellings -> OpenStreetMap's (renamed or split districts take
# the current name the bulk of the capacity sits in)
DISTRICT_ALIASES = {
    "kachchh": "kutch", "kanpur": "kanpurnagar", "narsimhapur": "narsinghpur",
    "bardhaman": "purbabardhaman", "warangalrural": "hanumakonda",
    "northsikkim": "mangan", "eastsikkim": "gangtok", "westsikkim": "gyalshing",
    "southsikkim": "namchi", "ysrkadapa": "kadapa", "ananthapuramu": "anantapur",
}

PLANT_STOPWORDS = re.compile(
    r"\b(tps|stps|sstps|tpp|ttps|stpp|ccpp|ccgt|thermal|power|station|project|plant|hep|"
    r"hydro ?electric|hydel|electric|hps|hpp|hep|gps|ps|ltd|limited|pvt|private|company|co|corporation|ext|"
    r"extension|stage|phase|unit|super|gas|based|combined|cycle|gt|nuclear|atomic|aps|npp|"
    r"of|the|and|i|ii|iii|iv|v)\b")


def zone_of(state: str | None) -> str | None:
    if not state:
        return None
    state = state.split(" and ")[0].split(",")[0].strip() if state not in STATE_ALIASES else state
    if state in STATE_ALIASES:
        return STATE_ALIASES[state]
    return NAME_TO_ZONE.get(state) or NAME_TO_ZONE.get(state.replace(" and ", " & "))


def norm_district(s: str | None) -> str:
    key = re.sub(r"[^a-z]", "", (s or "").lower().replace("district", ""))
    return DISTRICT_ALIASES.get(key, key)


def norm_plant(s: str | None) -> str:
    s = re.sub(r"[^a-z ]", " ", (s or "").lower())
    return " ".join(PLANT_STOPWORDS.sub(" ", s).split())


def _similar(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if (a in b or b in a) and min(len(a), len(b)) >= 4:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


# ---------------------------------------------------------------- OSM lookups

OVERPASS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
            "https://overpass.private.coffee/api/interpreter"]
AREA = 'area["ISO3166-1"="IN"][admin_level=2]->.in;'


def _overpass(query: str) -> dict:
    last = None
    for i in range(12):
        url = OVERPASS[i % len(OVERPASS)]
        try:
            r = httpx.post(url, data={"data": query}, timeout=300,
                           headers={"User-Agent": "india-electricity-data (https://github.com/ADIMANV/India-Energy-Data)"})
            if r.status_code == 200:
                return r.json()
            last = f"HTTP {r.status_code}"
        except httpx.HTTPError as e:
            last = str(e)
        print(f"[iced] overpass {url}: {last}; retrying", file=sys.stderr)
        time.sleep(30)
    raise RuntimeError(f"Overpass unavailable ({last})")


def fetch_osm() -> None:
    """Cache India's district centres and power-plant points from OpenStreetMap."""
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    geoms = load_state_geoms()
    names = ("name", "name:en", "alt_name", "old_name", "official_name")
    districts = []
    for e in _overpass(f'[out:json][timeout:240];{AREA}'
                       'rel["boundary"="administrative"]["admin_level"="5"](area.in);out center tags;')["elements"]:
        c, t = e.get("center"), e.get("tags", {})
        if c:
            districts.append({"names": sorted({t[k] for k in names if t.get(k)}),
                              "lon": round(c["lon"], 4), "lat": round(c["lat"], 4),
                              "zone": state_for(c["lon"], c["lat"], geoms)})
    plants = []
    for e in _overpass(f'[out:json][timeout:240];{AREA}nwr["power"="plant"](area.in);out center tags;')["elements"]:
        c = e.get("center") or ({"lon": e["lon"], "lat": e["lat"]} if "lon" in e else None)
        t = e.get("tags", {})
        if c and (t.get("name") or t.get("name:en")):
            plants.append({"name": t.get("name:en") or t.get("name"), "source": t.get("plant:source", ""),
                           "lon": round(c["lon"], 4), "lat": round(c["lat"], 4),
                           "zone": state_for(c["lon"], c["lat"], geoms)})
    for name, rows in (("districts", districts), ("power_plants", plants)):
        (OSM_DIR / f"{name}.json").write_text(json.dumps(
            {"attribution": "© OpenStreetMap contributors (ODbL)", "rows": rows}, separators=(",", ":")))
        print(f"[iced] cached {len(rows)} OSM {name}", file=sys.stderr)


def load_osm(name: str) -> list[dict]:
    return json.loads((OSM_DIR / f"{name}.json").read_text())["rows"]


# --------------------------------------------------------------- the workbook

def read_units(xlsx: str) -> list[dict]:
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)["PlantInfo"]
    rows = list(ws.iter_rows(values_only=True))
    head = [str(h or "").strip() for h in rows[0]]
    col = {name: head.index(name) for name in head}
    out = []
    for r in rows[1:]:
        if not r or not r[col["Source"]]:
            continue
        date = r[col["Commissioning Date"]]
        out.append({
            "source": r[col["Source"]], "status": str(r[col["Commissioning Group"]] or "").strip().lower(),
            "name": str(r[col["Name of Power Plant"]] or "").strip(), "state": r[col["State"]],
            "district": str(r[col["District"]] or "").strip(),
            "year": date.year if hasattr(date, "year") else None,
            "mw": float(r[col["Capacity (MW)"]] or 0), "agency": (r[col["Implementing Agency"]] or None),
        })
    return out


class Locator:
    def __init__(self, districts, osm_plants, gppd, geoms):
        self.geoms = geoms
        self.districts = defaultdict(list)
        for d in districts:
            self.districts[d["zone"]].append(({norm_district(n) for n in d["names"]}, (d["lon"], d["lat"])))
        self.osm = defaultdict(list)
        for p in osm_plants:
            self.osm[p["zone"]].append((norm_plant(p["name"]), OSM_SOURCE.get(p["source"]), (p["lon"], p["lat"])))
        self.gppd = defaultdict(list)
        for p in gppd:
            if p["lat"] is not None:
                self.gppd[p["zone"]].append((norm_plant(p["name"]), p["fuel"], (p["lon"], p["lat"])))
        self.state_centre = {}

    def district(self, zone, district):
        """Centre of the named district, trying each part of a multi-district label."""
        for part in re.split(r",| and ", district or ""):
            key = norm_district(part)
            if not key or key in ("na", "others"):
                continue
            best, score = None, 0.0
            for names, ll in self.districts.get(zone, []):
                for n in names:
                    s = 1.0 if n == key else SequenceMatcher(None, n, key).ratio()
                    if s > score:
                        best, score = ll, s
            if score >= 0.82:
                return best
        return None

    def plant(self, zone, fuel, name):
        """Coordinates for a named plant: WRI registry first, then OpenStreetMap."""
        key = norm_plant(name.split("/")[0])
        for pool, ok in ((self.gppd, lambda f: f in FAMILY[fuel]), (self.osm, lambda f: f == fuel)):
            best, score = None, 0.0
            for n, f, ll in pool.get(zone, []):
                if ok(f):
                    s = _similar(n, key)
                    if s > score:
                        best, score = ll, s
            if score >= 0.8:
                return best
        return None

    def state(self, zone, label_points):
        return label_points.get(zone)


# CEA's daily report abbreviates what ICED spells out
CEA_WORDS = {"rbph": "river bed", "chph": "canal head", "lb": "left bank", "rb": "right bank",
             "sgr": "sagar", "dph": "dam", "lig": "lignite", "addl": "additional",
             "ramagundem": "ramagundam"}
# Words that name an owner or a vintage, not a plant: matching them is a
# bonus, missing them isn't a miss ("ADANI POWER LIMITED TIRODA" is ICED's
# "Tirora TPS"; "KOTHAGUDEM TPS (NEW)" is part of "Kothagudem TPS").
OPTIONAL_WORDS = {"adani", "jsw", "gmr", "ntpc", "nhpc", "neepco", "sjvn", "nlc", "dvc", "jindal",
                  "lanco", "essar", "reliance", "rattanindia", "cesc", "torrent", "sembcorp", "energy",
                  "shree", "shri", "sri", "new", "old", "exp", "extn", "rep", "cfbc", "lignite", "liq",
                  "pss", "psp", "additional"}
# Plants renamed by an acquisition, where no word survives: CEA station key ->
# a fragment of ICED's name. Checked by hand against owner and capacity.
CEA_ALIASES = {
    "IN-CG|adani power limited raipur tpp": "raikheda",          # ex-GMR Chhattisgarh
    "IN-CG|adani power limited raigarh tpp": "avantha bhandar",  # ex-Korba West Power
    "IN-CG|vedanta ltd chhattisgarh tpp": "singhitarai",         # ex-Athena Chhattisgarh
    "IN-DL|i p ccpp": "i.p. gas turbine",
    "IN-PB|gh tps leh moh": "guru hargobind",                    # at Lehra Mohabbat
    "IN-JH|maithon rb tpp": "maithon tpp",
    "IN-TN|ntpl tuticorin tpp": "tuticorin joint venture",        # NLC–TANGEDCO JV
    "IN-UK|sravanthi ccpp": "kashipur combined cycle",            # Sravanthi's Kashipur, phases I+II
    "IN-ML|myntdu leshka st 1 hps": "myntdu",
}


def _tokens(s: str) -> list[str]:
    s = re.sub(r"\b((?:[A-Za-z]\.){2,})", lambda m: m.group(1).replace(".", "") + " ", s)  # D.P.L. -> DPL
    words = []
    for w in norm_plant(s).split():
        words += CEA_WORDS.get(w, w).split()
    return [w for w in words if len(w) >= 3]


def _aliases(name: str) -> list[str]:
    """ICED often packs several names into one: 'Vijayawada or Dr. Narla Tata
    Rao TPS', 'Akaltara TPS/ JSW Mahanadi Power Company Ltd'."""
    parts = re.split(r"/| or |\(|\)", name)
    return [name] + [x.strip() for x in parts if len(x.strip()) > 2]


def _name_score(station: str, plant_name: str) -> float:
    st = _tokens(station)
    if not st:
        return 0.0
    best = 0.0
    for alias in _aliases(plant_name):
        pt = _tokens(alias)
        initials = "".join(w[0] for w in re.findall(r"[a-z]+", alias.lower()))
        got, need, solid = 0.0, 0, False
        for t in st:
            r = max((SequenceMatcher(None, t, u).ratio() for u in pt), default=0.0)
            if r < 0.8 and len(t) >= 5 and (any(t in u for u in pt) or t in "".join(pt)):
                r = 0.9                                   # NALLUR in PILLAIPERUMALNALLUR; NABINAGAR = NABI NAGAR
            if r < 0.8 and 3 <= len(t) <= 5 and initials.startswith(t):
                r = 1.0                                   # DSPM, SGPL, GREL
            if r >= 0.8:
                got, need = got + r, need + 1
                solid = solid or len(t) >= 4 or r == 1.0  # URI, JOG: short but exact
            elif t not in OPTIONAL_WORDS:
                need += 1
        if need and solid:
            best = max(best, got / need)
    return best


def link_cea_stations(plants: dict, stations: list[dict]) -> dict:
    """Attach CEA daily-report stations to ICED plants: {plant key: [station_key]}.

    CEA's daily report says, per station, how much capacity is down; ICED says
    where and whose the plant is. Names are matched word by word against every
    name ICED gives a plant, and capacity settles near-ties (CEA's 2,600 MW
    "RAMAGUNDEM STPS" is ICED's 2,600 MW Ramagundam STPS, not the 1,600 MW
    "Ramagundam STPP/Telangana Phase I"). A plant takes stations only up to
    its capacity. ICED's phases of one plant are one target, since CEA often
    reports them together; a station can cross a state line only on a near-
    exact name and capacity (Lower Subansiri sits on the Assam border).
    """
    import math

    groups: dict = defaultdict(lambda: {"keys": [], "mw": 0.0})
    for key, p in plants.items():
        base = re.sub(r"\s*[-,(]?\s*\b(phase|stage|unit|ph)\b.*$", "", p["name"].lower()).strip()
        fam = next((f for f, members in FAMILY.items() if p["fuel"] in members), p["fuel"])
        g = groups[(p["zone"], fam, base)]
        g["keys"].append(key)
        g["mw"] += p["mw"]
        g["name"], g["zone"], g["fam"] = p["name"], p["zone"], fam
    pairs = []
    for st in stations:
        mw = st.get("monitored_mw") or 0.0
        alias = CEA_ALIASES.get(st["station_key"])
        for gid, g in groups.items():
            if st["fuel"] not in FAMILY.get(g["fam"], {g["fam"]}):
                continue
            same = g["zone"] == st["zone"]
            if alias:
                score = 1.0 if same and any(alias in plants[k]["name"].lower() for k in g["keys"]) else 0.0
            else:
                score = _name_score(st["station"], g["name"])
            fit = max(0.0, 1 - abs(math.log(mw / g["mw"]))) if mw > 0 and g["mw"] > 0 else 0.0
            if same and score >= 0.8:
                pairs.append((score + 0.2 * fit, st["station_key"], gid, mw))
            elif not same and score >= 0.95 and 0.67 <= (mw / g["mw"] if g["mw"] else 0) <= 1.5:
                pairs.append((score + 0.2 * fit - 0.1, st["station_key"], gid, mw))
    pairs.sort(key=lambda x: -x[0])
    taken, used = set(), defaultdict(float)
    links: dict = defaultdict(list)
    for _, skey, gid, mw in pairs:
        g = groups[gid]
        if skey in taken or used[gid] + mw > 1.25 * g["mw"] + 20:
            continue
        taken.add(skey)
        used[gid] += mw
        for k in g["keys"]:
            links[k].append(skey)
    return links


def build(units, locator, state_points, cea_stations=()) -> tuple[list[list], dict]:
    """-> (rows for plants.json, stats). Operational capacity only."""
    stats = Counter()
    plants: dict[tuple, dict] = {}
    totals: dict[tuple, dict] = {}
    for u in units:
        if u["status"] != "operational" or u["source"] not in SOURCES or u["mw"] <= 0:
            continue
        fuel, how = SOURCES[u["source"]]
        zone = zone_of(u["state"])
        if how == "plant":
            p = plants.setdefault((fuel, u["name"], u["state"]), {
                "fuel": fuel, "name": u["name"], "zone": zone, "district": u["district"],
                "mw": 0.0, "units": 0, "years": [], "agencies": Counter()})
            p["mw"] += u["mw"]
            p["units"] += 1
            if u["year"]:
                p["years"].append(u["year"])
            if u["agency"]:
                p["agencies"][u["agency"]] += u["mw"]
        else:
            district = u["district"] if u["district"] not in ("", "N.A.") else None
            t = totals.setdefault((fuel, zone, district, u["state"]), {"mw": 0.0, "n": 0})
            t["mw"] += u["mw"]
            t["n"] += 1

    links = link_cea_stations(plants, list(cea_stations))
    stats["cea_stations"] = len(cea_stations)
    stats["cea_stations_linked"] = len({s for v in links.values() for s in v})
    rows = []
    for key, p in plants.items():
        ll = locator.plant(p["zone"], p["fuel"], p["name"])
        located = "plant"
        if ll is None:
            ll, located = locator.district(p["zone"], p["district"]), "district"
        if ll is None:
            ll, located = state_points.get(p["zone"]), "state"
        if ll is None:
            stats["unplaced_mw"] += p["mw"]
            continue
        stats[f"plants_{located}"] += 1
        stats[f"plants_{located}_mw"] += p["mw"]
        owner = p["agencies"].most_common(1)[0][0] if p["agencies"] else None
        rows.append([p["name"], p["fuel"], round(p["mw"], 1), ll[0], ll[1], p["zone"], owner,
                     min(p["years"]) if p["years"] else None, p["district"] or None, p["units"],
                     "plant", located, links.get(key) or None])
        if links.get(key):
            stats["plants_with_status_mw"] += p["mw"]

    for (fuel, zone, district, state), t in totals.items():
        ll, kind = (locator.district(zone, district), "district") if district else (None, "state")
        if ll is None:
            ll, kind = state_points.get(zone), "state"
        if ll is None:
            stats["unplaced_mw"] += t["mw"]
            continue
        stats[f"totals_{kind}_mw"] += t["mw"]
        label = f"{district} district" if kind == "district" else f"{state}, districts not published"
        rows.append([label, fuel, round(t["mw"], 1), ll[0], ll[1], zone, None, None,
                     district, t["n"], kind, kind, None])
    rows.sort(key=lambda r: -r[2])
    return rows, dict(stats)


FIELDS = ["name", "fuel", "capacity_mw", "lon", "lat", "zone", "owner", "since",
          "district", "units", "kind", "located", "cea"]


def state_label_points(geoms) -> dict:
    """A point inside each state for state-level totals: its largest ring's centroid,
    pulled to the nearest vertex-average if the centroid falls outside."""
    from .plants import _point_in_geom
    out = {}
    for zone, geom in geoms:
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        ring = max((p[0] for p in polys), key=len)
        cx = sum(x for x, _ in ring) / len(ring)
        cy = sum(y for _, y in ring) / len(ring)
        if not _point_in_geom(cx, cy, geom):
            cx, cy = min(ring, key=lambda pt: (pt[0] - cx) ** 2 + (pt[1] - cy) ** 2)
        out[zone] = (round(cx, 4), round(cy, 4))
    return out


def export(xlsx: str, out: str, gppd_csv: str | None = None, dgr2: str | None = None) -> dict:
    """dgr2: a CEA daily generation report (.xls), to link each plant to the
    stations CEA reports outages for. Station names are stable day to day, so
    any recent report will do; the live status itself comes from the API."""
    from datetime import date

    from .cea import parse_station_status

    geoms = load_state_geoms()
    gppd = india_plants(_read_gppd(gppd_csv), geoms)
    locator = Locator(load_osm("districts"), load_osm("power_plants"), gppd, geoms)
    stations = parse_station_status(Path(dgr2).read_bytes(), date.today()) if dgr2 else []
    rows, stats = build(read_units(xlsx), locator, state_label_points(geoms), stations)
    doc = {
        "source": "NITI Aayog, India Climate & Energy Dashboard — Power Plants Database",
        "source_url": "https://iced.niti.gov.in/energy/electricity/generation/power-plant-details",
        "retrieved": Path(xlsx).stem.split("_")[-1],
        "locations": "WRI Global Power Plant Database (CC BY 4.0); © OpenStreetMap contributors (ODbL)",
        "fields": FIELDS,
        "plants": rows,
    }
    Path(out).write_text(json.dumps(doc, separators=(",", ":"), ensure_ascii=False))
    stats["rows"] = len(rows)
    stats["operational_mw"] = round(sum(r[2] for r in rows))
    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch-osm")
    ex = sub.add_parser("export")
    ex.add_argument("xlsx")
    ex.add_argument("--gppd-csv")
    ex.add_argument("--out", default=str(DEFAULT_OUT))
    ex.add_argument("--dgr2", help="a recent CEA dgr2 .xls, to link plants to CEA's daily outage report")
    args = ap.parse_args()
    if args.command == "fetch-osm":
        fetch_osm()
        return 0
    stats = export(args.xlsx, args.out, args.gppd_csv, args.dgr2)
    print(f"[iced] {json.dumps(stats)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
