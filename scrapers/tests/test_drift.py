from datetime import datetime, timezone

from gridscrapers.drift import kind_of, structure_hash
from gridscrapers.schema import RawResponse


def _raw(body: bytes, endpoint: str = "https://x.in/api/a", meta: dict | None = None) -> RawResponse:
    return RawResponse(
        source="t", endpoint=endpoint, fetched_at=datetime.now(timezone.utc),
        http_status=200, body=body, meta=meta or {},
    )


def test_json_value_change_same_hash():
    a = structure_hash(_raw(b'[{"Demand":"1,000","ISGS":"2"}]'))
    b = structure_hash(_raw(b'[{"Demand":"9,999","ISGS":null}]'))
    assert a == b


def test_json_key_change_different_hash():
    a = structure_hash(_raw(b'[{"Demand":"1","ISGS":"2"}]'))
    b = structure_hash(_raw(b'[{"DemandMet":"1","ISGS":"2"}]'))
    assert a != b


def test_html_text_change_same_hash_class_change_different():
    a = structure_hash(_raw(b'<span class="value_DemandMET_en">100 MW</span>'))
    b = structure_hash(_raw(b'<span class="value_DemandMET_en">999 MW</span>'))
    c = structure_hash(_raw(b'<span class="val_demand_v2">100 MW</span>'))
    assert a == b and a != c


def test_kind_is_per_endpoint_and_zone():
    a = kind_of(_raw(b"x", "https://vidyutpravah.in/state-data/maharashtra", {"zone": "IN-MH"}))
    b = kind_of(_raw(b"x", "https://vidyutpravah.in/state-data/goa", {"zone": "IN-GA"}))
    assert a != b  # state pages have state-specific markup: separate baselines
    # same POST endpoint, different state code -> separate kinds too
    c = kind_of(_raw(b"x", "https://meritindia.in/StateWiseDetails/BindCurrentStateStatus", {"zone": "IN-MH", "state_code": "MHA"}))
    d = kind_of(_raw(b"x", "https://meritindia.in/StateWiseDetails/BindCurrentStateStatus", {"zone": "IN-GA", "state_code": "GOA"}))
    assert c != d
