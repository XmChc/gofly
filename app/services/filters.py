"""Per-route offer filters shared by UI defaults and push matching."""

from __future__ import annotations

import json
from typing import Any, Optional

# Matches frontend state.offerFilters defaults.
DEFAULT_FILTERS: dict[str, Any] = {
    "maxDuration": None,
    "sameDay": None,
    "bag20": True,
    "directOnly": None,
}


def normalize_filters(raw: Any) -> dict[str, Any]:
    """Normalize stored / API filter payload to a stable dict."""
    data: dict[str, Any] = {}
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {}
    elif isinstance(raw, dict):
        data = raw

    out = dict(DEFAULT_FILTERS)

    md = data.get("maxDuration", data.get("max_duration"))
    if md is None or md == "" or md is False:
        out["maxDuration"] = None
    else:
        try:
            n = int(md)
            out["maxDuration"] = n if n > 0 else None
        except (TypeError, ValueError):
            out["maxDuration"] = None

    sd = data.get("sameDay", data.get("same_day"))
    if sd is None or sd == "":
        out["sameDay"] = None
    elif isinstance(sd, bool):
        out["sameDay"] = sd
    elif str(sd) in ("1", "true", "True"):
        out["sameDay"] = True
    elif str(sd) in ("0", "false", "False"):
        out["sameDay"] = False
    else:
        out["sameDay"] = None

    bag = data.get("bag20", data.get("bag_20"))
    if bag is None:
        out["bag20"] = True
    elif isinstance(bag, bool):
        out["bag20"] = bag
    else:
        out["bag20"] = str(bag) in ("1", "true", "True")

    direct = data.get("directOnly", data.get("direct_only"))
    if direct is None or direct == "":
        out["directOnly"] = None
    elif isinstance(direct, bool):
        out["directOnly"] = direct
    elif str(direct) in ("1", "true", "True"):
        out["directOnly"] = True
    elif str(direct) in ("0", "false", "False"):
        out["directOnly"] = False
    else:
        out["directOnly"] = None

    return out


def filters_to_json(filters: Any) -> str:
    return json.dumps(normalize_filters(filters), ensure_ascii=False, separators=(",", ":"))


def _meta(offer: dict[str, Any]) -> dict[str, Any]:
    m = offer.get("meta")
    if isinstance(m, dict):
        return m
    if isinstance(m, str) and m.strip():
        try:
            parsed = json.loads(m)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _hhmm_minutes(raw: str) -> Optional[int]:
    s = str(raw or "").strip()
    if len(s) >= 5 and s[-5] == ":":
        s = s[-5:]
    if ":" not in s:
        return None
    try:
        h, m = s.split(":", 1)
        return int(h) * 60 + int(m)
    except (TypeError, ValueError):
        return None


def offer_duration_min(offer: dict[str, Any]) -> Optional[int]:
    d = offer.get("duration_min")
    try:
        n = int(d) if d is not None else 0
        if n > 0:
            return n
    except (TypeError, ValueError):
        pass
    dep = _hhmm_minutes(str(offer.get("depart_time") or ""))
    arr = _hhmm_minutes(str(offer.get("arrive_time") or ""))
    if dep is None or arr is None:
        return None
    delta = arr - dep
    if delta <= 0:
        delta += 24 * 60
    return delta


def is_same_day_arrival(offer: dict[str, Any]) -> bool:
    m = _meta(offer)
    try:
        cross = int(m.get("cross_days") or 0)
    except (TypeError, ValueError):
        cross = 0
    if cross > 0:
        return False
    if m.get("cross_days_label"):
        return False
    dep = _hhmm_minutes(str(offer.get("depart_time") or ""))
    arr = _hhmm_minutes(str(offer.get("arrive_time") or ""))
    if dep is not None and arr is not None:
        dur = offer_duration_min(offer)
        if arr < dep and dur is not None and dur > 8 * 60:
            return False
    return True


def offer_has_20kg(offer: dict[str, Any]) -> bool:
    m = _meta(offer)
    if m.get("has_20kg") is True and m.get("baggage_status") != "unknown":
        return True
    kg = m.get("baggage_kg")
    if kg is not None and kg != "":
        try:
            n = float(kg)
            status = m.get("baggage_status") or ("ok" if n >= 20 else "none")
            if status != "unknown" and n >= 20:
                return True
        except (TypeError, ValueError):
            pass
    if m.get("baggage_status") == "unknown" or m.get("has_20kg") is None:
        from app.baggage import combine_leg_kg, iata_codes_from_text

        codes = iata_codes_from_text(offer.get("flight_no") or "")
        packed = combine_leg_kg(codes)
        return bool(packed.get("has_20kg"))
    return False


def is_transfer_offer(offer: dict[str, Any]) -> bool:
    m = _meta(offer)
    if m.get("is_transfer") in (True, 1, "true", "1"):
        return True
    try:
        if int(offer.get("stops") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if "/" in str(offer.get("flight_no") or ""):
        return True
    if m.get("transfer_city") or m.get("transfer_flight_no"):
        return True
    return False


def offer_matches_filters(offer: dict[str, Any], filters: Any) -> bool:
    f = normalize_filters(filters)
    max_dur = f.get("maxDuration")
    if max_dur is not None:
        dur = offer_duration_min(offer)
        if dur is None or dur > int(max_dur):
            return False
    same_day = f.get("sameDay")
    if same_day is True and not is_same_day_arrival(offer):
        return False
    if same_day is False and is_same_day_arrival(offer):
        return False
    if f.get("bag20") and not offer_has_20kg(offer):
        return False
    direct_only = f.get("directOnly")
    if direct_only is True and is_transfer_offer(offer):
        return False
    if direct_only is False and not is_transfer_offer(offer):
        return False
    return True


def filter_offers(offers: list[dict[str, Any]], filters: Any) -> list[dict[str, Any]]:
    f = normalize_filters(filters)
    return [o for o in offers if offer_matches_filters(o, f)]
