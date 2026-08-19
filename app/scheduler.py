from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import MIN_INTERVAL_SECONDS, effective_jitter_seconds, get_config
from app.services.monitor import run_all_enabled, run_one_exclusive

logger = logging.getLogger("gofly.scheduler")

_scheduler: Optional[BackgroundScheduler] = None
TZ = ZoneInfo("Asia/Shanghai")

FULL_JOB_ID = "gofly_scan"
PROBE_JOB_ID = "gofly_probe"


def _now() -> datetime:
    return datetime.now(TZ)


def _schedule_params() -> tuple[int, int]:
    cfg = get_config().schedule
    base = max(MIN_INTERVAL_SECONDS, int(cfg.interval_seconds))
    jitter = effective_jitter_seconds(base, cfg.jitter_seconds)
    return base, jitter


def _random_delay_seconds(base: int, jitter: int) -> float:
    """下次全量扫描等待：interval ± jitter（秒），至少 MIN_INTERVAL_SECONDS。"""
    lo = max(float(MIN_INTERVAL_SECONDS), float(base - jitter))
    hi = float(base + max(jitter, 0))
    if hi < lo:
        hi = lo
    return random.uniform(lo, hi)


def _job() -> None:
    try:
        logger.info("scheduled scan start")
        run_all_enabled(trigger="schedule")
        logger.info("scheduled scan done")
    except Exception:
        logger.exception("scheduled scan failed")
    finally:
        # 扫完再排下一次，节奏随耗时漂移，不易形成固定指纹
        _arm_next_cycle()


def _probe_job() -> None:
    """全量之间穿插随机单航线探测，打散请求节奏。"""
    try:
        from app import db

        routes = db.list_routes(enabled_only=True)
        if not routes:
            return
        route = random.choice(routes)
        logger.info(
            "probe scan route %s %s->%s",
            route["id"],
            route.get("origin"),
            route.get("destination"),
        )
        run_one_exclusive(route, trigger="probe")
    except Exception:
        logger.exception("probe scan failed")


def _clear_armed_jobs() -> None:
    if not _scheduler:
        return
    for job in list(_scheduler.get_jobs()):
        if job.id == FULL_JOB_ID or str(job.id).startswith(PROBE_JOB_ID):
            try:
                job.remove()
            except Exception:  # noqa: BLE001
                pass


def _arm_next_cycle() -> None:
    """安排下一次全量，并在等待窗口内穿插 0~2 次随机单航线扫描。"""
    if not _scheduler or not _scheduler.running:
        return
    base, jitter = _schedule_params()
    delay = _random_delay_seconds(base, jitter)
    run_at = _now() + timedelta(seconds=delay)
    _clear_armed_jobs()
    _scheduler.add_job(
        _job,
        trigger="date",
        run_date=run_at,
        id=FULL_JOB_ID,
        replace_existing=True,
    )
    logger.info(
        "next full scan in %.0f s (±%s around %s) at %s",
        delay,
        jitter,
        base,
        run_at.isoformat(),
    )

    routes = _enabled_routes()
    # 间隔够长才穿插探测（约 ≥8 分钟），避免最短 300s 档过密
    if delay < 480 or not routes:
        return
    probes = 1 if delay < 1500 else random.randint(1, 2)
    used: set[float] = set()
    for i in range(probes):
        # 落在等待窗口的 20%~80%，彼此至少隔开 120s
        for _ in range(12):
            offset = random.uniform(delay * 0.2, delay * 0.8)
            if all(abs(offset - u) >= 120.0 for u in used):
                used.add(offset)
                probe_at = _now() + timedelta(seconds=offset)
                jid = PROBE_JOB_ID if i == 0 else f"{PROBE_JOB_ID}_{i}"
                _scheduler.add_job(
                    _probe_job,
                    trigger="date",
                    run_date=probe_at,
                    id=jid,
                    replace_existing=True,
                )
                logger.info(
                    "probe scan armed in %.0f s at %s",
                    offset,
                    probe_at.isoformat(),
                )
                break


def _enabled_routes() -> list:
    try:
        from app import db

        return db.list_routes(enabled_only=True)
    except Exception:  # noqa: BLE001
        return []


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    cfg = get_config().schedule
    _scheduler = BackgroundScheduler(timezone=TZ)
    _scheduler.start()
    base, jitter = _schedule_params()
    logger.info("scheduler started: every ~%s±%s s (random + probes)", base, jitter)

    if cfg.run_on_start:
        run_at = _now() + timedelta(seconds=2)
        _scheduler.add_job(
            _job,
            trigger="date",
            run_date=run_at,
            id=FULL_JOB_ID,
            replace_existing=True,
        )
        logger.info("run_on_start at %s", run_at.isoformat())
    else:
        _arm_next_cycle()

    return _scheduler


def reschedule() -> dict[str, Any]:
    """按最新配置重置下次扫描（立即按新间隔随机排程）。"""
    if _scheduler and _scheduler.running:
        _arm_next_cycle()
        base, jitter = _schedule_params()
        logger.info("scheduler rescheduled: every ~%s±%s s", base, jitter)
    else:
        start_scheduler()
    return scheduler_status()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def scheduler_status() -> dict[str, Any]:
    cfg = get_config().schedule
    base, jitter = _schedule_params()
    next_run = None
    next_probe = None
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job(FULL_JOB_ID)
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
        probe_times = []
        for j in _scheduler.get_jobs():
            if str(j.id).startswith(PROBE_JOB_ID) and j.next_run_time:
                probe_times.append(j.next_run_time)
        if probe_times:
            next_probe = min(probe_times).isoformat()
    return {
        "interval_seconds": base,
        "jitter_seconds": jitter,
        "jitter_configured": cfg.jitter_seconds,
        # 兼容旧前端字段
        "interval_minutes": max(1, round(base / 60)),
        "jitter_minutes": max(0, round(jitter / 60)),
        "next_run_at": next_run,
        "next_probe_at": next_probe,
        "running": bool(_scheduler and _scheduler.running),
    }
