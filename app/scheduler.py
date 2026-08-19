from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_config
from app.services.monitor import run_all_enabled

logger = logging.getLogger("gofly.scheduler")

_scheduler: Optional[BackgroundScheduler] = None
TZ = ZoneInfo("Asia/Shanghai")


def _job() -> None:
    try:
        logger.info("scheduled scan start")
        run_all_enabled(trigger="schedule")
        logger.info("scheduled scan done")
    except Exception:
        logger.exception("scheduled scan failed")


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler and _scheduler.running:
        return _scheduler

    cfg = get_config().schedule
    base = max(5, cfg.interval_minutes)
    jitter = max(0, cfg.jitter_minutes)
    trigger = IntervalTrigger(minutes=base, jitter=jitter * 60 if jitter else None)

    _scheduler = BackgroundScheduler(timezone=TZ)
    _scheduler.add_job(_job, trigger=trigger, id="gofly_scan", replace_existing=True)
    _scheduler.start()
    logger.info("scheduler started: every %s±%s min", base, jitter)

    if cfg.run_on_start:
        run_at = datetime.now(TZ) + timedelta(seconds=2)
        _scheduler.add_job(
            _job,
            trigger="date",
            run_date=run_at,
            id="gofly_scan_once",
            replace_existing=True,
        )
        logger.info("run_on_start at %s", run_at.isoformat())

    return _scheduler


def reschedule() -> dict[str, Any]:
    """按最新配置重置间隔任务。"""
    cfg = get_config().schedule
    base = max(5, cfg.interval_minutes)
    jitter = max(0, cfg.jitter_minutes)
    trigger = IntervalTrigger(minutes=base, jitter=jitter * 60 if jitter else None)
    if _scheduler and _scheduler.running:
        _scheduler.reschedule_job("gofly_scan", trigger=trigger)
        logger.info("scheduler rescheduled: every %s±%s min", base, jitter)
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
    next_run = None
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("gofly_scan")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    return {
        "interval_minutes": cfg.interval_minutes,
        "jitter_minutes": cfg.jitter_minutes,
        "next_run_at": next_run,
        "running": bool(_scheduler and _scheduler.running),
    }
