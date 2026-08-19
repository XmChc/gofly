from __future__ import annotations

import json
import re
from typing import Any

from app.airlines import (
    enrich_offer_fields,
    normalize_hhmm,
    parse_duration_min,
)
from app.models import FlightOffer
from app.providers.playwright_base import PlaywrightProvider, extract_generic_prices


class CtripProvider(PlaywrightProvider):
    """携程 PC 国内单程列表：拦截 batchSearch JSON。

    若被跳转到登录页，请先运行：
      python -m app.login ctrip
    会话会保存在 user_data/ctrip。
    """

    name = "ctrip"
    use_mobile = False

    URL_TPL = (
        "https://flights.ctrip.com/online/list/oneway-{origin}-{dest}"
        "?depdate={date}&cabin=y_s_c_f&adult=1&child=0&infant=0&containstax=1"
    )

    XHR_KEYS = [
        "batchSearch",
        "flightListSearch",
        "getFlightList",
        "international/search/api/search",
    ]

    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        url = self.URL_TPL.format(
            origin=origin.lower(),
            dest=destination.lower(),
            date=depart_date,
        )
        with self.browser() as ctx:
            page = ctx.new_page()
            page.set_default_timeout(self.timeout_ms())
            captured = self.attach_xhr(page, self.XHR_KEYS)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(6000)

            for sel in (
                ".close",
                ".btn-close",
                "[aria-label='关闭']",
                ".login-box .close",
            ):
                try:
                    page.locator(sel).first.click(timeout=800)
                except Exception:
                    pass

            for _ in range(5):
                try:
                    page.mouse.wheel(0, 2200)
                except Exception:
                    pass
                page.wait_for_timeout(1200)

            if "login" in page.url.lower() or "passport" in page.url.lower():
                self.debug_dump(page, f"login_{depart_date}")
                raise RuntimeError("携程需要登录：请运行 python -m app.login ctrip")

            offers = self._parse_captured(captured, origin, destination, depart_date)
            if not offers:
                offers = self._parse_dom(page, origin, destination, depart_date)
            if not offers:
                self.debug_dump(page, f"empty_{depart_date}")
                raise RuntimeError("携程未解析到有效航班价（可能需登录或被风控）")
            return offers

    def _parse_captured(
        self,
        captured: list[dict[str, str]],
        origin: str,
        destination: str,
        depart_date: str,
    ) -> list[FlightOffer]:
        offers: list[FlightOffer] = []
        for item in captured:
            text = item.get("text") or ""
            offers.extend(self._parse_body(text, origin, destination, depart_date))
        return self._dedupe(offers)

    def _parse_body(
        self, text: str, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        if not text:
            return []
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            return []

        data = obj.get("data") if isinstance(obj, dict) else None
        itins = None
        if isinstance(data, dict):
            itins = data.get("flightItineraryList")
        if not isinstance(itins, list):
            # some payloads nest differently
            itins = self._find_itineraries(obj)
        if not isinstance(itins, list) or not itins:
            return []

        offers: list[FlightOffer] = []
        for itin in itins:
            if not isinstance(itin, dict):
                continue
            offer = self._from_itinerary(itin, origin, destination, depart_date)
            if offer:
                offers.append(offer)
        return offers

    def _from_itinerary(
        self,
        itin: dict[str, Any],
        origin: str,
        destination: str,
        depart_date: str,
    ) -> FlightOffer | None:
        segments = itin.get("flightSegments") or []
        if not isinstance(segments, list) or not segments:
            return None

        flights: list[dict[str, Any]] = []
        transfer_count = 0
        duration = 0
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            transfer_count += int(seg.get("transferCount") or 0)
            try:
                duration = max(duration, int(seg.get("duration") or 0))
            except (TypeError, ValueError):
                pass
            for fl in seg.get("flightList") or []:
                if isinstance(fl, dict):
                    flights.append(fl)
        if not flights:
            return None

        price = self._best_price(itin.get("priceList") or [])
        if price is None:
            return None

        first, last = flights[0], flights[-1]
        flight_nos = [str(f.get("flightNo") or "").strip() for f in flights]
        flight_nos = [x for x in flight_nos if x]
        flight_no = "/".join(flight_nos)

        airline = (
            str(first.get("marketAirlineName") or "")
            or str(segments[0].get("airlineName") or "")
            or str(first.get("airlineName") or "")
        )
        airline, flight_no = enrich_offer_fields(airline=airline, flight_no=flight_no)

        dep_time = normalize_hhmm(
            first.get("departureDateTime") or first.get("departTime")
        )
        arr_time = normalize_hhmm(
            last.get("arrivalDateTime") or last.get("arriveTime")
        )
        duration_min = parse_duration_min(duration) or parse_duration_min(
            first.get("duration")
        )

        aircraft = str(first.get("aircraftName") or first.get("aircraftCode") or "")
        # 中转用 transfer；经停仍算直飞航线但 stops 记经停次数便于展示
        stops = transfer_count if transfer_count > 0 else 0
        # 若只有经停，用 layover_min 存经停时长（可选）；stops 仍为 0 显示直飞/经停由前端 stops 判断
        # 为可读性：经停航班 stops 保持 0，aircraft 旁不加；前端仍显示直飞。可接受。

        return FlightOffer(
            platform=self.name,
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            price=price,
            airline=airline,
            flight_no=flight_no,
            depart_time=dep_time,
            arrive_time=arr_time,
            duration_min=duration_min,
            stops=stops,
            layover_min=None,
            seats_hint="",
            aircraft=aircraft,
        )

    @staticmethod
    def _best_price(price_list: Any) -> float | None:
        if not isinstance(price_list, list):
            return None
        best: float | None = None
        for p in price_list:
            if not isinstance(p, dict):
                continue
            for k in ("adultPrice", "sortPrice", "lowestPrice", "price", "totalPrice"):
                if p.get(k) is None:
                    continue
                try:
                    val = float(p[k])
                except (TypeError, ValueError):
                    continue
                if 100 <= val <= 50000 and (best is None or val < best):
                    best = val
                break
        return best

    def _find_itineraries(self, obj: Any) -> list | None:
        found: list | None = None

        def walk(n: Any, depth: int = 0) -> None:
            nonlocal found
            if found is not None or depth > 6:
                return
            if isinstance(n, dict):
                if isinstance(n.get("flightItineraryList"), list):
                    found = n["flightItineraryList"]
                    return
                for v in n.values():
                    walk(v, depth + 1)
            elif isinstance(n, list):
                for v in n[:20]:
                    walk(v, depth + 1)

        walk(obj)
        return found

    def _parse_dom(
        self, page: Any, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        """Last-resort: scrape visible list row text."""
        try:
            rows = page.evaluate(
                """() => {
                  const nodes = Array.from(document.querySelectorAll(
                    '[class*="flight-item"], [class*="FlightItem"], [class*="list-item"]'
                  )).slice(0, 40);
                  return nodes.map(n => (n.innerText || '').trim()).filter(Boolean);
                }"""
            )
        except Exception:
            rows = []
        offers: list[FlightOffer] = []
        for text in rows or []:
            prices = [
                int(m.group(1))
                for m in re.finditer(r"[¥￥]\s*(\d{3,5})", text)
                if 100 <= int(m.group(1)) <= 50000
            ]
            if not prices:
                continue
            nos = re.findall(r"\b([A-Z0-9]{2}\d{3,4}(?:/[A-Z0-9]{2}\d{3,4})*)\b", text)
            times = re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
            airline, flight_no = enrich_offer_fields(
                flight_no=nos[0] if nos else ""
            )
            dep = f"{int(times[0][0]):02d}:{times[0][1]}" if len(times) >= 1 else ""
            arr = f"{int(times[1][0]):02d}:{times[1][1]}" if len(times) >= 2 else ""
            offers.append(
                FlightOffer(
                    platform=self.name,
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    price=float(min(prices)),
                    airline=airline,
                    flight_no=flight_no,
                    depart_time=dep,
                    arrive_time=arr,
                )
            )
        if offers:
            return self._dedupe(offers)
        # bare lowest price fallback
        html = page.content()
        prices = extract_generic_prices(html)
        prices += [
            int(m.group(1))
            for m in re.finditer(r"[¥￥]\s*(\d{3,5})", html)
            if 100 <= int(m.group(1)) <= 50000
        ]
        if prices:
            return [
                FlightOffer(
                    platform=self.name,
                    origin=origin,
                    destination=destination,
                    depart_date=depart_date,
                    price=float(min(prices)),
                )
            ]
        return []

    @staticmethod
    def _dedupe(offers: list[FlightOffer]) -> list[FlightOffer]:
        best: dict[tuple, FlightOffer] = {}
        bare: list[FlightOffer] = []
        for o in offers:
            if not o.flight_no and not o.depart_time:
                bare.append(o)
                continue
            key = (o.flight_no, o.depart_time)
            prev = best.get(key)
            if prev is None or o.price < prev.price:
                best[key] = o
        result = list(best.values())
        if result:
            result.sort(key=lambda x: x.price)
            return result
        if bare:
            return [min(bare, key=lambda x: x.price)]
        return []
