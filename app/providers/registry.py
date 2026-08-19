from __future__ import annotations

from typing import Any

from app.providers import BaseProvider
from app.providers.ctrip import CtripProvider
from app.providers.fliggy import FliggyProvider
from app.providers.mock import BiasedMockProvider, MockProvider
from app.providers.qunar import QunarProvider

REAL_REGISTRY: dict[str, type[BaseProvider]] = {
    "mock": MockProvider,
    "fliggy": FliggyProvider,
    "ctrip": CtripProvider,
    "qunar": QunarProvider,
}


def build_providers(
    names: list[str], config: dict[str, Any], *, demo_multi: bool = False
) -> list[BaseProvider]:
    """
    demo_multi=True 且仅配置了 mock 时，展开为 mock/fliggy/ctrip/qunar 影子源，
    便于本地看多平台比价 UI。
    """
    providers: list[BaseProvider] = []
    normalized = [n.strip().lower() for n in names if n.strip()]
    if not normalized:
        normalized = ["mock"]

    if demo_multi and normalized == ["mock"]:
        for name in ("mock", "fliggy", "ctrip", "qunar"):
            providers.append(BiasedMockProvider(config, name))
        return providers

    for name in normalized:
        if name not in REAL_REGISTRY:
            raise ValueError(f"未知平台: {name}，可选: {list(REAL_REGISTRY)}")
        providers.append(REAL_REGISTRY[name](config))
    return providers
