from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = ROOT / "config.yaml"
EXAMPLE_CONFIG = ROOT / "config.example.yaml"


class ScheduleConfig(BaseModel):
    """扫描节奏。优先 interval_seconds；旧配置 interval_minutes 会自动换算。"""

    interval_seconds: int = 3600
    jitter_seconds: int = 900
    run_on_start: bool = True
    # 兼容旧字段（写入时不再依赖）
    interval_minutes: int | None = None
    jitter_minutes: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _legacy_minutes(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if out.get("interval_seconds") is None and out.get("interval_minutes") is not None:
            out["interval_seconds"] = int(out["interval_minutes"]) * 60
        if out.get("jitter_seconds") is None and out.get("jitter_minutes") is not None:
            out["jitter_seconds"] = int(out["jitter_minutes"]) * 60
        return out


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
    host: str = "0.0.0.0"
    port: int = 8787


class DatabaseConfig(BaseModel):
    path: str = "data/gofly.db"


class NotifyConfig(BaseModel):
    """推送提醒，多渠道兼容。"""

    enabled: bool = False
    # spt / wxpusher | serverchan | pushplus | email（token 前缀 SPT_/SCT 也可自动识别）
    channel: str = "spt"
    # SPT_xxx（WxPusher）或 SCT...（Server酱）等；email 通道可留空
    token: str = ""
    # email 通道（建议 QQ 邮箱 + 微信「QQ邮箱提醒」）
    smtp_host: str = "smtp.qq.com"
    smtp_port: int = 465
    smtp_ssl: bool | None = None  # None=按端口推断：465 SSL，587 STARTTLS
    smtp_user: str = ""
    smtp_pass: str = ""  # QQ 邮箱用授权码，非登录密码
    mail_from: str = ""  # 空则用 smtp_user
    mail_to: str = ""  # 空则用 smtp_user；微信提醒请填已绑定的 QQ 邮箱


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
    if cfg_path.is_dir():
        raise FileNotFoundError(
            f"配置路径是目录而非文件: {cfg_path}（请挂载文件到 /app/config.yaml，不要挂成空目录）"
        )
    with open(cfg_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _apply_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    """环境变量覆盖 YAML（便于 Docker/绿联改监听地址）。"""
    out = dict(raw)
    server = dict(out.get("server") or {})
    host = os.environ.get("GOFLY_HOST") or os.environ.get("SERVER_HOST")
    port = os.environ.get("GOFLY_PORT") or os.environ.get("SERVER_PORT")
    if host:
        server["host"] = host.strip()
    if port:
        server["port"] = int(port)
    if server:
        out["server"] = server
    return out


@lru_cache
def get_config() -> AppConfig:
    return AppConfig.model_validate(_apply_env_overrides(load_raw()))


def reload_config() -> AppConfig:
    get_config.cache_clear()
    return get_config()


def db_path() -> Path:
    p = _resolve_path(get_config().database.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def crawler_dict() -> dict[str, Any]:
    return get_config().crawler.model_dump()


MIN_INTERVAL_SECONDS = 300


def config_file_path() -> Path:
    return _resolve_path(os.environ.get("GOFLY_CONFIG", DEFAULT_CONFIG))


def effective_jitter_seconds(interval_s: int, jitter_s: int | None = None) -> int:
    """抖动上限随间隔缩放（约 40%），最短间隔 300s 时约 ±120s。"""
    interval_s = max(MIN_INTERVAL_SECONDS, int(interval_s))
    raw = int(jitter_s if jitter_s is not None else get_config().schedule.jitter_seconds)
    cap = max(30, interval_s * 2 // 5)
    return max(0, min(raw, cap))


def _upsert_yaml_int(text: str, key: str, value: int) -> str:
    if re.search(rf"{key}\s*:", text):
        return re.sub(
            rf"({key}\s*:\s*)\d+",
            rf"\g<1>{value}",
            text,
            count=1,
        )
    if re.search(r"^schedule\s*:", text, flags=re.M):
        return re.sub(
            r"(^schedule\s*:\s*\n)",
            rf"\1  {key}: {value}\n",
            text,
            count=1,
            flags=re.M,
        )
    return text + f"\nschedule:\n  {key}: {value}\n"


def _remove_yaml_key(text: str, key: str) -> str:
    return re.sub(rf"(?m)^[ \t]*{key}\s*:.*\n?", "", text)


def update_schedule_interval_seconds(seconds: int) -> int:
    seconds = int(seconds)
    if seconds < MIN_INTERVAL_SECONDS:
        raise ValueError(f"扫描间隔不得少于 {MIN_INTERVAL_SECONDS} 秒")
    path = config_file_path()
    if not path.exists():
        path = EXAMPLE_CONFIG
    text = path.read_text(encoding="utf-8")
    text = _upsert_yaml_int(text, "interval_seconds", seconds)
    # 去掉旧分钟字段，避免下次加载被覆盖回旧值
    text = _remove_yaml_key(text, "interval_minutes")
    path.write_text(text, encoding="utf-8")
    reload_config()
    return seconds


# 兼容旧调用名
def update_schedule_interval(minutes: int) -> int:
    return update_schedule_interval_seconds(int(minutes) * 60) // 60
