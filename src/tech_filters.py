"""Optional technical filters the admin can toggle for long/short labels."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
SETTINGS_PATH = ROOT / "data" / "tech_filters.json"

# needs: row fields required before the filter can reject a name.
# Missing values pass, so older scans are not wiped before the next refresh.
TECH_CATALOG: list[dict[str, Any]] = [
    {
        "id": "rsi",
        "group": "動能",
        "name": "RSI(14) 區間",
        "desc": "作多：RSI ≤ 前台作多上限；作空：RSI ≥ 前台作空下限。",
        "needs": ["rsi14"],
        "default": True,
    },
    {
        "id": "macd_cross",
        "group": "動能",
        "name": "MACD 金叉／死叉",
        "desc": "作多：MACD 在訊號線之上；作空：MACD 在訊號線之下。",
        "needs": ["macd", "macd_signal"],
        "default": False,
    },
    {
        "id": "macd_hist",
        "group": "動能",
        "name": "MACD 柱狀轉強／轉弱",
        "desc": "作多：柱狀為正，且較前一日放大；作空：柱狀為負，且較前一日縮小。",
        "needs": ["macd_hist"],
        "default": False,
    },
    {
        "id": "kd",
        "group": "動能",
        "name": "KD 交叉",
        "desc": "作多：K > D 且 K < 80；作空：K < D 且 K > 20。",
        "needs": ["k9", "d9"],
        "default": False,
    },
    {
        "id": "ma_align_s",
        "group": "均線",
        "name": "短均線多空排列（5／10／20／30）",
        "desc": "作多：MA5 > MA10 > MA20 > MA30；作空：反向空頭排列。",
        "needs": ["ma5", "ma10", "ma20", "ma30"],
        "default": False,
    },
    {
        "id": "ma_align_m",
        "group": "均線",
        "name": "中均線多空排列（10／20／60／90）",
        "desc": "作多：MA10 > MA20 > MA60 > MA90；作空：反向空頭排列。",
        "needs": ["ma10", "ma20", "ma60", "ma90"],
        "default": False,
    },
    {
        "id": "price_ma",
        "group": "均線",
        "name": "收盤站上／跌破均線",
        "desc": "作多：收盤高於 MA20 與 MA60；作空：收盤低於 MA20 與 MA60。",
        "needs": ["price", "ma20", "ma60"],
        "default": False,
    },
    {
        "id": "bias_ma20",
        "group": "均線",
        "name": "MA20 乖離",
        "desc": "作多：收盤在 MA20 的 -3%～+2%（未追高）；作空：收盤高於 MA20 至少 5%。",
        "needs": ["price", "ma20"],
        "default": False,
    },
    {
        "id": "bb_mid",
        "group": "通道與量價",
        "name": "布林中軌",
        "desc": "作多：收盤不高於布林中軌；作空：收盤不低於布林中軌。",
        "needs": ["price", "bb_mid"],
        "default": False,
    },
    {
        "id": "volume",
        "group": "通道與量價",
        "name": "量能放大",
        "desc": "成交量至少為 20 日均量的 1.2 倍。作多與作空都要有量。",
        "needs": ["vol_ratio"],
        "default": False,
    },
    {
        "id": "breakout_20",
        "group": "通道與量價",
        "name": "20 日高低",
        "desc": "作多：收盤接近或突破 20 日高；作空：收盤接近或跌破 20 日低。",
        "needs": ["price", "high_20", "low_20"],
        "default": False,
    },
    {
        "id": "atr_calm",
        "group": "通道與量價",
        "name": "波動未過度擴張",
        "desc": "ATR(14) 不超過收盤價的 4%。作多與作空都套用。",
        "needs": ["price", "atr14"],
        "default": False,
    },
]

_IDS = {item["id"] for item in TECH_CATALOG}
_ALIASES = {"ma_align": ("ma_align_s", "ma_align_m")}


def catalog_public() -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "group": item["group"],
            "name": item["name"],
            "desc": item["desc"],
            "needs": list(item["needs"]),
            "default": bool(item["default"]),
        }
        for item in TECH_CATALOG
    ]


def default_enabled() -> list[str]:
    return [item["id"] for item in TECH_CATALOG if item["default"]]


def _expand(ids: list[Any]) -> list[str]:
    out: list[str] = []
    for raw in ids:
        key = str(raw)
        out.extend(_ALIASES.get(key, (key,)))
    return out


def _clean(ids: list[Any]) -> list[str]:
    wanted = set(_expand(ids))
    seen: set[str] = set()
    ordered: list[str] = []
    for item in TECH_CATALOG:
        if item["id"] in wanted and item["id"] not in seen:
            seen.add(item["id"])
            ordered.append(item["id"])
    return ordered


def load_enabled() -> list[str]:
    if not SETTINGS_PATH.exists():
        return default_enabled()
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_enabled()
    raw = data.get("enabled") if isinstance(data, dict) else None
    if not isinstance(raw, list):
        return default_enabled()
    return _clean([str(x) for x in raw])


def save_enabled(ids: list[Any]) -> list[str]:
    cleaned = _clean([str(x) for x in ids])
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps({"enabled": cleaned}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return cleaned


def parse_filter_list(raw: str) -> tuple[str, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    unknown = [p for p in parts if p not in _IDS]
    if unknown:
        known = ", ".join(item["id"] for item in TECH_CATALOG)
        raise ValueError(f"unknown tech filter: {', '.join(unknown)} (known: {known})")
    return tuple(_clean(parts))


def row_num(row: Any, key: str) -> Optional[float]:
    try:
        if isinstance(row, dict):
            if key not in row:
                return None
            value = row[key]
        else:
            if key not in getattr(row, "index", ()):
                return None
            value = row[key]
    except Exception:
        return None
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _ready_row(row: Any, keys: list[str]) -> bool:
    return all(row_num(row, key) is not None for key in keys)


def filter_pass(filter_id: str, side: str, row: Any, cfg: Any) -> Optional[bool]:
    """True/False when the row can be judged. None when required fields are missing."""
    spec = next((item for item in TECH_CATALOG if item["id"] == filter_id), None)
    if spec is None:
        return True
    if not _ready_row(row, spec["needs"]):
        return None

    price = row_num(row, "price")
    if filter_id == "rsi":
        rsi = row_num(row, "rsi14")
        assert rsi is not None
        if side == "long":
            return rsi <= float(getattr(cfg, "rsi_long_max", 55))
        return rsi >= float(getattr(cfg, "rsi_short_min", 65))

    if filter_id == "macd_cross":
        macd = row_num(row, "macd")
        signal = row_num(row, "macd_signal")
        assert macd is not None and signal is not None
        return macd > signal if side == "long" else macd < signal

    if filter_id == "macd_hist":
        hist = row_num(row, "macd_hist")
        prev = row_num(row, "macd_hist_prev")
        assert hist is not None
        if side == "long":
            return hist > 0 and (prev is None or hist > prev)
        return hist < 0 and (prev is None or hist < prev)

    if filter_id == "kd":
        k = row_num(row, "k9")
        d = row_num(row, "d9")
        assert k is not None and d is not None
        return (k > d and k < 80) if side == "long" else (k < d and k > 20)

    if filter_id in ("ma_align_s", "ma_align_m"):
        keys = spec["needs"]
        vals = [row_num(row, key) for key in keys]
        if any(v is None for v in vals):
            return None
        stacked = all(vals[i] > vals[i + 1] for i in range(len(vals) - 1))
        reversed_stack = all(vals[i] < vals[i + 1] for i in range(len(vals) - 1))
        return stacked if side == "long" else reversed_stack

    if filter_id == "price_ma":
        ma20 = row_num(row, "ma20")
        ma60 = row_num(row, "ma60")
        assert price is not None and ma20 is not None and ma60 is not None
        return (price > ma20 and price > ma60) if side == "long" else (price < ma20 and price < ma60)

    if filter_id == "bias_ma20":
        ma20 = row_num(row, "ma20")
        assert price is not None and ma20 is not None
        if ma20 == 0:
            return None
        bias = (price - ma20) / ma20
        return (-0.03 <= bias <= 0.02) if side == "long" else (bias >= 0.05)

    if filter_id == "bb_mid":
        mid = row_num(row, "bb_mid")
        assert price is not None and mid is not None
        return price <= mid if side == "long" else price >= mid

    if filter_id == "volume":
        vol = row_num(row, "vol_ratio")
        assert vol is not None
        return vol >= 1.2

    if filter_id == "breakout_20":
        high_20 = row_num(row, "high_20")
        low_20 = row_num(row, "low_20")
        assert price is not None and high_20 is not None and low_20 is not None
        return price >= high_20 * 0.995 if side == "long" else price <= low_20 * 1.005

    if filter_id == "atr_calm":
        atr = row_num(row, "atr14")
        assert price is not None and atr is not None
        if price == 0:
            return None
        return (atr / price) <= 0.04

    return True


def tech_hits(side: str, row: Any, cfg: Any) -> tuple[int, int]:
    """How many enabled filters pass, and how many could be judged."""
    enabled = getattr(cfg, "tech_filters", None) or ()
    passed = 0
    judged = 0
    for filter_id in enabled:
        verdict = filter_pass(str(filter_id), side, row, cfg)
        if verdict is None:
            continue
        judged += 1
        if verdict:
            passed += 1
    return passed, judged


def tech_passes(side: str, row: Any, cfg: Any) -> bool:
    """A side qualifies when at least half of the enabled filters pass.

    Requiring every filter at once drops the whole list: a pullback rule and
    a 20-day breakout cannot both be true. Missing inputs are skipped.
    """
    passed, judged = tech_hits(side, row, cfg)
    if judged == 0:
        return True
    return passed * 2 >= judged


def readiness(rows: list[dict[str, Any]]) -> dict[str, bool]:
    sample = rows[:40]
    out: dict[str, bool] = {}
    for item in TECH_CATALOG:
        out[item["id"]] = any(_ready_row(row, item["needs"]) for row in sample) if sample else False
    return out


def public_state(rows: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return {
        "enabled": load_enabled(),
        "filters": catalog_public(),
        "ready": readiness(rows or []),
    }
