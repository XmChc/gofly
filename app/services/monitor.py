from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from app import db
from app.config import crawler_dict, get_config
from app.providers.registry import build_providers
from app.services.notify import send_drop_digest

logger = logging.getLogger("gofly.monitor")

_state_lock = threading.Lock()
_scan_state: dict[str, Any] = {
    "scanning": False,
    "trigger": None,
    "started_at": None,
    "current_route_id": None,
    "progress": "0/0",
}


def get_scan_state() -> dict[str, Any]:
    with _state_lock:
        return dict(_scan_state)


def _set_scan_state(**kwargs: Any) -> None:
    with _state_lock:
        _scan_state.update(kwargs)


def _collect_drops(route: dict[str, Any], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """对本轮各平台快照检测航班降价，并写入记录（仅默认筛选项内）。"""
    filters = route.get("filters")
    drops: list[dict[str, Any]] = []
    for r in results:
        sid = r.get("snapshot_id")
        if not sid or r.get("min_price") is None:
            continue
        for d in db.detect_flight_drops(route["id"], int(sid), filters=filters):
            db.record_alert(
                route["id"],
                d["platform"],
                float(d["price"]),
                float(d["prev_price"]),
                d.get("snapshot_id"),
            )
            drops.append({**d, "route": route})
    return drops


def _drops_for_notify(drops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按航线提醒限额过滤推送：限额 > 0 时仅推送现价 ≤ 限额的降价；空/0 不校验限额。"""
    out: list[dict[str, Any]] = []
    for d in drops:
        route = d.get("route") or {}
        try:
            limit = float(route.get("alert_threshold") or 0)
        except (TypeError, ValueError):
            limit = 0.0
        if limit > 0 and float(d.get("price") or 0) > limit:
            continue
        out.append(d)
    return out


def run_route(
    route: dict[str, Any],
    *,
    demo_multi: bool | None = None,
    notify: bool = True,
) -> dict[str, Any]:
    cfg = get_config()
    if demo_multi is None:
        demo_multi = list(cfg.platforms) == ["mock"]
    providers = build_providers(cfg.platforms, crawler_dict(), demo_multi=demo_multi)
    dates = db.route_depart_dates(route) or [route["depart_date"]]

    results: list[dict[str, Any]] = []

    def _one(provider, depart_date: str):
        offers, err = provider.safe_search(
            route["origin"], route["destination"], depart_date
        )
        sid = db.save_platform_result(
            route["id"],
            provider.name,
            offers,
            error=err,
            depart_date=depart_date,
        )
        return {
            "platform": provider.name,
            "depart_date": depart_date,
            "snapshot_id": sid,
            "min_price": min((o.price for o in offers), default=None),
            "offer_count": len(offers),
            "error": err,
            "top_offers": [o.to_dict() for o in offers[:8]],
        }

    workers = min(3, max(1, len(providers)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {}
        for depart_date in dates:
            for p in providers:
                futs[pool.submit(_one, p, depart_date)] = (p.name, depart_date)
        for fut in as_completed(futs):
            name, depart_date = futs[fut]
            try:
                results.append(fut.result())
            except Exception as exc:  # noqa: BLE001
                logger.exception("provider %s %s failed: %s", name, depart_date, exc)
                sid = db.save_platform_result(
                    route["id"],
                    name,
                    [],
                    error=str(exc),
                    depart_date=depart_date,
                )
                results.append(
                    {
                        "platform": name,
                        "depart_date": depart_date,
                        "snapshot_id": sid,
                        "min_price": None,
                        "offer_count": 0,
                        "error": str(exc),
                        "top_offers": [],
                    }
                )

    priced = [r for r in results if r["min_price"] is not None]
    best = min(priced, key=lambda r: r["min_price"]) if priced else None
    drops = _collect_drops(route, results)
    notify_drops = _drops_for_notify(drops)
    notified = False
    if notify and notify_drops:
        notified = send_drop_digest(notify_drops)

    return {
        "route_id": route["id"],
        "depart_dates": dates,
        "results": sorted(
            results,
            key=lambda r: (
                r.get("depart_date") or "",
                r["min_price"] is None,
                r["min_price"] or 0,
            ),
        ),
        "best": best,
        "drops": drops,
        "alerts": drops,  # 兼容前端旧字段
        "notified": notified,
    }


def run_one_exclusive(route: dict[str, Any], *, trigger: str = "manual_one") -> dict[str, Any]:
    """扫描单条航线并占用扫描锁，避免与「扫描全部」/定时任务交叉改价。"""
    rid = int(route["id"])
    with _state_lock:
        if _scan_state["scanning"]:
            return {"busy": True, "route_id": rid, "results": [], "drops": []}
        _scan_state.update(
            {
                "scanning": True,
                "trigger": trigger,
                "started_at": db.utc_now(),
                "current_route_id": rid,
                "progress": "1/1",
            }
        )
    try:
        logger.info(
            "scan one %s %s->%s %s",
            rid,
            route["origin"],
            route["destination"],
            db.route_date_label(route) or route["depart_date"],
        )
        return run_route(route)
    finally:
        _set_scan_state(
            scanning=False,
            trigger=None,
            started_at=None,
            current_route_id=None,
            progress="0/0",
        )


def run_all_enabled(*, trigger: str = "manual") -> dict[str, Any]:
    routes = db.list_routes(enabled_only=True)
    with _state_lock:
        if _scan_state["scanning"]:
            return {"busy": True, "results": [], "run_id": None}
        run_id = db.begin_scan_run(trigger, len(routes))
        _scan_state.update(
            {
                "scanning": True,
                "trigger": trigger,
                "started_at": db.utc_now(),
                "current_route_id": None,
                "progress": f"0/{len(routes)}",
            }
        )

    out: list[dict[str, Any]] = []
    all_drops: list[dict[str, Any]] = []
    ok = 0
    fail = 0
    try:
        for i, route in enumerate(routes, start=1):
            _set_scan_state(current_route_id=route["id"], progress=f"{i}/{len(routes)}")
            logger.info(
                "scan %s %s->%s %s",
                route["id"],
                route["origin"],
                route["destination"],
                db.route_date_label(route) or route["depart_date"],
            )
            result = run_route(route, notify=False)
            out.append(result)
            all_drops.extend(result.get("drops") or [])
            if result.get("best"):
                ok += 1
            else:
                fail += 1
        db.finish_scan_run(run_id, ok, fail)
    except Exception as exc:  # noqa: BLE001
        db.finish_scan_run(run_id, ok, fail, note=str(exc))
        raise
    finally:
        _set_scan_state(
            scanning=False,
            trigger=None,
            started_at=None,
            current_route_id=None,
            progress=f"{len(routes)}/{len(routes)}",
        )

    notified = False
    notify_drops = _drops_for_notify(all_drops)
    if notify_drops:
        notified = send_drop_digest(notify_drops)

    return {
        "busy": False,
        "run_id": run_id,
        "results": out,
        "drops": all_drops,
        "notified": notified,
    }
