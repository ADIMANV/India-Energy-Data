"""Maharashtra SLDC (mahasldc.in) — live generation by fuel via vision parsing.

The MSETCL SCADA dashboard is published only as a JPEG
(/assets/public/scada/mvrreport3.jpg) with no machine-readable feed. This
plugin archives the image bytes (raw-first, like every source) and hands them
to the generic `vision` parser with a strict schema + bounds. Reconciliation:
the four fuel totals must sum to the reported demand within 10%, else the
report is quarantined and nothing is written.

Bump PARSER_VERSION whenever VISION_SPEC's prompt/schema/model changes — it is
pinned to the spec fingerprint so archived images re-parse reproducibly.
"""

from datetime import datetime

from .. import vision
from ..http import IST, make_client, request_raw
from ..schema import Datapoint, Metric, RawResponse, Unit

SOURCE = "maha_vision"
ZONE = "IN-MH"
IMAGE_URL = "https://mahasldc.in/assets/public/scada/mvrreport3.jpg"

VISION_SPEC = vision.VisionSpec(
    name="mahasldc-mvrreport3",
    prompt=(
        "This is the Maharashtra State Load Despatch Centre SCADA dashboard. "
        "Read the aggregate state generation figures, all in MW. Report:\n"
        "- generation_mw: the state totals for THERMAL (coal), HYDRO, GAS, and "
        "SOLAR. Use the section/column totals, not individual station rows.\n"
        "- demand_mw: the Maharashtra demand met / total state demand.\n"
        "- frequency_hz: the grid frequency (around 50).\n"
        "- timestamp: the date and time printed on the dashboard, verbatim.\n"
        "Read digits exactly as shown. If a value is unreadable, use null."
    ),
    schema={
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "generation_mw": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "thermal": {"type": ["number", "null"]},
                    "hydro": {"type": ["number", "null"]},
                    "gas": {"type": ["number", "null"]},
                    "solar": {"type": ["number", "null"]},
                },
                "required": ["thermal", "hydro", "gas", "solar"],
            },
            "demand_mw": {"type": ["number", "null"]},
            "frequency_hz": {"type": ["number", "null"]},
            "timestamp": {"type": ["string", "null"]},
        },
        "required": ["generation_mw", "demand_mw", "frequency_hz", "timestamp"],
    },
    bounds={
        "generation_mw.thermal": (0, 40000),
        "generation_mw.hydro": (0, 20000),
        "generation_mw.gas": (0, 10000),
        "generation_mw.solar": (0, 20000),
        "demand_mw": (5000, 40000),
        "frequency_hz": (48, 52),
    },
    reconcile_parts=(
        "generation_mw.thermal", "generation_mw.hydro",
        "generation_mw.gas", "generation_mw.solar",
    ),
    total_path="demand_mw",
    tolerance=0.10,  # own gen vs demand; MH is broadly self-supplied
)

# pinned to the spec so a prompt/schema/model change forces reproducible re-parse
PARSER_VERSION = int(VISION_SPEC.fingerprint()[:8], 16) % 1000

FUEL_KEYS = {"thermal": "coal", "hydro": "hydro", "gas": "gas", "solar": "solar"}


def fetch() -> list[RawResponse]:
    with make_client(legacy_tls=True) as client:
        return [request_raw(client, SOURCE, "GET", IMAGE_URL,
                            meta={"zone": ZONE, "spec": VISION_SPEC.fingerprint()})]


def _ts(raw_ts: str | None, fetched_at: datetime) -> datetime:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M", "%d.%m.%y %H:%M", "%d.%m.%Y %H:%M"):
        try:
            return datetime.strptime((raw_ts or "").strip(), fmt).replace(tzinfo=IST)
        except (ValueError, AttributeError):
            continue
    return fetched_at.replace(second=0, microsecond=0)


def parse(raw: RawResponse) -> list[Datapoint]:
    if not raw.body or (raw.http_status or 0) != 200 or raw.body[:2] != b"\xff\xd8":
        return []
    data, error = vision.parse_image(bytes(raw.body), "image/jpeg", VISION_SPEC)
    if error:
        # "can't even attempt" (no key / SDK missing) is a soft skip, not a
        # quarantine — the raw image is archived for re-parse once configured.
        # A real model response that fails bounds/reconciliation DOES raise.
        soft = ("no API credentials", "not installed", "Could not resolve authentication")
        if any(s in error for s in soft):
            return []
        raise ValueError(f"vision quarantine: {error}")

    ts = _ts(data.get("timestamp"), raw.fetched_at)
    common = dict(zone=ZONE, ts=ts, source=SOURCE, parser_version=PARSER_VERSION,
                  estimated=False)
    points: list[Datapoint] = []
    for key, fuel in FUEL_KEYS.items():
        mw = data["generation_mw"].get(key)
        if isinstance(mw, (int, float)) and mw > 0:
            points.append(Datapoint(metric=Metric.GENERATION, fuel=fuel,
                                    value=float(mw), unit=Unit.MW, **common))
    if isinstance(data.get("demand_mw"), (int, float)):
        points.append(Datapoint(metric=Metric.DEMAND_MET, value=float(data["demand_mw"]),
                                unit=Unit.MW, **common))
    if isinstance(data.get("frequency_hz"), (int, float)):
        points.append(Datapoint(metric=Metric.FREQUENCY, value=float(data["frequency_hz"]),
                                unit=Unit.HZ, **common))
    return points
