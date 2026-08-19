"""Free checked-baggage inference for China domestic fares.

Fliggy `mtop.trip.flight.flightSearch` list items currently have **no**
行李/托运/kg fields in `priceInfo`, `attributeShowMap`, `itemDatas`,
`transferInfo`, or `texts`. Cabin/OTA detail is a separate (rate-limited)
call per flight, so we do not fetch it during scans.

Behavior:
1. If any explicit baggage string/number appears, that wins (`source=api`).
2. Else airline base-fare policy (`source=airline_policy`):
   - LCC whose cheapest OTA fare typically has **no** free checked bag: 0kg
     (春秋 9C、九元 AQ、西部 PN).
   - Other known domestic airlines: 20kg economy allowance.
3. Transfers use the **strictest** (minimum) leg.
4. Unknown airline → `status=unknown`, `has_20kg=False`.
   Default UI filter hides unknown and <20kg.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from app.airlines import AIRLINE_NAMES

# Cheapest published fare usually has 0kg checked baggage.
NO_FREE_CHECKED: frozenset[str] = frozenset({"9C", "AQ", "PN"})

_KG_RE = re.compile(
    r"(?:免费)?(?:托运|行李(?:额)?)?\s*(\d+)\s*(?:KG|kg|公斤)",
    re.I,
)
_ZERO_RE = re.compile(
    r"无(?:免费)?(?:托运|行李)|不含(?:免费)?(?:托运|行李)|行李额\s*0|0\s*(?:KG|kg|公斤)",
    re.I,
)
_CARRY_ONLY_RE = re.compile(r"仅?(?:手提|舱内)", re.I)
_CODE_RE = re.compile(r"([A-Z0-9]{2})\d{2,4}", re.I)
_HINT_KEY = re.compile(r"bag|lugg|行李|托运|weight|allowance", re.I)


def iata_codes_from_text(*parts: object) -> list[str]:
    codes: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not part:
            continue
        s = str(part).upper().replace("-", "/").replace("_", "/")
        for token in re.split(r"[/\s,;+]+", s):
            token = token.strip()
            if not token:
                continue
            m = _CODE_RE.match(token)
            code = m.group(1).upper() if m else (token if len(token) == 2 else "")
            if code and code not in seen and re.fullmatch(r"[A-Z0-9]{2}", code):
                seen.add(code)
                codes.append(code)
    return codes


def _walk_hints(obj: Any, acc: list[str], depth: int = 0) -> None:
    if depth > 8 or obj is None:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if _HINT_KEY.search(str(k)):
                if isinstance(v, (str, int, float)):
                    acc.append(str(v))
                else:
                    _walk_hints(v, acc, depth + 1)
            else:
                _walk_hints(v, acc, depth + 1)
    elif isinstance(obj, list):
        for item in obj[:60]:
            _walk_hints(item, acc, depth + 1)
    elif isinstance(obj, str) and _HINT_KEY.search(obj):
        acc.append(obj)


def parse_explicit_kg(ds: dict[str, Any]) -> Optional[int]:
    """Return checked-baggage kg if Fliggy payload states it; else None."""
    hints: list[str] = []
    _walk_hints(ds, hints)
    if not hints:
        return None

    blob = " ".join(hints)
    if _ZERO_RE.search(blob) or _CARRY_ONLY_RE.search(blob):
        # Explicit zero / carry-on-only, unless a 托运Nkg is also present.
        checked = re.findall(r"托运\s*(\d+)\s*(?:KG|kg|公斤)", blob, flags=re.I)
        if checked:
            return max(int(x) for x in checked)
        return 0

    kgs: list[int] = []
    for h in hints:
        if _CARRY_ONLY_RE.search(h) and "托运" not in h:
            continue
        for m in _KG_RE.finditer(h):
            kgs.append(int(m.group(1)))
    if not kgs:
        return None
    # Ignore typical carry-on 5–10kg if a larger checked figure exists.
    checked_like = [n for n in kgs if n >= 15]
    return max(checked_like or kgs)


def _policy_kg(code: str) -> tuple[Optional[int], str]:
    code = (code or "").upper()
    if not code:
        return None, "unknown"
    if code in NO_FREE_CHECKED:
        return 0, "airline_policy"
    if code in AIRLINE_NAMES:
        return 20, "airline_policy"
    return None, "unknown"


def combine_leg_kg(codes: Iterable[str]) -> dict[str, Any]:
    statuses: list[str] = []
    kgs: list[int] = []
    source = "airline_policy"
    for code in codes:
        kg, src = _policy_kg(code)
        statuses.append(src)
        if kg is None:
            continue
        kgs.append(kg)
        if src == "unknown":
            source = "unknown"

    if not list(codes):
        return _pack(None, "unknown", "unknown")
    if any(s == "unknown" for s in statuses) and not kgs:
        return _pack(None, "unknown", "unknown")
    if any(s == "unknown" for s in statuses):
        # Mixed known+unknown: hide by default.
        return _pack(min(kgs) if kgs else None, "unknown", "unknown")
    return _pack(min(kgs) if kgs else None, source, "none" if (kgs and min(kgs) < 20) else "ok")


def _pack(kg: Optional[int], source: str, status_hint: str) -> dict[str, Any]:
    if kg is None:
        status = "unknown"
        has_20 = False
        text = "行李未知"
    elif kg >= 20:
        status = "ok"
        has_20 = True
        text = f"托运{kg}kg"
    else:
        status = "none"
        has_20 = False
        text = "不含托运" if kg <= 0 else f"托运{kg}kg"
    if status_hint == "unknown":
        status = "unknown"
        has_20 = False
        if kg is None:
            text = "行李未知"
    return {
        "baggage_kg": kg,
        "baggage_text": text,
        "baggage_source": source,
        "baggage_status": status,
        "has_20kg": has_20,
    }


def baggage_meta_for_item(
    ds: dict[str, Any],
    *,
    flight_no: str = "",
    extra_codes: Iterable[str] | None = None,
) -> dict[str, Any]:
    explicit = parse_explicit_kg(ds)
    if explicit is not None:
        packed = _pack(explicit, "api", "ok" if explicit >= 20 else "none")
        packed["baggage_source"] = "api"
        packed["has_20kg"] = explicit >= 20
        packed["baggage_status"] = "ok" if explicit >= 20 else "none"
        packed["baggage_text"] = f"托运{explicit}kg" if explicit > 0 else "不含托运"
        return packed

    codes = [str(c).upper() for c in (extra_codes or []) if c]
    codes.extend(iata_codes_from_text(flight_no))
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    return combine_leg_kg(uniq)
