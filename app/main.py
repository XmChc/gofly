from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import db
from app.cities import CITY_NAMES, CityResolveError, resolve_route_inputs, suggest_cities
from app.config import get_config
from app.scheduler import reschedule, scheduler_status, start_scheduler, stop_scheduler
from app.services.demo_history import backfill_demo_history
from app.services.monitor import get_scan_state, run_all_enabled, run_one_exclusive
from app.services.notify import notify_status, resolve_route_recipients, send_drop_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gofly")

STATIC_DIR = Path(__file__).resolve().parent / "static"


class RouteIn(BaseModel):
    # 支持中文城市名（厦门）或三字码（XMN）
    origin: str = Field(..., min_length=1, max_length=32)
    destination: str = Field(..., min_length=1, max_length=32)
    depart_date: str
    depart_date_end: Optional[str] = None
    alert_threshold: float = 0
    enabled: bool = True
    origin_name: str = ""
    destination_name: str = ""
    filters: Optional[dict[str, Any]] = None


class RoutePatch(BaseModel):
    enabled: Optional[bool] = None
    alert_threshold: Optional[float] = None
    filters: Optional[dict[str, Any]] = None
    depart_date: Optional[str] = None
    depart_date_end: Optional[str] = None
    notify_emails: Optional[list[str]] = None


class ResolveIn(BaseModel):
    origin: str = Field(..., min_length=1, max_length=32)
    destination: str = Field(..., min_length=1, max_length=32)


class ScheduleIn(BaseModel):
    interval_minutes: int


class NotifyTestIn(BaseModel):
    """可选：指定测试接收邮箱；留空列表则走全局默认。"""
    emails: Optional[list[str]] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    db.init_db()
    seeds = [s.model_dump() for s in cfg.seed_routes]
    n = db.seed_routes_if_empty(seeds)
    if n:
        logger.info("seeded %s routes", n)
    filled = backfill_demo_history()
    if filled:
        logger.info("backfilled %s demo price points", filled)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(title="GoFly", description="国内机票价格监控（飞猪）", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict[str, Any]:
    cfg = get_config()
    sched = scheduler_status()
    scan = get_scan_state()
    last = db.latest_scan_run()
    return {
        "ok": True,
        "platforms": cfg.platforms,
        "interval_minutes": cfg.schedule.interval_minutes,
        "interval_options": [15, 30, 45, 60, 90, 120, 180, 360, 720, 1440],
        "jitter_minutes": cfg.schedule.jitter_minutes,
        "next_run_at": sched.get("next_run_at"),
        "scanning": scan.get("scanning"),
        "scan_progress": scan.get("progress"),
        "scan_route_id": scan.get("current_route_id"),
        "last_scan": last,
        "notify": notify_status(),
    }


@app.patch("/api/schedule")
def api_schedule(body: ScheduleIn) -> dict[str, Any]:
    from app.config import update_schedule_interval

    try:
        minutes = update_schedule_interval(body.interval_minutes)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    status = reschedule()
    return {
        "ok": True,
        "interval_minutes": minutes,
        **status,
    }


@app.get("/api/cities")
def api_cities() -> dict[str, str]:
    return CITY_NAMES


@app.get("/api/cities/catalog")
def api_cities_catalog() -> list[dict[str, str]]:
    from app.cities import city_catalog

    return city_catalog()


@app.get("/api/cities/suggest")
def api_cities_suggest(q: str = "", limit: int = 12) -> list[dict[str, str]]:
    return suggest_cities(q, limit=limit)


@app.post("/api/cities/resolve")
def api_cities_resolve(body: ResolveIn) -> dict[str, str]:
    try:
        return resolve_route_inputs(body.origin, body.destination)
    except CityResolveError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/alerts")
def api_alerts(
    limit: int = 40,
    route_id: Optional[int] = None,
    latest_batch: bool = False,
) -> list[dict[str, Any]]:
    """默认返回仍有效的降价提醒（扫描时会按现价涨删/再降更新）。"""
    return db.list_alerts(limit=limit, route_id=route_id, latest_batch=latest_batch)


@app.post("/api/notify/test")
def api_notify_test(body: NotifyTestIn = NotifyTestIn()) -> dict[str, Any]:
    status = notify_status()
    if not status["enabled"]:
        raise HTTPException(
            400,
            "未启用推送：请在 config.yaml 设置 notify.enabled=true，"
            "并填写 token（微信通道）或 SMTP（email 通道）后重启",
        )
    route: dict[str, Any] = {
        "origin": "XMN",
        "origin_name": "厦门",
        "destination": "URC",
        "destination_name": "乌鲁木齐",
        "depart_date": "2026-09-25",
    }
    if body.emails is not None:
        route["notify_emails"] = body.emails
    recipients = resolve_route_recipients(route)
    if status["channel"] == "email" and not recipients:
        raise HTTPException(400, "没有可用的接收邮箱，请添加邮箱或配置全局默认")
    ok = send_drop_digest(
        [
            {
                "route": route,
                "platform": "fliggy",
                "flight_no": "MF8281/CZ6950",
                "airline": "厦航",
                "price": 1450,
                "prev_price": 1680,
                "delta": -230,
                "depart_time": "13:20",
                "arrive_time": "23:20",
                "duration_min": 600,
                "layover_min": 125,
                "stops": 1,
                "seats_hint": "充足",
                "depart_date": "2026-09-25",
                "origin": "XMN",
                "destination": "URC",
                "meta": {
                    "is_transfer": True,
                    "transfer_city": "兰州",
                    "layover_text": "2小时5分",
                    "cabin": "经济舱",
                    "baggage_text": "托运20kg",
                    "baggage_kg": 20,
                    "dep_airport": "XMN",
                    "arr_airport": "URC",
                    "leg_flights": ["MF8281", "CZ6950"],
                    "leg_airlines": ["厦航", "南航"],
                },
            }
        ]
    )
    if not ok:
        raise HTTPException(
            502,
            "推送失败，请检查 token / SMTP 配置 / 网络，并查看服务日志",
        )
    return {
        "ok": True,
        "channel": status["channel"],
        "recipients": recipients,
    }


@app.get("/api/routes")
def api_routes() -> list[dict[str, Any]]:
    return db.route_dashboard(platforms=get_config().platforms)


@app.post("/api/routes")
def api_create_route(body: RouteIn) -> dict[str, Any]:
    try:
        resolved = resolve_route_inputs(body.origin, body.destination)
        payload = {
            **resolved,
            "depart_date": body.depart_date,
            "depart_date_end": body.depart_date_end or body.depart_date,
            "alert_threshold": body.alert_threshold,
            "enabled": body.enabled,
        }
        if body.filters is not None:
            payload["filters"] = body.filters
        return db.create_route(payload)
    except CityResolveError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc)) from exc


@app.patch("/api/routes/{route_id}")
def api_patch_route(route_id: int, body: RoutePatch) -> dict[str, Any]:
    route = db.get_route(route_id)
    if not route:
        raise HTTPException(404, "route not found")
    try:
        if body.enabled is not None:
            route = db.set_route_enabled(route_id, body.enabled)
        if body.alert_threshold is not None:
            route = db.update_route_threshold(route_id, body.alert_threshold)
        if body.filters is not None:
            route = db.update_route_filters(route_id, body.filters)
        if body.notify_emails is not None:
            route = db.update_route_notify_emails(route_id, body.notify_emails)
        if body.depart_date is not None or body.depart_date_end is not None:
            start = body.depart_date or route["depart_date"]
            end = body.depart_date_end or body.depart_date or route.get("depart_date_end")
            route = db.update_route_dates(route_id, start, end)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return route  # type: ignore[return-value]


@app.delete("/api/routes/{route_id}")
def api_delete_route(route_id: int) -> dict[str, bool]:
    ok = db.delete_route(route_id)
    if not ok:
        raise HTTPException(404, "route not found")
    return {"ok": True}


@app.get("/api/routes/{route_id}/compare")
def api_compare(route_id: int) -> dict[str, Any]:
    route = db.get_route(route_id)
    if not route:
        raise HTTPException(404, "route not found")
    platforms = db.latest_compare(route_id, platforms=get_config().platforms)
    enriched = []
    for p in platforms:
        prev = db.previous_min(
            route_id,
            p["platform"],
            p["id"],
            depart_date=str(p.get("depart_date") or ""),
        )
        delta = None
        if prev is not None and p["min_price"] is not None:
            delta = float(p["min_price"]) - prev
        offers = db.offers_for_snapshot(p["id"])
        offers = db.enrich_offers_with_history(route_id, offers, days=30, points=24)
        enriched.append(
            {
                **p,
                "delta_vs_prev": delta,
                "offers": offers,
            }
        )
    return {
        "route": route,
        "platforms": enriched,
        "alerts": db.list_alerts(limit=5, route_id=route_id),
    }


@app.get("/api/routes/{route_id}/trend")
def api_trend(
    route_id: int,
    platform: Optional[str] = None,
    days: Optional[int] = None,
    limit: int = 300,
) -> dict[str, Any]:
    route = db.get_route(route_id)
    if not route:
        raise HTTPException(404, "route not found")
    bundle = db.trend_bundle(route_id, days=days, limit=limit)
    allow = {p.lower() for p in get_config().platforms}
    if platform:
        bundle["series"] = {
            k: v for k, v in bundle["series"].items() if k == platform
        }
    elif allow:
        bundle["series"] = {
            k: v for k, v in bundle["series"].items() if k.lower() in allow
        }
    # 默认图表用航班曲线；平台曲线仍返回供可选
    return {
        "route": route,
        "days": days,
        **bundle,
    }


@app.post("/api/routes/{route_id}/scan")
def api_scan_one(route_id: int) -> dict[str, Any]:
    route = db.get_route(route_id)
    if not route:
        raise HTTPException(404, "route not found")
    result = run_one_exclusive(route)
    if result.get("busy"):
        raise HTTPException(409, "正在扫描中，请稍候")
    return result


@app.post("/api/scan")
def api_scan_all() -> dict[str, Any]:
    result = run_all_enabled(trigger="manual")
    if result.get("busy"):
        raise HTTPException(409, "正在扫描中，请稍候")
    return result


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    cfg = get_config().server
    uvicorn.run(
        "app.main:app",
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
