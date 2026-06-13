"""Vision validation gate — the safety net that prevents hallucinated numbers."""

from datetime import datetime, timezone

from gridscrapers import vision
from gridscrapers.schema import RawResponse
from gridscrapers.sources import maha_vision
from gridscrapers.sources.maha_vision import VISION_SPEC


def _clean():
    return {"generation_mw": {"thermal": 18000, "hydro": 1500, "gas": 900, "solar": 4000},
            "demand_mw": 25000, "frequency_hz": 49.98, "timestamp": "2026.06.13 08:00:00"}


def test_clean_report_validates():
    assert vision.validate(_clean(), VISION_SPEC) == []


def test_reconciliation_rejects_mismatch():
    d = _clean()
    d["demand_mw"] = 40000  # fuels sum 24400, ~39% under
    errs = vision.validate(d, VISION_SPEC)
    assert any("reconcile" in e for e in errs)


def test_bounds_reject_out_of_range():
    d = _clean()
    d["generation_mw"]["thermal"] = 99999
    errs = vision.validate(d, VISION_SPEC)
    assert any("thermal" in e for e in errs)


def test_missing_field_flagged():
    d = _clean()
    d["frequency_hz"] = None
    errs = vision.validate(d, VISION_SPEC)
    assert any("frequency_hz" in e for e in errs)


def test_fingerprint_pins_parser_version():
    # prompt/schema/model fingerprint is stable; parser_version derives from it
    assert len(VISION_SPEC.fingerprint()) == 16
    assert isinstance(maha_vision.PARSER_VERSION, int)


def test_parse_soft_skips_without_credentials():
    # a real JPEG with no API key configured → [] (soft skip), never a crash
    raw = RawResponse(source="maha_vision", endpoint="x",
                      fetched_at=datetime.now(timezone.utc), http_status=200,
                      body=b"\xff\xd8fakejpegbytes", meta={"zone": "IN-MH"})
    assert maha_vision.parse(raw) == []


def test_timestamp_parsing():
    fetched = datetime(2026, 6, 13, 12, 0, tzinfo=timezone.utc)
    ts = maha_vision._ts("2026.06.13 08:00:00", fetched)
    assert ts.hour == 8 and ts.tzinfo is not None
    # unparseable → falls back to the fetch timestamp (minute-floored)
    assert maha_vision._ts("garbage", fetched) == fetched.replace(second=0, microsecond=0)
