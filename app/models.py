from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional


@dataclass
class FlightOffer:
    platform: str
    origin: str
    destination: str
    depart_date: str
    price: float
    airline: str = ""
    flight_no: str = ""
    depart_time: str = ""
    arrive_time: str = ""
    duration_min: Optional[int] = None
    stops: int = 0
    layover_min: Optional[int] = None
    seats_hint: str = ""
    aircraft: str = ""
    # UI extras: transfer city, icons, cross-day, etc.
    meta: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d
