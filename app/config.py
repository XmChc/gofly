from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config.example.yaml"


class ScheduleConfig(BaseModel):
    interval_minutes: int = 60
    jitter_minutes: int = 15
    run_on_start: bool = True


class CrawlerConfig(BaseModel):
    headless: bool = True
    timeout_seconds: int = 45
    delay_min: float = 3
    delay_max: float = 8
    debug: bool = False
    debug_dir: str = "debug"
    user_data_dir: str = "user_data"
    max_attempts: int = 4
    fliggy_max_poll: int = 3
    rate_limit: bool = True
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    )
    mobile_user_agent: str = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    )


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8787


class DatabaseConfig(BaseModel):
    path: str = "data/gofly.db"


class NotifyConfig(BaseModel):
    """微信推送：推荐 WxPusher（永久免费、无需实名）。"""

    enabled: bool = False
    # wxpusher | serverchan | pushplus
    channel: str = "wxpusher"
    # WxPusher 极简 SPT，或 Server酱 SendKey
    token: str = ""


class SeedRoute(BaseModel):
    origin: str
    origin_name: str = ""
    destination: str
    destination_name: str = ""
    depart_date: str
    alert_threshold: float = 0


class AppConfig(BaseModel):
    platforms: list[str] = Field(default_factory=lambda: ["mock"])
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    crawler: CrawlerConfig = Field(default_factory=CrawlerConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    notify: NotifyConfig = Field(default_factory=NotifyConfig)
    seed_routes: list[SeedRoute] = Field(default_factory=list)


def _resolve_path(path: str | Path) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = ROOT / p
    return p


def load_raw(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or _resolve_path(os.environ.get("GOFLY_CONFIG", DEFAULT_CONFIG))
    if not cfg_path.exists():
        cfg_path = EXAMPLE_CONFIG
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@lru_cache
def get_config() -> AppConfig:
    return AppConfig.model_validate(load_raw())


def reload_config() -> AppConfig:
    get_config.cache_clear()
    return get_config()


def db_path() -> Path:
    p = _resolve_path(get_config().database.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def crawler_dict() -> dict[str, Any]:
    return get_config().crawler.model_dump()


ALLOWED_INTERVALS = (15, 30, 45, 60, 90, 120, 180, 360, 720, 1440)


def config_file_path() -> Path:
    return _resolve_path(os.environ.get("GOFLY_CONFIG", DEFAULT_CONFIG))


def update_schedule_interval(minutes: int) -> int:
    minutes = int(minutes)
    if minutes not in ALLOWED_INTERVALS:
        raise ValueError(f"扫描间隔仅支持: {', '.join(map(str, ALLOWED_INTERVALS))} 分钟")
    path = config_file_path()
    if not path.exists():
        path = EXAMPLE_CONFIG
    text = path.read_text(encoding="utf-8")
    if re.search(r"interval_minutes\s*:", text):
        text = re.sub(
            r"(interval_minutes\s*:\s*)\d+",
            rf"\g<1>{minutes}",
            text,
            count=1,
        )
    else:
        text += f"\nschedule:\n  interval_minutes: {minutes}\n"
    path.write_text(text, encoding="utf-8")
    reload_config()
    return minutes
