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


class QunarProvider(PlaywrightProvider):
    """去哪儿 PC：打开搜索页，关掉登录弹窗后拦截报价 XHR。

    若持续失败，先登录保存会话：
      python -m app.login qunar
    """

    name = "qunar"
    use_mobile = False

    URL_TPL = (
        "https://flight.qunar.com/site/oneway_list.htm"
        "?searchDepartureAirport={origin_name}"
        "&searchArrivalAirport={dest_name}"
        "&searchDepartureTime={date}"
        "&searchArrivalTime={date}"
        "&nextNDays=0&startSearch=true"
        "&fromCode={origin}&toCode={dest}"
        "&from={origin_name}&to={dest_name}&lowestPrice=null"
    )

    XHR_KEYS = [
        "twell/flight",
        "twell/searchrt",
        "searchrt_ui",
        "wbdflightlist",
        "flight/list",
        "flightList",
        "f_flight",
        "touchbase",
        "tagSearch",
        "gw/f/flight",
    ]

    def search(
        self, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        url = self.URL_TPL.format(
            origin=origin,
            dest=destination,
            date=depart_date,
            origin_name=self.city_name(origin),
            dest_name=self.city_name(destination),
        )
        with self.browser() as ctx:
            page = ctx.new_page()
            page.set_default_timeout(self.timeout_ms())
            captured = self.attach_xhr(page, self.XHR_KEYS)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)

            for sel in (
                "#QunarPopBoxClosePop",
                ".login_close",
                ".dialog-close",
                "a.close",
                ".login_content_head .login_close",
            ):
                try:
                    page.locator(sel).first.click(timeout=1000)
                except Exception:
                    pass

            try:
                page.locator("text=搜索").first.click(timeout=1500)
            except Exception:
                pass

            page.wait_for_timeout(8000)
            for _ in range(4):
                try:
                    page.mouse.wheel(0, 2000)
                except Exception:
                    pass
                page.wait_for_timeout(900)

            offers = self._parse(captured, origin, destination, depart_date)
            if not offers:
                offers = self._parse_dom(page, origin, destination, depart_date)
            if not offers:
                self.debug_dump(page, f"empty_{depart_date}")
                raise RuntimeError("去哪儿未解析到有效价格（可先 python -m app.login qunar）")
            return offers

    def _parse(
        self,
        captured: list[dict[str, str]],
        origin: str,
        destination: str,
        depart_date: str,
    ) -> list[FlightOffer]:
        offers: list[FlightOffer] = []
        for item in captured:
            text = item.get("text") or ""
            offers.extend(self._from_json(text, origin, destination, depart_date))
        return self._dedupe(offers)

    def _from_json(
        self, text: str, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        obj: Any
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            m = re.search(r"^[^(]*\((\{.*\})\)\s*;?\s*$", text, re.S)
            if not m:
                return []
            try:
                obj = json.loads(m.group(1))
            except json.JSONDecodeError:
                return []

        offers: list[FlightOffer] = []

        def walk(n: Any) -> None:
            if isinstance(n, dict):
                offer = self._from_flight_node(n, origin, destination, depart_date)
                if offer:
                    offers.append(offer)
                for v in n.values():
                    walk(v)
            elif isinstance(n, list):
                for v in n:
                    walk(v)

        walk(obj)
        return offers

    def _from_flight_node(
        self,
        n: dict[str, Any],
        origin: str,
        destination: str,
        depart_date: str,
    ) -> FlightOffer | None:
        binfo = n.get("binfo") if isinstance(n.get("binfo"), dict) else {}
        # Connection legs: binfo1 / binfo2 ...
        binfs: list[dict[str, Any]] = []
        if binfo:
            binfs.append(binfo)
        for i in range(1, 5):
            bi = n.get(f"binfo{i}")
            if isinstance(bi, dict):
                binfs.append(bi)

        flight_no = (
            n.get("code")
            or n.get("flightNo")
            or n.get("flightnum")
            or (binfs[0].get("flightNo") if binfs else None)
            or ""
        )
        flight_no = str(flight_no or "").strip()

        price = None
        for k in ("minPrice", "barePrice", "price", "totalPrice", "tprice"):
            if n.get(k) is None:
                continue
            try:
                price = float(n[k])
            except (TypeError, ValueError):
                continue
            break
        if price is None or not (100 <= price <= 50000):
            return None

        # Require flight identity — skip bare calendar/price nodes
        if not flight_no and not binfs:
            return None
        if not flight_no and not (
            binfo.get("depTime") or binfo.get("arrTime") or n.get("depTime")
        ):
            return None

        airline = (
            n.get("airs")
            or n.get("airline")
            or n.get("airCompany")
            or n.get("airsName")
            or (binfs[0].get("airsName") if binfs else "")
            or (binfs[0].get("carrier") if binfs else "")
            or ""
        )
        if isinstance(airline, list):
            airline = ",".join(str(x) for x in airline)
        airline, flight_no = enrich_offer_fields(
            airline=str(airline or ""), flight_no=flight_no
        )

        first = binfs[0] if binfs else {}
        last = binfs[-1] if binfs else {}
        dep_time = normalize_hhmm(
            first.get("depTime")
            or n.get("depTime")
            or n.get("btime")
            or n.get("departureTime")
        )
        arr_time = normalize_hhmm(
            last.get("arrTime")
            or n.get("arrTime")
            or n.get("etime")
            or n.get("arrivalTime")
        )
        duration_min = parse_duration_min(
            first.get("flightTime")
            or n.get("flightTime")
            or n.get("duration")
            or n.get("totalTime")
        )
        aircraft = str(
            first.get("flightType")
            or first.get("planeType")
            or n.get("flightType")
            or ""
        )
        stops = 0
        if "/" in flight_no:
            stops = max(0, flight_no.count("/"))
        elif n.get("flightType") in ("transfer", "transit", "ZZ", "ZH"):
            stops = 1
        elif n.get("transCity") or n.get("transferDur"):
            stops = 1

        seats = str(n.get("showCabin") or n.get("remain") or n.get("quantity") or "")

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
            seats_hint=seats,
            aircraft=aircraft,
        )

    def _parse_dom(
        self, page: Any, origin: str, destination: str, depart_date: str
    ) -> list[FlightOffer]:
        try:
            rows = page.evaluate(
                """() => {
                  const sels = [
                    '.e-airfly', '.m-airfly', '[class*="airfly"]',
                    '.list-item', '[class*="flight-item"]'
                  ];
                  let nodes = [];
                  for (const s of sels) {
                    nodes = Array.from(document.querySelectorAll(s));
                    if (nodes.length) break;
                  }
                  return nodes.slice(0, 50).map(n => (n.innerText || '').trim()).filter(t => t.length > 10);
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
            nos = re.findall(
                r"\b([A-Z0-9]{2}\d{3,4}(?:\s*/\s*[A-Z0-9]{2}\d{3,4})*)\b", text
            )
            times = re.findall(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", text)
            airline, flight_no = enrich_offer_fields(
                flight_no=(nos[0].replace(" ", "") if nos else "")
            )
            dep = f"{int(times[0][0]):02d}:{times[0][1]}" if len(times) >= 1 else ""
            arr = f"{int(times[1][0]):02d}:{times[1][1]}" if len(times) >= 2 else ""
            if not flight_no and not dep:
                continue
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
                    stops=1 if flight_no.count("/") else 0,
                )
            )
        if offers:
            return self._dedupe(offers)

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
            if o.flight_no or o.depart_time:
                key = (o.flight_no, o.depart_time, round(o.price))
                prev = best.get(key)
                if prev is None or o.price < prev.price:
                    # Prefer richer rows
                    if prev and (prev.airline and not o.airline):
                        continue
                    best[key] = o
            else:
                bare.append(o)
        result = list(best.values())
        if result:
            result.sort(key=lambda x: x.price)
            return result
        if bare:
            return [min(bare, key=lambda x: x.price)]
        return []
