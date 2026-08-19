"""交互登录：保存 Playwright 会话，供携程/去哪儿复用。

用法:
  .\\.venv\\Scripts\\python.exe -m app.login ctrip
  .\\.venv\\Scripts\\python.exe -m app.login qunar
"""

from __future__ import annotations

import sys

from app.config import crawler_dict, get_config


LOGIN_URLS = {
    "ctrip": "https://flights.ctrip.com/online/channel/domestic",
    "qunar": "https://flight.qunar.com/",
}


def main(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args or args[0] not in LOGIN_URLS:
        print("用法: python -m app.login <ctrip|qunar>")
        return 1

    name = args[0]
    cfg = crawler_dict()
    # 强制可见浏览器
    cfg = {**cfg, "headless": False}

    if name == "ctrip":
        from app.providers.ctrip import CtripProvider

        provider = CtripProvider(cfg)
    else:
        from app.providers.qunar import QunarProvider

        provider = QunarProvider(cfg)

    url = LOGIN_URLS[name]
    print(f"打开 {name}：{url}")
    print("请在浏览器中完成登录，完成后回到终端按 Enter 保存会话。")
    with provider.browser(headless=False) as ctx:
        page = ctx.new_page()
        page.goto(url, wait_until="domcontentloaded")
        try:
            input(">>> 登录完成后按 Enter：")
        except EOFError:
            import time

            time.sleep(120)
    print(f"会话已保存到 user_data/{name}")
    print("可回到网页点击「扫描全部」或「重新扫描」。")
    _ = get_config()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
