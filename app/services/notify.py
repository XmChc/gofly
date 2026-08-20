from __future__ import annotations

import html
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
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


def _email_ready(cfg: Any) -> bool:
    user = (cfg.smtp_user or "").strip()
    password = (cfg.smtp_pass or "").strip()
    to_addr = (cfg.mail_to or "").strip() or user
    return bool(user and password and to_addr)


def resolve_channel(cfg: Any | None = None) -> str:
    """按 token 前缀优先识别渠道，否则用 channel 配置。"""
    cfg = cfg or get_config().notify
    token = _token(cfg)
    upper = token.upper()
    # token 形态优先，避免 channel 写错仍能推送
    if upper.startswith("SPT"):
        return "wxpusher"
    if upper.startswith("SCT") or token.lower().startswith("sctp"):
        return "serverchan"
    channel = (cfg.channel or "spt").strip().lower()
    aliases = {
        "wxpusher": "wxpusher",
        "wx": "wxpusher",
        "spt": "wxpusher",
        "simple": "wxpusher",
        "serverchan": "serverchan",
        "sct": "serverchan",
        "ftqq": "serverchan",
        "pushplus": "pushplus",
        "push": "pushplus",
        "email": "email",
        "mail": "email",
        "smtp": "email",
    }
    return aliases.get(channel, "wxpusher")


def notify_status() -> dict[str, Any]:
    cfg = get_config().notify
    channel = resolve_channel(cfg)
    if channel == "email":
        ready = _email_ready(cfg)
        has_default = bool(
            (cfg.mail_to or "").strip() or (cfg.smtp_user or "").strip()
        )
    else:
        ready = bool(_token(cfg))
        has_default = False
    return {
        "enabled": bool(cfg.enabled and ready),
        "channel": channel,
        "configured": ready,
        # 仅返回是否已配置，不回传真实邮箱，避免界面/接口泄露
        "has_default_mail": has_default,
    }


def _default_recipients(cfg: Any | None = None) -> list[str]:
    cfg = cfg or get_config().notify
    from app.db import parse_notify_emails

    return parse_notify_emails(
        [(cfg.mail_to or "").strip() or (cfg.smtp_user or "").strip()]
    )


def resolve_route_recipients(route: dict[str, Any] | None = None) -> list[str]:
    """航线自定义接收组优先，否则用全局 mail_to。"""
    from app.db import parse_notify_emails

    route = route or {}
    custom = parse_notify_emails(route.get("notify_emails"))
    if custom:
        return custom
    return _default_recipients()


def _route_label(route: dict[str, Any]) -> str:
    o = route.get("origin_name") or route.get("origin") or "?"
    d = route.get("destination_name") or route.get("destination") or "?"
    return f"{o} → {d}"


def _hhmm(value: object) -> str:
    s = str(value or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else s[-5:]


def _format_duration(minutes: object) -> str:
    try:
        m = int(round(float(minutes)))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return ""
    if m <= 0:
        return ""
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}小时{mm}分"
    if h:
        return f"{h}小时"
    return f"{mm}分"


def _short_airline(name: object) -> str:
    s = str(name or "").split("|")[0]
    return re.sub(r"航空|公司", "", s).strip() or str(name or "")


def _airline_for_leg(flight_no: str, fallback: str = "") -> str:
    from app.airlines import airline_from_flight_no

    return _short_airline(airline_from_flight_no(flight_no) or fallback)


def _is_transfer(d: dict[str, Any]) -> bool:
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    if meta.get("is_transfer") in (True, 1, "true", "1"):
        return True
    if "/" in str(d.get("flight_no") or ""):
        return True
    if meta.get("transfer_city") or meta.get("transfer_flight_no"):
        return True
    try:
        return int(d.get("stops") or 0) > 0 and bool(meta.get("transfer_city"))
    except (TypeError, ValueError):
        return False


def _seat_label(hint: object) -> str:
    s = str(hint or "").strip()
    if not s or s in {"null", "—", "-"}:
        return ""
    if s.startswith("余票"):
        return s
    if re.search(r"充足|A\b|>9", s, re.I):
        return "余票充足"
    if re.search(r"正常|B\b", s):
        return "余票正常"
    if re.search(r"紧张|少|C\b|^[1-4]$", s):
        return "余票紧张"
    if s.isdigit():
        n = int(s)
        if n > 9:
            return "余票充足"
        if n >= 5:
            return "余票正常"
        return "余票紧张"
    return f"余票{s}"


def _baggage_text(d: dict[str, Any]) -> str:
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    if meta.get("baggage_text"):
        return str(meta["baggage_text"])
    kg = meta.get("baggage_kg")
    if kg is not None and str(kg).strip() != "":
        try:
            n = int(float(kg))
            return f"托运{n}kg" if n > 0 else "不含托运"
        except (TypeError, ValueError):
            pass
    from app.baggage import baggage_meta_for_item

    packed = baggage_meta_for_item({}, flight_no=str(d.get("flight_no") or ""))
    return str(packed.get("baggage_text") or "")


def _leg_parts(d: dict[str, Any]) -> list[dict[str, str]]:
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    legs = meta.get("leg_flights") if isinstance(meta.get("leg_flights"), list) else None
    if not legs:
        legs = [x for x in str(d.get("flight_no") or "").split("/") if x]
    airs = meta.get("leg_airlines") if isinstance(meta.get("leg_airlines"), list) else []
    out: list[dict[str, str]] = []
    for i, fn in enumerate(legs or ["?"]):
        air = ""
        if i < len(airs) and airs[i]:
            air = _short_airline(airs[i])
        if not air:
            air = _airline_for_leg(str(fn), str(d.get("airline") or ""))
        out.append({"airline": air or "航司", "flight_no": str(fn)})
    return out


def _normalize_flight(d: dict[str, Any]) -> dict[str, Any]:
    route = d.get("route") or {}
    meta = d.get("meta") if isinstance(d.get("meta"), dict) else {}
    dep = _hhmm(d.get("depart_time"))
    arr = _hhmm(d.get("arrive_time"))
    duration = _format_duration(d.get("duration_min"))
    if not duration and dep and arr:
        from app.airlines import duration_from_hhmm

        duration = _format_duration(duration_from_hhmm(dep, arr))
    layover = str(meta.get("layover_text") or "").strip() or _format_duration(
        d.get("layover_min")
    )
    xfer = _is_transfer(d)
    legs = _leg_parts(d)
    title = " · ".join(f"{x['airline']} {x['flight_no']}" for x in legs)
    dep_code = str(meta.get("dep_airport") or d.get("origin") or route.get("origin") or "")
    arr_code = str(
        meta.get("arr_airport") or d.get("destination") or route.get("destination") or ""
    )
    price = float(d.get("price") or 0)
    prev = d.get("prev_price")
    delta = abs(float(d.get("delta") or 0))
    fare = meta.get("fare")
    tax = meta.get("tax")
    try:
        fare = float(fare) if fare is not None else None
    except (TypeError, ValueError):
        fare = None
    try:
        tax = float(tax) if tax is not None else None
    except (TypeError, ValueError):
        tax = None
    if fare is None and tax is not None and price:
        fare = round(price - tax, 2)
    if tax is None and fare is not None and price > fare + 0.5:
        tax = round(price - fare, 2)
    return {
        "title": title,
        "legs": legs,
        "is_transfer": xfer,
        "transfer_city": str(meta.get("transfer_city") or ("中转" if xfer else "")),
        "layover": layover,
        "dep": dep or "—",
        "arr": arr or "—",
        "dep_code": dep_code,
        "arr_code": arr_code,
        "cross_days": str(meta.get("cross_days_label") or ""),
        "duration": duration or "—",
        "cabin": str(meta.get("cabin") or "经济舱"),
        "baggage": _baggage_text(d),
        "seat": _seat_label(d.get("seats_hint")),
        "stop_city": str(meta.get("stop_city") or ""),
        "is_stop": bool(meta.get("is_stop")),
        "platform": _PLATFORM_LABEL.get(d.get("platform", ""), d.get("platform", "")),
        "price": price,
        "prev_price": float(prev) if prev is not None else None,
        "delta": delta,
        "fare": fare,
        "tax": tax,
        "depart_date": str(
            d.get("depart_date")
            or route.get("date_label")
            or route.get("depart_date")
            or ""
        ),
        "fliggy_url": _fliggy_url(route, d.get("depart_date")),
    }


def _fliggy_url(route: dict[str, Any], depart_date: object = None) -> str:
    from urllib.parse import quote

    dep = quote(str(route.get("origin") or ""), safe="")
    arr = quote(str(route.get("destination") or ""), safe="")
    date = quote(str(depart_date or route.get("depart_date") or ""), safe="")
    return (
        "https://sjipiao.fliggy.com/flight_search_result.htm"
        f"?tripType=0&depCity={dep}&arrCity={arr}&depDate={date}&searchBy=1280"
    )


def _group_drops(drops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按航线+日期分组，航班字段对齐看板卡片。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for d in drops:
        route = d.get("route") or {}
        day = d.get("depart_date") or route.get("date_label") or route.get("depart_date") or ""
        key = f"{route.get('id')}|{day}|{_route_label(route)}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(d)

    result: list[dict[str, Any]] = []
    for key in order:
        items = groups[key]
        route = items[0].get("route") or {}
        day = (
            items[0].get("depart_date")
            or route.get("date_label")
            or route.get("depart_date")
            or ""
        )
        flights = [
            _normalize_flight(d)
            for d in sorted(items, key=lambda x: float(x.get("delta") or 0))
        ]
        result.append(
            {
                "route_label": _route_label(route),
                "date": day,
                "flights": flights,
            }
        )
    return result


def _format_text(groups: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for g in groups:
        head = g["route_label"]
        if g["date"]:
            head = f"{head} · {g['date']}"
        lines.append(head)
        for f in g["flights"]:
            lines.append(f"  {f['title']}  ¥{f['price']:.0f}（↓{f['delta']:.0f}）")
            fare_line = _fare_caption(f)
            if fare_line:
                lines.append(f"    {fare_line}")
            mid = (
                f"{f['transfer_city']} 停 {f['layover']}"
                if f["is_transfer"]
                else ("经停" + f["stop_city"] if f["is_stop"] else "直飞")
            )
            lines.append(
                f"    {f['dep']} {f['dep_code']} → {mid} → {f['arr']} {f['arr_code']}"
            )
            bits = [x for x in (f"总时长 {f['duration']}", f"舱位 {f['cabin']}", f["baggage"], f["seat"], f["platform"]) if x]
            lines.append(f"    {' · '.join(bits)}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _fare_caption(f: dict[str, Any]) -> str:
    fare = f.get("fare")
    tax = f.get("tax")
    price = float(f.get("price") or 0)
    try:
        fare_n = float(fare) if fare is not None else None
    except (TypeError, ValueError):
        fare_n = None
    if fare_n is None or abs(fare_n - price) < 0.5:
        return ""
    try:
        tax_n = float(tax) if tax is not None else None
    except (TypeError, ValueError):
        tax_n = None
    if tax_n is None and price > fare_n:
        tax_n = price - fare_n
    bits = [f"机票 ¥{fare_n:.0f}"]
    if tax_n and tax_n > 0:
        bits.append(f"机建燃油 ¥{tax_n:.0f}")
    return " · ".join(bits)


def _pill(text: str, *, bg: str, fg: str) -> str:
    if not text:
        return ""
    return (
        f'<span style="display:inline-block;padding:2px 8px;border-radius:999px;'
        f'margin:2px 4px 2px 0;background:{bg};color:{fg};font-size:12px;'
        f'font-weight:600;line-height:1.4;">{html.escape(text)}</span>'
    )


def _render_flight_card(f: dict[str, Any]) -> str:
    prev_html = ""
    if f.get("prev_price") is not None:
        prev_html = (
            f'<span style="color:#94a3b8;text-decoration:line-through;font-size:13px;'
            f'margin-right:6px;">¥{f["prev_price"]:.0f}</span>'
        )
    legs_html = "".join(
        f"""
        <td style="padding:0 10px 0 0;vertical-align:top;">
          <div style="font-size:14px;font-weight:700;color:#0f172a;">
            {html.escape(leg['airline'])}
          </div>
          <div style="font-size:12px;color:#64748b;margin-top:2px;">
            {html.escape(leg['flight_no'])}
          </div>
        </td>
        """
        for leg in f["legs"]
    )
    if f["is_transfer"]:
        mid_html = f"""
          <div style="font-size:12px;font-weight:600;color:#1d4ed8;">
            {html.escape(f['transfer_city'] or '中转')}
          </div>
          <div style="font-size:11px;color:#64748b;margin-top:2px;">
            停 {html.escape(f['layover'] or '—')}
          </div>
        """
    elif f["is_stop"]:
        mid_html = f"""
          <div style="font-size:12px;color:#b45309;font-weight:600;">
            经停{html.escape(f['stop_city'])}
          </div>
        """
    else:
        mid_html = '<div style="font-size:12px;color:#64748b;">直飞</div>'

    cross = (
        f'<span style="margin-left:4px;font-size:11px;color:#ef4444;font-weight:600;">'
        f'{html.escape(f["cross_days"])}</span>'
        if f.get("cross_days")
        else ""
    )
    pills = "".join(
        [
            _pill(f"总时长 {f['duration']}", bg="#eff6ff", fg="#1d4ed8")
            if f.get("duration") and f["duration"] != "—"
            else "",
            _pill(f"舱位 {f['cabin']}", bg="#f8fafc", fg="#475569") if f.get("cabin") else "",
            _pill(f["baggage"], bg="#ecfdf5", fg="#047857") if f.get("baggage") else "",
            _pill(f["seat"], bg="#fef3c7", fg="#b45309") if f.get("seat") else "",
            _pill(str(f["platform"]), bg="#eef2ff", fg="#4338ca") if f.get("platform") else "",
        ]
    )
    link = ""
    if f.get("fliggy_url"):
        link = (
            f'<div style="margin-top:10px;">'
            f'<a href="{html.escape(f["fliggy_url"])}" '
            f'style="color:#2563eb;font-size:13px;font-weight:600;text-decoration:none;">'
            f'飞猪查余票 →</a></div>'
        )
    fare_cap = _fare_caption(f)
    fare_html = (
        f'<div style="margin-top:4px;font-size:12px;color:#64748b;">{html.escape(fare_cap)}</div>'
        if fare_cap
        else ""
    )

    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
        style="margin:0 0 10px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;">
      <tr>
        <td style="padding:14px 14px 10px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
            <tr>
              <td style="vertical-align:top;">
                <table role="presentation" cellpadding="0" cellspacing="0"><tr>{legs_html}</tr></table>
              </td>
              <td style="vertical-align:top;text-align:right;white-space:nowrap;padding-left:10px;">
                {prev_html}
                <span style="font-size:22px;font-weight:800;color:#ef4444;letter-spacing:-0.02em;">
                  ¥{f['price']:.0f}
                </span>
                {fare_html}
                <div style="margin-top:4px;">
                  {_pill(f"↓{f['delta']:.0f}", bg="#dcfce7", fg="#15803d")}
                </div>
              </td>
            </tr>
          </table>
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:12px;">
            <tr>
              <td style="width:28%;vertical-align:middle;">
                <div style="font-size:20px;font-weight:700;color:#0f172a;">{html.escape(f['dep'])}</div>
                <div style="font-size:12px;color:#64748b;margin-top:2px;">{html.escape(f['dep_code'])}</div>
              </td>
              <td style="width:44%;text-align:center;vertical-align:middle;padding:0 6px;">
                <div style="height:1px;background:#cbd5e1;margin:0 0 6px;"></div>
                {mid_html}
                <div style="height:1px;background:#cbd5e1;margin:6px 0 0;"></div>
              </td>
              <td style="width:28%;text-align:right;vertical-align:middle;">
                <div style="font-size:20px;font-weight:700;color:#0f172a;">
                  {html.escape(f['arr'])}{cross}
                </div>
                <div style="font-size:12px;color:#64748b;margin-top:2px;">{html.escape(f['arr_code'])}</div>
              </td>
            </tr>
          </table>
          <div style="margin-top:12px;">{pills}</div>
          {link}
        </td>
      </tr>
    </table>
    """


def _format_email_html(title: str, groups: list[dict[str, Any]], count: int) -> str:
    """邮件客户端友好的表格布局（对齐看板航班卡片）。"""
    sections: list[str] = []
    for g in groups:
        cards = "".join(_render_flight_card(f) for f in g["flights"])
        date_bit = (
            f'<span style="color:#64748b;font-weight:400;font-size:13px;">'
            f' · {html.escape(str(g["date"]))}</span>'
            if g["date"]
            else ""
        )
        sections.append(
            f"""
            <div style="margin:0 0 8px;padding:0 4px;">
              <div style="font-size:15px;font-weight:700;color:#1e293b;margin:0 0 10px;">
                {html.escape(g['route_label'])}{date_bit}
              </div>
              {cards}
            </div>
            """
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width"></head>
<body style="margin:0;padding:0;background:#eef2f7;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
      style="background:#eef2f7;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
            style="max-width:600px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',
            'PingFang SC','Noto Sans SC',sans-serif;">
          <tr>
            <td style="padding:22px 20px;border-radius:14px 14px 0 0;
                background:linear-gradient(135deg,#3b82f6,#1d4ed8);">
              <div style="font-size:13px;letter-spacing:0.04em;color:#bfdbfe;font-weight:600;">
                GoFly
              </div>
              <div style="margin-top:6px;font-size:22px;font-weight:700;color:#ffffff;line-height:1.3;">
                {html.escape(title)}
              </div>
              <div style="margin-top:10px;">
                <span style="display:inline-block;padding:4px 10px;border-radius:999px;
                    background:rgba(255,255,255,0.18);color:#eff6ff;font-size:12px;font-weight:600;">
                  共 {count} 班降价
                </span>
              </div>
            </td>
          </tr>
          <tr>
            <td style="padding:16px 8px 8px;background:#eef2f7;">
              {''.join(sections)}
            </td>
          </tr>
          <tr>
            <td style="padding:8px 16px 20px;text-align:center;font-size:12px;color:#94a3b8;">
              来自 GoFly 机票价格监控 · 打开看板查看详情
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""


def _send_raw(
    title: str,
    content: str,
    *,
    html_body: str | None = None,
    mail_to: list[str] | str | None = None,
) -> bool:
    """推送提醒。未配置或失败时返回 False，不抛错。"""
    cfg = get_config().notify
    if not cfg.enabled:
        return False

    channel = resolve_channel(cfg)
    if channel == "email":
        if not _email_ready(cfg):
            return False
    elif not _token(cfg):
        return False

    try:
        if channel == "serverchan":
            ok = _send_serverchan(_token(cfg), title, content)
        elif channel == "pushplus":
            ok = _send_pushplus(_token(cfg), title, content)
        elif channel == "email":
            ok = _send_email(cfg, title, content, html_body=html_body, mail_to=mail_to)
        else:
            ok = _send_wxpusher(_token(cfg), title, content)
        if ok:
            logger.info("notify ok via %s: %s", channel, title)
        return ok
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify failed via %s: %s", channel, exc)
        return False


def send_drop_digest(drops: list[dict[str, Any]]) -> bool:
    """把本轮降价航班合并推送；邮件通道按接收组拆分发送。"""
    if not drops:
        return False

    channel = resolve_channel()
    if channel != "email":
        groups = _group_drops(drops)
        count = len(drops)
        title = f"机票降价提醒（{count} 班）"
        content = _format_text(groups)
        html_body = _format_email_html(title, groups, count)
        return _send_raw(title, content, html_body=html_body)

    buckets: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for d in drops:
        recipients = resolve_route_recipients(d.get("route") or {})
        key = ",".join(recipients)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(d)

    any_ok = False
    for key in order:
        bucket = buckets[key]
        if not key:
            logger.warning("skip email digest: no recipients for %s drops", len(bucket))
            continue
        groups = _group_drops(bucket)
        count = len(bucket)
        title = f"机票降价提醒（{count} 班）"
        content = _format_text(groups)
        html_body = _format_email_html(title, groups, count)
        if _send_raw(title, content, html_body=html_body, mail_to=key.split(",")):
            any_ok = True
    return any_ok


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
    body = (
        f"<b>{html.escape(title)}</b><br>"
        f"{html.escape(content).replace(chr(10), '<br>')}"
    )
    with httpx.Client(timeout=15.0) as client:
        r = client.post(
            "https://wxpusher.zjiecode.com/api/send/message/simple-push",
            json={
                "spt": spt,
                "summary": title[:100],
                "content": body,
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
                "content": html.escape(content).replace("\n", "<br>"),
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


def _use_ssl(cfg: Any) -> bool:
    if cfg.smtp_ssl is not None:
        return bool(cfg.smtp_ssl)
    return int(cfg.smtp_port or 465) == 465


def _send_email(
    cfg: Any,
    title: str,
    content: str,
    *,
    html_body: str | None = None,
    mail_to: list[str] | str | None = None,
) -> bool:
    """SMTP 发信；配合微信「QQ邮箱提醒」可在微信收到通知。"""
    from app.db import parse_notify_emails

    host = (cfg.smtp_host or "smtp.qq.com").strip()
    port = int(cfg.smtp_port or 465)
    user = (cfg.smtp_user or "").strip()
    password = (cfg.smtp_pass or "").strip()
    mail_from = (cfg.mail_from or "").strip() or user
    recipients = parse_notify_emails(mail_to) if mail_to is not None else []
    if not recipients:
        recipients = parse_notify_emails(
            (cfg.mail_to or "").strip() or (cfg.smtp_user or "").strip()
        )
    if not (user and password and recipients):
        logger.warning("email notify incomplete: need smtp_user / smtp_pass / mail_to")
        return False

    msg = EmailMessage()
    msg["Subject"] = f"✈ {title}"
    msg["From"] = f"GoFly <{mail_from}>"
    msg["To"] = ", ".join(recipients)
    msg.set_content(content or title)
    msg.add_alternative(
        html_body
        or (
            f"<pre style=\"font-family:sans-serif;white-space:pre-wrap\">"
            f"{html.escape(content)}</pre>"
        ),
        subtype="html",
    )

    context = ssl.create_default_context()
    if _use_ssl(cfg):
        with smtplib.SMTP_SSL(host, port, timeout=20, context=context) as smtp:
            smtp.login(user, password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            smtp.ehlo()
            smtp.starttls(context=context)
            smtp.ehlo()
            smtp.login(user, password)
            smtp.send_message(msg)
    return True
