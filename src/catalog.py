"""Custom stock categories and tickers (admin-managed catalog)."""

from __future__ import annotations

import json
import re
import secrets
import threading
from pathlib import Path
from typing import Any, Optional

import pandas as pd

from src.fetch_holdings import blank_membership

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CATALOG_PATH = DATA_DIR / "catalog.json"

TICKER_RE = re.compile(r"^\d{4,6}$")
_LOCK = threading.Lock()

DEFAULT_CATALOG: dict[str, Any] = {
    "categories": [
        {
            "id": "watchlist",
            "name": "自選",
            "note": "手動新增的觀察標的",
        }
    ],
    "stocks": [],
}


def _empty_catalog() -> dict[str, Any]:
    return {
        "categories": [dict(c) for c in DEFAULT_CATALOG["categories"]],
        "stocks": [],
        "excluded": [],
    }


def _normalize(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _empty_catalog()
    cats = data.get("categories") or []
    stocks = data.get("stocks") or []
    out_cats: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for c in cats:
        if not isinstance(c, dict):
            continue
        cid = str(c.get("id") or "").strip()
        name = str(c.get("name") or "").strip()
        if not cid or not name or cid in seen_ids:
            continue
        seen_ids.add(cid)
        out_cats.append({"id": cid, "name": name, "note": str(c.get("note") or "").strip()})
    if not out_cats:
        out_cats = [dict(c) for c in DEFAULT_CATALOG["categories"]]

    valid_ids = {c["id"] for c in out_cats}
    out_stocks: list[dict[str, Any]] = []
    seen_t: set[str] = set()
    for s in stocks:
        if not isinstance(s, dict):
            continue
        ticker = normalize_ticker(s.get("ticker"))
        if not ticker or ticker in seen_t:
            continue
        seen_t.add(ticker)
        ids = [i for i in (s.get("category_ids") or []) if isinstance(i, str) and i in valid_ids]
        out_stocks.append(
            {
                "ticker": ticker,
                "name": str(s.get("name") or "").strip(),
                "category_ids": ids,
            }
        )
    excluded: list[str] = []
    seen_ex: set[str] = set()
    for raw in data.get("excluded") or []:
        ticker = normalize_ticker(raw)
        if not ticker or ticker in seen_ex:
            continue
        seen_ex.add(ticker)
        excluded.append(ticker)
    return {"categories": out_cats, "stocks": out_stocks, "excluded": excluded}


def normalize_ticker(value: Any) -> str:
    raw = str(value or "").strip().upper().replace(".TW", "").replace(".TWO", "")
    raw = re.sub(r"\D", "", raw)
    if not TICKER_RE.fullmatch(raw):
        return ""
    return raw.zfill(4) if len(raw) <= 4 else raw


def load_catalog() -> dict[str, Any]:
    with _LOCK:
        if not CATALOG_PATH.exists():
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            data = _empty_catalog()
            CATALOG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return data
        try:
            data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = _empty_catalog()
        return _normalize(data)


def save_catalog(data: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize(data)
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        CATALOG_PATH.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return normalized


def _slug(name: str) -> str:
    ascii_part = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    suffix = secrets.token_hex(2)
    return f"{ascii_part}-{suffix}" if ascii_part else f"cat-{suffix}"


def add_category(name: str, note: str = "") -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("分類名稱不可空白")
    data = load_catalog()
    if any(c["name"] == name for c in data["categories"]):
        raise ValueError(f"分類「{name}」已存在")
    item = {"id": _slug(name), "name": name, "note": note.strip()}
    data["categories"].append(item)
    save_catalog(data)
    return item


def update_category(cat_id: str, name: Optional[str] = None, note: Optional[str] = None) -> dict[str, Any]:
    data = load_catalog()
    target = next((c for c in data["categories"] if c["id"] == cat_id), None)
    if not target:
        raise KeyError("找不到分類")
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("分類名稱不可空白")
        if any(c["name"] == name and c["id"] != cat_id for c in data["categories"]):
            raise ValueError(f"分類「{name}」已存在")
        target["name"] = name
    if note is not None:
        target["note"] = note.strip()
    save_catalog(data)
    return target


def delete_category(cat_id: str) -> None:
    data = load_catalog()
    if not any(c["id"] == cat_id for c in data["categories"]):
        raise KeyError("找不到分類")
    if len(data["categories"]) <= 1:
        raise ValueError("至少需保留一個分類")
    data["categories"] = [c for c in data["categories"] if c["id"] != cat_id]
    for s in data["stocks"]:
        s["category_ids"] = [i for i in s["category_ids"] if i != cat_id]
    save_catalog(data)


def add_stock(ticker: str, name: str = "", category_ids: Optional[list[str]] = None) -> dict[str, Any]:
    ticker = normalize_ticker(ticker)
    if not ticker:
        raise ValueError("股票代碼需為 4～6 位數字")
    data = load_catalog()
    if any(s["ticker"] == ticker for s in data["stocks"]):
        raise ValueError(f"{ticker} 已在名單中")
    valid = {c["id"] for c in data["categories"]}
    ids = [i for i in (category_ids or []) if i in valid]
    item = {"ticker": ticker, "name": name.strip(), "category_ids": ids}
    data["stocks"].append(item)
    save_catalog(data)
    return item


def update_stock(
    ticker: str,
    name: Optional[str] = None,
    category_ids: Optional[list[str]] = None,
) -> dict[str, Any]:
    ticker = normalize_ticker(ticker)
    data = load_catalog()
    target = next((s for s in data["stocks"] if s["ticker"] == ticker), None)
    if not target:
        raise KeyError("找不到股票")
    if name is not None:
        target["name"] = name.strip()
    if category_ids is not None:
        valid = {c["id"] for c in data["categories"]}
        target["category_ids"] = [i for i in category_ids if i in valid]
    save_catalog(data)
    return target


def exclude_stock(ticker: str) -> str:
    """Hide a ticker from the screener until the user adds it again."""
    ticker = normalize_ticker(ticker)
    if not ticker:
        raise ValueError("股票代碼需為 4～6 位數字")
    data = load_catalog()
    excluded = list(data.get("excluded") or [])
    if ticker not in excluded:
        excluded.append(ticker)
    data["excluded"] = excluded
    data["stocks"] = [s for s in data["stocks"] if s["ticker"] != ticker]
    save_catalog(data)
    return ticker


def clear_exclusion(ticker: str) -> None:
    ticker = normalize_ticker(ticker)
    if not ticker:
        return
    data = load_catalog()
    data["excluded"] = [t for t in (data.get("excluded") or []) if t != ticker]
    save_catalog(data)


def delete_stock(ticker: str) -> None:
    ticker = normalize_ticker(ticker)
    data = load_catalog()
    before = len(data["stocks"])
    data["stocks"] = [s for s in data["stocks"] if s["ticker"] != ticker]
    if len(data["stocks"]) == before:
        raise KeyError("找不到股票")
    save_catalog(data)


def apply_catalog_to_universe(df: pd.DataFrame) -> pd.DataFrame:
    """Attach category tags and append custom tickers not already in the ETF universe."""
    catalog = load_catalog()
    cat_by_id = {c["id"]: c["name"] for c in catalog["categories"]}
    stock_map = {s["ticker"]: s for s in catalog["stocks"]}
    excluded = set(catalog.get("excluded") or [])

    rows = df.to_dict(orient="records") if not df.empty else []
    rows = [r for r in rows if normalize_ticker(r.get("ticker")) not in excluded]
    seen = {str(r.get("ticker", "")).zfill(4) for r in rows}

    for r in rows:
        t = str(r.get("ticker", "")).zfill(4)
        r["ticker"] = t
        extra = stock_map.get(t)
        ids = list(extra.get("category_ids") or []) if extra else []
        r["category_ids"] = ids
        r["category_names"] = [cat_by_id[i] for i in ids if i in cat_by_id]
        r["custom"] = False
        if extra and extra.get("name") and not r.get("name"):
            r["name"] = extra["name"]

    for s in catalog["stocks"]:
        t = s["ticker"]
        if t in seen or t in excluded:
            continue
        ids = list(s.get("category_ids") or [])
        rows.append(
            {
                "ticker": t,
                "name": s.get("name") or t,
                **blank_membership(),
                "as_of_0050": None,
                "as_of_00919": None,
                "source_0050": None,
                "source_00919": None,
                "custom": True,
                "category_ids": ids,
                "category_names": [cat_by_id[i] for i in ids if i in cat_by_id],
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(["weight_max", "ticker"], ascending=[False, True]).reset_index(drop=True)
