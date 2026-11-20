from gridscrapers import iced

GEOMS = []  # Locator only stores this

DISTRICTS = [
    {"names": ["Kutch"], "lon": 69.8, "lat": 23.5, "zone": "IN-GJ"},
    {"names": ["Anantapur", "Anantapuramu"], "lon": 77.6, "lat": 14.7, "zone": "IN-AP"},
    {"names": ["Janjgir-Champa"], "lon": 82.6, "lat": 21.9, "zone": "IN-CG"},
]
OSM_PLANTS = [{"name": "Tamnar Thermal Power Station", "source": "coal", "lon": 83.4, "lat": 22.1, "zone": "IN-CG"}]
GPPD = [{"name": "AKALTARA TPS", "fuel": "coal", "lon": 82.55, "lat": 21.95, "zone": "IN-CG"}]
STATE_POINTS = {"IN-GJ": (71.5, 22.7), "IN-RJ": (74.0, 26.6), "IN-CG": (82.0, 21.3)}


def locator():
    return iced.Locator(DISTRICTS, OSM_PLANTS, GPPD, GEOMS)


def unit(source, name, state, district, mw, status="operational", year=2015, agency=None):
    return {"source": source, "status": status, "name": name, "state": state,
            "district": district, "year": year, "mw": mw, "agency": agency}


def test_state_names_map_to_zones_including_shared_and_renamed():
    assert iced.zone_of("Chhattisgarh") == "IN-CG"
    assert iced.zone_of("Delhi") == "IN-DL"
    assert iced.zone_of("Ladakh") == "IN-JK"
    assert iced.zone_of("Rajasthan and Gujarat") == "IN-RJ"   # shared plants take the first state
    assert iced.zone_of("Others") is None


def test_district_spellings_resolve_through_aliases_and_multi_district_labels():
    loc = locator()
    assert loc.district("IN-GJ", "Kachchh") == (69.8, 23.5)                    # Kachchh → Kutch
    assert loc.district("IN-AP", "YSR Kadapa and Ananthapuramu") == (77.6, 14.7)  # second part matches
    assert loc.district("IN-GJ", "N.A.") is None


def test_plants_take_registry_coordinates_then_osm_then_their_district():
    rows, stats = iced.build([
        unit("Coal", "Akaltara TPS/ JSW Mahanadi Power Company Ltd", "Chhattisgarh", "Janjgir-Champa", 600,
             year=2013, agency="JSW Energy Ltd."),
        unit("Coal", "Akaltara TPS/ JSW Mahanadi Power Company Ltd", "Chhattisgarh", "Janjgir-Champa", 600,
             year=2018, agency="JSW Energy Ltd."),
        unit("Coal", "Tamnar TPP", "Chhattisgarh", "Raigarh", 600),
        unit("Coal", "Brand New TPS", "Chhattisgarh", "Janjgir-Champa", 800),
    ], locator(), STATE_POINTS)
    by = {r[0]: dict(zip(iced.FIELDS, r)) for r in rows}
    akaltara = by["Akaltara TPS/ JSW Mahanadi Power Company Ltd"]
    assert (akaltara["lon"], akaltara["lat"], akaltara["located"]) == (82.55, 21.95, "plant")
    assert (akaltara["capacity_mw"], akaltara["units"], akaltara["since"], akaltara["owner"]) == (
        1200, 2, 2013, "JSW Energy Ltd.")
    assert (by["Tamnar TPP"]["lon"], by["Tamnar TPP"]["located"]) == (83.4, "plant")      # via OSM
    assert (by["Brand New TPS"]["lon"], by["Brand New TPS"]["located"]) == (82.6, "district")
    assert stats["plants_district"] == 1


def test_renewables_become_district_or_state_totals_never_plants():
    rows, _ = iced.build([
        unit("Wind", "Gujarat-Kachchh", "Gujarat", "Kachchh", 3000),
        unit("Solar", "Gujarat N.A. Others (Districts not specified)", "Gujarat", "N.A.", 24000),
        unit("Solar", "Gujarat N.A. Rooftop (Grid Connected)", "Gujarat", "N.A.", 8000),
    ], locator(), STATE_POINTS)
    by = {(r[1], r[10]): dict(zip(iced.FIELDS, r)) for r in rows}
    wind = by[("wind", "district")]
    assert (wind["capacity_mw"], wind["lon"], wind["owner"]) == (3000, 69.8, None)
    solar = by[("solar", "state")]                       # both N.A. rows summed into one state total
    assert (solar["capacity_mw"], (solar["lon"], solar["lat"]), solar["units"]) == (32000, (71.5, 22.7), 2)
    assert not any(r[10] == "plant" for r in rows)


def test_only_operational_units_count():
    rows, _ = iced.build([
        unit("Coal", "Akaltara TPS", "Chhattisgarh", "Janjgir-Champa", 600),
        unit("Coal", "Akaltara TPS", "Chhattisgarh", "Janjgir-Champa", 600, status="pipeline"),
        unit("Coal", "Akaltara TPS", "Chhattisgarh", "Janjgir-Champa", 600, status="retired"),
    ], locator(), STATE_POINTS)
    assert [r[2] for r in rows] == [600]
