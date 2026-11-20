from gridscrapers import gridlines

OSM = {"elements": [
    {"type": "way", "tags": {"power": "line", "voltage": "400000"},
     "geometry": [{"lon": 77.0, "lat": 28.0}, {"lon": 77.5, "lat": 28.00001}, {"lon": 78.0, "lat": 28.0}]},
    {"type": "way", "tags": {"power": "line", "voltage": "765000;400000"},
     "geometry": [{"lon": 80.0, "lat": 22.0}, {"lon": 81.0, "lat": 23.0}]},
    {"type": "way", "tags": {"power": "line", "voltage": "400000"},
     "geometry": [{"lon": 70.0, "lat": 20.0}, {"lon": 71.0, "lat": 21.0}]},
    {"type": "way", "tags": {"power": "line"}, "geometry": [{"lon": 1, "lat": 1}, {"lon": 2, "lat": 2}]},
    {"type": "way", "tags": {"power": "line", "voltage": "400000"}, "geometry": [{"lon": 1, "lat": 1}]},
]}


def test_merges_ways_by_highest_voltage_class():
    doc = gridlines.to_geojson(OSM)
    by_kv = {f["properties"]["kv"]: f for f in doc["features"]}
    assert set(by_kv) == {400, 765}                       # no-voltage and 1-point ways dropped
    assert by_kv[400]["properties"]["ways"] == 2
    assert by_kv[765]["geometry"]["type"] == "MultiLineString"   # "765000;400000" files under 765


def test_simplify_drops_points_that_dont_change_the_shape():
    line = gridlines.to_geojson(OSM)["features"][0]["geometry"]["coordinates"][0]
    assert line == [[77.0, 28.0], [78.0, 28.0]]          # the 1 m kink is gone
