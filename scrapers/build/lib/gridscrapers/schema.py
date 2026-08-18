"""Common datapoint schema shared by all source plugins."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class Metric(StrEnum):
    DEMAND_MET = "demand_met"
    GENERATION = "generation"
    EXCHANGE_PURCHASE = "exchange_purchase"
    EXCHANGE_PRICE = "exchange_price"
    PEAK_SHORTAGE = "peak_shortage"
    ENERGY_SHORTAGE = "energy_shortage"
    FREQUENCY = "frequency"
    NET_IMPORT = "net_import"
    CARBON_INTENSITY = "carbon_intensity"


class Unit(StrEnum):
    MW = "MW"
    MWH = "MWh"
    INR_PER_KWH = "INR/kWh"
    MU = "MU"
    PCT = "pct"
    HZ = "Hz"
    GCO2_PER_KWH = "gCO2/kWh"


class Datapoint(BaseModel):
    zone: str  # ISO 3166-2:IN ('IN-MH') or 'IN' national, 'IN-WR' region
    ts: datetime  # observation time, must be tz-aware
    metric: Metric
    fuel: str = ""  # '' when the metric has no fuel dimension
    value: float
    unit: Unit = Unit.MW
    source: str  # plugin name
    parser_version: int = 1
    estimated: bool = False

    @field_validator("ts")
    @classmethod
    def _tz_aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("ts must be timezone-aware")
        return v.astimezone(timezone.utc)


class RawResponse(BaseModel):
    """A fetched payload, archived verbatim before any parsing."""

    source: str
    endpoint: str
    fetched_at: datetime
    http_status: int | None = None
    content_type: str | None = None
    body: bytes
    meta: dict[str, Any] = Field(default_factory=dict)
