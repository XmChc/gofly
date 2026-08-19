from __future__ import annotations

import json
import os
import random
import re
import time
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional

from app.providers import BaseProvider

DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/16.6 Mobile/15E148 Safari/604.1"
)


class PlaywrightProvider(BaseProvider):
    use_mobile: bool = False

    def _ua(self) -> str:
        if self.use_mobile:
            return self.config.get("mobile_user_agent") or MOBILE_UA
        return self.config.get("user_agent") or DESKTOP_UA

    def _user_data_dir(self) -> str:
        root = self.config.get("user_data_dir", "user_data")
        path = os.path.join(root, self.name)
        os.makedirs(path, exist_ok=True)
        return path

    @contextmanager
    def browser(self, headless: Optional[bool] = None) -> Iterator[Any]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError(
                "ctrip/qunar 需要 Playwright：pip install playwright && python -m playwright install chromium"
            ) from exc

        hl = self.config.get("headless", True) if headless is None else headless
        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                user_data_dir=self._user_data_dir(),
                headless=hl,
                user_agent=self._ua(),
                viewport={"width": 390, "height": 844}
                if self.use_mobile
                else {"width": 1366, "height": 900},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                is_mobile=self.use_mobile,
                has_touch=self.use_mobile,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            try:
                yield ctx
            finally:
                ctx.close()

    def attach_xhr(self, page: Any, patterns: List[str]) -> list[dict[str, str]]:
        captured: list[dict[str, str]] = []

        def on_response(resp: Any) -> None:
            try:
                url = resp.url
                if not any(p in url for p in patterns):
                    return
                text = resp.text()
                captured.append({"url": url, "text": text})
            except Exception:
                return

        page.on("response", on_response)
        return captured

    def timeout_ms(self) -> int:
        return int(self.config.get("timeout_seconds", 45)) * 1000

    def debug_dump(self, page: Any, tag: str) -> None:
        if not self.config.get("debug"):
            return
        debug_dir = self.config.get("debug_dir", "debug")
        os.makedirs(debug_dir, exist_ok=True)
        base = os.path.join(debug_dir, f"{self.name}_{tag}")
        try:
            page.screenshot(path=base + ".png", full_page=True)
        except Exception:
            pass
        try:
            with open(base + ".html", "w", encoding="utf-8") as f:
                f.write(page.content())
        except Exception:
            pass


def extract_generic_prices(text: str) -> list[int]:
    prices: list[int] = []
    for m in re.finditer(
        r'"(lowestPrice|salePrice|TotalPrice|displayPrice|cabinTotalPrice|minPrice|adultPrice)"\s*:\s*"?(\d{3,5})',
        text,
    ):
        prices.append(int(m.group(2)))
    if not prices:
        for m in re.finditer(r"[¥￥]\s*(\d{3,5})", text):
            prices.append(int(m.group(1)))
    return [p for p in prices if 100 <= p <= 50000]
