"""Airline IATA code helpers."""
from __future__ import annotations

import re

# Common China domestic airline codes → short Chinese name
AIRLINE_NAMES: dict[str, str] = {
    "CA": "国航",
    "CZ": "南航",
    "MU": "东航",
    "HU": "海航",
    "3U": "川航",
    "SC": "山航",
    "MF": "厦航",
    "ZH": "深航",
    "FM": "上航",
    "9C": "春秋",
    "HO": "吉祥",
    "KN": "联航",
    "G5": "华夏",
    "GS": "天津航",
    "JD": "首都航",
    "PN": "西部航",
    "EU": "成都航",
    "8L": "祥鹏",
    "AQ": "九元",
    "GY": "多彩贵州",
    "DR": "瑞丽",
    "UQ": "乌航",
    "TV": "西藏航",
    "NS": "河北航",
    "FU": "福州航",
    "CN": "大新华",
    "BK": "奥凯",
    "QW": "青岛航",
    "KY": "昆航",
    "GJ": "长龙",
    "Y8": "金鹏",
    "A6": "湖南航",
    "LT": "龙江",
    "GX": "北部湾",
    "RY": "江西航",
    "GT": "桂林航",
    "9H": "长安航",
}


_FLIGHT_NO_RE = re.compile(r"([A-Z0-9]{2})\s*\d{2,4}", re.I)


def airline_from_flight_no(flight_no: str) -> str:
    """Infer airline short name from first flight number code."""
    if not flight_no:
        return ""
    # Prefer first leg for connections: MU8174/MU6107
    first = str(flight_no).split("/")[0].strip().upper()
    m = _FLIGHT_NO_RE.match(first.replace(" ", ""))
    if not m:
        # bare code like MU8174 without regex? try first 2 chars if alphanumeric
        code = "".join(ch for ch in first if ch.isalnum())[:2]
    else:
        code = m.group(1).upper()
    return AIRLINE_NAMES.get(code, "")


def normalize_hhmm(value: object) -> str:
    """Normalize various datetime strings to HH:MM."""
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    # 2026-09-20 08:10:00 / 2026-09-20 08:10 / 08:10
    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"
    return ""


def duration_from_hhmm(dep: str, arr: str) -> int | None:
    """Estimate duration minutes from HH:MM (supports +1 day)."""
    dep_t = normalize_hhmm(dep)
    arr_t = normalize_hhmm(arr)
    if not dep_t or not arr_t:
        return None
    try:
        dh, dm = map(int, dep_t.split(":"))
        ah, am = map(int, arr_t.split(":"))
    except ValueError:
        return None
    start = dh * 60 + dm
    end = ah * 60 + am
    if end < start:
        end += 24 * 60
    dur = end - start
    return dur if dur > 0 else None


def parse_duration_min(value: object) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        if v <= 0:
            return None
        # ms timestamps mistakenly used as duration
        if v > 10000:
            return int(v // 60000)
        return int(v)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return int(s) if int(s) > 0 else None
    h = re.search(r"(\d+)\s*小时", s)
    m = re.search(r"(\d+)\s*分", s)
    if h or m:
        return (int(h.group(1)) if h else 0) * 60 + (int(m.group(1)) if m else 0)
    # 5h30m / 5:30
    hm = re.search(r"(\d+)\s*[hH小时]\s*(\d+)?", s)
    if hm:
        return int(hm.group(1)) * 60 + (int(hm.group(2)) if hm.group(2) else 0)
    colon = re.fullmatch(r"(\d{1,2}):(\d{2})", s)
    if colon:
        return int(colon.group(1)) * 60 + int(colon.group(2))
    return None


def enrich_offer_fields(
    *,
    airline: str = "",
    flight_no: str = "",
) -> tuple[str, str]:
    airline = (airline or "").strip()
    flight_no = (flight_no or "").strip()
    if not airline and flight_no:
        airline = airline_from_flight_no(flight_no)
    return airline, flight_no
