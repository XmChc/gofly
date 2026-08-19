from __future__ import annotations

import hashlib
import math
import random
from datetime import datetime
from typing import Any

from app.models import FlightOffer
from app.providers import BaseProvider

AIRLINES = [
    ("CA", "中国国际航空"),
    ("MU", "中国东方航空"),
    ("CZ", "中国南方航空"),
    ("HU", "海南航空"),
    ("3U", "四川航空"),
    ("9C", "春秋航空"),
    ("HO", "吉祥航空"),
]


class MockProvider(BaseProvider):
    """本地演示：多平台差异价 + 可复现的日波动，方便趋势图联调。"""

    name = "mock"

    # 模拟其它平台相对偏移，便于「多平台比价」演示
    PLATFORM_BIAS = {
        "mock": 0,
        "fliggy": -18,
        "ctrip": 12,
        "qunar": -6,
    }

    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        seed = f"{origin}-{destination}-{depart_date}-{datetime.utcnow().strftime('%Y%m%d%H')}"
        rng = random.Random(hashlib.md5(seed.encode()).hexdigest())
        base = 380 + (abs(hash(f"{origin}{destination}")) % 420)
        hour = datetime.utcnow().hour
        wave = 40 * math.sin(hour / 24 * math.pi * 2)
        noise = rng.uniform(-25, 25)
        floor = max(199, base + wave + noise)

        offers: list[FlightOffer] = []
        for i in range(6):
            code, name = AIRLINES[i % len(AIRLINES)]
            stops = 0 if i < 4 else 1
            price = floor + i * rng.uniform(35, 90) + (stops * 40)
            dep_h = 7 + i * 2
            dur = 120 + stops * 90 + rng.randint(0, 40)
            arr_h = dep_h + dur // 60
            offers.append(
                FlightOffer(
                    platform=self.name,
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    price=round(price, 0),
                    airline=name,
                    flight_no=f"{code}{1000 + rng.randint(1, 8999)}",
                    depart_time=f"{dep_h:02d}:{rng.randint(0, 5) * 10:02d}",
                    arrive_time=f"{arr_h % 24:02d}:{rng.randint(0, 5) * 10:02d}",
                    duration_min=dur,
                    stops=stops,
                    layover_min=75 if stops else None,
                    seats_hint=rng.choice(["充足", "紧张", "余票>9", "余票4"]),
                )
            )
        return offers


class BiasedMockProvider(MockProvider):
    """把 mock 拆成带平台名的影子源，用于纯本地多平台演示。"""

    def __init__(self, config: dict[str, Any], platform_name: str):
        super().__init__(config)
        self.name = platform_name

    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        offers = super().search(origin, destination, depart_date)
        bias = self.PLATFORM_BIAS.get(self.name, 0)
        for o in offers:
            o.platform = self.name
            o.price = max(99, round(o.price + bias + random.uniform(-8, 8), 0))
        return offers
