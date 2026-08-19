from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import get_config

logger = logging.getLogger("gofly.notify")

_PLATFORM_LABEL = {
    "fliggy": "飞猪",
    "ctrip": "携程",
    "qunar": "去哪儿",
    "mock": "演示",
}


def _token(cfg: Any) -> str:
    return (cfg.token or "").strip()


def resolve_channel(cfg: Any | None = None) -> str:
    cfg = cfg or get_config().notify
    token = _token(cfg)
    upper = token.upper()
    if upper.startswith("SPT"):
        return "wxpusher"
    if upper.startswith("SCT") or token.lower().startswith("sctp"):
        return "serverchan"
    channel = (cfg.channel or "wxpusher").strip().lower()
    aliases = {
        "wxpusher": "wxpusher",
        "wx": "wxpusher",
        "spt": "wxpusher",
        "serverchan": "serverchan",
        "sct": "serverchan",
        "ftqq": "serverchan",
        "pushplus": "pushplus",
    }
    return aliases.get(channel, "wxpusher")


def notify_status() -> dict[str, Any]:
    cfg = get_config().notify
    token = _token(cfg)
    return {
        "enabled": bool(cfg.enabled and token),
        "channel": resolve_channel(cfg),
        "configured": bool(token),
    }


def _route_label(route: dict[str, Any]) -> str:
    o = route.get("origin_name") or route.get("origin") or "?"
    d = route.get("destination_name") or route.get("destination") or "?"
    return f"{o} → {d}"


def _send_raw(title: str, content: str) -> bool:
    """推送微信提醒。未配置或失败时返回 False，不抛错。"""
    cfg = get_config().notify
    token = _token(cfg)
    if not cfg.enabled or not token:
        return False

    channel = resolve_channel(cfg)
    try:
        if channel == "serverchan":
            ok = _send_serverchan(token, title, content)
        elif channel == "pushplus":
            ok = _send_pushplus(token, title, content)
        else:
            ok = _send_wxpusher(token, title, content)
        if ok:
            logger.info("wechat notify ok via %s: %s", channel, title)
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("wechat notify failed: %s", exc)
        return False


def send_drop_digest(drops: list[dict[str, Any]]) -> bool:
    """把本轮所有降价航班合并成一条微信提醒。"""
    if not drops:
        return False

    title = f"机票降价提醒（{len(drops)} 班）"
    # 按航线分组
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for d in drops:
        route = d.get("route") or {}
        key = f"{route.get('id')}|{route.get('date_label') or route.get('depart_date')}|{_route_label(route)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)

    lines: list[str] = []
    for key in order:
        items = groups[key]
        route = items[0].get("route") or {}
        date_txt = route.get("date_label") or route.get("depart_date", "")
        lines.append(f"{_route_label(route)} · {date_txt}")
        for d in sorted(items, key=lambda x: x.get("delta", 0)):
            plat = _PLATFORM_LABEL.get(d.get("platform", ""), d.get("platform", ""))
            fn = d.get("flight_no") or "?"
            airline = d.get("airline") or ""
            label = f"{airline}{fn}" if airline and not str(fn).startswith(str(airline)) else fn
            delta = abs(float(d.get("delta") or 0))
            lines.append(
                f"  {label} {plat} ¥{float(d['price']):.0f}（↓{delta:.0f}）"
            )
        lines.append("")

    content = "\n".join(lines).rstrip()
    return _send_raw(title, content)


def send_price_alert(
    route: dict[str, Any],
    *,
    platform: str,
    price: float,
    threshold: float,
) -> bool:
    """兼容旧调用 / 测试推送。"""
    return send_drop_digest(
        [
            {
                "route": route,
                "platform": platform,
                "flight_no": "TEST",
                "airline": "",
                "price": price,
                "prev_price": threshold,
                "delta": price - threshold if threshold else -1,
            }
        ]
    )


def _send_wxpusher(spt: str, title: str, content: str) -> bool:
    # https://wxpusher.zjiecode.com/ 极简推送，永久免费、无需实名
    html = f"<b>{title}</b><br>{content.replace(chr(10), '<br>')}"
    with httpx.Client(timeout=15.0) as client:
        r = client.post(
            "https://wxpusher.zjiecode.com/api/send/message/simple-push",
            json={
                "spt": spt,
                "summary": title[:100],
                "content": html,
                "contentType": 2,
            },
        )
        r.raise_for_status()
        data = r.json()
    if data.get("code") not in (1000, "1000"):
        logger.warning("wxpusher reject: %s", data)
        return False
    return True


def _send_pushplus(token: str, title: str, content: str) -> bool:
    # 需实名付费，不推荐
    with httpx.Client(timeout=15.0) as client:
        r = client.post(
            "https://www.pushplus.plus/send",
            json={
                "token": token,
                "title": title,
                "content": content.replace("\n", "<br>"),
                "template": "html",
            },
        )
        r.raise_for_status()
        data = r.json()
    code = data.get("code")
    if code not in (200, "200"):
        logger.warning("pushplus reject: %s", data)
        return False
    return True


def _send_serverchan(sendkey: str, title: str, content: str) -> bool:
    # https://sct.ftqq.com/ 免费每天 5 条
    url = f"https://sctapi.ftqq.com/{sendkey}.send"
    with httpx.Client(timeout=15.0) as client:
        r = client.post(url, data={"title": title, "desp": content})
        r.raise_for_status()
        data = r.json()
    if data.get("code") not in (0, "0"):
        logger.warning("serverchan reject: %s", data)
        return False
    return True
