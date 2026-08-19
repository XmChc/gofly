from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from app.config import db_path
from app.models import FlightOffer

SCHEMA = """
CREATE TABLE IF NOT EXISTS watch_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    origin TEXT NOT NULL,
    origin_name TEXT NOT NULL DEFAULT '',
    destination TEXT NOT NULL,
    destination_name TEXT NOT NULL DEFAULT '',
    depart_date TEXT NOT NULL,
    depart_date_end TEXT NOT NULL DEFAULT '',
    alert_threshold REAL NOT NULL DEFAULT 0,
    filter_json TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    UNIQUE(origin, destination, depart_date)
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    depart_date TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    min_price REAL,
    currency TEXT NOT NULL DEFAULT 'CNY',
    offer_count INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    FOREIGN KEY(route_id) REFERENCES watch_routes(id)
);

CREATE TABLE IF NOT EXISTS flight_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    airline TEXT,
    flight_no TEXT,
    depart_time TEXT,
    arrive_time TEXT,
    duration_min INTEGER,
    stops INTEGER DEFAULT 0,
    layover_min INTEGER,
    price REAL NOT NULL,
    seats_hint TEXT,
    aircraft TEXT,
    meta_json TEXT,
    FOREIGN KEY(snapshot_id) REFERENCES price_snapshots(id)
);

CREATE TABLE IF NOT EXISTS scan_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    trigger TEXT NOT NULL DEFAULT 'manual',
    route_count INTEGER NOT NULL DEFAULT 0,
    ok_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'running',
    note TEXT
);

CREATE TABLE IF NOT EXISTS price_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    route_id INTEGER NOT NULL,
    platform TEXT NOT NULL,
    price REAL NOT NULL,
    threshold REAL NOT NULL,
    observed_at TEXT NOT NULL,
    snapshot_id INTEGER,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(route_id) REFERENCES watch_routes(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_route_time
    ON price_snapshots(route_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_platform
    ON price_snapshots(route_id, platform, observed_at);
CREATE INDEX IF NOT EXISTS idx_alerts_route
    ON price_alerts(route_id, observed_at);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def expand_depart_dates(start: str, end: str | None = None, *, max_days: int = 31) -> list[str]:
    """Inclusive date range YYYY-MM-DD → list of days (capped)."""
    start = (start or "").strip()
    end = (end or start or "").strip() or start
    if not start:
        return []
    try:
        a = datetime.strptime(start, "%Y-%m-%d").date()
        b = datetime.strptime(end, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("出发日期格式应为 YYYY-MM-dd") from exc
    if b < a:
        a, b = b, a
    days = (b - a).days + 1
    if days > max_days:
        raise ValueError(f"日期范围最多 {max_days} 天，当前 {days} 天")
    out: list[str] = []
    cur = a
    while cur <= b:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def normalize_route_dates(depart_date: str, depart_date_end: str | None = None) -> tuple[str, str]:
    dates = expand_depart_dates(depart_date, depart_date_end)
    if not dates:
        raise ValueError("请填写出发日期")
    return dates[0], dates[-1]


def route_date_label(route: dict[str, Any]) -> str:
    start = str(route.get("depart_date") or "")
    end = str(route.get("depart_date_end") or start)
    if not start:
        return ""
    if not end or end == start:
        return start
    try:
        n = len(expand_depart_dates(start, end))
    except ValueError:
        n = 0
    if n > 1:
        return f"{start} ~ {end}（{n}天）"
    return f"{start} ~ {end}"


def route_depart_dates(route: dict[str, Any]) -> list[str]:
    start = str(route.get("depart_date") or "")
    end = str(route.get("depart_date_end") or start)
    try:
        return expand_depart_dates(start, end)
    except ValueError:
        return [start] if start else []


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_route(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    from app.services.filters import normalize_filters

    d = dict(row)
    d["filters"] = normalize_filters(d.pop("filter_json", None) or "")
    start = str(d.get("depart_date") or "")
    end = str(d.get("depart_date_end") or "") or start
    d["depart_date_end"] = end
    d["date_label"] = route_date_label(d)
    d["date_count"] = len(route_depart_dates(d)) if start else 0
    return d


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        offer_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(flight_offers)").fetchall()
        }
        if "aircraft" not in offer_cols:
            conn.execute("ALTER TABLE flight_offers ADD COLUMN aircraft TEXT")
        if "meta_json" not in offer_cols:
            conn.execute("ALTER TABLE flight_offers ADD COLUMN meta_json TEXT")
        route_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(watch_routes)").fetchall()
        }
        if "filter_json" not in route_cols:
            from app.services.filters import filters_to_json

            conn.execute(
                "ALTER TABLE watch_routes ADD COLUMN filter_json TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                "UPDATE watch_routes SET filter_json = ? WHERE filter_json IS NULL OR filter_json = ''",
                (filters_to_json(None),),
            )
        if "depart_date_end" not in route_cols:
            conn.execute(
                "ALTER TABLE watch_routes ADD COLUMN depart_date_end TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                """
                UPDATE watch_routes
                SET depart_date_end = depart_date
                WHERE depart_date_end IS NULL OR depart_date_end = ''
                """
            )
        snap_cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()
        }
        if "depart_date" not in snap_cols:
            conn.execute(
                "ALTER TABLE price_snapshots ADD COLUMN depart_date TEXT NOT NULL DEFAULT ''"
            )
            conn.execute(
                """
                UPDATE price_snapshots
                SET depart_date = COALESCE(
                    (SELECT depart_date FROM watch_routes WHERE id = price_snapshots.route_id),
                    ''
                )
                WHERE depart_date IS NULL OR depart_date = ''
                """
            )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_snapshots_route_date
            ON price_snapshots(route_id, depart_date, platform, observed_at)
            """
        )


def seed_routes_if_empty(seeds: list[dict[str, Any]]) -> int:
    from app.cities import CityResolveError, resolve_route_inputs
    from app.services.filters import filters_to_json

    with connect() as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM watch_routes").fetchone()["c"]
        if n > 0 or not seeds:
            return 0
        now = utc_now()
        added = 0
        default_filters = filters_to_json(None)
        for s in seeds:
            try:
                resolved = resolve_route_inputs(s["origin"], s["destination"])
            except CityResolveError:
                # 兼容旧配置里的三字码
                from app.cities import resolve_route_names

                origin = str(s["origin"]).upper()
                destination = str(s["destination"]).upper()
                on, dn = resolve_route_names(origin, destination)
                resolved = {
                    "origin": origin,
                    "destination": destination,
                    "origin_name": on,
                    "destination_name": dn,
                }
            conn.execute(
                """
                INSERT OR IGNORE INTO watch_routes
                (origin, origin_name, destination, destination_name, depart_date,
                 depart_date_end, alert_threshold, filter_json, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    resolved["origin"],
                    resolved["origin_name"],
                    resolved["destination"],
                    resolved["destination_name"],
                    s["depart_date"],
                    str(s.get("depart_date_end") or s["depart_date"]),
                    float(s.get("alert_threshold") or 0),
                    filters_to_json(s.get("filters")) if s.get("filters") is not None else default_filters,
                    now,
                ),
            )
            added += 1
        return added


def list_routes(enabled_only: bool = False) -> list[dict[str, Any]]:
    sql = "SELECT * FROM watch_routes"
    if enabled_only:
        sql += " WHERE enabled = 1"
    sql += " ORDER BY id"
    with connect() as conn:
        rows = conn.execute(sql).fetchall()
    return [_row_to_route(r) for r in rows]


def get_route(route_id: int) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM watch_routes WHERE id = ?", (route_id,)
        ).fetchone()
    return _row_to_route(row) if row else None


def find_route(origin: str, destination: str, depart_date: str) -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM watch_routes
            WHERE origin = ? AND destination = ? AND depart_date = ?
            """,
            (origin.upper(), destination.upper(), depart_date),
        ).fetchone()
    return _row_to_route(row) if row else None


def create_route(payload: dict[str, Any]) -> dict[str, Any]:
    from app.cities import resolve_route_names
    from app.services.filters import filters_to_json, normalize_filters

    now = utc_now()
    origin = str(payload["origin"]).upper()
    destination = str(payload["destination"]).upper()
    origin_name, destination_name = resolve_route_names(
        origin,
        destination,
        payload.get("origin_name") or "",
        payload.get("destination_name") or "",
    )
    threshold = float(payload.get("alert_threshold") or 0)
    enabled = 1 if payload.get("enabled", True) else 0
    depart_date, depart_date_end = normalize_route_dates(
        str(payload.get("depart_date") or ""),
        str(payload.get("depart_date_end") or "") or None,
    )
    filter_raw = payload.get("filters", payload.get("filter_json"))
    filter_json = filters_to_json(filter_raw if filter_raw is not None else normalize_filters(None))

    existing = find_route(origin, destination, depart_date)
    if existing:
        with connect() as conn:
            conn.execute(
                """
                UPDATE watch_routes
                SET origin_name = ?, destination_name = ?,
                    depart_date_end = ?,
                    alert_threshold = ?, enabled = ?
                WHERE id = ?
                """,
                (
                    origin_name,
                    destination_name,
                    depart_date_end,
                    threshold,
                    enabled,
                    existing["id"],
                ),
            )
            # Keep existing filters on upsert unless explicitly provided.
            if filter_raw is not None:
                conn.execute(
                    "UPDATE watch_routes SET filter_json = ? WHERE id = ?",
                    (filter_json, existing["id"]),
                )
        route = get_route(existing["id"])
        assert route is not None
        return {**route, "_upsert": "updated"}

    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO watch_routes
            (origin, origin_name, destination, destination_name, depart_date,
             depart_date_end, alert_threshold, filter_json, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                origin,
                origin_name,
                destination,
                destination_name,
                depart_date,
                depart_date_end,
                threshold,
                filter_json,
                enabled,
                now,
            ),
        )
        rid = cur.lastrowid
    route = get_route(rid)
    assert route is not None
    return {**route, "_upsert": "created"}


def delete_route(route_id: int) -> bool:
    with connect() as conn:
        conn.execute("DELETE FROM flight_offers WHERE snapshot_id IN (SELECT id FROM price_snapshots WHERE route_id = ?)", (route_id,))
        conn.execute("DELETE FROM price_snapshots WHERE route_id = ?", (route_id,))
        conn.execute("DELETE FROM price_alerts WHERE route_id = ?", (route_id,))
        cur = conn.execute("DELETE FROM watch_routes WHERE id = ?", (route_id,))
        return cur.rowcount > 0


def set_route_enabled(route_id: int, enabled: bool) -> Optional[dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE watch_routes SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, route_id),
        )
        if cur.rowcount == 0:
            return None
    return get_route(route_id)


def update_route_threshold(route_id: int, threshold: float) -> Optional[dict[str, Any]]:
    with connect() as conn:
        cur = conn.execute(
            "UPDATE watch_routes SET alert_threshold = ? WHERE id = ?",
            (float(threshold or 0), route_id),
        )
        if cur.rowcount == 0:
            return None
    return get_route(route_id)


def update_route_filters(route_id: int, filters: Any) -> Optional[dict[str, Any]]:
    from app.services.filters import filters_to_json

    with connect() as conn:
        cur = conn.execute(
            "UPDATE watch_routes SET filter_json = ? WHERE id = ?",
            (filters_to_json(filters), route_id),
        )
        if cur.rowcount == 0:
            return None
    return get_route(route_id)


def save_platform_result(
    route_id: int,
    platform: str,
    offers: list[FlightOffer],
    error: str | None = None,
    *,
    depart_date: str = "",
) -> int:
    import json

    now = utc_now()
    min_price = min((o.price for o in offers), default=None)
    snap_date = (depart_date or "").strip()
    if not snap_date and offers:
        snap_date = str(getattr(offers[0], "depart_date", "") or "")
    with connect() as conn:
        if not snap_date:
            row = conn.execute(
                "SELECT depart_date FROM watch_routes WHERE id = ?",
                (route_id,),
            ).fetchone()
            snap_date = str(row["depart_date"]) if row else ""
        cur = conn.execute(
            """
            INSERT INTO price_snapshots
            (route_id, platform, depart_date, observed_at, min_price, currency, offer_count, error)
            VALUES (?, ?, ?, ?, ?, 'CNY', ?, ?)
            """,
            (route_id, platform, snap_date, now, min_price, len(offers), error),
        )
        sid = int(cur.lastrowid)
        for o in offers[:40]:
            conn.execute(
                """
                INSERT INTO flight_offers
                (snapshot_id, airline, flight_no, depart_time, arrive_time,
                 duration_min, stops, layover_min, price, seats_hint, aircraft, meta_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sid,
                    o.airline,
                    o.flight_no,
                    o.depart_time,
                    o.arrive_time,
                    o.duration_min,
                    o.stops,
                    o.layover_min,
                    o.price,
                    o.seats_hint,
                    o.aircraft,
                    json.dumps(o.meta or {}, ensure_ascii=False) if o.meta else None,
                ),
            )
    return sid


def latest_compare(
    route_id: int, platforms: list[str] | None = None
) -> list[dict[str, Any]]:
    """每个平台×出发日最近一次快照；失败（无价）的平台不展示旧残缺数据。

    platforms 若给定，只返回配置中启用的平台（避免历史 ctrip/qunar 脏数据）。
    """
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*
            FROM price_snapshots s
            INNER JOIN (
                SELECT platform, depart_date, MAX(id) AS max_id
                FROM price_snapshots
                WHERE route_id = ?
                GROUP BY platform, depart_date
            ) t ON s.id = t.max_id
            WHERE s.min_price IS NOT NULL
            ORDER BY s.depart_date ASC, s.min_price ASC
            """,
            (route_id,),
        ).fetchall()
    out = [dict(r) for r in rows]
    if platforms:
        allow = {p.lower() for p in platforms}
        out = [r for r in out if str(r.get("platform", "")).lower() in allow]
    return out


def previous_min(
    route_id: int,
    platform: str,
    before_id: int,
    *,
    depart_date: str | None = None,
) -> Optional[float]:
    with connect() as conn:
        if depart_date is None:
            cur = conn.execute(
                "SELECT depart_date FROM price_snapshots WHERE id = ?",
                (before_id,),
            ).fetchone()
            depart_date = str(cur["depart_date"] or "") if cur else ""
        row = conn.execute(
            """
            SELECT min_price FROM price_snapshots
            WHERE route_id = ? AND platform = ? AND id < ? AND min_price IS NOT NULL
              AND IFNULL(depart_date, '') = ?
            ORDER BY id DESC LIMIT 1
            """,
            (route_id, platform, before_id, depart_date or ""),
        ).fetchone()
    return float(row["min_price"]) if row and row["min_price"] is not None else None


def begin_scan_run(trigger: str, route_count: int) -> int:
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO scan_runs (started_at, trigger, route_count, status)
            VALUES (?, ?, ?, 'running')
            """,
            (utc_now(), trigger, route_count),
        )
        return int(cur.lastrowid)


def finish_scan_run(run_id: int, ok: int, fail: int, note: str = "") -> None:
    with connect() as conn:
        conn.execute(
            """
            UPDATE scan_runs
            SET finished_at = ?, ok_count = ?, fail_count = ?, status = 'done', note = ?
            WHERE id = ?
            """,
            (utc_now(), ok, fail, note, run_id),
        )


def latest_scan_run() -> Optional[dict[str, Any]]:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def record_alert(
    route_id: int,
    platform: str,
    price: float,
    threshold: float,
    snapshot_id: int | None,
) -> bool:
    """写入降价记录。threshold 字段存上期价格（便于列表展示）。"""
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO price_alerts
            (route_id, platform, price, threshold, observed_at, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (route_id, platform, price, threshold, utc_now(), snapshot_id),
        )
    return True


def detect_flight_drops(
    route_id: int,
    snapshot_id: int,
    *,
    filters: Any = None,
) -> list[dict[str, Any]]:
    """对比同平台上一快照，找出本轮降价的航班（按航班号）。

    仅统计命中航线默认筛选项的报价，用于提醒与推送。
    """
    from app.services.filters import normalize_filters, offer_matches_filters

    with connect() as conn:
        snap = conn.execute(
            "SELECT id, platform, depart_date FROM price_snapshots WHERE id = ? AND route_id = ?",
            (snapshot_id, route_id),
        ).fetchone()
        if not snap:
            return []
        prev = conn.execute(
            """
            SELECT id FROM price_snapshots
            WHERE route_id = ? AND platform = ? AND id < ?
              AND min_price IS NOT NULL
              AND IFNULL(depart_date, '') = ?
            ORDER BY id DESC LIMIT 1
            """,
            (route_id, snap["platform"], snapshot_id, snap["depart_date"] or ""),
        ).fetchone()
        if not prev:
            return []
        if filters is None:
            row = conn.execute(
                "SELECT filter_json FROM watch_routes WHERE id = ?",
                (route_id,),
            ).fetchone()
            filters = row["filter_json"] if row else None

    route_filters = normalize_filters(filters)
    curr_offers = offers_for_snapshot(snapshot_id)
    prev_offers = offers_for_snapshot(int(prev["id"]))
    prev_by_fn: dict[str, float] = {}
    for o in prev_offers:
        fn = str(o.get("flight_no") or "").strip().upper()
        if not fn:
            continue
        price = float(o["price"])
        if fn not in prev_by_fn or price < prev_by_fn[fn]:
            prev_by_fn[fn] = price

    best: dict[str, dict[str, Any]] = {}
    for o in curr_offers:
        if not offer_matches_filters(o, route_filters):
            continue
        fn = str(o.get("flight_no") or "").strip().upper()
        if not fn or fn not in prev_by_fn:
            continue
        cur = float(o["price"])
        old = prev_by_fn[fn]
        if cur >= old:
            continue
        item = {
            "route_id": route_id,
            "platform": snap["platform"],
            "flight_no": fn,
            "airline": o.get("airline") or "",
            "price": cur,
            "prev_price": old,
            "delta": round(cur - old, 1),
            "snapshot_id": snapshot_id,
            "depart_time": o.get("depart_time") or "",
        }
        if fn not in best or cur < best[fn]["price"]:
            best[fn] = item
    return sorted(best.values(), key=lambda x: x["delta"])


def list_alerts(limit: int = 20, route_id: int | None = None) -> list[dict[str, Any]]:
    sql = """
        SELECT a.*, r.origin, r.destination, r.origin_name, r.destination_name,
               r.depart_date, r.depart_date_end
        FROM price_alerts a
        JOIN watch_routes r ON r.id = a.route_id
    """
    params: list[Any] = []
    if route_id is not None:
        sql += " WHERE a.route_id = ?"
        params.append(route_id)
    sql += " ORDER BY a.id DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["date_label"] = route_date_label(d)
        out.append(d)
    return out


def sparkline(route_id: int, points: int = 24) -> list[float]:
    """跨平台按分钟聚合的最低价序列（用于卡片小图）。"""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT strftime('%Y-%m-%dT%H:%M', observed_at) AS bucket,
                   MIN(min_price) AS best
            FROM price_snapshots
            WHERE route_id = ? AND min_price IS NOT NULL AND platform != 'mock'
            GROUP BY bucket
            ORDER BY bucket DESC
            LIMIT ?
            """,
            (route_id, points),
        ).fetchall()
    vals = [float(r["best"]) for r in rows if r["best"] is not None]
    vals.reverse()
    return vals


def trend_series(
    route_id: int,
    platform: str | None = None,
    limit: int = 200,
    days: int | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT observed_at, platform, min_price
        FROM price_snapshots
        WHERE route_id = ? AND min_price IS NOT NULL AND platform != 'mock'
    """
    params: list[Any] = [route_id]
    if platform:
        sql += " AND platform = ?"
        params.append(platform)
    if days:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=int(days))
        ).replace(microsecond=0).isoformat()
        sql += " AND observed_at >= ?"
        params.append(cutoff)
    sql += " ORDER BY observed_at DESC LIMIT ?"
    params.append(limit)
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    data = [dict(r) for r in rows]
    data.reverse()
    return data


def flight_price_history(
    route_id: int,
    *,
    days: int | None = None,
    flight_nos: list[str] | None = None,
    limit_points: int = 60,
) -> dict[str, list[dict[str, Any]]]:
    """按航班号聚合历史价格（同一时刻多平台取最低）。"""
    sql = """
        SELECT fo.flight_no,
               fo.airline,
               fo.depart_time,
               fo.price,
               ps.observed_at,
               ps.platform
        FROM flight_offers fo
        JOIN price_snapshots ps ON ps.id = fo.snapshot_id
        WHERE ps.route_id = ?
          AND fo.flight_no IS NOT NULL
          AND fo.flight_no != ''
          AND ps.platform != 'mock'
    """
    params: list[Any] = [route_id]
    if days:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=int(days))
        ).replace(microsecond=0).isoformat()
        sql += " AND ps.observed_at >= ?"
        params.append(cutoff)
    if flight_nos:
        placeholders = ",".join("?" for _ in flight_nos)
        sql += f" AND fo.flight_no IN ({placeholders})"
        params.extend(flight_nos)
    sql += " ORDER BY ps.observed_at ASC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()

    # flight_no -> bucket -> min price
    buckets: dict[str, dict[str, float]] = {}
    meta: dict[str, dict[str, str]] = {}
    for r in rows:
        fn = str(r["flight_no"])
        bucket = str(r["observed_at"])[:16]
        buckets.setdefault(fn, {})
        prev = buckets[fn].get(bucket)
        price = float(r["price"])
        if prev is None or price < prev:
            buckets[fn][bucket] = price
        info = meta.setdefault(fn, {})
        if r["airline"]:
            info["airline"] = str(r["airline"])
        if r["depart_time"]:
            info["depart_time"] = str(r["depart_time"])

    out: dict[str, list[dict[str, Any]]] = {}
    for fn, by_t in buckets.items():
        pts = [{"t": t, "price": p} for t, p in sorted(by_t.items())]
        if limit_points and len(pts) > limit_points:
            pts = pts[-limit_points:]
        # attach latest airline/depart for UI labels
        info = meta.get(fn) or {}
        for p in pts:
            p["airline"] = info.get("airline", "")
            p["depart_time"] = info.get("depart_time", "")
        out[fn] = pts
    return out


def trend_bundle(
    route_id: int, days: int | None = None, limit: int = 300
) -> dict[str, Any]:
    series_rows = trend_series(route_id, days=days, limit=limit)
    by_platform: dict[str, list[dict[str, Any]]] = {}
    for row in series_rows:
        by_platform.setdefault(row["platform"], []).append(
            {"t": row["observed_at"], "price": row["min_price"]}
        )

    by_bucket: dict[str, list[float]] = {}
    for row in series_rows:
        bucket = str(row["observed_at"])[:16]
        by_bucket.setdefault(bucket, []).append(float(row["min_price"]))
    best_series = [
        {"t": t, "price": min(vals)} for t, vals in sorted(by_bucket.items())
    ]

    flight_hist = flight_price_history(
        route_id, days=days, limit_points=max(40, limit // 5)
    )
    # 优先展示当前仍出现、采样点多的航班
    flight_series = dict(
        sorted(
            flight_hist.items(),
            key=lambda kv: (-len(kv[1]), kv[1][-1]["price"] if kv[1] else 0),
        )[:40]
    )

    # 统计改为基于航班曲线汇总之「全网最低」仍保留，同时给出航班维度摘要
    prices = [p["price"] for p in best_series]
    best_now = prices[-1] if prices else None
    best_first = prices[0] if prices else None
    stats = {
        "sample_count": len(best_series),
        "current": best_now,
        "history_min": min(prices) if prices else None,
        "history_max": max(prices) if prices else None,
        "avg": round(sum(prices) / len(prices), 1) if prices else None,
        "delta_from_first": (
            round(best_now - best_first, 1)
            if best_now is not None and best_first is not None
            else None
        ),
        "flight_count": len(flight_series),
    }
    return {
        "series": by_platform,
        "best_series": best_series,
        "flight_series": flight_series,
        "stats": stats,
    }


def enrich_offers_with_history(
    route_id: int, offers: list[dict[str, Any]], *, days: int = 30, points: int = 24
) -> list[dict[str, Any]]:
    nos = [str(o["flight_no"]) for o in offers if o.get("flight_no")]
    if not nos:
        return offers
    hist = flight_price_history(
        route_id, days=days, flight_nos=nos, limit_points=points
    )
    for o in offers:
        fn = str(o.get("flight_no") or "")
        series = hist.get(fn) or []
        o["price_history"] = [float(p["price"]) for p in series]
        o["price_history_full"] = series
        if len(series) >= 2:
            o["price_delta"] = round(
                float(series[-1]["price"]) - float(series[-2]["price"]), 1
            )
        elif series:
            o["price_delta"] = 0.0
        else:
            o["price_delta"] = None
    return offers


def offers_for_snapshot(snapshot_id: int) -> list[dict[str, Any]]:
    import json

    from app.airlines import airline_from_flight_no, normalize_hhmm

    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM flight_offers
            WHERE snapshot_id = ?
            ORDER BY price ASC
            """,
            (snapshot_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        if not d.get("airline") and d.get("flight_no"):
            d["airline"] = airline_from_flight_no(str(d["flight_no"]))
        if d.get("depart_time"):
            d["depart_time"] = normalize_hhmm(d["depart_time"]) or d["depart_time"]
        if d.get("arrive_time"):
            d["arrive_time"] = normalize_hhmm(d["arrive_time"]) or d["arrive_time"]
        meta: dict[str, Any] = {}
        raw_meta = d.pop("meta_json", None)
        if raw_meta:
            try:
                meta = json.loads(raw_meta)
            except json.JSONDecodeError:
                meta = {}
        d["meta"] = meta
        # 统一余票为状态词
        hint = str(d.get("seats_hint") or "")
        if hint.isdigit() or hint.upper() in {"A", "B", "C"}:
            from app.providers.fliggy import _seats_from_left

            d["seats_hint"] = _seats_from_left(hint)
        elif hint.startswith("余票") and hint[2:].isdigit():
            d["seats_hint"] = "紧张" if int(hint[2:]) < 5 else "正常"
        out.append(d)
    return out


def previous_filtered_min(
    route_id: int,
    platform: str,
    before_id: int,
    filters: Any,
) -> Optional[float]:
    """上一快照中、命中筛选项的最低价（同出发日）。"""
    from app.services.filters import filter_offers

    with connect() as conn:
        cur = conn.execute(
            "SELECT depart_date FROM price_snapshots WHERE id = ?",
            (before_id,),
        ).fetchone()
        depart_date = str(cur["depart_date"] or "") if cur else ""
        row = conn.execute(
            """
            SELECT id FROM price_snapshots
            WHERE route_id = ? AND platform = ? AND id < ? AND min_price IS NOT NULL
              AND IFNULL(depart_date, '') = ?
            ORDER BY id DESC LIMIT 1
            """,
            (route_id, platform, before_id, depart_date),
        ).fetchone()
    if not row:
        return None
    matched = filter_offers(offers_for_snapshot(int(row["id"])), filters)
    if not matched:
        return None
    return min(float(o["price"]) for o in matched)


def best_filtered_quote(
    route_id: int,
    filters: Any,
    *,
    platforms: list[str] | None = None,
) -> Optional[dict[str, Any]]:
    """各平台最近快照中，命中航线默认筛选的最低报价。"""
    from app.services.filters import filter_offers

    compare = latest_compare(route_id, platforms=platforms)
    best: Optional[dict[str, Any]] = None
    for snap in compare:
        matched = filter_offers(offers_for_snapshot(int(snap["id"])), filters)
        if not matched:
            continue
        price = min(float(o["price"]) for o in matched)
        if best is None or price < float(best["price"]):
            best = {
                "price": price,
                "platform": snap["platform"],
                "snapshot_id": int(snap["id"]),
                "observed_at": snap["observed_at"],
            }
    if not best:
        return None
    prev = previous_filtered_min(
        route_id, str(best["platform"]), int(best["snapshot_id"]), filters
    )
    best["delta_vs_prev"] = (
        round(float(best["price"]) - prev, 1) if prev is not None else None
    )
    return best


def route_dashboard(platforms: list[str] | None = None) -> list[dict[str, Any]]:
    routes = list_routes()
    out = []
    for r in routes:
        compare = latest_compare(r["id"], platforms=platforms)
        quote = best_filtered_quote(r["id"], r.get("filters"), platforms=platforms)
        best_price = quote["price"] if quote else None
        below = (
            r["alert_threshold"]
            and best_price is not None
            and float(best_price) <= float(r["alert_threshold"])
        )
        out.append(
            {
                **r,
                "platforms": compare,
                "best_price": best_price,
                "best_platform": quote["platform"] if quote else None,
                "delta_vs_prev": quote["delta_vs_prev"] if quote else None,
                "observed_at": quote["observed_at"] if quote else None,
                "sparkline": sparkline(r["id"]),
                "below_threshold": bool(below),
            }
        )
    return out
