from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from typing import Any

from app.cities import city_name as lookup_city
from app.models import FlightOffer

logger = logging.getLogger("gofly.providers")


class BaseProvider(ABC):
    name: str = "base"

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger(f"gofly.providers.{self.name}")

    def city_name(self, code: str) -> str:
        return lookup_city(code)

    def sleep(self) -> None:
        lo = float(self.config.get("delay_min", 2))
        hi = float(self.config.get("delay_max", 5))
        time.sleep(random.uniform(lo, hi))

    @abstractmethod
    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        raise NotImplementedError

    def safe_search(
        self, origin: str, destination: str, depart_date: str
    ) -> tuple[list[FlightOffer], str | None]:
        try:
            offers = self.search(origin.upper(), destination.upper(), depart_date) or []
            offers = [o for o in offers if o.price and 50 <= o.price <= 50000]
            offers.sort(key=lambda o: o.price)
            return offers, None
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("[%s] search failed: %s", self.name, exc)
            return [], str(exc)
