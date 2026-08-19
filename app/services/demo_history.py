from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from app import db
from app.config import get_config


def backfill_demo_history(points: int = 24) -> int:
    """为演示模式补历史点，让趋势图立刻有曲线。"""
    cfg = get_config()
    if list(cfg.platforms) != ["mock"]:
        return 0

    routes = db.list_routes(enabled_only=True)
    written = 0
    platforms = ["mock", "fliggy", "ctrip", "qunar"]
    bias = {"mock": 0, "fliggy": -18, "ctrip": 12, "qunar": -6}

    with db.connect() as conn:
        for route in routes:
            n = conn.execute(
                "SELECT COUNT(*) AS c FROM price_snapshots WHERE route_id = ?",
                (route["id"],),
            ).fetchone()["c"]
            if n >= points:
                continue
            base = 400 + (abs(hash(f"{route['origin']}{route['destination']}")) % 350)
            now = datetime.now(timezone.utc)
            for i in range(points, 0, -1):
                t = now - timedelta(hours=i * 3)
                wave = 35 * math.sin(i / 5)
                for p in platforms:
                    price = max(
                        199,
                        round(base + wave + bias[p] + random.uniform(-20, 20), 0),
                    )
                    conn.execute(
                        """
                        INSERT INTO price_snapshots
                        (route_id, platform, observed_at, min_price, currency, offer_count, error)
                        VALUES (?, ?, ?, ?, 'CNY', 1, NULL)
                        """,
                        (
                            route["id"],
                            p,
                            t.replace(microsecond=0).isoformat(),
                            price,
                        ),
                    )
                    written += 1
    return written
