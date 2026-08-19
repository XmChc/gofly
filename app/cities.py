"""国内城市名 ↔ OTA 城市三字码。

用户可输入「厦门」「乌鲁木齐」或 XMN / URC。
"""

from __future__ import annotations

# 首选城市码（携程/飞猪常用城市码，非严格机场 IATA）
CITY_CODES: dict[str, str] = {
    "北京": "BJS",
    "上海": "SHA",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "重庆": "CKG",
    "杭州": "HGH",
    "南京": "NKG",
    "武汉": "WUH",
    "西安": "SIA",
    "昆明": "KMG",
    "厦门": "XMN",
    "长沙": "CSX",
    "三亚": "SYX",
    "海口": "HAK",
    "青岛": "TAO",
    "大连": "DLC",
    "天津": "TSN",
    "沈阳": "SHE",
    "郑州": "CGO",
    "济南": "TNA",
    "福州": "FOC",
    "南宁": "NNG",
    "贵阳": "KWE",
    "合肥": "HFE",
    "南昌": "KHN",
    "宁波": "NGB",
    "温州": "WNZ",
    "无锡": "WUX",
    "常州": "CZX",
    "烟台": "YNT",
    "哈尔滨": "HRB",
    "长春": "CGQ",
    "兰州": "LHW",
    "乌鲁木齐": "URC",
    "银川": "INC",
    "西宁": "XNN",
    "丽江": "LJG",
    "大理": "DLU",
    "西双版纳": "JHG",
    "香格里拉": "DIG",
    "腾冲": "TCZ",
    "珠海": "ZUH",
    "揭阳": "SWA",
    "汕头": "SWA",
    "呼和浩特": "HET",
    "太原": "TYN",
    "石家庄": "SJW",
    "洛阳": "LYA",
    "万州": "WXN",
    "绵阳": "MIG",
    "宜昌": "YIH",
    "恩施": "ENH",
    "张家界": "DYG",
    "喀什": "KHG",
    "库尔勒": "KRL",
    "伊宁": "YIN",
    "阿克苏": "AKU",
    "和田": "HTN",
    "奎屯": "KJI",
    "哈密": "HMI",
    "拉萨": "LXA",
    "林芝": "LZY",
    "日喀则": "RKZ",
    "桂林": "KWL",
    "北海": "BHY",
    "柳州": "LZH",
    "泉州": "JJN",
    "武夷山": "WUS",
    "义乌": "YIW",
    "黄山": "TXN",
    "赣州": "KOW",
    "景德镇": "JDZ",
    "九江": "JIU",
    "宜春": "YIC",
    "上饶": "SQD",
    "徐州": "XUZ",
    "连云港": "LYG",
    "南通": "NTG",
    "盐城": "YNZ",
    "扬州": "YTY",
    "淮安": "HIA",
    "苏州": "SZV",
    "东莞": "DGM",
    "佛山": "FUO",
    "惠州": "HUZ",
    "湛江": "ZHA",
    "梅州": "MXZ",
    "襄阳": "XFN",
    "十堰": "WDS",
    "荆州": "SHS",
    "南阳": "NNY",
    "洛阳": "LYA",
    "运城": "YCU",
    "大同": "DAT",
    "长治": "CIH",
    "临汾": "LFQ",
    "包头": "BAV",
    "赤峰": "CIF",
    "通辽": "TGO",
    "海拉尔": "HLD",
    "满洲里": "NZH",
    "延吉": "YNJ",
    "牡丹江": "MDG",
    "齐齐哈尔": "NDG",
    "佳木斯": "JMU",
    "丹东": "DDG",
    "锦州": "JNZ",
    "营口": "YKH",
    "威海": "WEH",
    "临沂": "LYI",
    "济宁": "JNG",
    "潍坊": "WEF",
    "日照": "RIZ",
    "东营": "DOY",
    "遵义": "ZYI",
    "铜仁": "TEN",
    "兴义": "ACX",
    "安顺": "AVA",
    "毕节": "BFJ",
    "丽水": "LIW",
    "衢州": "JUZ",
    "台州": "HYN",
    "舟山": "HSN",
    "嘉兴": "HGH",
    "绍兴": "HGH",
    "湖州": "HGH",
    "中卫": "ZHY",
    "固原": "GYU",
    "嘉峪关": "JGN",
    "敦煌": "DNH",
    "张掖": "YZY",
    "天水": "THQ",
    "榆林": "UYN",
    "延安": "ENY",
    "汉中": "HZG",
    "安康": "AKA",
    "西昌": "XIC",
    "攀枝花": "PZI",
    "南充": "NAO",
    "达州": "DAX",
    "宜宾": "YBP",
    "泸州": "LZO",
    "广元": "GYS",
    "九寨沟": "JZH",
    "稻城": "DCY",
    "康定": "KGT",
    "保山": "BSD",
    "芒市": "LUM",
    "昭通": "ZAT",
    "普洱": "SYM",
    "临沧": "LNJ",
    "文山": "WNH",
    "迪庆": "DIG",
    "银川": "INC",
    "鄂尔多斯": "DSN",
    "乌海": "WUA",
    "锡林浩特": "XIL",
    "阿拉善左旗": "AXF",
    "景德镇": "JDZ",
    "井冈山": "JGS",
    "赣州": "KOW",
    "吉安": "KNC",
    "常德": "CGD",
    "怀化": "HJJ",
    "邵阳": "WGN",
    "永州": "LLF",
    "衡阳": "HNY",
    "岳阳": "YYA",
    "琼海": "BAR",
    "三沙": "XYI",
    "香港": "HKG",
    "澳门": "MFM",
    "台北": "TPE",
}

# 别名 / 口语 → 标准城市名
ALIASES: dict[str, str] = {
    "帝都": "北京",
    "魔都": "上海",
    "鹭岛": "厦门",
    "春城": "昆明",
    "羊城": "广州",
    "鹏城": "深圳",
    "山城": "重庆",
    "蓉城": "成都",
    "星城": "长沙",
    "榕城": "福州",
    "冰城": "哈尔滨",
    "泉城": "济南",
    "江城": "武汉",
    "凤凰城": "凤凰古城",
    "乌市": "乌鲁木齐",
    "乌鲁木齐市": "乌鲁木齐",
    "喀什市": "喀什",
    "喀什地区": "喀什",
    "南昌市": "南昌",
    "厦门市": "厦门",
    "北京市": "北京",
    "上海市": "上海",
    "广州市": "广州",
    "深圳市": "深圳",
    "成都市": "成都",
    "重庆市": "重庆",
    "杭州市": "杭州",
    "南京市": "南京",
    "武汉市": "武汉",
    "西安市": "西安",
    "昆明市": "昆明",
    "长沙市": "长沙",
    "合肥市": "合肥",
    "福州市": "福州",
    "济南市": "济南",
    "青岛市": "青岛",
    "大连市": "大连",
    "沈阳市": "沈阳",
    "哈尔滨市": "哈尔滨",
    "长春市": "长春",
    "郑州市": "郑州",
    "太原市": "太原",
    "石家庄市": "石家庄",
    "呼和浩特市": "呼和浩特",
    "南宁市": "南宁",
    "贵阳市": "贵阳",
    "兰州市": "兰州",
    "西宁市": "西宁",
    "银川市": "银川",
    "拉萨市": "拉萨",
    "海口市": "海口",
    "三亚市": "三亚",
    "丽江市": "丽江",
    "大理市": "大理",
    "揭阳市": "揭阳",
    "潮汕": "揭阳",
    "西双版纳州": "西双版纳",
    "西双版纳傣族自治州": "西双版纳",
}

# 三字码 → 展示名（含机场码映射到城市）
CITY_NAMES: dict[str, str] = {
    "BJS": "北京",
    "PEK": "北京",
    "PKX": "北京",
    "SHA": "上海",
    "PVG": "上海",
    "CAN": "广州",
    "SZX": "深圳",
    "CTU": "成都",
    "TFU": "成都",
    "CKG": "重庆",
    "HGH": "杭州",
    "NKG": "南京",
    "WUH": "武汉",
    "XIY": "西安",
    "SIA": "西安",
    "KMG": "昆明",
    "XMN": "厦门",
    "CSX": "长沙",
    "SYX": "三亚",
    "HAK": "海口",
    "TAO": "青岛",
    "DLC": "大连",
    "TSN": "天津",
    "SHE": "沈阳",
    "CGO": "郑州",
    "TNA": "济南",
    "FOC": "福州",
    "NNG": "南宁",
    "KWE": "贵阳",
    "HFE": "合肥",
    "KHN": "南昌",
    "NGB": "宁波",
    "WNZ": "温州",
    "WUX": "无锡",
    "CZX": "常州",
    "YNT": "烟台",
    "HRB": "哈尔滨",
    "CGQ": "长春",
    "LHW": "兰州",
    "URC": "乌鲁木齐",
    "INC": "银川",
    "XNN": "西宁",
    "LJG": "丽江",
    "DLU": "大理",
    "JHG": "西双版纳",
    "DIG": "香格里拉",
    "TCZ": "腾冲",
    "ZUH": "珠海",
    "SWA": "揭阳",
    "HET": "呼和浩特",
    "TYN": "太原",
    "SJW": "石家庄",
    "LYA": "洛阳",
    "WXN": "万州",
    "MIG": "绵阳",
    "YIH": "宜昌",
    "ENH": "恩施",
    "DYG": "张家界",
    "KHG": "喀什",
    "KRL": "库尔勒",
    "YIN": "伊宁",
    "AKU": "阿克苏",
    "HTN": "和田",
    "HMI": "哈密",
    "LXA": "拉萨",
    "KWL": "桂林",
    "BHY": "北海",
    "JJN": "泉州",
    "YIW": "义乌",
    "XUZ": "徐州",
    "NTG": "南通",
    "DSN": "鄂尔多斯",
    "HLD": "海拉尔",
    "WEH": "威海",
    "LYI": "临沂",
    "XIC": "西昌",
    "BSD": "保山",
    "LUM": "芒市",
    "DCY": "稻城",
    "JZH": "九寨沟",
    "HKG": "香港",
    "MFM": "澳门",
    "TPE": "台北",
}

# 保证 CITY_CODES 里的码都能反查到名字
for _name, _code in CITY_CODES.items():
    CITY_NAMES.setdefault(_code, _name)


class CityResolveError(ValueError):
    pass


def _normalize_label(raw: str) -> str:
    s = (raw or "").strip()
    for ch in (" ", "\t", "　", "-", "—", "–"):
        s = s.replace(ch, "")
    # 常见后缀
    for suffix in ("国际机场", "机场", "地区", "自治州", "市", "县", "区"):
        if len(s) > 2 and s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s


def city_name(code: str) -> str:
    return CITY_NAMES.get((code or "").upper(), (code or "").upper())


def resolve_city(raw: str) -> tuple[str, str]:
    """把用户输入解析为 (城市码, 中文名)。支持中文名 / 别名 / 三字码。"""
    text = (raw or "").strip()
    if not text:
        raise CityResolveError("城市不能为空")

    # 三字码
    if len(text) == 3 and text.isascii() and text.isalpha():
        code = text.upper()
        name = CITY_NAMES.get(code)
        if not name:
            raise CityResolveError(f"未识别城市码：{code}")
        # 统一到首选城市码（如 PEK→BJS）
        preferred = CITY_CODES.get(name, code)
        return preferred, name

    label = _normalize_label(text)
    label = ALIASES.get(label, label)
    label = ALIASES.get(label, label)

    code = CITY_CODES.get(label)
    if code:
        return code, label

    # 模糊：包含匹配（输入「乌鲁木」也能命中）
    candidates = [n for n in CITY_CODES if label in n or n in label]
    if len(candidates) == 1:
        name = candidates[0]
        return CITY_CODES[name], name
    if len(candidates) > 1:
        # 优先完全相等已处理；取最短名称（更精确）
        name = min(candidates, key=len)
        if label in name or name.startswith(label):
            return CITY_CODES[name], name
        raise CityResolveError(
            f"「{text}」匹配到多个城市：{'、'.join(candidates[:6])}，请写全称"
        )

    raise CityResolveError(f"未识别城市：「{text}」。请用中文城市名，如 厦门、乌鲁木齐")


def resolve_route_names(
    origin: str,
    destination: str,
    origin_name: str = "",
    destination_name: str = "",
) -> tuple[str, str]:
    o = (origin or "").upper()
    d = (destination or "").upper()
    return (
        (origin_name or "").strip() or city_name(o),
        (destination_name or "").strip() or city_name(d),
    )


def resolve_route_inputs(origin_raw: str, destination_raw: str) -> dict[str, str]:
    o_code, o_name = resolve_city(origin_raw)
    d_code, d_name = resolve_city(destination_raw)
    if o_code == d_code:
        raise CityResolveError("出发地与目的地不能相同")
    return {
        "origin": o_code,
        "origin_name": o_name,
        "destination": d_code,
        "destination_name": d_name,
    }


def city_catalog() -> list[dict[str, str]]:
    """前端自动完成用：按中文名排序。"""
    items = [{"name": name, "code": code} for name, code in CITY_CODES.items()]
    items.sort(key=lambda x: x["name"])
    return items


def suggest_cities(q: str, limit: int = 12) -> list[dict[str, str]]:
    qn = _normalize_label(q)
    if not qn:
        return city_catalog()[:limit]
    qn = ALIASES.get(qn, qn)
    scored: list[tuple[int, str, str]] = []
    for name, code in CITY_CODES.items():
        if name.startswith(qn):
            scored.append((0, name, code))
        elif qn in name:
            scored.append((1, name, code))
        elif name in qn and len(name) >= 2:
            scored.append((2, name, code))
    scored.sort(key=lambda x: (x[0], len(x[1]), x[1]))
    # 去重
    seen = set()
    out = []
    for _, name, code in scored:
        if name in seen:
            continue
        seen.add(name)
        out.append({"name": name, "code": code})
        if len(out) >= limit:
            break
    return out
