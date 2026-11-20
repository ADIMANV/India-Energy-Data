import json

from gridscrapers import plants

HEADER = ("country,country_long,name,gppd_idnr,capacity_mw,latitude,longitude,"
          "primary_fuel,other_fuel1,other_fuel2,other_fuel3,commissioning_year,owner")
CSV = "\n".join([
    HEADER,
    "IND,India,BIG COAL TPS,IND0000001,4760.0,24.1,82.6,Coal,,,,1987.0,NTPC",
    "IND,India,Small Solar,IND0000002,5.0,26.9,70.9,Solar,,,,,",
    "IND,India,No Coords Hydro,IND0000003,100.0,,,Hydro,,,,,",
    "IND,India,Odd Fuel,IND0000004,10.0,24.2,82.7,Wave and Tidal,,,,,  ",
    "PAK,Pakistan,Not India,PAK0000001,1000.0,25.0,68.0,Gas,,,,,",
])
# one square "state" covering the coal plant only
GEOMS = [("IN-MP", {"type": "Polygon",
                    "coordinates": [[[80, 22], [85, 22], [85, 26], [80, 26], [80, 22]]]})]


def test_india_plants_filters_maps_and_attributes():
    rows = plants.india_plants(CSV, GEOMS)
    assert [r["source_id"] for r in rows] == [
        "IND0000001", "IND0000002", "IND0000003", "IND0000004"]
    coal, solar, hydro, odd = rows
    assert (coal["fuel"], coal["zone"], coal["owner"], coal["commissioning_year"]) == (
        "coal", "IN-MP", "NTPC", 1987)
    assert solar["zone"] is None          # outside every polygon
    assert solar["owner"] is None         # blank owner is None, not ""
    assert hydro["lat"] is None and hydro["zone"] is None
    assert odd["fuel"] == "other" and odd["owner"] is None   # whitespace-only owner


def test_export_is_compact_drops_uncoordinated_and_sorts_by_capacity(tmp_path, monkeypatch):
    monkeypatch.setattr(plants, "load_state_geoms", lambda: GEOMS)
    src = tmp_path / "gppd.csv"
    src.write_text(CSV, encoding="utf-8")
    out = tmp_path / "plants.json"

    n = plants.export(str(src), str(out))

    doc = json.loads(out.read_text())
    assert n == 3                                   # the coordinate-less hydro is dropped
    assert doc["fields"] == plants.EXPORT_FIELDS
    assert [r[0] for r in doc["plants"]] == ["IND0000001", "IND0000004", "IND0000002"]
    big = dict(zip(doc["fields"], doc["plants"][0]))
    assert big == {"id": "IND0000001", "name": "BIG COAL TPS", "fuel": "coal",
                   "capacity_mw": 4760.0, "lon": 82.6, "lat": 24.1, "zone": "IN-MP",
                   "owner": "NTPC", "commissioning_year": 1987}
