"""Fetch constituent holdings for the screener universe (auto, with cache)."""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "output"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

YUANTA_BRIDGE = "https://etfapi.yuantaetfs.com/ectranslation/api/bridge"
CAPITAL_PORTFOLIO = "https://www.capitalfund.com.tw/etf/product/detail/195/portfolio"
CATHAY_API = "https://cwapi.cathaysite.com.tw/api/ETF/"
EZMONEY_PCF = "https://www.ezmoney.com.tw/ETF/Transaction/GetPCF"
FUBON_ASSETS = "https://websys.fsit.com.tw/FubonETF/Trade/Assets.aspx"
CTBC_API = "https://www.ctbcinvestments.com.tw/API/"

# Default constituent universe. "both" / "all" / "custom" load every code here.
CONSTITUENT_ETFS = ("0050", "00919", "00878", "00403A", "00406A", "009828", "0052")

TICKER_RE = re.compile(r"^\d{4}$")
ASP_DATE_RE = re.compile(r"/Date\((-?\d+)\)/")


def _is_equity_ticker(code: str) -> bool:
    return bool(TICKER_RE.fullmatch(str(code).strip()))


def _slash_date(value: Any) -> Optional[str]:
    m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", str(value or ""))
    if not m:
        return None
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def _asp_date(value: Any) -> Optional[str]:
    m = ASP_DATE_RE.search(str(value or ""))
    if not m:
        return None
    ms = int(m.group(1))
    if ms < 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _json_headers(referer: str) -> dict[str, str]:
    return {**HEADERS, "Accept": "application/json", "Referer": referer}


def blank_membership() -> dict[str, Any]:
    """Fields for a name that is not in any constituent ETF."""
    return {
        "in_0050": False,
        "in_00919": False,
        "weight_0050": None,
        "weight_00919": None,
        "weights": {},
        "member_etfs": [],
        "weight_max": 0.0,
        "etf_membership": "custom",
    }


def _write_cache(etf: str, rows: list[dict[str, Any]], as_of: Optional[str], source: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"holdings_{etf}.csv"
    df = pd.DataFrame(rows)
    if df.empty:
        raise ValueError(f"No holdings rows to cache for {etf}")
    df["etf"] = _normalize_etf_code(etf)
    df["as_of"] = as_of
    df["source"] = source
    df["ticker"] = df["ticker"].astype(str).str.zfill(4)
    df = df[["etf", "ticker", "name", "weight_pct", "as_of", "source"]]
    # Keep leading zeros: write etf/ticker as strings explicitly
    df.to_csv(path, index=False)
    return path


def _read_cache(etf: str) -> pd.DataFrame:
    path = DATA_DIR / f"holdings_{etf}.csv"
    if not path.exists():
        raise FileNotFoundError(f"No holdings cache for {etf}: {path}")
    df = pd.read_csv(path, dtype={"ticker": str, "etf": str})
    df["ticker"] = df["ticker"].astype(str).str.zfill(4)
    df["etf"] = df["etf"].astype(str).map(_normalize_etf_code)
    return df


def _normalize_etf_code(value: Any) -> str:
    s = str(value).strip()
    if s in ("50", "0050", "50.0"):
        return "0050"
    if s in ("919", "00919", "919.0"):
        return "00919"
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    if s.isdigit() and len(s) <= 4:
        return s.zfill(4)
    return s


def fetch_0050_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """Yuanta ETFAPI PCF/Daily → FundWeights.StockWeights (full ~50 names)."""
    params = {
        "APIType": "ETFAPI",
        "CompanyName": "YUANTAFUNDS",
        "PageName": "/product/detail/0050/ratio",
        "DeviceId": "null",
        "FuncId": "PCF/Daily",
        "AppName": "ETF",
        "Device": "3",
        "Platform": "ETF",
        "ticker": "0050",
    }
    resp = requests.get(
        YUANTA_BRIDGE,
        params=params,
        headers={**HEADERS, "Accept": "application/json", "Referer": "https://www.yuantaetfs.com/"},
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    stocks = (payload.get("FundWeights") or {}).get("StockWeights") or []
    as_of = None
    pcf = payload.get("PCF") or {}
    if pcf.get("trandate"):
        raw = str(pcf["trandate"])
        as_of = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}" if len(raw) == 8 else raw

    rows: list[dict[str, Any]] = []
    for item in stocks:
        code = str(item.get("code", "")).strip()
        if not _is_equity_ticker(code):
            continue
        weight = item.get("weights")
        if weight is None:
            continue
        rows.append(
            {
                "ticker": code.zfill(4),
                "name": str(item.get("name") or "").strip(),
                "weight_pct": float(weight),
            }
        )
    if not rows:
        raise ValueError("Yuanta 0050 response contained no equity stock weights")

    source = "yuanta_etfapi_pcf_daily"
    _write_cache("0050", rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = "0050"
    df["as_of"] = as_of
    df["source"] = source
    return df


def fetch_00919_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """Capital portfolio page (SSR top holdings table)."""
    resp = requests.get(
        CAPITAL_PORTFOLIO,
        headers={**HEADERS, "Accept": "text/html"},
        timeout=timeout,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in soup.select("div.tr.show-for-medium"):
        cells = [c.get_text(strip=True) for c in row.find_all(class_=["th", "td"])]
        if len(cells) < 3:
            continue
        code = cells[0].strip()
        if not _is_equity_ticker(code) or code in seen:
            continue
        weight_raw = cells[2].replace("%", "").replace(",", "").strip()
        try:
            weight = float(weight_raw)
        except ValueError:
            continue
        seen.add(code)
        rows.append(
            {
                "ticker": code.zfill(4),
                "name": cells[1].strip(),
                "weight_pct": weight,
            }
        )

    if not rows:
        # Fallback: any th code / adjacent weight pattern in HTML
        for m in re.finditer(
            r'class="th">\s*(\d{4})\s*</div>\s*<div[^>]*class="th">\s*([^<]+?)\s*</div>\s*'
            r'<div[^>]*class="td">\s*([\d.]+)\s*%',
            resp.text,
        ):
            code = m.group(1)
            if code in seen:
                continue
            seen.add(code)
            rows.append(
                {
                    "ticker": code.zfill(4),
                    "name": m.group(2).strip(),
                    "weight_pct": float(m.group(3)),
                }
            )

    if not rows:
        raise ValueError("Capital 00919 portfolio page contained no equity holdings")

    as_of = None
    date_m = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", resp.text)
    if date_m:
        as_of = f"{date_m.group(1)}-{int(date_m.group(2)):02d}-{int(date_m.group(3)):02d}"

    source = "capitalfund_portfolio_html"
    _write_cache("00919", rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = "00919"
    df["as_of"] = as_of
    df["source"] = source
    return df


def _cathay_fund_code(stock_code: str, timeout: float) -> str:
    headers = _json_headers("https://www.cathaysite.com.tw/")
    for page in range(1, 8):
        resp = requests.get(
            CATHAY_API + "GetETFList",
            params={"currentPage": page},
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        for row in resp.json().get("result") or []:
            if str(row.get("stockCode") or "").strip() == stock_code:
                code = str(row.get("fundCode") or "").strip()
                if code:
                    return code
    raise ValueError(f"Cathay fund code not found for {stock_code}")


def fetch_00878_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """Cathay index constituents (MSCI Taiwan ESG High Dividend Select 30)."""
    headers = _json_headers("https://www.cathaysite.com.tw/")
    fund_code = _cathay_fund_code("00878", timeout)
    resp = requests.get(
        CATHAY_API + "GetIndexStockWeights",
        params={"fundCode": fund_code},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise ValueError(payload.get("returnMessage") or "Cathay 00878 index weights unavailable")
    result = payload.get("result") or {}
    stocks = result.get("stockWeights") or []
    rows: list[dict[str, Any]] = []
    for item in stocks:
        code = str(item.get("stockCode") or "").strip()
        if not _is_equity_ticker(code):
            continue
        try:
            weight = float(str(item.get("weights")).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "ticker": code.zfill(4),
                "name": str(item.get("stockName") or "").strip(),
                "weight_pct": weight,
            }
        )
    if not rows:
        raise ValueError("Cathay 00878 response contained no equity weights")
    as_of = _slash_date(result.get("date"))
    source = "cathay_index_stock_weights"
    _write_cache("00878", rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = "00878"
    df["as_of"] = as_of
    df["source"] = source
    return df


def fetch_00403A_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """Uni-President active ETF daily PCF stock basket (fund 63YTW)."""
    headers = {
        **_json_headers("https://www.ezmoney.com.tw/ETF/Transaction/PCF?fundCode=63YTW"),
        "Content-Type": "application/json",
    }
    details: list[dict[str, Any]] = []
    last_error = "no stock basket"
    for delta in range(0, 6):
        day = (date.today() - timedelta(days=delta)).strftime("%Y/%m/%d")
        resp = requests.post(
            EZMONEY_PCF,
            headers=headers,
            json={"fundCode": "63YTW", "date": day, "specificDate": False},
            timeout=timeout,
        )
        resp.raise_for_status()
        try:
            payload = resp.json()
        except ValueError:
            last_error = f"{day} returned non-JSON"
            continue
        for asset in payload.get("asset") or []:
            if str(asset.get("AssetCode") or "") != "ST":
                continue
            details = list(asset.get("Details") or [])
        if details:
            break
        last_error = f"{day} stock basket empty"
    if not details:
        raise ValueError(f"ezmoney 00403A PCF contained no stocks ({last_error})")

    rows: list[dict[str, Any]] = []
    as_of = None
    for item in details:
        code = str(item.get("DetailCode") or "").strip()
        if not _is_equity_ticker(code):
            continue
        try:
            weight = float(item.get("NavRate"))
        except (TypeError, ValueError):
            continue
        if as_of is None:
            raw_date = item.get("TranDate")
            as_of = _asp_date(raw_date) or _slash_date(raw_date)
        rows.append(
            {
                "ticker": code.zfill(4),
                "name": str(item.get("DetailName") or "").strip(),
                "weight_pct": weight,
            }
        )
    if not rows:
        raise ValueError("ezmoney 00403A PCF contained no Taiwan equity rows")
    source = "ezmoney_getpcf"
    _write_cache("00403A", rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = "00403A"
    df["as_of"] = as_of
    df["source"] = source
    return df


def fetch_ctbc_holdings(etf_id: str, timeout: float = 30.0) -> pd.DataFrame:
    """CTBC holdings. Overseas names, futures, and options are skipped."""
    etf_id = str(etf_id).strip()
    headers = {
        **_json_headers("https://www.ctbcinvestments.com.tw/"),
        "Content-Type": "application/json",
    }
    auth = requests.post(CTBC_API + "home/AuthToken", headers=headers, json={}, timeout=timeout)
    auth.raise_for_status()
    token = ((auth.json().get("Data") or {}).get("token")) or ""
    if not token:
        raise ValueError("CTBC AuthToken returned no token")

    def _post(path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            CTBC_API + path,
            headers=headers,
            params={"token": token},
            json={"token": token, **body},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("ResultCode") != 0:
            raise ValueError(payload.get("ResultMsg") or f"CTBC {path} failed")
        return payload.get("Data") or {}

    listing = _post("etf/ETFList", {"IsWithETF": "Y"})
    fid = None
    for row in listing.get("Data") or []:
        if str(row.get("ETF_ID") or "").strip() == etf_id:
            fid = str(row.get("FID") or "").strip()
            break
    if not fid:
        raise ValueError(f"CTBC ETF list has no {etf_id}")

    stocks: list[dict[str, Any]] = []
    as_of = None
    skipped = 0
    for delta in range(0, 10):
        day = (date.today() - timedelta(days=delta)).strftime("%Y/%m/%d")
        data = _post("etf/ETFHoldingWeight", {"FID": fid, "StartDate": day})
        found: list[dict[str, Any]] = []
        for block in data.get("FundAssetsDetail") or []:
            if str(block.get("Code") or "") != "STOCK":
                continue
            found.extend(block.get("Data") or [])
        if not found:
            continue
        assets = data.get("FundAssets") or []
        if assets:
            as_of = _slash_date(assets[0].get("資料日期") or assets[0].get("NAV_DT"))
        stocks = found
        break
    if not stocks:
        raise ValueError(f"CTBC {etf_id} holdings were empty")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in stocks:
        code = str(item.get("code_") or "").strip()
        if not _is_equity_ticker(code):
            if code:
                skipped += 1
            continue
        if code in seen:
            continue
        try:
            weight = float(str(item.get("weights_")).replace("%", "").replace(",", ""))
        except (TypeError, ValueError):
            continue
        seen.add(code)
        rows.append(
            {
                "ticker": code.zfill(4),
                "name": str(item.get("name_") or "").strip(),
                "weight_pct": weight,
            }
        )
    if skipped:
        print(f"{etf_id}: skipped {skipped} non-equity holdings (no .TW price)")
    if not rows:
        raise ValueError(f"CTBC {etf_id} contained no Taiwan 4-digit holdings")
    source = "ctbc_etf_holding_weight"
    _write_cache(etf_id, rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = etf_id
    df["as_of"] = as_of
    df["source"] = source
    return df


def fetch_009828_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """CTBC 009828. Overseas names are skipped; OTC names are priced via .TWO."""
    return fetch_ctbc_holdings("009828", timeout)


def fetch_00406A_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """CTBC 00406A active ETF. Futures, options, and cash are skipped."""
    return fetch_ctbc_holdings("00406A", timeout)


def fetch_0052_holdings(timeout: float = 30.0) -> pd.DataFrame:
    """Fubon ETF asset page stock table."""
    resp = requests.get(
        FUBON_ASSETS,
        params={"lan": "TW", "stkId": "0052"},
        headers={**HEADERS, "Accept": "text/html"},
        timeout=timeout,
    )
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for table in soup.find_all("table"):
        trs = table.find_all("tr")
        if not trs:
            continue
        header = [c.get_text(strip=True) for c in trs[0].find_all(["th", "td"])]
        if not header or header[0] != "股票代碼":
            continue
        for tr in trs[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) < 5:
                continue
            code = cells[0].strip()
            if not _is_equity_ticker(code) or code in seen:
                continue
            try:
                weight = float(cells[4].replace("%", "").replace(",", ""))
            except ValueError:
                continue
            seen.add(code)
            rows.append(
                {
                    "ticker": code.zfill(4),
                    "name": cells[1].strip(),
                    "weight_pct": weight,
                }
            )
    if not rows:
        raise ValueError("Fubon 0052 asset page contained no equity holdings")
    as_of = None
    date_m = re.search(r"資料日期[：:]\s*(\d{4}/\d{1,2}/\d{1,2})", resp.text)
    if date_m:
        as_of = _slash_date(date_m.group(1))
    source = "fubon_trade_assets"
    _write_cache("0052", rows, as_of, source)
    df = pd.DataFrame(rows)
    df["etf"] = "0052"
    df["as_of"] = as_of
    df["source"] = source
    return df


def load_holdings(etf: str, use_cache: bool = False, timeout: float = 30.0) -> pd.DataFrame:
    """Fetch holdings for one ETF; fall back to cache on network/parse failure."""
    etf = _resolve_etf(etf)
    fetchers = {
        "0050": fetch_0050_holdings,
        "00919": fetch_00919_holdings,
        "00878": fetch_00878_holdings,
        "00403A": fetch_00403A_holdings,
        "00406A": fetch_00406A_holdings,
        "009828": fetch_009828_holdings,
        "0052": fetch_0052_holdings,
    }
    if etf not in fetchers:
        raise ValueError(f"Unsupported ETF: {etf}")

    if use_cache:
        return _read_cache(etf)

    try:
        return fetchers[etf](timeout=timeout)
    except Exception as exc:
        try:
            cached = _read_cache(etf)
            print(f"Holdings fetch failed for {etf} ({exc}); using cache")
            return cached
        except FileNotFoundError:
            raise RuntimeError(f"Failed to fetch {etf} holdings and no cache available: {exc}") from exc


def _resolve_etf(value: str) -> str:
    raw = str(value).strip()
    for code in CONSTITUENT_ETFS:
        if raw.lower() == code.lower():
            return code
    return _normalize_etf_code(raw)


def etfs_for_universe(universe: str) -> list[str]:
    key = str(universe).strip().lower()
    if key in ("both", "all", "custom"):
        return list(CONSTITUENT_ETFS)
    for code in CONSTITUENT_ETFS:
        if key == code.lower():
            return [code]
    allowed = ", ".join((*CONSTITUENT_ETFS, "both", "all", "custom"))
    raise ValueError(f"universe must be one of: {allowed}")


def union_universe(
    universe: str = "both",
    use_cache: bool = False,
    min_weight: float = 0.0,
) -> pd.DataFrame:
    """
    Build the stock universe from constituent ETFs.

    One row per Taiwan ticker, with per-ETF weights and legacy 0050/00919 flags.
    """
    etfs = etfs_for_universe(universe)
    order = {code: i for i, code in enumerate(CONSTITUENT_ETFS)}
    frames = [load_holdings(e, use_cache=use_cache) for e in etfs]
    by_ticker: dict[str, dict[str, Any]] = {}
    for df in frames:
        etf = _resolve_etf(str(df["etf"].iloc[0]))
        for _, row in df.iterrows():
            t = str(row["ticker"]).zfill(4)
            weight = float(row["weight_pct"])
            if weight < min_weight:
                continue
            entry = by_ticker.setdefault(
                t,
                {
                    "ticker": t,
                    "name": str(row["name"]),
                    "in_0050": False,
                    "in_00919": False,
                    "weight_0050": None,
                    "weight_00919": None,
                    "weights": {},
                    "member_etfs": [],
                    "as_of_0050": None,
                    "as_of_00919": None,
                    "source_0050": None,
                    "source_00919": None,
                },
            )
            entry["weights"][etf] = weight
            if etf not in entry["member_etfs"]:
                entry["member_etfs"].append(etf)
            if etf == "0050":
                entry["in_0050"] = True
                entry["weight_0050"] = weight
                entry["as_of_0050"] = row.get("as_of")
                entry["source_0050"] = row.get("source")
            elif etf == "00919":
                entry["in_00919"] = True
                entry["weight_00919"] = weight
                entry["as_of_00919"] = row.get("as_of")
                entry["source_00919"] = row.get("source")
            if row.get("name"):
                entry["name"] = str(row["name"])

    out = pd.DataFrame(list(by_ticker.values()))
    if out.empty:
        raise ValueError("Universe is empty after filters")

    def _max_w(r: pd.Series) -> float:
        weights = r["weights"] if isinstance(r["weights"], dict) else {}
        vals = []
        for v in weights.values():
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            vals.append(float(v))
        return float(max(vals)) if vals else 0.0

    def _label(r: pd.Series) -> str:
        members = r["member_etfs"] if isinstance(r["member_etfs"], list) else []
        ordered = sorted(members, key=lambda c: order.get(c, 99))
        return "+".join(ordered) if ordered else "custom"

    out["member_etfs"] = out["member_etfs"].apply(
        lambda members: sorted(members, key=lambda c: order.get(c, 99)) if isinstance(members, list) else []
    )
    out["weight_max"] = out.apply(_max_w, axis=1)
    out["etf_membership"] = out.apply(_label, axis=1)
    out = out.sort_values(["weight_max", "ticker"], ascending=[False, True]).reset_index(drop=True)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    snap = {
        "universe": universe,
        "count": int(len(out)),
        "holdings": out.to_dict(orient="records"),
    }
    (OUTPUT_DIR / "holdings_latest.json").write_text(
        json.dumps(snap, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return out


if __name__ == "__main__":
    u = union_universe("both")
    print(u.head(15).to_string(index=False))
    print(f"total={len(u)}")
