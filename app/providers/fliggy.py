from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from typing import Any, Optional

import httpx

from app.airlines import (
    enrich_offer_fields,
    duration_from_hhmm,
    normalize_hhmm,
    parse_duration_min,
)
from app.baggage import baggage_meta_for_item
from app.models import FlightOffer
from app.providers import BaseProvider

APPKEY = "12574478"
MTOP_GW = "https://h5api.m.taobao.com/h5/{api}/{ver}/"
SEARCH_API = "mtop.trip.flight.flightSearch"
SEARCH_VER = "1.0"
REFERER = "https://h5.m.taobao.com/trip/flight/search/index.html"
FLIGHT_TYPES = {"DIRECT", "TRANSFER", "TRANSFER_RECOMMEND", "STOP"}


class FliggyProvider(BaseProvider):
    """飞猪 MTOP H5 网关取价（个人监控用，请控制频率）。"""

    name = "fliggy"

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.max_attempts = int(config.get("max_attempts", 4))
        self.max_poll = int(config.get("fliggy_max_poll", 3))
        self.backoff_s = float(config.get("backoff_seconds", 5))
        self.rate_limit = bool(config.get("rate_limit", True))
        self._success_times: list[float] = []
        self._lock = threading.Lock()

    @staticmethod
    def _sign(token: str, t: str, data: str) -> str:
        return hashlib.md5(f"{token}&{t}&{APPKEY}&{data}".encode()).hexdigest()

    @staticmethod
    def _token(client: httpx.Client) -> str:
        tk = client.cookies.get("_m_h5_tk", "") or ""
        return tk.split("_")[0] if tk else ""

    def _rate_acquire(self) -> None:
        while True:
            with self._lock:
                now = time.time()
                self._success_times = [t for t in self._success_times if now - t < 60]
                if len(self._success_times) < 5:
                    return
                wait = 60 - (now - self._success_times[0]) + 0.5
            time.sleep(min(wait, 30))

    def _rate_record(self) -> None:
        with self._lock:
            self._success_times.append(time.time())

    def _mtop_get(
        self, client: httpx.Client, data_obj: dict[str, Any]
    ) -> httpx.Response:
        data = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
        t = str(int(time.time() * 1000))
        token = self._token(client)
        params = {
            "jsv": "2.7.0",
            "appKey": APPKEY,
            "t": t,
            "sign": self._sign(token, t, data),
            "api": SEARCH_API,
            "v": SEARCH_VER,
            "type": "originaljson",
            "dataType": "json",
            "data": data,
        }
        return client.get(
            MTOP_GW.format(api=SEARCH_API, ver=SEARCH_VER),
            params=params,
            timeout=25,
        )

    @staticmethod
    def _is_real(body: str) -> bool:
        if not body or "SUCCESS" not in body:
            return False
        try:
            obj = json.loads(body)
        except json.JSONDecodeError:
            return False
        if "SUCCESS" not in str(obj.get("ret", "")):
            return False
        data = obj.get("data") or {}
        return bool(data.get("success")) and (
            bool(data.get("items")) or bool(data.get("lowestPrice"))
        )

    def _one_attempt(
        self, origin: str, destination: str, depart_date: str
    ) -> tuple[bool, Optional[dict], bool]:
        ua = self.config.get("mobile_user_agent") or self.config.get("user_agent")
        client = httpx.Client(
            headers={
                "User-Agent": ua,
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Referer": REFERER,
            },
            timeout=25,
            follow_redirects=True,
        )
        blocked = False
        try:
            data_obj = {
                "searchType": 1,
                "depCityCode": origin,
                "arrCityCode": destination,
                "leaveDate": depart_date,
                "itineraryFilter": "0",
                "leaveCabinClass": "0",
                "useAcrossAgent": 1,
            }
            last = ""
            for _ in range(max(self.max_poll, 2)):
                r = self._mtop_get(client, data_obj)
                last = r.text
                if r.status_code != 200:
                    blocked = True
                    time.sleep(1.0)
                    continue
                if self._is_real(last):
                    return True, json.loads(last), blocked
                if "TOKEN_EMPTY" in last or "TOKEN_EXPIRED" in last:
                    time.sleep(0.4)
                    continue
                if "FAIL_SYS_ILLEGAL_ACCESS" in last or "x5sec" in last or "RGV587" in last:
                    blocked = True
                    return False, None, blocked
            return False, None, blocked
        finally:
            client.close()

    def _fetch_raw(
        self, origin: str, destination: str, depart_date: str
    ) -> Optional[dict]:
        for attempt in range(1, self.max_attempts + 1):
            if self.rate_limit:
                self._rate_acquire()
            ok, raw, blocked = self._one_attempt(origin, destination, depart_date)
            if ok and raw:
                if self.rate_limit:
                    self._rate_record()
                self.logger.info("[fliggy] got prices on attempt %s", attempt)
                return raw
            time.sleep(self.backoff_s * (2 if blocked else 1))
        return None

    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        raw = self._fetch_raw(origin, destination, depart_date)
        if not raw:
            raise RuntimeError("飞猪未返回有效价格（可能被风控或无航班）")
        offers = self._parse(raw, origin, destination, depart_date)
        if offers:
            return offers
        lp = (raw.get("data") or {}).get("lowestPrice")
        if lp and float(lp) > 0:
            return [
                FlightOffer(
                    platform=self.name,
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    price=float(lp),
                )
            ]
        raise RuntimeError("飞猪响应无法解析价格")

    def _parse(
        self, raw: dict, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        data = raw.get("data") or {}
        offers: list[FlightOffer] = []
        seen: set[tuple] = set()
        for group in data.get("items") or []:
            item_type = group.get("itemType")
            if item_type not in FLIGHT_TYPES:
                continue
            for ds in group.get("itemDatas") or []:
                offer = self._from_item(
                    ds, item_type, origin, destination, depart_date
                )
                if not offer:
                    continue
                key = (offer.flight_no, offer.depart_time, offer.price)
                if key in seen:
                    continue
                seen.add(key)
                offers.append(offer)
        return offers

    def _from_item(
        self,
        ds: dict[str, Any],
        item_type: str,
        origin: str,
        destination: str,
        depart_date: str,
    ) -> FlightOffer | None:
        try:
            price = float(ds.get("bestPrice"))
        except (TypeError, ValueError):
            return None
        if price <= 0:
            return None

        ti = ds.get("transferInfo") if isinstance(ds.get("transferInfo"), dict) else {}
        sti = (
            ds.get("stopTransferInfo")
            if isinstance(ds.get("stopTransferInfo"), dict)
            else {}
        )
        track = ds.get("trackInfo") if isinstance(ds.get("trackInfo"), dict) else {}

        is_transfer = bool(ds.get("isTransfer")) or item_type in (
            "TRANSFER",
            "TRANSFER_RECOMMEND",
        )
        is_stop = bool(ds.get("isStop")) or bool(sti.get("isStop"))
        stops = 1 if is_transfer else 0

        flight_nos_raw = str(track.get("flightNos") or "")
        if flight_nos_raw:
            legs = [x for x in flight_nos_raw.replace("-", "_").split("_") if x]
        else:
            legs = []
            if ds.get("flightName"):
                legs.append(str(ds["flightName"]))
            if ti.get("transferFlightNo"):
                legs.append(str(ti["transferFlightNo"]))
        flight_no = "/".join(legs) if legs else str(ds.get("flightName") or "")

        airline = str(
            ds.get("airlineChineseShortName")
            or ds.get("airlineChineseName")
            or ""
        )
        transfer_airline = str(
            ti.get("transferAirlineChineseShortName")
            or ti.get("transferAirlineChineseName")
            or ds.get("transferAirlineChineseName")
            or ""
        )
        airline_display, flight_no = enrich_offer_fields(
            airline=airline or transfer_airline, flight_no=flight_no
        )

        dep_raw = str(ds.get("depTime") or ds.get("depTimeShow") or "")
        arr_raw = str(ds.get("arrTime") or ds.get("arrTimeShow") or "")
        # Prefer Fliggy duration minutes (already absolute travel time)
        duration_min = parse_duration_min(ds.get("duration")) or parse_duration_min(
            ds.get("flightTime") or ds.get("totalTravelTime") or ds.get("costTime")
        )
        if duration_min is None:
            duration_min = duration_from_hhmm(dep_raw, arr_raw)
            # overnight +N days when oneMore set
            try:
                more = int(ds.get("oneMore") or 0)
            except (TypeError, ValueError):
                more = 0
            if duration_min is not None and more > 0:
                duration_min += more * 24 * 60

        layover_min = parse_duration_min(ti.get("transferTime")) or parse_duration_min(
            ti.get("transferStopTime")
        )
        if not layover_min and is_stop:
            layover_min = parse_duration_min(sti.get("stopTotalTime"))

        craft = f"{ds.get('manufacturer') or ''}{ds.get('flightType') or ''}".strip()
        if not craft:
            craft = str(
                ds.get("craftTypeName")
                or ds.get("planeFullType")
                or ds.get("craft")
                or ""
            )

        seats = _seats_from_left(
            ds.get("leftNum") or ds.get("left") or ds.get("quantity") or ""
        )

        try:
            cross_days = int(ds.get("oneMore") or 0)
        except (TypeError, ValueError):
            cross_days = 0
        cross_label = str(ds.get("oneMoreShow") or "")
        if not cross_label and cross_days:
            cross_label = f"+{cross_days}天"

        transfer_city = str(ti.get("transferCityName") or "")
        stop_city = str(sti.get("stopCity") or ds.get("stopCity") or "")
        layover_text = str(ti.get("transferStopTime") or "")
        if not layover_text and layover_min:
            h, m = divmod(int(layover_min), 60)
            layover_text = f"{h}小时{m}分" if h else f"{m}分"

        icon = str(ds.get("airlineIcon") or "")
        if icon.startswith("//"):
            icon = "https:" + icon
        t_icon = str(ti.get("transferAirlineIcon") or "")
        if t_icon.startswith("//"):
            t_icon = "https:" + t_icon

        meta = {
            "item_type": item_type,
            "is_transfer": is_transfer,
            "is_stop": bool(is_stop and not is_transfer),
            "transfer_city": transfer_city,
            "stop_city": stop_city,
            "transfer_flight_no": str(ti.get("transferFlightNo") or ""),
            "transfer_airline": transfer_airline,
            "layover_text": layover_text,
            "cross_days": cross_days,
            "cross_days_label": cross_label,
            "airline_icon": icon,
            "transfer_airline_icon": t_icon,
            "leg_airlines": [x for x in (airline, transfer_airline if is_transfer else "") if x],
            "leg_flights": legs,
            "dep_airport": str(
                ds.get("depAirportCode")
                or ds.get("depAirportShortName")
                or origin
            ),
            "arr_airport": str(
                ds.get("arrAirportCode")
                or ds.get("arrAirportShortName")
                or destination
            ),
            "price_tag": "联程优惠价" if is_transfer else "",
            "cabin": str(ds.get("bestCabinClassName") or ""),
            "transfer_aircraft": str(ti.get("transferFlightSize") or ""),
        }
        meta.update(
            baggage_meta_for_item(
                ds,
                flight_no=flight_no,
                extra_codes=[
                    ds.get("airlineCode"),
                    ti.get("transferAirlineCode"),
                    ds.get("transferAirlineCode"),
                ],
            )
        )

        return FlightOffer(
            platform=self.name,
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            price=price,
            airline=airline_display,
            flight_no=flight_no,
            depart_time=normalize_hhmm(dep_raw) or str(ds.get("depTimeShow") or ""),
            arrive_time=normalize_hhmm(arr_raw) or str(ds.get("arrTimeShow") or ""),
            duration_min=duration_min,
            stops=stops,
            layover_min=layover_min,
            seats_hint=seats,
            aircraft=craft,
            meta=meta,
        )


def _seats_from_left(left: Any) -> str:
    """只返回余票状态，不返回具体数量。"""
    if left is None or left == "":
        return "未知"
    s = str(left).strip().upper()
    if s in {"A", "充足", ">9", "9+", "余票充足"}:
        return "充足"
    if s in {"B", "正常", "余票正常"}:
        return "正常"
    if s in {"C", "紧张", "少", "余票紧张"}:
        return "紧张"
    if s.isdigit():
        n = int(s)
        if n > 9:
            return "充足"
        if n >= 5:
            return "正常"
        return "紧张"
    if "充足" in str(left):
        return "充足"
    if "紧张" in str(left) or "少" in str(left):
        return "紧张"
    if "正常" in str(left):
        return "正常"
    return "未知"
